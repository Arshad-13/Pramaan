"""Create the demo world: accounts, prescription history and ready-made sample files (Phase 10).

Usage : python scripts/seed_demo.py --reset            (wipes the local database and storage/)
        python scripts/seed_demo.py --reset --samples samples/demo
Makes  : an admin and an auditor, two activated doctors, two approved pharmacists, four patients,
         about 18 ordinary prescriptions (so the anomaly model has a baseline), and one of each
         demo case: ready to dispense, already used, expired, revoked, suspicious, controlled.
With --samples it also writes each case's PDF and QR text, and forged variants of the ready one
(edited image, white-box overlay, hidden text, extra medicine, photographs, one-character QR).

Everything goes through the real API (in-process), so keys, signatures, encryption and the audit
log are exactly what a live run produces. The passwords below are DEMO values for a local machine.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core import audit, clock  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import ApprovalStatus, Role, User  # noqa: E402

ADMIN = ("admin@pramaan.test", "Admin-Demo-2026", "Site Admin")
AUDITOR = ("auditor@pramaan.test", "Auditor-Demo-2026", "Anita Auditor")
SIGNING_PASSWORD = "Doctor-Signing-Phrase-9"  # noqa: S105 - local demo value
DOCTORS = [
    ("dr.shah@clinic.test", "Doctor-Login-2026", "Dr. A. Shah", "GJ-12345", "Shah Clinic, Surat"),
    (
        "dr.iyer@clinic.test",
        "Doctor-Login-2026",
        "Dr. M. Iyer",
        "MH-70421",
        "Iyer Diabetes Centre, Pune",
    ),
]
PHARMACISTS = [
    ("meera@citypharm.test", "Pharma-Secret-2026", "Meera Shah", "PH-2201", "City Pharmacy"),
    ("rohan@medplus.test", "Pharma-Secret-2026", "Rohan Gupta", "PH-3310", "MedPlus Chemists"),
]
PATIENTS = [
    ("ravi.patel@example.test", "Patient-Demo-2026", "Ravi Patel"),
    ("sneha.rao@example.test", "Patient-Demo-2026", "Sneha Rao"),
    ("kabir.khan@example.test", "Patient-Demo-2026", "Kabir Khan"),
    ("anita.desai@example.test", "Patient-Demo-2026", "Anita Desai"),
]

READY_MEDICINES = [
    {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5},
    {"name": "Paracetamol", "dose_mg": 650, "frequency": "SOS", "duration_days": 3},
]
HISTORY_SHAH = [
    [("Paracetamol", 500, "TDS", 3)],
    [("Amoxicillin", 500, "TDS", 5), ("Paracetamol", 500, "SOS", 3)],
    [("Cetirizine", 10, "HS", 7)],
    [("Azithromycin", 500, "OD", 3), ("Paracetamol", 650, "SOS", 3)],
    [("Omeprazole", 20, "OD", 14), ("Domperidone", 10, "TDS", 5)],
    [("Ibuprofen", 400, "TDS", 5), ("Pantoprazole", 40, "OD", 5)],
    [("Cefixime", 200, "BD", 5)],
    [("Metronidazole", 400, "TDS", 5), ("Ondansetron", 4, "BD", 2)],
    [("Doxycycline", 100, "BD", 7)],
    [("Montelukast", 10, "HS", 14), ("Levocetirizine", 5, "HS", 14)],
]
HISTORY_IYER = [
    [("Metformin", 500, "BD", 30)],
    [("Metformin", 850, "BD", 30), ("Glimepiride", 2, "OD", 30)],
    [("Atorvastatin", 20, "HS", 30), ("Metformin", 500, "BD", 30)],
    [("Telmisartan", 40, "OD", 30)],
    [("Gliclazide", 80, "BD", 30), ("Metformin", 500, "BD", 30)],
    [("Amlodipine", 5, "OD", 30), ("Telmisartan", 40, "OD", 30)],
    [("Metformin", 1000, "BD", 30), ("Atorvastatin", 10, "HS", 30)],
    [("Folic Acid", 5, "OD", 30), ("Metformin", 500, "BD", 30)],
]


@dataclass
class DemoWorld:
    admin: tuple[str, str]
    auditor: tuple[str, str]
    doctors: list[tuple[str, str]]
    pharmacists: list[tuple[str, str]]
    patients: list[tuple[str, str]]
    signing_password: str = SIGNING_PASSWORD
    rx: dict[str, str] = field(default_factory=dict)  # case label -> prescription id
    qr: dict[str, str] = field(default_factory=dict)  # case label -> QR text
    pdf: dict[str, bytes] = field(default_factory=dict)  # case label -> original PDF


def _bearer(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, f"login failed for {email}: {response.text}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _bootstrap(db, email: str, password: str, name: str, role: Role) -> None:
    user = User(
        email=email,
        name=name,
        role=role,
        password_hash=hash_password(password),
        approval_status=ApprovalStatus.APPROVED,
    )
    db.add(user)
    db.flush()
    audit.append(
        db, None, "seed", "USER_REGISTER", user.public_id, {"role": role.value, "via": "seed"}
    )


def seed(client: TestClient) -> DemoWorld:
    """Build the demo world through `client`. The database must be empty."""
    from app.config import get_settings
    from app.db import SessionLocal

    settings = get_settings()
    settings.rate_limit_enabled = False  # a script signing in many times is not an attack

    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            raise SystemExit("The database already has accounts. Run with --reset to start clean.")
        _bootstrap(db, *ADMIN[:2], ADMIN[2], Role.admin)
        _bootstrap(db, *AUDITOR[:2], AUDITOR[2], Role.auditor)
        db.commit()
    admin = _bearer(client, ADMIN[0], ADMIN[1])

    for email, password, name, licence, org in DOCTORS:
        created = client.post(
            "/api/admin/users",
            headers=admin,
            json={"email": email, "name": name, "license_no": licence, "org_name": org},
        )
        assert created.status_code == 201, created.text
        activated = client.post(
            "/api/auth/activate",
            json={
                "email": email,
                "token": created.json()["activation_token"],
                "login_password": password,
                "signing_password": SIGNING_PASSWORD,
            },
        )
        assert activated.status_code == 204, activated.text

    for email, password, name, licence, org in PHARMACISTS:
        registered = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "name": name,
                "password": password,
                "role": "pharmacist",
                "license_no": licence,
                "org_name": org,
            },
        )
        assert registered.status_code == 201, registered.text
        approved = client.post(
            f"/api/admin/users/{registered.json()['public_id']}/approve", headers=admin
        )
        assert approved.status_code == 200, approved.text

    for email, password, name in PATIENTS:
        registered = client.post(
            "/api/auth/register",
            json={"email": email, "name": name, "password": password, "role": "patient"},
        )
        assert registered.status_code == 201, registered.text

    world = DemoWorld(
        admin=ADMIN[:2],
        auditor=AUDITOR[:2],
        doctors=[(d[0], d[1]) for d in DOCTORS],
        pharmacists=[(p[0], p[1]) for p in PHARMACISTS],
        patients=[(p[0], p[1]) for p in PATIENTS],
    )
    shah = _bearer(client, DOCTORS[0][0], DOCTORS[0][1])
    iyer = _bearer(client, DOCTORS[1][0], DOCTORS[1][1])
    patient_ids = {
        email: client.get("/api/patients/lookup", params={"email": email}, headers=shah).json()[
            "public_id"
        ]
        for email, _, _ in PATIENTS
    }
    patient_emails = [p[0] for p in PATIENTS]

    def issue(headers, patient_email, meds, *, override=None, notes="", require_pin=True, age=None):
        body = {
            "patient_id": patient_ids[patient_email],
            "medicines": (
                [
                    {"name": n, "dose_mg": d, "frequency": f, "duration_days": days}
                    for n, d, f, days in meds
                ]
                if isinstance(meds[0], tuple)
                else meds
            ),
            "notes": notes,
            "validity_days": 30,
            "max_fills": 1,
            "signing_password": SIGNING_PASSWORD,
            "require_pin": require_pin,
        }
        if age is not None:
            body["age_years"] = age
        if override:
            body["override_reason"] = override
        response = client.post("/api/prescriptions", headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()["rx_id"]

    def pdf_of(headers, rx_id) -> bytes:
        response = client.get(f"/api/prescriptions/{rx_id}/pdf", headers=headers)
        assert response.status_code == 200, response.text
        return response.content

    def register_case(label, headers, rx_id):
        world.rx[label] = rx_id
        world.pdf[label] = pdf_of(headers, rx_id)
        from app.ai import samples
        from app.core.qr import decode_qr

        world.qr[label] = decode_qr(samples.rasterize(world.pdf[label])) or ""

    # --- an expired prescription: issued 45 days ago under a frozen clock -------------------------
    past = clock.now_utc() - timedelta(days=45)
    clock.freeze(past)
    try:
        old_shah = _bearer(client, DOCTORS[0][0], DOCTORS[0][1])
        rx_id = issue(
            old_shah, patient_emails[1], [("Cetirizine", 10, "HS", 7)], notes="Expired sample"
        )
        register_case("expired", old_shah, rx_id)
    finally:
        clock.freeze(None)

    # --- ordinary history, so each doctor has a baseline for the anomaly model --------------------
    for i, meds in enumerate(HISTORY_SHAH):
        issue(shah, patient_emails[i % len(patient_emails)], meds)
    for i, meds in enumerate(HISTORY_IYER):
        issue(iyer, patient_emails[(i + 1) % len(patient_emails)], meds)

    # --- the demo cases ----------------------------------------------------------------------------
    ready = issue(
        shah, patient_emails[0], READY_MEDICINES, notes="Take after food. Avoid alcohol.", age=34
    )
    register_case("ready", shah, ready)

    controlled = issue(
        shah, patient_emails[2], [("Alprazolam", 1, "OD", 7)], notes="Controlled sample"
    )
    register_case("controlled", shah, controlled)

    used = issue(
        shah, patient_emails[3], [("Amoxicillin", 500, "TDS", 5)], notes="Already dispensed sample"
    )
    register_case("used", shah, used)
    meera = _bearer(client, PHARMACISTS[0][0], PHARMACISTS[0][1])
    anita = _bearer(client, PATIENTS[3][0], PATIENTS[3][1])
    pin = client.get(f"/api/prescriptions/{used}/pin", headers=anita).json()["pin"]
    dispensed = client.post(
        f"/api/prescriptions/{used}/dispense",
        headers=meera,
        json={"qr_string": world.qr["used"], "patient_pin": pin},
    )
    assert dispensed.status_code == 200, dispensed.text

    revoked = issue(shah, patient_emails[1], [("Ibuprofen", 400, "TDS", 5)], notes="Revoked sample")
    register_case("revoked", shah, revoked)
    assert client.post(f"/api/prescriptions/{revoked}/revoke", headers=shah).status_code == 200

    suspicious = issue(
        shah,
        patient_emails[0],
        [("Zorbitrex", 50, "BD", 5)],
        override="Imported brand named by the patient; confirmed with the manufacturer.",
        notes="Suspicious sample",
    )
    register_case("suspicious", shah, suspicious)
    return world


def write_samples(world: DemoWorld, out: Path) -> None:
    """Forged variants of the 'ready' prescription, plus plain copies of every case."""
    from app.ai import samples

    out.mkdir(parents=True, exist_ok=True)
    for label, pdf in world.pdf.items():
        (out / f"{label}.pdf").write_bytes(pdf)
        (out / f"{label}.qr.txt").write_text(world.qr[label], encoding="utf-8")
    pdf = world.pdf["ready"]
    page = samples.rasterize(pdf)
    payload = {"medicines": READY_MEDICINES}
    forged = samples.edit_medicine(page, payload, 0, dose_mg=800)
    (out / "ready_forged_dose_800mg.png").write_bytes(samples.to_png(forged))
    (out / "ready_forged_dose_photo.jpg").write_bytes(
        samples.to_jpeg(samples.photograph(forged, 9), 90)
    )
    (out / "ready_genuine_photo.jpg").write_bytes(samples.to_jpeg(samples.photograph(page, 11), 90))
    (out / "ready_forged_overlay.pdf").write_bytes(
        samples.pdf_overlay_edit(pdf, "med_0_dose", "900 mg")
    )
    (out / "ready_forged_hidden_text.pdf").write_bytes(
        samples.pdf_hidden_text_edit(pdf, "med_0_dose", "900 mg")
    )
    extra = samples.add_medicine_row(
        page, 2, {"name": "Tramadol", "dose_mg": 100, "frequency": "TDS", "duration_days": 10}
    )
    (out / "ready_forged_extra_medicine.png").write_bytes(samples.to_png(extra))
    (out / "ready_forged_scribble.png").write_bytes(
        samples.to_png(samples.add_margin_text(page, "Refill x10 - Dr A. Shah"))
    )
    code = world.qr["ready"]
    flipped = code[:-3] + ("A" if code[-3] != "A" else "B") + code[-2:]
    (out / "ready_forged_qr.qr.txt").write_text(flipped, encoding="utf-8")


def reset_database() -> None:
    from app import models
    from app.config import get_settings
    from app.db import get_engine

    settings = get_settings()
    engine = get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    storage = Path(settings.storage_dir)
    if storage.is_dir():
        for path in storage.glob("*.pdf.enc"):
            path.unlink()
    Path(settings.anchor_file).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="wipe the local database and storage first"
    )
    parser.add_argument("--samples", help="folder to write sample files into")
    args = parser.parse_args()

    from app.db import init_db
    from app.main import create_app

    if args.reset:
        reset_database()
    init_db()
    with TestClient(create_app()) as client:
        world = seed(client)
    if args.samples:
        write_samples(world, Path(args.samples))
        print(f"Sample files written to {args.samples}")
    print("\nDemo accounts (local demo passwords)")
    print("  admin      ", *world.admin)
    print("  auditor    ", *world.auditor)
    for who, rows in (
        ("doctor", world.doctors),
        ("pharmacist", world.pharmacists),
        ("patient", world.patients),
    ):
        for email, password in rows:
            print(f"  {who:<11}", email, password)
    print(f"  signing password for both doctors: {world.signing_password}")
    print("\nCases:", ", ".join(world.rx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
