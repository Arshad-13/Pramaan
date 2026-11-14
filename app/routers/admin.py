"""Admin and audit endpoints (Spec Section 12).

Roles: admin manages accounts; auditor reads the audit log and runs integrity checks. Neither can
change the audit log; admins cannot read it.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.db import get_db
from app.deps import require_role
from app.errors import NotFound
from app.models import AuditLog, Role, SecurityEvent, Severity, User
from app.schemas import (
    ActivationOut,
    AuditPageOut,
    AuditVerifyOut,
    CreateDoctorIn,
    ModelStatusOut,
    SecurityEventOut,
    SecurityEventUpdateIn,
    UserListOut,
    UserOut,
)
from app.services import account_service as accounts
from app.services import events, prescription_service
from app.services import mfa_service as mfa

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
    q: str | None = Query(None, max_length=80),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = AdminUser,
    db: Session = Depends(get_db),
) -> UserListOut:
    items, total = accounts.list_users(
        db, role=role, approval_status=approval_status, q=q, limit=limit, offset=offset
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


ActorRole = Literal["doctor", "patient", "pharmacist", "admin", "auditor"]
EXPORT_MAX_ROWS = 5000


def _filtered_audit(
    action: str | None,
    actor_role: str | None,
    resource: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if actor_role:
        query = query.where(AuditLog.actor_role == actor_role)
    if resource:
        query = query.where(AuditLog.resource_id.icontains(resource, autoescape=True))
    if since:
        query = query.where(AuditLog.ts >= since)
    if until:
        query = query.where(AuditLog.ts <= until)
    return query


@router.post("/users/{user_id}/reset-mfa", response_model=UserOut)
def reset_mfa(user_id: str, admin: User = AdminUser, db: Session = Depends(get_db)) -> User:
    """For someone who lost their phone and recovery codes. Audited; ends their sessions."""
    user = accounts.get_user_by_public_id(db, user_id)
    mfa.admin_reset(db, admin, user)
    return user


@router.get("/audit", response_model=AuditPageOut)
def list_audit(
    action: str | None = Query(None, max_length=40),
    actor_role: ActorRole | None = None,
    resource: str | None = Query(None, max_length=64),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auditor: User = AuditorUser,
    db: Session = Depends(get_db),
) -> AuditPageOut:
    query = _filtered_audit(action, actor_role, resource, since, until)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditLog.seq.desc()).limit(limit).offset(offset)).all()
    return AuditPageOut(items=list(rows), total=total, actions=sorted(audit.AUDIT_ACTIONS))


_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: object) -> str:
    """Spreadsheet programs run cells that start with = + - @ as formulas: defuse them."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


@router.get("/audit/export")
def export_audit(
    action: str | None = Query(None, max_length=40),
    actor_role: ActorRole | None = None,
    resource: str | None = Query(None, max_length=64),
    since: datetime | None = None,
    until: datetime | None = None,
    auditor: User = AuditorUser,
    db: Session = Depends(get_db),
) -> Response:
    """The filtered log as CSV (newest first, at most EXPORT_MAX_ROWS). The export is itself
    logged, so who took a copy and when is on the record."""
    query = _filtered_audit(action, actor_role, resource, since, until)
    rows = db.scalars(query.order_by(AuditLog.seq.desc()).limit(EXPORT_MAX_ROWS)).all()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        ["seq", "time_utc", "actor_id", "actor_role", "action", "resource", "details", "entry_hash"]
    )
    for r in rows:
        writer.writerow(
            [
                r.seq,
                r.ts.isoformat(),
                r.actor_id,
                _csv_cell(r.actor_role),
                _csv_cell(r.action),
                _csv_cell(r.resource_id),
                _csv_cell(r.details_json),
                r.entry_hash,
            ]
        )
    audit.append(db, auditor.id, auditor.role.value, "AUDIT_EXPORTED", None, {"rows": len(rows)})
    db.commit()
    stamp = clock.now_utc().strftime("%Y%m%d-%H%M%S")
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="pramaan-audit-{stamp}.csv"'},
    )


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
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] | None = None,
    severity: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    _user: User = AdminOrAuditor,
    db: Session = Depends(get_db),
) -> list[SecurityEvent]:
    query = select(SecurityEvent)
    if status:
        query = query.where(SecurityEvent.status == status)
    if severity:
        query = query.where(SecurityEvent.severity == Severity(severity))
    return list(db.scalars(query.order_by(SecurityEvent.id.desc()).limit(limit)).all())


@router.patch("/security-events/{event_id}", response_model=SecurityEventOut)
def update_security_event(
    event_id: int,
    data: SecurityEventUpdateIn,
    admin: User = AdminUser,
    db: Session = Depends(get_db),
) -> SecurityEvent:
    """Acknowledge or resolve an alert. The auditor can read alerts but not close them, so the
    person who reviews the log is not the person who clears what it flagged."""
    event = db.get(SecurityEvent, event_id)
    if event is None:
        raise NotFound("Alert not found.")
    event.status = data.status
    event.note = data.note
    if data.status == "OPEN":
        event.handled_by = None
        event.handled_at = None
    else:
        event.handled_by = admin.id
        event.handled_at = clock.now_utc()
    audit.append(
        db,
        admin.id,
        admin.role.value,
        "SECURITY_EVENT_HANDLED",
        str(event.id),
        {"status": data.status, "event_type": event.event_type},
    )
    db.commit()
    return event


@router.get("/model-status", response_model=ModelStatusOut)
def model_status(_user: User = AdminOrAuditor) -> ModelStatusOut:
    return prescription_service.model_status()
