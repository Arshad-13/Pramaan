"""P0: configuration must fail closed."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.config import ConfigError, Settings, validate_settings
from tests.conftest import TEST_ENV


def _settings(**overrides) -> Settings:
    values = {k.lower(): v for k, v in TEST_ENV.items()}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_settings_pass():
    validate_settings(_settings())


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret_key": "GENERATE_WITH_scripts/gen_keys.py"},
        {"secret_key": "change-me-long-random-string-change-me-long"},
        {"secret_key": "too-short"},
        {"master_key": "BASE64_OF_32_RANDOM_BYTES"},
        {"master_key": base64.b64encode(b"x" * 16).decode()},  # wrong length
        {"master_key": "not base64 !!!"},
        {"audit_key": base64.b64encode(b"y" * 31).decode()},
        {"audit_signing_key_path": "./does/not/exist.pem"},
        {"pbkdf2_iterations": 1000},
    ],
)
def test_insecure_settings_are_rejected(overrides):
    with pytest.raises(ConfigError):
        validate_settings(_settings(**overrides))


def test_master_and_audit_keys_must_differ():
    same = base64.b64encode(b"z" * 32).decode()
    with pytest.raises(ConfigError):
        validate_settings(_settings(master_key=same, audit_key=same))


def test_non_pem_signing_key_rejected(tmp_path: Path):
    bogus = tmp_path / "k.pem"
    bogus.write_text("not a key")
    with pytest.raises(ConfigError):
        validate_settings(_settings(audit_signing_key_path=str(bogus)))


def test_error_message_never_contains_secret_value():
    secret = "short-secret"
    with pytest.raises(ConfigError) as exc:
        validate_settings(_settings(secret_key=secret))
    assert secret not in str(exc.value)


def test_list_properties():
    s = _settings(cors_origins="http://a.test, http://b.test", trusted_proxy_ips="")
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]
    assert s.trusted_proxy_list == []
