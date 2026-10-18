"""Verification and dispensing endpoints for pharmacists (Spec Section 12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import DispenseIn, DispenseOut, VerifyOut, VerifyQRIn
from app.services import verification_service as verification

router = APIRouter(tags=["verification"])

PharmacistUser = Depends(require_role(Role.pharmacist))


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/verify/qr", response_model=VerifyOut)
def verify_qr(
    data: VerifyQRIn,
    request: Request,
    pharmacist: User = PharmacistUser,
    db: Session = Depends(get_db),
) -> VerifyOut:
    return verification.verify_qr(db, pharmacist, data.qr_string, _ip(request))


@router.post("/prescriptions/{rx_id}/dispense", response_model=DispenseOut)
def dispense(
    rx_id: str,
    data: DispenseIn,
    request: Request,
    pharmacist: User = PharmacistUser,
    db: Session = Depends(get_db),
) -> dict:
    return verification.dispense(
        db,
        pharmacist,
        rx_id,
        data.qr_string,
        data.patient_pin,
        data.patient_identity_checked,
        _ip(request),
    )
