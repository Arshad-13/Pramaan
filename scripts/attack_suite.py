"""Attack suite: try to break Pramaan the way each adversary would, and show what stopped it (Phase 10).

Usage : python scripts/seed_demo.py --reset      (once, to create the demo accounts)
        python scripts/attack_suite.py [--json out.json]
Runs against the local database through the real API (in-process). Every attack creates its own
fresh prescriptions or throw-away accounts, so the seeded demo cases are left as they were. Attacks
that must damage the audit log do it inside a transaction that is rolled back.
Exit code 0 means every attack was detected or blocked.

Each attack is also a test: tests/test_attack_suite.py runs this module against a seeded test
database, so the table below cannot drift from what the code really does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402
from seed_demo import READY_MEDICINES, DemoWorld  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.ai import samples  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.core import audit  # noqa: E402
from app.core import pdf_layout as layout  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import AuditLog, Dispense, SecurityEvent  # noqa: E402


@dataclass
class Result:
    number: int
    attack: str
    control: str
    detected: bool
    evidence: str


class Ctx:
    """Everything an attack needs: the client, the seeded accounts and a few helpers."""

    def __init__(self, client: TestClient, world: DemoWorld) -> None:
        self.client = client
        self.world = world
        self._tokens: dict[str, dict[str, str]] = {}
        self.signing_password = world.signing_password

    # --- accounts -----------------------------------------------------------------------------
    def login(self, email: str, password: str) -> dict[str, str]:
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, f"{email}: {response.text}"
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def token(self, email: str, password: str) -> dict[str, str]:
        if email not in self._tokens:
            self._tokens[email] = self.login(email, password)
        return self._tokens[email]

    @property
    def doctor(self) -> dict[str, str]:
        return self.token(*self.world.doctors[0])

    @property
    def admin(self) -> dict[str, str]:
        return self.token(*self.world.admin)

    @property
    def pharmacist_a(self) -> dict[str, str]:
        return self.token(*self.world.pharmacists[0])

    @property
    def pharmacist_b(self) -> dict[str, str]:
        return self.token(*self.world.pharmacists[1])

    def patient(self, index: int = 0) -> dict[str, str]:
        return self.token(*self.world.patients[index])

    # --- prescriptions -------------------------------------------------------------------------
    def issue(
        self, medicines: list[dict] | None = None, patient_index: int = 0
    ) -> tuple[str, str, bytes]:
        """Issue a fresh prescription as Dr. Shah. Returns (rx_id, qr_text, original_pdf)."""
        email = self.world.patients[patient_index][0]
        pid = self.client.get(
            "/api/patients/lookup", params={"email": email}, headers=self.doctor
        ).json()["public_id"]
        created = self.client.post(
            "/api/prescriptions",
            headers=self.doctor,
            json={
                "patient_id": pid,
                "medicines": medicines or READY_MEDICINES,
                "notes": "Attack suite",
                "validity_days": 30,
                "max_fills": 1,
                "signing_password": self.signing_password,
            },
        )
        assert created.status_code == 201, created.text
        rx_id = created.json()["rx_id"]
        pdf = self.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=self.doctor).content
        from app.core.qr import decode_qr

        return rx_id, decode_qr(samples.rasterize(pdf)) or "", pdf

    def verify(self, qr: str, headers: dict[str, str] | None = None) -> dict:
        response = self.client.post(
            "/api/verify/qr", headers=headers or self.pharmacist_a, json={"qr_string": qr}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def upload(
        self, data: bytes, name: str = "file", headers: dict[str, str] | None = None
    ) -> dict:
        response = self.client.post(
            "/api/verify/upload",
            headers=headers or self.pharmacist_a,
            files={"file": (name, data, "application/octet-stream")},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def pin(self, rx_id: str, patient_index: int = 0) -> str:
        return self.client.get(
            f"/api/prescriptions/{rx_id}/pin", headers=self.patient(patient_index)
        ).json()["pin"]

    def dispense(
        self, rx_id: str, qr: str, pin: str | None = None, headers: dict[str, str] | None = None
    ):
        body = {"qr_string": qr, **({"patient_pin": pin} if pin is not None else {})}
        return self.client.post(
            f"/api/prescriptions/{rx_id}/dispense", headers=headers or self.pharmacist_a, json=body
        )

    def sql(self, statement: str, **params) -> None:
        with SessionLocal() as db:
            db.execute(text(statement), params)
            db.commit()

    def events(self, kind: str) -> list[SecurityEvent]:
        with SessionLocal() as db:
            return list(db.scalars(select(SecurityEvent).where(SecurityEvent.event_type == kind)))

    def throwaway(self, role: str, suffix: str) -> tuple[str, str]:
        """A disposable pharmacist or doctor account, so lockout attacks never hit the demo users."""
        import uuid

        email = f"attack-{suffix}-{uuid.uuid4().hex[:6]}@example.test"
        password = "Attack-Throwaway-2026"  # noqa: S105 - throw-away local account
        if role == "doctor":
            created = self.client.post(
                "/api/admin/users",
                headers=self.admin,
                json={
                    "email": email,
                    "name": "Dr. Attack Target",
                    "license_no": "AT-1",
                    "org_name": "Attack Clinic",
                },
            )
            assert created.status_code == 201, created.text
            activated = self.client.post(
                "/api/auth/activate",
                json={
                    "email": email,
                    "token": created.json()["activation_token"],
                    "login_password": password,
                    "signing_password": self.signing_password,
                },
            )
            assert activated.status_code == 204, activated.text
        else:
            registered = self.client.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "name": "Attack Target",
                    "password": password,
                    "role": "pharmacist",
                    "license_no": "AT-2",
                    "org_name": "Attack Pharmacy",
                },
            )
            assert registered.status_code == 201, registered.text
            self.client.post(
                f"/api/admin/users/{registered.json()['public_id']}/approve", headers=self.admin
            )
        return email, password


ATTACKS: list[tuple[int, str, Callable[[Ctx], Result]]] = []


def attack(number: int, title: str):
    def register(fn: Callable[[Ctx], tuple[str, bool, str]]):
        def run(ctx: Ctx) -> Result:
            control, detected, evidence = fn(ctx)
            return Result(number, title, control, detected, evidence)

        ATTACKS.append((number, title, run))
        return run

    return register


# --- 1-2: the database --------------------------------------------------------------------------


@attack(1, "Flip one bit of the stored payload in the database")
def a01(ctx: Ctx):
    rx_id, qr, _ = ctx.issue()
    with SessionLocal() as db:
        blob = bytearray(
            db.execute(
                text("SELECT payload_enc FROM prescriptions WHERE id = :i"), {"i": rx_id}
            ).scalar_one()
        )
    blob[len(blob) // 2] ^= 0x01
    ctx.sql("UPDATE prescriptions SET payload_enc = :b WHERE id = :i", b=bytes(blob), i=rx_id)
    body = ctx.verify(qr)
    return (
        "AES-GCM authentication tag + hash check",
        body["result"] == "TAMPERED",
        f"{body['result']} {body['reason_codes']}",
    )


@attack(2, "Extend validity by editing the expires_at column")
def a02(ctx: Ctx):
    rx_id, qr, _ = ctx.issue()
    ctx.sql("UPDATE prescriptions SET expires_at = '2099-01-01 00:00:00' WHERE id = :i", i=rx_id)
    body = ctx.verify(qr)
    return (
        "Plain columns cross-checked against the signed payload",
        body["result"] == "TAMPERED",
        f"{body['result']} {body['reason_codes']}",
    )


# --- 3-5, 7: the page --------------------------------------------------------------------------


@attack(3, "Edit one dose digit in a rendered image (500 mg -> 800 mg)")
def a03(ctx: Ctx):
    rx_id, qr, pdf = ctx.issue()
    forged = samples.edit_medicine(
        samples.rasterize(pdf), {"medicines": READY_MEDICINES}, 0, dose_mg=800
    )
    body = ctx.upload(samples.to_png(forged), "forged.png")
    zones = [z["zone"] for z in body["content_zones"]]
    held = ctx.dispense(rx_id, qr, ctx.pin(rx_id))  # the genuine QR must not redeem the forged page
    ok = body["result"] == "TAMPERED" and zones == ["med_0_dose"] and held.status_code == 409
    reads = [z["read"] for z in body["content_zones"]]
    return (
        "Render-and-diff + OCR against the signed content; dispense hold",
        ok,
        f"{body['result']} field={zones} read={reads}, dispense afterwards={held.status_code}",
    )


@attack(4, "White-box overlay on the PDF text (new dose drawn over the old)")
def a04(ctx: Ctx):
    _, _, pdf = ctx.issue()
    body = ctx.upload(samples.pdf_overlay_edit(pdf, "med_0_dose", "900 mg"), "forged.pdf")
    ok = body["result"] == "TAMPERED" and bool(
        {"HIDDEN_TEXT_OR_OVERLAY", "CONTENT_MISMATCH"} & set(body["reason_codes"])
    )
    return (
        "PDF text layer vs. rendered page vs. signed text",
        ok,
        f"{body['result']} {body['reason_codes']}",
    )


@attack(5, "Add an extra medicine line below the table")
def a05(ctx: Ctx):
    _, _, pdf = ctx.issue()
    forged = samples.add_medicine_row(
        samples.rasterize(pdf),
        2,
        {"name": "Tramadol", "dose_mg": 100, "frequency": "TDS", "duration_days": 10},
    )
    body = ctx.upload(samples.to_png(forged), "forged.png")
    ok = body["result"] == "TAMPERED" and any(
        z["zone"].startswith("med_2_") for z in body["content_zones"]
    )
    return (
        "Blank rows must stay blank (extra-content check)",
        ok,
        f"{body['result']} {[z['zone'] for z in body['content_zones']]}",
    )


@attack(6, "Forge one character of the QR signature")
def a06(ctx: Ctx):
    _, qr, _ = ctx.issue()
    flipped = qr[:-3] + ("A" if qr[-3] != "A" else "B") + qr[-2:]
    body = ctx.verify(flipped)
    ok = body["result"] == "TAMPERED"
    return "ECDSA signature + QR/hash cross-check", ok, f"{body['result']} {body['reason_codes']}"


@attack(7, "Swap in the QR code of another prescription")
def a07(ctx: Ctx):
    _, _, pdf_a = ctx.issue()
    _, _, pdf_b = ctx.issue(patient_index=1)
    page = samples.rasterize(pdf_a)
    other = samples.rasterize(pdf_b)
    x0, y0, x1, y1 = (int(v) for v in _zone_pixels("qr"))
    page[y0:y1, x0:x1] = other[y0:y1, x0:x1]  # cut B's QR out of B's page and paste it onto A's
    body = ctx.upload(samples.to_png(page), "swapped.png")
    ok = body["result"] == "TAMPERED"
    return (
        "The page is checked against the record its own QR names",
        ok,
        f"{body['result']} {body['reason_codes']}",
    )


def _zone_pixels(name: str) -> tuple[float, float, float, float]:
    from app.ai.rectify import zone_box

    return zone_box(layout.ZONES[name])


# --- 8-10: redeeming ----------------------------------------------------------------------------


@attack(8, "Replay the same QR at a second pharmacy")
def a08(ctx: Ctx):
    rx_id, qr, _ = ctx.issue()
    first = ctx.dispense(rx_id, qr, ctx.pin(rx_id))
    body = ctx.verify(qr, ctx.pharmacist_b)
    alerts = [e for e in ctx.events("POSSIBLE_REPLAY") if rx_id in e.details_json]
    ok = first.status_code == 200 and body["result"] == "ALREADY_USED" and len(alerts) == 1
    return (
        "Atomic dispense + cross-pharmacy alert",
        ok,
        f"second scan={body['result']}, MEDIUM alerts={len(alerts)}",
    )


@attack(9, "Concurrent double dispense (20 threads at once)")
def a09(ctx: Ctx):
    rx_id, qr, _ = ctx.issue()
    pin = ctx.pin(rx_id)
    token = ctx.pharmacist_a
    codes: list[int] = []
    gate = threading.Barrier(20)

    def worker() -> None:
        from app.main import app

        with TestClient(app) as client:
            gate.wait()
            response = client.post(
                f"/api/prescriptions/{rx_id}/dispense",
                headers=token,
                json={"qr_string": qr, "patient_pin": pin},
            )
            codes.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with SessionLocal() as db:
        rows = db.scalars(select(Dispense).where(Dispense.rx_id == rx_id)).all()
    ok = codes.count(200) == 1 and len(rows) == 1
    return (
        "Conditional UPDATE + UNIQUE(rx_id, fill_no)",
        ok,
        f"successes={codes.count(200)} of 20, dispense rows={len(rows)}",
    )


@attack(10, "Redeem a photographed QR without the patient's PIN")
def a10(ctx: Ctx):
    rx_id, qr, _ = ctx.issue()
    none = ctx.dispense(rx_id, qr)
    wrong = [ctx.dispense(rx_id, qr, "000000" if i % 2 else "111111").status_code for i in range(3)]
    right = ctx.dispense(rx_id, qr, ctx.pin(rx_id))  # even the right PIN is refused once locked
    with SessionLocal() as db:
        used = db.scalars(select(Dispense).where(Dispense.rx_id == rx_id)).all()
    ok = none.status_code == 400 and 403 in wrong and right.status_code == 423 and not used
    return (
        "Patient-consent PIN + 3-try lock",
        ok,
        f"no PIN={none.status_code}, wrong PINs={wrong}, right PIN after lock={right.status_code}",
    )


# --- 11-14: accounts ------------------------------------------------------------------------------


@attack(11, "Brute-force a login (many wrong passwords)")
def a11(ctx: Ctx):
    email, password = ctx.throwaway("pharmacist", "login")
    settings = get_settings()
    settings.rate_limit_enabled = True
    limiter.reset()
    try:
        codes = [
            ctx.client.post(
                "/api/auth/login", json={"email": email, "password": "wrong-password-1"}
            ).status_code
            for _ in range(7)
        ]
        limiter.reset()
        after = ctx.client.post(
            "/api/auth/login", json={"email": email, "password": password}
        ).status_code
    finally:
        settings.rate_limit_enabled = False
        limiter.reset()
    ok = 429 in codes and after in (401, 403)  # rate limited, then the account itself is locked
    return (
        "Rate limit (IP + account) and account lockout",
        ok,
        f"codes={codes}, correct password after lock={after}",
    )


@attack(12, "Brute-force the signing password")
def a12(ctx: Ctx):
    email, password = ctx.throwaway("doctor", "sign")
    headers = ctx.login(email, password)
    pid = ctx.client.get(
        "/api/patients/lookup", params={"email": ctx.world.patients[0][0]}, headers=headers
    ).json()["public_id"]
    body = {
        "patient_id": pid,
        "medicines": READY_MEDICINES,
        "signing_password": "wrong-signing-password",
    }
    codes = [
        ctx.client.post("/api/prescriptions", headers=headers, json=body).status_code
        for _ in range(7)
    ]
    good = ctx.client.post(
        "/api/prescriptions",
        headers=headers,
        json={**body, "signing_password": ctx.signing_password},
    ).status_code
    alerts = ctx.events("SIGNING_LOCKED")
    ok = 423 in codes and good == 423 and bool(alerts)
    return (
        "Signing-key lockout + MEDIUM alert",
        ok,
        f"codes={codes}, correct password while locked={good}",
    )


@attack(13, "Use a stolen token after logout and after deactivation")
def a13(ctx: Ctx):
    email, password = ctx.throwaway("pharmacist", "token")
    stolen = ctx.login(email, password)
    live = ctx.client.get("/api/auth/me", headers=stolen).status_code
    ctx.client.post("/api/auth/logout", headers=stolen)
    after_logout = ctx.client.get("/api/auth/me", headers=stolen).status_code
    fresh = ctx.login(email, password)
    users = ctx.client.get("/api/admin/users?role=pharmacist&limit=200", headers=ctx.admin).json()[
        "items"
    ]
    target = next(u for u in users if u["email"] == email)
    ctx.client.patch(f"/api/admin/users/{target['public_id']}/deactivate", headers=ctx.admin)
    after_deactivation = ctx.client.get("/api/auth/me", headers=fresh).status_code
    ok = live == 200 and after_logout == 401 and after_deactivation == 401
    return (
        "token_version revoked on logout; role and status read from the DB each request",
        ok,
        f"before={live}, after logout={after_logout}, after deactivation={after_deactivation}",
    )


@attack(14, "A pharmacist calls doctor and admin endpoints")
def a14(ctx: Ctx):
    headers = ctx.pharmacist_a
    attempts = [
        (
            "POST",
            "/api/prescriptions",
            {
                "patient_id": "x",
                "medicines": READY_MEDICINES,
                "signing_password": ctx.signing_password,
            },
        ),
        (
            "POST",
            "/api/admin/users",
            {"email": "evil@example.test", "name": "Evil", "license_no": "1", "org_name": "x"},
        ),
        ("GET", "/api/admin/users", None),
        ("GET", "/api/admin/security-events", None),
        ("GET", "/api/admin/audit", None),
        (
            "POST",
            "/api/keys/rotate",
            {"current_signing_password": "x" * 12, "new_signing_password": "y" * 12},
        ),
        ("GET", "/api/patients/lookup?email=ravi.patel@example.test", None),
    ]
    codes = [ctx.client.request(m, u, headers=headers, json=b).status_code for m, u, b in attempts]
    return (
        "Role x endpoint matrix (require_role)",
        all(c == 403 for c in codes),
        f"statuses={codes}",
    )


# --- 15-16: the log and the model --------------------------------------------------------------------


@attack(15, "Edit an audit row; edit and recompute; truncate the tail")
def a15(ctx: Ctx):
    with SessionLocal() as db:
        audit.create_checkpoint(db)  # a signed, anchored head to compare against
        db.commit()
    outcomes: dict[str, dict] = {}
    for mode in ("edit", "recompute", "truncate"):
        with SessionLocal() as db:
            last = db.scalar(select(AuditLog.seq).order_by(AuditLog.seq.desc()))
            middle = max(2, last // 2)
            if mode == "edit":
                db.execute(
                    text("UPDATE audit_log SET details_json = :d WHERE seq = :s"),
                    {"d": '{"tampered":true}', "s": middle},
                )
            elif mode == "recompute":
                db.execute(
                    text("UPDATE audit_log SET details_json = :d WHERE seq = :s"),
                    {"d": '{"tampered":true}', "s": middle},
                )
                row = db.execute(
                    text("SELECT prev_hash, details_json FROM audit_log WHERE seq = :s"),
                    {"s": middle},
                ).one()
                plain = hashlib.sha256(
                    (row[0] + row[1]).encode()
                ).hexdigest()  # the attacker has no HMAC key
                db.execute(
                    text("UPDATE audit_log SET entry_hash = :h WHERE seq = :s"),
                    {"h": plain, "s": middle},
                )
            else:
                db.execute(text("DELETE FROM audit_log WHERE seq > :s"), {"s": last - 3})
            outcomes[mode] = audit.verify_chain(db)
            db.rollback()  # the real log is left exactly as it was
    ok = all(not r["ok"] for r in outcomes.values())
    detail = ", ".join(
        f"{m}: {'detected' if not r['ok'] else 'MISSED'}" for m, r in outcomes.items()
    )
    return "HMAC hash chain + signed checkpoints + external anchor", ok, detail


@attack(16, "Swap the anomaly model file for another")
def a16(ctx: Ctx):
    import tempfile

    from cryptography.hazmat.primitives.asymmetric import ec

    from app.ai import anomaly, model_io

    settings = get_settings()
    original = settings.anomaly_model_path
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "iforest.joblib"
        model_io.save_model(
            {"forest": "attacker controlled"}, fake, ec.generate_private_key(ec.SECP256R1())
        )
        settings.anomaly_model_path = str(fake)
        anomaly.forget()
        try:
            check = ctx.client.post(
                "/api/prescriptions/risk-check",
                headers=ctx.doctor,
                json={"medicines": READY_MEDICINES},
            ).json()
            rx_id, _, _ = ctx.issue()  # still works: the system carries on with rules only
        finally:
            settings.anomaly_model_path = original
            anomaly.forget()
    alerts = [e for e in ctx.events("MODEL_FILE_INVALID")]
    ok = "MODEL_UNAVAILABLE" in check["warnings"] and bool(rx_id)
    return (
        "Model signature verified before unpickling",
        ok,
        f"warnings={check['warnings']}, HIGH alerts so far={len(alerts)}",
    )


def run_all(ctx: Ctx, only: set[int] | None = None) -> list[Result]:
    results = []
    for number, title, run in sorted(ATTACKS, key=lambda a: a[0]):
        if only and number not in only:
            continue
        try:
            results.append(run(ctx))
        except Exception as exc:  # noqa: BLE001 - an attack that crashes is reported, not hidden
            results.append(
                Result(
                    number, title, "(attack failed to run)", False, f"{type(exc).__name__}: {exc}"
                )
            )
    return results


def table(results: list[Result]) -> str:
    rows = [("#", "Attack", "Control that caught it", "Result", "Evidence")]
    for r in results:
        rows.append(
            (
                str(r.number),
                r.attack,
                r.control,
                "BLOCKED" if r.detected else "** NOT CAUGHT **",
                r.evidence,
            )
        )
    widths = [
        min(max(len(row[i]) for row in rows), cap) for i, cap in enumerate((3, 58, 52, 16, 70))
    ]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(cell[: widths[i]].ljust(widths[i]) for i, cell in enumerate(row)))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def markdown(results: list[Result]) -> str:
    lines = [
        "# Attack suite results",
        "",
        "Produced by `python scripts/attack_suite.py --markdown docs/attack_suite.md` against the seeded",
        "demo database. The same attacks run as tests in `tests/test_attack_suite.py`.",
        "",
        "| # | Attack | Control that caught it | Result | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        evidence = r.evidence.replace("|", "/")
        lines.append(
            f"| {r.number} | {r.attack} | {r.control} | {'Blocked' if r.detected else '**NOT CAUGHT**'} | {evidence} |"
        )
    caught = sum(r.detected for r in results)
    lines += ["", f"**{caught} of {len(results)} attacks detected or blocked.**", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="also write the results to this file")
    parser.add_argument("--markdown", help="also write a Markdown results table to this file")
    parser.add_argument("--only", type=int, nargs="*", help="run only these attack numbers")
    args = parser.parse_args()

    from app.db import init_db
    from app.main import create_app

    init_db()
    app = create_app()
    get_settings().rate_limit_enabled = False
    world = DemoWorld(
        admin=("admin@pramaan.test", "Admin-Demo-2026"),
        auditor=("auditor@pramaan.test", "Auditor-Demo-2026"),
        doctors=[
            ("dr.shah@clinic.test", "Doctor-Login-2026"),
            ("dr.iyer@clinic.test", "Doctor-Login-2026"),
        ],
        pharmacists=[
            ("meera@citypharm.test", "Pharma-Secret-2026"),
            ("rohan@medplus.test", "Pharma-Secret-2026"),
        ],
        patients=[
            ("ravi.patel@example.test", "Patient-Demo-2026"),
            ("sneha.rao@example.test", "Patient-Demo-2026"),
            ("kabir.khan@example.test", "Patient-Demo-2026"),
            ("anita.desai@example.test", "Patient-Demo-2026"),
        ],
    )
    with TestClient(app) as client:
        try:
            ctx = Ctx(client, world)
            _ = ctx.admin
        except AssertionError:
            print("Could not sign in as the demo admin. Run: python scripts/seed_demo.py --reset")
            return 2
        results = run_all(ctx, set(args.only) if args.only else None)
    print(table(results))
    caught = sum(r.detected for r in results)
    print(f"\n{caught} of {len(results)} attacks were detected or blocked.")
    if args.markdown:
        Path(args.markdown).write_text(markdown(results), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(
            json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
        )
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
