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
