"""SQLAlchemy models (Spec Section 6).

Purpose: the database schema.
Notes :
- Anything that appears inside a signed payload uses `public_id` (UUID), never the integer id.
- `payload_enc` is ciphertext; only query/cross-check columns are plaintext.
- Datetimes are stored as naive UTC and always returned timezone-aware (`UTCDateTime`).
- EXPIRED is derived from the signed payload, so it is not a stored status.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.clock import now_utc


class UTCDateTime(TypeDecorator):
    """Store UTC datetimes; SQLite drops tzinfo, so re-attach UTC on the way out."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _enum(cls: type[enum.Enum]) -> SAEnum:
    # Store the member *name* as a plain string (no native DB enum type).
    return SAEnum(cls, native_enum=False, length=20, validate_strings=True)


class Role(enum.StrEnum):
    doctor = "doctor"
    patient = "patient"
    pharmacist = "pharmacist"
    admin = "admin"
    auditor = "auditor"


class ApprovalStatus(enum.StrEnum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class KeyStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class RxStatus(enum.StrEnum):
    ISSUED = "ISSUED"
    DISPENSED = "DISPENSED"
    REVOKED = "REVOKED"


class Severity(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(_enum(Role))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    org_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    patient_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        _enum(ApprovalStatus), default=ApprovalStatus.APPROVED
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)


class ActivationToken(Base):
    """One-time doctor activation token. Only its SHA-256 is stored."""

    __tablename__ = "activation_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DoctorKey(Base):
    __tablename__ = "doctor_keys"
    __table_args__ = (
        # At most one ACTIVE key per doctor.
        Index(
            "uq_one_active_key_per_doctor",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    key_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    public_key_pem: Mapped[str] = mapped_column(Text)
    enc_private_key: Mapped[bytes] = mapped_column(LargeBinary)
    kdf: Mapped[str] = mapped_column(String(32), default="pbkdf2-sha256")
    kdf_salt: Mapped[bytes] = mapped_column(LargeBinary)
    kdf_iterations: Mapped[int] = mapped_column(Integer)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[KeyStatus] = mapped_column(_enum(KeyStatus), default=KeyStatus.ACTIVE)
    failed_unlocks: Mapped[int] = mapped_column(Integer, default=0)
    unlock_locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = (
        CheckConstraint("fills_used >= 0 AND fills_used <= max_fills", name="ck_fills_range"),
        CheckConstraint("max_fills BETWEEN 1 AND 5", name="ck_max_fills"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)  # rx_id
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key_id: Mapped[str] = mapped_column(ForeignKey("doctor_keys.key_id"))
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)  # nonce || AES-GCM(canonical payload)
    payload_hash: Mapped[str] = mapped_column(String(64))
    signature_b64: Mapped[str] = mapped_column(String(128))
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    kek_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[RxStatus] = mapped_column(_enum(RxStatus), default=RxStatus.ISSUED, index=True)
    max_fills: Mapped[int] = mapped_column(Integer, default=1)
    fills_used: Mapped[int] = mapped_column(Integer, default=0)
    redeem_secret_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    require_pin: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_flags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    risk_features_json: Mapped[str] = mapped_column(Text, default="{}")
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    pdf_path: Mapped[str] = mapped_column(String(255))
    pdf_sha256: Mapped[str] = mapped_column(String(64))


class Dispense(Base):
    """One row per fill. UNIQUE(rx_id, fill_no) makes a double spend impossible at DB level."""

    __tablename__ = "dispenses"
    __table_args__ = (UniqueConstraint("rx_id", "fill_no", name="uq_rx_fill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rx_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"), index=True)
    fill_no: Mapped[int] = mapped_column(Integer)
    pharmacist_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)


class AuditLog(Base):
    """HMAC-chained audit entries. Details hold IDs/codes only, never PII or secrets."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    head_hash: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    signature_b64: Mapped[str] = mapped_column(String(128))


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[Severity] = mapped_column(_enum(Severity))
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pharmacist_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rx_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(24))
    reason_codes: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=now_utc)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
