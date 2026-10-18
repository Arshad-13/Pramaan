"""Auth endpoints: register, sign in/out, current user, change password, doctor activation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.security import clear_session_cookies, create_access_token, set_session_cookies
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import ActivateIn, ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from app.services import account_service as accounts

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)) -> User:
    return accounts.register_user(db, data)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    user = accounts.authenticate(db, data.email, data.password)
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
    accounts.change_password(db, user, data.current_password, data.new_password)
    clear_session_cookies(response)  # all sessions were invalidated; sign in again


@router.post("/activate", status_code=204)
def activate(data: ActivateIn, db: Session = Depends(get_db)) -> None:
    accounts.activate_doctor(
        db,
        email=data.email,
        token=data.token,
        login_password=data.login_password,
        signing_password=data.signing_password,
    )
