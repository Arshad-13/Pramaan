"""Shared test helpers: make users, sign in, read the database with short-lived sessions."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.core import audit
from app.core.security import hash_password
from app.db import SessionLocal
from app.models import ApprovalStatus, Role, User

PASSWORD = "correct-horse-battery"
SIGNING_PASSWORD = "another-long-secret-phrase"


@contextmanager
def session():
    """Short-lived session: always closed, so SQLite's write lock is released."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def make_user(
    email: str,
    role: Role,
    *,
    password: str | None = PASSWORD,
    approval: ApprovalStatus = ApprovalStatus.APPROVED,
    name: str | None = None,
    is_active: bool = True,
) -> str:
    """Insert a user directly; returns the public_id."""
    with session() as db:
        user = User(
            email=email,
            name=name or email.split("@")[0].title(),
            role=role,
            password_hash=hash_password(password) if password else None,
            license_no="LIC-1" if role in (Role.doctor, Role.pharmacist) else None,
            org_name="Org" if role in (Role.doctor, Role.pharmacist) else None,
            approval_status=approval,
            is_active=is_active,
            patient_code=f"T-{uuid.uuid4().hex[:8].upper()}" if role == Role.patient else None,
        )
        db.add(user)
        db.flush()
        audit.append(db, None, "test", "USER_REGISTER", user.public_id, {"role": role.value})
        db.commit()
        return user.public_id


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def bearer(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = login(client, email, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def get_user(email: str) -> User:
    from sqlalchemy import select

    with session() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        db.expunge(user)
        return user
