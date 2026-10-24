"""Application settings, loaded from the environment / `.env`.

Purpose: single place for configuration, and a *fail-closed* check on secrets.
Inputs : environment variables (see `.env.example`).
Outputs: `get_settings()` returns a validated `Settings`; a `ConfigError` is raised if any
         secret is missing, a placeholder, or malformed.

Why fail closed: a server that silently starts with a guessable JWT secret or a
too-short encryption key looks healthy but is not secure. We refuse to start instead.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_MARKERS = ("GENERATE_WITH", "BASE64_OF", "change-me", "changeme", "CHANGE_ME")
MIN_SECRET_KEY_BYTES = 32


class ConfigError(Exception):
    """Raised when configuration is missing or insecure. The app must not start."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./pramaan.db"
    secret_key: str  # JWT signing secret
    master_key: str  # base64 of 32 bytes: KEK for envelope encryption
    master_key_version: int = 1
    audit_key: str  # base64 of 32 bytes: HMAC key for audit chain + patient PIN
    audit_signing_key_path: str = "./secrets/audit_signing.pem"
    anomaly_model_path: str = "./models/iforest.joblib"

    access_token_minutes: int = 30
    pbkdf2_iterations: int = 600_000
    storage_dir: str = "./storage"
    anchor_file: str = "./storage/anchors.jsonl"
    audit_checkpoint_every: int = 50  # signed audit checkpoint every N entries

    risk_threshold: int = 60
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    max_failed_unlocks: int = 5
    pin_step_seconds: int = 120

    frozen_time: str = ""  # demo/testing only
    debug: bool = False
    cors_origins: str = "http://localhost:5173"
    trusted_proxy_ips: str = ""
    cookie_secure: bool = False
    rate_limit_enabled: bool = True
    login_rate_per_minute: int = 5  # per IP and, separately, per target account
    verify_rate_per_minute: int = 30  # per signed-in user
    signup_rate_per_minute: int = 10  # register and activate, per IP

    @property
    def master_key_bytes(self) -> bytes:
        """The 32-byte key-encryption key (validated at startup)."""
        return base64.b64decode(self.master_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [ip.strip() for ip in self.trusted_proxy_ips.split(",") if ip.strip()]


def _is_placeholder(value: str) -> bool:
    return any(marker.lower() in value.lower() for marker in PLACEHOLDER_MARKERS)


def _check_b64_32(name: str, value: str) -> None:
    if _is_placeholder(value):
        raise ConfigError(f"{name} is still a placeholder. Run: python scripts/gen_keys.py")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConfigError(f"{name} is not valid base64.") from exc
    if len(raw) != 32:
        raise ConfigError(f"{name} must decode to exactly 32 bytes (got {len(raw)}).")


def validate_settings(s: Settings) -> None:
    """Fail closed on insecure or malformed secrets. Never echoes secret values."""
    if _is_placeholder(s.secret_key):
        raise ConfigError("SECRET_KEY is still a placeholder. Run: python scripts/gen_keys.py")
    if len(s.secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES:
        raise ConfigError(f"SECRET_KEY must be at least {MIN_SECRET_KEY_BYTES} bytes long.")
    _check_b64_32("MASTER_KEY", s.master_key)
    _check_b64_32("AUDIT_KEY", s.audit_key)
    if s.master_key == s.audit_key:
        raise ConfigError("MASTER_KEY and AUDIT_KEY must be different keys.")

    pem = Path(s.audit_signing_key_path)
    if not pem.is_file():
        raise ConfigError(f"Audit signing key not found at {pem}. Run: python scripts/gen_keys.py")
    if b"BEGIN PRIVATE KEY" not in pem.read_bytes()[:64]:
        raise ConfigError(f"{pem} is not a PKCS8 PEM private key.")

    if s.pbkdf2_iterations < 100_000:
        raise ConfigError("PBKDF2_ITERATIONS is dangerously low (minimum 100000).")
    if s.access_token_minutes <= 0 or s.max_failed_logins <= 0 or s.lockout_minutes <= 0:
        raise ConfigError("Token and lockout settings must be positive.")


@lru_cache
def get_settings() -> Settings:
    """Load and validate settings once. Raises ConfigError (never a raw traceback with secrets)."""
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = sorted({str(err["loc"][0]).upper() for err in exc.errors() if err["loc"]})
        raise ConfigError(
            f"Missing or invalid settings: {', '.join(missing)}. Run: python scripts/gen_keys.py"
        ) from None
    validate_settings(settings)
    return settings
