"""Accounts: registration, sign-in, doctor activation, approvals, suspension.

Purpose: all account business rules live here; routers stay thin. Every action writes an audit
entry in the SAME transaction as the change (Spec Section 9).
Inputs : a SQLAlchemy session and validated request data.
Outputs: ORM objects; raises `ServiceError` subclasses (mapped to HTTP by main.py).

Key rules:
- Unknown email, wrong password, locked account and not-yet-activated account all raise the same
  `AuthFailed` (no user enumeration); a dummy hash is verified so timing is similar.
- After a correct password, accounts that cannot be used (pending, rejected, disabled) get a
  clear 403, which reveals nothing to someone who does not already know the password.
- Doctors are created by an admin WITHOUT a password. A one-time activation token (24 h, stored
  only as SHA-256) lets the doctor set their own login password and a different signing password;
  the signing keypair is generated at that moment. The admin never learns either password.
- Suspending a doctor deactivates the account, bumps `token_version` (kills sessions) and revokes
  every signing key, so their unused prescriptions stop verifying (Spec Section 10.2 step 7).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock
from app.core.keys import compute_key_id, generate_keypair, protect_private_key, public_key_pem
from app.core.security import (
    PasswordPolicyError,
    hash_password,
    passwords_equal,
    validate_password,
    verify_password,
)
from app.errors import AccountNotUsable, AuthFailed, BadRequest, Conflict, NotFound
from app.models import (
    ActivationToken,
    ApprovalStatus,
    DoctorKey,
    KeyStatus,
    Role,
    User,
)
from app.schemas import RegisterIn

ACTIVATION_TOKEN_HOURS = 24
_PATIENT_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O/1/I/L: easy to read aloud


def _check_password(password: str) -> None:
    try:
        validate_password(password)
    except PasswordPolicyError as exc:
        raise BadRequest(str(exc)) from exc


def _new_patient_code(db: Session) -> str:
    for _ in range(20):
        raw = "".join(secrets.choice(_PATIENT_CODE_ALPHABET) for _ in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        if db.scalar(select(User.id).where(User.patient_code == code)) is None:
            return code
    raise RuntimeError("could not allocate a patient code")  # pragma: no cover


def get_user_by_public_id(db: Session, public_id: str) -> User:
    user = db.scalar(select(User).where(User.public_id == public_id))
    if user is None:
        raise NotFound()
    return user


# --- registration ------------------------------------------------------------------------------


def register_user(db: Session, data: RegisterIn) -> User:
    _check_password(data.password)
    role = Role(data.role)
    user = User(
        email=data.email,
        name=data.name,
        role=role,
        password_hash=hash_password(data.password),
        license_no=data.license_no,
        org_name=data.org_name,
        patient_code=_new_patient_code(db) if role == Role.patient else None,
        approval_status=(
            ApprovalStatus.PENDING if role == Role.pharmacist else ApprovalStatus.APPROVED
        ),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with that email already exists.") from None
    audit.append(db, user.id, role.value, "USER_REGISTER", user.public_id, {"role": role.value})
    db.commit()
    return user


# --- sign-in -----------------------------------------------------------------------------------


def _fail(db: Session, user: User | None, reason: str) -> AuthFailed:
    """Record a failed sign-in (committed, even though the request then errors) and return
    the generic error to raise."""
    audit.append(
        db,
        user.id if user else None,
        user.role.value if user else None,
        "LOGIN_FAIL",
        user.public_id if user else None,
        {"reason": reason},
    )
    db.commit()
    return AuthFailed()


def authenticate(db: Session, email: str, password: str) -> User:
    settings = get_settings()
    now = clock.now_utc()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        verify_password(None, password)  # equalise timing
        raise _fail(db, None, "UNKNOWN_ACCOUNT")

    if user.locked_until is not None and user.locked_until <= now:
        user.locked_until = None  # lockout served: start counting fresh
        user.failed_logins = 0
    if user.locked_until is not None:
        verify_password(user.password_hash, password)
        raise _fail(db, user, "LOCKED")

    if user.password_hash is None:
        verify_password(None, password)
        raise _fail(db, user, "NOT_ACTIVATED")

    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            audit.append(
                db, user.id, user.role.value, "ACCOUNT_LOCKED", user.public_id,
                {"minutes": settings.lockout_minutes},
            )  # fmt: skip
        raise _fail(db, user, "BAD_PASSWORD")

    user.failed_logins = 0
    user.locked_until = None
    if not user.is_active:
        audit.append(
            db, user.id, user.role.value, "LOGIN_FAIL", user.public_id, {"reason": "DISABLED"}
        )
        db.commit()
        raise AccountNotUsable("This account has been disabled.")
    if user.approval_status != ApprovalStatus.APPROVED:
        audit.append(
            db, user.id, user.role.value, "LOGIN_FAIL", user.public_id, {"reason": "NOT_APPROVED"}
        )
        db.commit()
        message = (
            "Your account is waiting for administrator approval."
            if user.approval_status == ApprovalStatus.PENDING
            else "Your registration was not approved."
        )
        raise AccountNotUsable(message)

    audit.append(db, user.id, user.role.value, "LOGIN_SUCCESS", user.public_id, {})
    db.commit()
    return user


def logout(db: Session, user: User) -> None:
    user.token_version += 1  # invalidates every session of this user
    audit.append(db, user.id, user.role.value, "LOGOUT", user.public_id, {})
    db.commit()


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(user.password_hash, current):
        raise BadRequest("Current password is incorrect.")
    _check_password(new)
    user.password_hash = hash_password(new)
    user.token_version += 1
    audit.append(
        db, user.id, user.role.value, "LOGOUT", user.public_id, {"reason": "PASSWORD_CHANGED"}
    )
    db.commit()


# --- doctor accounts and activation ------------------------------------------------------------


def _issue_activation_token(db: Session, user: User) -> tuple[str, datetime]:
    # Any earlier unused token stops working.
    for old in db.scalars(
        select(ActivationToken).where(
            ActivationToken.user_id == user.id, ActivationToken.used_at.is_(None)
        )
    ):
        old.used_at = clock.now_utc()
    token = secrets.token_urlsafe(24)
    expires_at = clock.now_utc() + timedelta(hours=ACTIVATION_TOKEN_HOURS)
    db.add(
        ActivationToken(
            user_id=user.id,
            token_sha256=hashlib.sha256(token.encode("ascii")).hexdigest(),
            expires_at=expires_at,
        )
    )
    return token, expires_at


def create_doctor(
    db: Session, admin: User, *, email: str, name: str, license_no: str, org_name: str
) -> tuple[User, str, datetime]:
    user = User(
        email=email,
        name=name,
        role=Role.doctor,
        password_hash=None,  # set by the doctor at activation
        license_no=license_no,
        org_name=org_name,
        approval_status=ApprovalStatus.APPROVED,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with that email already exists.") from None
    token, expires_at = _issue_activation_token(db, user)
    audit.append(
        db, admin.id, admin.role.value, "ADMIN_USER_CREATED", user.public_id, {"role": "doctor"}
    )
    db.commit()
    return user, token, expires_at


def reissue_activation(db: Session, admin: User, user: User) -> tuple[str, datetime]:
    if user.role != Role.doctor or user.password_hash is not None:
        raise BadRequest("Only doctors who have not activated yet can receive a new code.")
    token, expires_at = _issue_activation_token(db, user)
    audit.append(
        db, admin.id, admin.role.value, "ADMIN_USER_CREATED", user.public_id,
        {"role": "doctor", "reissued": True},
    )  # fmt: skip
    db.commit()
    return token, expires_at


def activate_doctor(
    db: Session, *, email: str, token: str, login_password: str, signing_password: str
) -> User:
    invalid = BadRequest("That activation code is invalid or has expired.")
    row = db.scalar(
        select(ActivationToken).where(
            ActivationToken.token_sha256 == hashlib.sha256(token.encode("utf-8")).hexdigest()
        )
    )
    now = clock.now_utc()
    user = db.get(User, row.user_id) if row else None
    if (
        row is None
        or user is None
        or row.used_at is not None
        or row.expires_at <= now
        or user.email != email
        or user.role != Role.doctor
        or user.password_hash is not None
    ):
        raise invalid

    _check_password(login_password)
    _check_password(signing_password)
    if passwords_equal(login_password, signing_password):
        raise BadRequest("The signing password must be different from your login password.")

    settings = get_settings()
    private_key = generate_keypair()
    protected = protect_private_key(
        private_key, signing_password, iterations=settings.pbkdf2_iterations
    )
    key_id = compute_key_id(private_key.public_key())
    db.add(
        DoctorKey(
            key_id=key_id,
            user_id=user.id,
            public_key_pem=public_key_pem(private_key.public_key()),
            enc_private_key=protected.ciphertext,
            kdf=protected.kdf,
            kdf_salt=protected.kdf_salt,
            kdf_iterations=protected.kdf_iterations,
            nonce=protected.nonce,
            status=KeyStatus.ACTIVE,
        )
    )
    user.password_hash = hash_password(login_password)
    row.used_at = now
    audit.append(db, user.id, user.role.value, "ACCOUNT_ACTIVATED", user.public_id, {})
    audit.append(db, user.id, user.role.value, "KEY_GENERATED", user.public_id, {"key_id": key_id})
    db.commit()
    return user


# --- admin actions -----------------------------------------------------------------------------


def list_users(
    db: Session,
    *,
    role: str | None = None,
    approval_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    query = select(User)
    if role:
        query = query.where(User.role == Role(role))
    if approval_status:
        query = query.where(User.approval_status == ApprovalStatus(approval_status))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(User.id.desc()).limit(limit).offset(offset)).all()
    return list(items), total


def set_pharmacist_approval(db: Session, admin: User, user: User, *, approve: bool) -> User:
    if user.role != Role.pharmacist:
        raise BadRequest("Only pharmacist accounts need approval.")
    if user.approval_status != ApprovalStatus.PENDING:
        raise Conflict("This registration has already been decided.")
    user.approval_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    audit.append(
        db, admin.id, admin.role.value,
        "PHARMACIST_APPROVED" if approve else "PHARMACIST_REJECTED", user.public_id, {},
    )  # fmt: skip
    db.commit()
    return user


def suspend_user(db: Session, admin: User, user: User) -> User:
    """Deactivate, kill sessions, and (for doctors) revoke all signing keys."""
    if user.id == admin.id:
        raise BadRequest("You cannot deactivate your own account.")
    if not user.is_active:
        raise Conflict("This account is already deactivated.")
    now = clock.now_utc()
    user.is_active = False
    user.token_version += 1
    audit.append(db, admin.id, admin.role.value, "ADMIN_USER_DEACTIVATED", user.public_id, {})
    if user.role == Role.doctor:
        for key in db.scalars(
            select(DoctorKey).where(
                DoctorKey.user_id == user.id, DoctorKey.status != KeyStatus.REVOKED
            )
        ):
            key.status = KeyStatus.REVOKED
            key.revoked_at = now
            key.revoke_reason = "DOCTOR_SUSPENDED"
            audit.append(
                db,
                admin.id,
                admin.role.value,
                "KEY_REVOKED",
                user.public_id,
                {"key_id": key.key_id},
            )
    db.commit()
    return user
