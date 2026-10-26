"""Pydantic request/response models (strict input validation at the edge).

Names, licence numbers and organisation names must be representable in signed payloads, so they
are checked with the same canonicaliser the signing code uses (no control or bidi characters).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.core.canonical import CanonicalError, normalise
from app.models import ApprovalStatus, Role

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def _clean_text(value: str) -> str:
    value = value.strip()
    try:
        return normalise(value)
    except CanonicalError as exc:
        raise ValueError("contains characters that are not allowed") from exc


def _email(value: str) -> str:
    value = _clean_text(value).lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


Email = Annotated[str, Field(max_length=254), AfterValidator(_email)]
Name = Annotated[str, Field(min_length=2, max_length=120), AfterValidator(_clean_text)]
ShortText = Annotated[str, Field(min_length=2, max_length=160), AfterValidator(_clean_text)]
Password = Annotated[str, Field(min_length=1, max_length=256)]  # policy is checked in the service


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegisterIn(Strict):
    email: Email
    name: Name
    password: Password
    role: Literal["patient", "pharmacist"]
    license_no: ShortText | None = None
    org_name: ShortText | None = None

    @model_validator(mode="after")
    def _pharmacist_needs_licence(self) -> RegisterIn:
        if self.role == "pharmacist" and not (self.license_no and self.org_name):
            raise ValueError("pharmacists must provide a licence number and pharmacy name")
        if self.role == "patient":
            self.license_no = None
            self.org_name = None
        return self


class LoginIn(Strict):
    email: Email
    password: Password


class ActivateIn(Strict):
    email: Email
    token: Annotated[str, Field(min_length=20, max_length=128)]
    login_password: Password
    signing_password: Password


class ChangePasswordIn(Strict):
    current_password: Password
    new_password: Password


class CreateDoctorIn(Strict):
    email: Email
    name: Name
    license_no: ShortText
    org_name: ShortText


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    email: str
    name: str
    role: Role
    license_no: str | None
    org_name: str | None
    patient_code: str | None
    approval_status: ApprovalStatus
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    role: Role
    name: str


class ActivationOut(BaseModel):
    user: UserOut
    activation_token: str  # shown once; only its SHA-256 is stored
    expires_at: datetime


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    ts: datetime
    actor_id: int | None
    actor_role: str | None
    action: str
    resource_id: str | None
    details_json: str
    prev_hash: str
    entry_hash: str


class AuditPageOut(BaseModel):
    items: list[AuditEntryOut]
    total: int


class SecurityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    user_id: int | None
    ip: str | None
    event_type: str
    severity: str
    details_json: str


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None
    checkpoint_ok: bool
    truncated: bool
    problems: list[str]
    last_seq: int
    checkpoints: int
    anchors: int


# --- prescriptions and keys (Phase 4) -------------------------------------------------------------

Frequency = Literal["OD", "BD", "TDS", "QID", "HS", "SOS"]


def _clean_notes(value: str) -> str:
    """Notes may contain newlines; everything else goes through the same canonical checks."""
    try:
        return normalise({"notes": value.strip()})["notes"]
    except CanonicalError as exc:
        raise ValueError("contains characters that are not allowed") from exc


class MedicineIn(Strict):
    name: Annotated[str, Field(min_length=2, max_length=60), AfterValidator(_clean_text)]
    dose_mg: Annotated[int, Field(ge=1, le=99999)]
    frequency: Frequency
    duration_days: Annotated[int, Field(ge=1, le=365)]


class IssueIn(Strict):
    patient_id: Annotated[str, Field(min_length=1, max_length=64)]
    medicines: Annotated[list[MedicineIn], Field(min_length=1, max_length=8)]
    notes: Annotated[str, Field(max_length=500), AfterValidator(_clean_notes)] = ""
    validity_days: Annotated[int, Field(ge=1, le=90)] = 30
    max_fills: Annotated[int, Field(ge=1, le=5)] = 1
    age_years: Annotated[int, Field(ge=0, le=120)] | None = None
    signing_password: Password
    override_reason: Annotated[str, Field(max_length=300)] | None = None
    require_pin: bool = True


class RiskOut(BaseModel):
    score: int
    flags: list[str]
    explanations: list[str]


class IssueOut(BaseModel):
    rx_id: str
    issued_at: datetime
    expires_at: datetime
    max_fills: int
    key_id: str
    fingerprint: str
    risk: RiskOut
    warnings: list[str]


class MedicineOut(BaseModel):
    name: str
    dose_mg: int
    frequency: str
    duration_days: int


class PrescriptionOut(BaseModel):
    id: str
    status: (
        str  # what to show: ISSUED, DISPENSED, REVOKED or EXPIRED (derived from the signed expiry)
    )
    issued_at: datetime
    expires_at: datetime
    max_fills: int
    fills_used: int
    doctor_name: str | None
    patient_name: str | None
    medicines: list[MedicineOut]
    notes: str
    key_id: str
    fingerprint: str
    risk_score: int | None = None  # visible to the issuing doctor only
    flagged: bool = False  # issuing doctor only: the score reached the review threshold
    require_pin: bool = True
    readable: bool = True  # False if the stored record failed its integrity check


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key_id: str
    status: str
    created_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None


class RotateKeyIn(Strict):
    current_signing_password: Password
    new_signing_password: Password


class PatientLookupOut(BaseModel):
    public_id: str
    name: str
    patient_code: str | None


# --- verification and dispensing (Phase 5) ---------------------------------------------

VerifyResult = Literal[
    "VALID", "TAMPERED", "REVOKED", "ALREADY_USED", "EXPIRED", "SUSPICIOUS",
    "REVIEW_REQUIRED", "NOT_FOUND", "INVALID_QR",
]  # fmt: skip


class VerifyQRIn(Strict):
    qr_string: Annotated[str, Field(min_length=1, max_length=400)]


class ChecksOut(BaseModel):
    signature_valid: bool | None = None
    hash_match: bool | None = None
    key_state: str | None = None
    doctor_active: bool | None = None
    status: str | None = None
    fills_remaining: int | None = None
    not_expired: bool | None = None
    content_check: str = "NOT_CHECKED"
    file_integrity: str | None = None


class VerifiedDoctor(BaseModel):
    name: str
    license_no: str


class VerifiedPatient(BaseModel):
    name: str  # masked: initial + surname


class ContentZoneOut(BaseModel):
    zone: str
    label: str
    signed: str
    read: str | None = None
    status: str  # MISMATCH, EXTRA_CONTENT or UNREADABLE
    quad: list[list[float]]  # outline on the overlay image, in overlay pixels


class OverlayOut(BaseModel):
    image: str  # JPEG data URL of the upload, downscaled
    width: int
    height: int


class VerifyOut(BaseModel):
    result: VerifyResult
    reason_codes: list[str]
    rx_id: str | None = None
    checks: ChecksOut | None = None
    content_zones: list[ContentZoneOut] = []
    overlay: OverlayOut | None = None
    qr_string: str | None = None  # upload verification only: lets the pharmacist dispense next
    risk: RiskOut | None = None
    warnings: list[str] = []
    doctor: VerifiedDoctor | None = None
    patient: VerifiedPatient | None = None
    medicines: list[MedicineOut] | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    can_dispense: bool = False
    pin_required: bool = False


class RecentVerificationOut(BaseModel):
    ts: datetime
    result: str
    rx_ref: str | None = None  # first characters of the prescription id; no personal data


class RecentActivityOut(BaseModel):
    verified_today: int
    flagged_today: int
    dispensed_today: int
    recent: list[RecentVerificationOut]


class DispenseIn(Strict):
    qr_string: Annotated[str, Field(min_length=1, max_length=400)]
    patient_pin: Annotated[str, Field(min_length=1, max_length=12)] | None = None
    patient_identity_checked: bool = False


class DispenseOut(BaseModel):
    rx_id: str
    fill_no: int
    fills_remaining: int
    status: str


class PinOut(BaseModel):
    pin: str
    seconds_remaining: int
    step_seconds: int


# --- risk check and drug list (Phase 6) ----------------------------------------------------------------


class RiskCheckIn(Strict):
    medicines: Annotated[list[MedicineIn], Field(min_length=1, max_length=8)]
    max_fills: Annotated[int, Field(ge=1, le=5)] = 1


class MedicineNoteOut(BaseModel):
    index: int
    name: str
    status: str  # KNOWN, POSSIBLE_TYPO or UNKNOWN
    suggestion: str | None = None
    generic: str | None = None
    flags: list[str] = []


class RiskCheckOut(BaseModel):
    risk: RiskOut
    threshold: int
    requires_override: bool
    medicines: list[MedicineNoteOut]
    warnings: list[str]
    controlled: bool = False


class DrugOut(BaseModel):
    name: str
    generic: str
    is_brand: bool
