"""Auth endpoints: register, sign in/out, current user, change password, doctor activation."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock
from app.core.net import client_ip
from app.core.ratelimit import limiter
from app.core.security import (
    clear_session_cookies,
    create_access_token,
    create_mfa_token,
    session_ends_by,
    set_session_cookies,
)
from app.db import get_db
from app.deps import get_current_user
from app.errors import NotAuthenticated
from app.models import User
from app.schemas import (
    ActivateIn,
    ChangePasswordIn,
    LoginIn,
    MeOut,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnableOut,
    MfaEnrolIn,
    MfaEnrolOut,
    MfaLoginIn,
    MfaRequiredOut,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.services import account_service as accounts
from app.services import mfa_service as mfa

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit_signup(request: Request, action: str) -> None:
    limiter.check(f"{action}:ip:{client_ip(request)}", get_settings().signup_rate_per_minute)


@router.post("/register", response_model=UserOut, status_code=201)
def register(request: Request, data: RegisterIn, db: Session = Depends(get_db)) -> User:
    _limit_signup(request, "register")
    return accounts.register_user(db, data)


@router.post("/login", response_model=TokenOut | MfaRequiredOut)
def login(
    request: Request, data: LoginIn, response: Response, db: Session = Depends(get_db)
) -> TokenOut | MfaRequiredOut:
    ip = client_ip(request)
    per_minute = get_settings().login_rate_per_minute
    # Two independent limits: one address cannot try many accounts, and one account cannot be
    # hammered from many addresses (it only waits out the minute; the lockout rules still apply).
    limiter.check(f"login:ip:{ip}", per_minute)
    limiter.check(f"login:account:{data.email}", per_minute)
    user = accounts.authenticate(db, data.email, data.password, ip=ip)
    if user.totp_enabled:
        return MfaRequiredOut(mfa_token=create_mfa_token(user.id, user.token_version))
    token, claims = create_access_token(user.id, user.token_version)
    set_session_cookies(response, token, claims)
    return TokenOut(access_token=token, role=user.role, name=user.name)


@router.post("/login/mfa", response_model=TokenOut)
def login_mfa(
    request: Request, data: MfaLoginIn, response: Response, db: Session = Depends(get_db)
) -> TokenOut:
    ip = client_ip(request)
    per_minute = get_settings().login_rate_per_minute
    limiter.check(f"login:ip:{ip}", per_minute)
    limiter.check(
        f"mfa:token:{hashlib.sha256(data.mfa_token.encode()).hexdigest()[:24]}", per_minute
    )
    user = mfa.complete_login(db, data.mfa_token, data.code, ip)
    token, claims = create_access_token(user.id, user.token_version)
    set_session_cookies(response, token, claims)
    return TokenOut(access_token=token, role=user.role, name=user.name)


@router.post("/mfa/enrol", response_model=MfaEnrolOut)
def mfa_enrol(
    data: MfaEnrolIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MfaEnrolOut:
    limiter.check(f"mfa:user:{user.id}", 10)
    return mfa.begin_enrol(db, user, data.password)


@router.post("/mfa/enable", response_model=MfaEnableOut)
def mfa_enable(
    data: MfaCodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MfaEnableOut:
    limiter.check(f"mfa:user:{user.id}", 10)
    return MfaEnableOut(recovery_codes=mfa.enable(db, user, data.code))


@router.post("/mfa/disable", status_code=204)
def mfa_disable(
    data: MfaDisableIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    limiter.check(f"mfa:user:{user.id}", 10)
    mfa.disable(db, user, data.password, data.code)


@router.post("/logout", status_code=204)
def logout(
    response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    accounts.logout(db, user)
    clear_session_cookies(response)


@router.get("/me", response_model=MeOut)
def me(request: Request, user: User = Depends(get_current_user)) -> MeOut:
    claims = request.state.claims
    return MeOut(
        **UserOut.model_validate(user).model_dump(),
        session_expires_at=claims.expires_at,
        session_ends_by=session_ends_by(claims.auth_time),
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenOut:
    """Renew a session that is still valid, on the person's say-so (the page asks first).

    Only a live session can be renewed, and never past `session_max_hours` after the original
    sign-in: the cap is measured from the first sign-in, which every renewed token carries along.
    """
    limiter.check(f"refresh:user:{user.id}", 10)
    claims = request.state.claims
    if clock.now_utc() >= session_ends_by(claims.auth_time):
        raise NotAuthenticated()
    token, fresh = create_access_token(user.id, user.token_version, claims.auth_time)
    set_session_cookies(response, token, fresh)
    audit.append(db, user.id, user.role.value, "SESSION_RENEWED", user.public_id, {})
    db.commit()
    return TokenOut(access_token=token, role=user.role, name=user.name)


@router.post("/change-password", status_code=204)
def change_password(
    data: ChangePasswordIn,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    # The current-password check is a password oracle for anyone holding a stolen session, so it
    # gets the same per-minute budget as sign-in.
    limiter.check(f"change-password:user:{user.id}", get_settings().login_rate_per_minute)
    accounts.change_password(db, user, data.current_password, data.new_password)
    clear_session_cookies(response)  # all sessions were invalidated; sign in again


@router.post("/activate", status_code=204)
def activate(request: Request, data: ActivateIn, db: Session = Depends(get_db)) -> None:
    _limit_signup(request, "activate")
    accounts.activate_doctor(
        db,
        email=data.email,
        token=data.token,
        login_password=data.login_password,
        signing_password=data.signing_password,
    )
