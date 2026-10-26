"""Auth endpoints: register, sign in/out, current user, change password, doctor activation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.net import client_ip
from app.core.ratelimit import limiter
from app.core.security import clear_session_cookies, create_access_token, set_session_cookies
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import ActivateIn, ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from app.services import account_service as accounts

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit_signup(request: Request, action: str) -> None:
    limiter.check(f"{action}:ip:{client_ip(request)}", get_settings().signup_rate_per_minute)


@router.post("/register", response_model=UserOut, status_code=201)
def register(request: Request, data: RegisterIn, db: Session = Depends(get_db)) -> User:
    _limit_signup(request, "register")
    return accounts.register_user(db, data)


@router.post("/login", response_model=TokenOut)
def login(
    request: Request, data: LoginIn, response: Response, db: Session = Depends(get_db)
) -> TokenOut:
    ip = client_ip(request)
    per_minute = get_settings().login_rate_per_minute
    # Two independent limits: one address cannot try many accounts, and one account cannot be
    # hammered from many addresses (it only waits out the minute; the lockout rules still apply).
    limiter.check(f"login:ip:{ip}", per_minute)
    limiter.check(f"login:account:{data.email}", per_minute)
    user = accounts.authenticate(db, data.email, data.password, ip=ip)
    token, claims = create_access_token(user.id, user.token_version)
    set_session_cookies(response, token, claims)
    return TokenOut(access_token=token, role=user.role, name=user.name)


@router.post("/logout", status_code=204)
def logout(
    response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    accounts.logout(db, user)
    clear_session_cookies(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


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
