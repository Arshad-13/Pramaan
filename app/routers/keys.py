"""Signing-key endpoints for doctors: list own keys and rotate (Spec Section 7.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import KeyOut, RotateKeyIn
from app.services import key_service

router = APIRouter(prefix="/keys", tags=["keys"])

DoctorUser = Depends(require_role(Role.doctor))


@router.get("/mine", response_model=list[KeyOut])
def my_keys(doctor: User = DoctorUser, db: Session = Depends(get_db)) -> list[KeyOut]:
    return [
        KeyOut(
            key_id=k.key_id,
            status=k.status.value,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
            revoke_reason=k.revoke_reason,
        )
        for k in key_service.list_keys(db, doctor)
    ]


@router.post("/rotate", response_model=KeyOut)
def rotate(data: RotateKeyIn, doctor: User = DoctorUser, db: Session = Depends(get_db)) -> KeyOut:
    key = key_service.rotate_key(
        db, doctor, data.current_signing_password, data.new_signing_password
    )
    return KeyOut(
        key_id=key.key_id,
        status=key.status.value,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
        revoke_reason=key.revoke_reason,
    )
