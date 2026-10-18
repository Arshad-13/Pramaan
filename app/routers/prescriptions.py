"""Prescription endpoints: issue, list, download, revoke, and patient lookup (Spec Section 12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Role, User
from app.schemas import IssueIn, IssueOut, PatientLookupOut, PinOut, PrescriptionOut
from app.services import prescription_service as rx

router = APIRouter(tags=["prescriptions"])

DoctorUser = Depends(require_role(Role.doctor))
DoctorOrPatient = Depends(require_role(Role.doctor, Role.patient))
PatientUser = Depends(require_role(Role.patient))


@router.post("/prescriptions", response_model=IssueOut, status_code=201)
def issue(data: IssueIn, doctor: User = DoctorUser, db: Session = Depends(get_db)) -> IssueOut:
    return rx.issue_prescription(db, doctor, data)


@router.get("/prescriptions/mine", response_model=list[PrescriptionOut])
def mine(user: User = DoctorOrPatient, db: Session = Depends(get_db)) -> list[PrescriptionOut]:
    return rx.list_mine(db, user)


@router.get("/prescriptions/{rx_id}/pdf")
def download_pdf(
    rx_id: str, user: User = DoctorOrPatient, db: Session = Depends(get_db)
) -> Response:
    pdf = rx.get_pdf(db, user, rx_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="prescription-{rx_id[:8]}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/prescriptions/{rx_id}/pin", response_model=PinOut)
def pin(rx_id: str, patient: User = PatientUser, db: Session = Depends(get_db)) -> PinOut:
    return rx.get_pin(db, patient, rx_id)


@router.post("/prescriptions/{rx_id}/revoke", response_model=PrescriptionOut)
def revoke(rx_id: str, doctor: User = DoctorUser, db: Session = Depends(get_db)) -> PrescriptionOut:
    return rx.revoke(db, doctor, rx_id)


@router.get("/patients/lookup", response_model=PatientLookupOut)
def lookup_patient(
    email: str | None = Query(None, max_length=254),
    code: str | None = Query(None, max_length=16),
    _doctor: User = DoctorUser,
    db: Session = Depends(get_db),
) -> PatientLookupOut:
    patient = rx.lookup_patient(db, email=email, code=code)
    return PatientLookupOut(
        public_id=patient.public_id, name=patient.name, patient_code=patient.patient_code
    )
