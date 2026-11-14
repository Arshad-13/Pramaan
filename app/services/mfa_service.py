"""Two-factor sign-in with an authenticator app (Spec extension K3).

Flow : sign in with the password -> if the account has a second factor, the server answers
       `mfa_required` with a short-lived token that is NOT a session -> the person sends that token
       and a code -> only then is a session issued.
Set-up: `begin_enrol` (needs the current password; stores a new secret, not yet active) ->
       `enable` (needs a valid code from the app; turns it on and shows recovery codes once).
Off  : `disable` needs the password and a valid code or recovery code. An administrator can switch
       it off for someone who lost both (`admin_reset`); that is audited and tells the person.
Keys : the secret is encrypted under the master key (purpose "totp", bound to the user's id) and is
       re-wrapped when the master key is rotated, like the prescription keys.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock, crypto, totp
from app.core.qr import qr_matrix
from app.core.security import TokenError, decode_mfa_token, verify_password
from app.errors import AccountNotUsable, AuthFailed, BadRequest, Conflict
from app.models import ApprovalStatus, User
from app.schemas import MfaEnrolOut
from app.services.account_service import register_failed_attempt

WRONG_CODE = "That code is not right. Check the time on your phone and try the newest code."


def _secret_of(user: User) -> bytes | None:
    if user.totp_secret_enc is None:
        return None
    try:
        return crypto.unwrap_key(
            get_settings().master_key_bytes,
            user.totp_secret_enc,
            rx_id=user.public_id,
            kek_version=user.totp_kek_version,
            purpose=b"totp",
        )
    except crypto.DecryptionError:
        return None  # treated as "no valid secret": the code check fails, nothing leaks


def _recovery_key() -> bytes:
    return get_settings().secret_key.encode("utf-8")


def _check_factor(user: User, code: str) -> str | None:
    """Accept an authenticator code or a recovery code. Returns which one worked, else None.
    Mutates the user (last used step, used-up recovery code); the caller commits."""
    code = code.strip()
    if totp.looks_like_totp(code):
        secret = _secret_of(user)
        if secret is None:
            return None
        step = totp.verify(secret, code, clock.now_utc(), user.totp_last_step)
        if step is None:
            return None
        user.totp_last_step = step
        return "totp"
    hashes: list[str] = json.loads(user.recovery_codes_json or "[]")
    candidate = totp.recovery_hash(_recovery_key(), code)
    matched = None
    for stored in hashes:
        if crypto.constant_time_equal(stored, candidate):
            matched = stored
    if matched is None:
        return None
    hashes.remove(matched)
    user.recovery_codes_json = json.dumps(hashes)
    return "recovery"


def begin_enrol(db: Session, user: User, password: str) -> MfaEnrolOut:
    if user.totp_enabled:
        raise Conflict("Two-factor sign-in is already on.")
    if not verify_password(user.password_hash, password):
        raise BadRequest("Current password is incorrect.")
    secret = totp.new_secret()
    settings = get_settings()
    user.totp_secret_enc = crypto.wrap_key(
        settings.master_key_bytes,
        secret,
        rx_id=user.public_id,
        kek_version=settings.master_key_version,
        purpose=b"totp",
    )
    user.totp_kek_version = settings.master_key_version
    user.totp_last_step = 0
    db.commit()
    uri = totp.provisioning_uri(secret, user.email)
    return MfaEnrolOut(secret=totp.to_base32(secret), otpauth_uri=uri, qr_matrix=qr_matrix(uri))


def enable(db: Session, user: User, code: str) -> list[str]:
    """Turn the second factor on. Returns the recovery codes (the only time they are shown)."""
    if user.totp_enabled:
        raise Conflict("Two-factor sign-in is already on.")
    secret = _secret_of(user)
    if secret is None:
        raise BadRequest("Start the set-up first.")
    step = totp.verify(secret, code, clock.now_utc(), user.totp_last_step)
    if step is None:
        raise BadRequest(WRONG_CODE)
    codes = totp.new_recovery_codes()
    user.totp_last_step = step
    user.totp_enabled = True
    user.recovery_codes_json = json.dumps([totp.recovery_hash(_recovery_key(), c) for c in codes])
    audit.append(db, user.id, user.role.value, "MFA_ENABLED", user.public_id, {})
    db.commit()
    return codes


def _clear(user: User) -> None:
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = 0
    user.recovery_codes_json = None


def disable(db: Session, user: User, password: str, code: str) -> None:
    if not user.totp_enabled:
        raise Conflict("Two-factor sign-in is not on.")
    if not verify_password(user.password_hash, password):
        raise BadRequest("Current password is incorrect.")
    if _check_factor(user, code) is None:
        db.rollback()
        raise BadRequest(WRONG_CODE)
    _clear(user)
    audit.append(db, user.id, user.role.value, "MFA_DISABLED", user.public_id, {"by": "self"})
    db.commit()


def admin_reset(db: Session, admin: User, user: User) -> None:
    """For someone who lost the phone and the recovery codes. Their sessions end too."""
    if not user.totp_enabled and user.totp_secret_enc is None:
        raise Conflict("Two-factor sign-in is not on for this account.")
    _clear(user)
    user.token_version += 1
    audit.append(
        db, admin.id, admin.role.value, "MFA_DISABLED", user.public_id, {"by": "administrator"}
    )
    db.commit()


def complete_login(db: Session, mfa_token: str, code: str, ip: str | None) -> User:
    """Second sign-in step. Wrong codes count towards the same lockout as wrong passwords."""
    try:
        user_id, version = decode_mfa_token(mfa_token)
    except TokenError:
        raise AuthFailed("This sign-in step has expired. Start again.") from None
    user = db.get(User, user_id)
    if user is None or user.token_version != version or not user.totp_enabled:
        raise AuthFailed("This sign-in step has expired. Start again.")
    now = clock.now_utc()
    if user.locked_until is not None and user.locked_until > now:
        raise AuthFailed(WRONG_CODE)
    if user.locked_until is not None:  # lockout served
        user.locked_until = None
        user.failed_logins = 0

    method = _check_factor(user, code)
    if method is None:
        register_failed_attempt(db, user, ip)
        audit.append(
            db, user.id, user.role.value, "LOGIN_FAIL", user.public_id, {"reason": "BAD_MFA"}
        )
        db.commit()
        raise AuthFailed(WRONG_CODE)

    if not user.is_active:
        raise AccountNotUsable("This account has been disabled.")
    if user.approval_status != ApprovalStatus.APPROVED:
        raise AccountNotUsable("Your account is not approved.")
    user.failed_logins = 0
    user.locked_until = None
    audit.append(db, user.id, user.role.value, "LOGIN_SUCCESS", user.public_id, {"mfa": method})
    if method == "recovery":
        left = len(json.loads(user.recovery_codes_json or "[]"))
        audit.append(
            db, user.id, user.role.value, "MFA_RECOVERY_USED", user.public_id, {"left": left}
        )
    db.commit()
    return user
