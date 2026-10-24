"""Admin and audit endpoints (Spec Section 12).

Roles: admin manages accounts; auditor reads the audit log and runs integrity checks. Neither can
change the audit log; admins cannot read it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.db import get_db
from app.deps import require_role
from app.models import AuditLog, Role, SecurityEvent, User
from app.schemas import (
    ActivationOut,
    AuditPageOut,
    AuditVerifyOut,
    CreateDoctorIn,
    SecurityEventOut,
    UserListOut,
    UserOut,
)
from app.services import account_service as accounts
from app.services import events

router = APIRouter(prefix="/admin", tags=["admin"])

AdminUser = Depends(require_role(Role.admin))
AuditorUser = Depends(require_role(Role.auditor))
AdminOrAuditor = Depends(require_role(Role.admin, Role.auditor))


@router.post("/users", response_model=ActivationOut, status_code=201)
def create_doctor(
    data: CreateDoctorIn, admin: User = AdminUser, db: Session = Depends(get_db)
) -> ActivationOut:
    user, token, expires_at = accounts.create_doctor(
        db,
        admin,
        email=data.email,
        name=data.name,
        license_no=data.license_no,
        org_name=data.org_name,
    )
    return ActivationOut(
        user=UserOut.model_validate(user), activation_token=token, expires_at=expires_at
    )


@router.get("/users", response_model=UserListOut)
def list_users(
    role: Literal["doctor", "patient", "pharmacist", "admin", "auditor"] | None = None,
    approval_status: Literal["APPROVED", "PENDING", "REJECTED"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = AdminUser,
    db: Session = Depends(get_db),
) -> UserListOut:
    items, total = accounts.list_users(
        db, role=role, approval_status=approval_status, limit=limit, offset=offset
    )
    return UserListOut(items=[UserOut.model_validate(u) for u in items], total=total)


@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_pharmacist(
    user_id: str, admin: User = AdminUser, db: Session = Depends(get_db)
) -> User:
    return accounts.set_pharmacist_approval(
        db, admin, accounts.get_user_by_public_id(db, user_id), approve=True
    )


@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_pharmacist(user_id: str, admin: User = AdminUser, db: Session = Depends(get_db)) -> User:
    return accounts.set_pharmacist_approval(
        db, admin, accounts.get_user_by_public_id(db, user_id), approve=False
    )


@router.post("/users/{user_id}/reissue-token", response_model=ActivationOut)
def reissue_token(
    user_id: str, admin: User = AdminUser, db: Session = Depends(get_db)
) -> ActivationOut:
    user = accounts.get_user_by_public_id(db, user_id)
    token, expires_at = accounts.reissue_activation(db, admin, user)
    return ActivationOut(
        user=UserOut.model_validate(user), activation_token=token, expires_at=expires_at
    )


@router.patch("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(user_id: str, admin: User = AdminUser, db: Session = Depends(get_db)) -> User:
    return accounts.suspend_user(db, admin, accounts.get_user_by_public_id(db, user_id))


@router.get("/audit", response_model=AuditPageOut)
def list_audit(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auditor: User = AuditorUser,
    db: Session = Depends(get_db),
) -> AuditPageOut:
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.seq.desc()).limit(limit).offset(offset)
    ).all()
    return AuditPageOut(items=list(rows), total=total)


@router.get("/audit/verify", response_model=AuditVerifyOut)
def verify_audit(auditor: User = AuditorUser, db: Session = Depends(get_db)) -> dict:
    result = audit.verify_and_record(db, auditor.id, auditor.role.value)
    events.check_audit_result(db, auditor.id, result)
    db.commit()
    return result


@router.post("/audit/checkpoint", response_model=AuditVerifyOut)
def checkpoint_audit(auditor: User = AuditorUser, db: Session = Depends(get_db)) -> dict:
    audit.create_checkpoint(db, actor_id=auditor.id, actor_role=auditor.role.value)
    db.commit()
    return audit.verify_chain(db)


@router.get("/security-events", response_model=list[SecurityEventOut])
def security_events(
    limit: int = Query(100, ge=1, le=500),
    _user: User = AdminOrAuditor,
    db: Session = Depends(get_db),
) -> list[SecurityEvent]:
    return list(
        db.scalars(select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(limit)).all()
    )
