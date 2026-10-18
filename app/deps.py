"""FastAPI dependencies: who is calling, and are they allowed? (Spec Sections 8.1, 8.2)

`get_current_user`:
  - reads the session from the HttpOnly cookie, or from `Authorization: Bearer` (scripts/tests);
  - loads the user from the database on EVERY request and rejects inactive, unapproved or
    token-version-mismatched accounts, so deactivation and logout take effect immediately;
  - for cookie sessions, requires a valid CSRF header on state-changing methods (Bearer tokens are
    not sent automatically by browsers, so they need no CSRF check).
`require_role(...)` adds the role check. Roles always come from the database, never from the token.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.crypto import constant_time_equal
from app.core.security import (
    CSRF_HEADER,
    SESSION_COOKIE,
    TokenError,
    csrf_token_for,
    decode_access_token,
)
from app.db import get_db
from app.errors import Forbidden, NotAuthenticated
from app.models import ApprovalStatus, Role, User

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _extract_token(request: Request) -> tuple[str | None, str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None, "bearer"
    return request.cookies.get(SESSION_COOKIE), "cookie"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token, source = _extract_token(request)
    if not token:
        raise NotAuthenticated()
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise NotAuthenticated() from None

    user = db.get(User, claims.user_id)
    if (
        user is None
        or not user.is_active
        or user.approval_status != ApprovalStatus.APPROVED
        or user.token_version != claims.token_version
    ):
        raise NotAuthenticated()

    if source == "cookie" and request.method not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not constant_time_equal(supplied, csrf_token_for(claims.jti)):
            raise Forbidden("Missing or invalid CSRF token.")

    request.state.jti = claims.jti
    return user


def require_role(*roles: Role) -> Callable[..., User]:
    allowed = frozenset(roles)

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise Forbidden()
        return user

    return dependency
