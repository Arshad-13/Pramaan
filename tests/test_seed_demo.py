"""P10: the demo seed builds a consistent world through the real API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_demo  # noqa: E402

from app.main import app  # noqa: E402
from tests.helpers import bearer  # noqa: E402


@pytest.fixture(scope="module")
def demo():
    from app import models
    from app.config import get_settings
    from app.db import get_engine
    from tests.conftest import TEST_ENV  # noqa: F401

    engine = get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    get_settings().rate_limit_enabled = False
    with TestClient(app) as client:
        world = seed_demo.seed(client)
        yield client, world


def verify(client, world, label, who=0):
    token = bearer(client, *world.pharmacists[who])
    return client.post("/api/verify/qr", headers=token, json={"qr_string": world.qr[label]}).json()


def test_every_demo_case_gives_its_expected_verdict(demo):
    client, world = demo
    expected = {
        "ready": "VALID",
        "controlled": "VALID",
        "used": "ALREADY_USED",
        "expired": "EXPIRED",
        "revoked": "REVOKED",
        "suspicious": "SUSPICIOUS",
    }
    got = {label: verify(client, world, label)["result"] for label in expected}
    assert got == expected


def test_the_controlled_sample_is_flagged_but_not_blocked(demo):
    client, world = demo
    body = verify(client, world, "controlled")
    assert "CONTROLLED_SUBSTANCE" in body["risk"]["flags"] and body["can_dispense"]


def test_the_ready_sample_can_be_dispensed_with_the_patients_pin(demo):
    client, world = demo
    patient = bearer(client, *world.patients[0])
    rx = world.rx["ready"]
    pin = client.get(f"/api/prescriptions/{rx}/pin", headers=patient).json()["pin"]
    pharmacist = bearer(client, *world.pharmacists[0])
    wrong = client.post(
        f"/api/prescriptions/{rx}/dispense",
        headers=pharmacist,
        json={
            "qr_string": world.qr["ready"],
            "patient_pin": "000000" if pin != "000000" else "111111",
        },
    )
    assert wrong.status_code == 403
    done = client.post(
        f"/api/prescriptions/{rx}/dispense",
        headers=pharmacist,
        json={"qr_string": world.qr["ready"], "patient_pin": pin},
    )
    assert done.status_code == 200


def test_the_audit_chain_of_the_seeded_world_is_intact(demo):
    client, world = demo
    auditor = bearer(client, *world.auditor)
    result = client.get("/api/admin/audit/verify", headers=auditor).json()
    assert result["ok"] is True and result["checked"] > 50


def test_seeding_twice_is_refused(demo):
    client, _ = demo
    with pytest.raises(SystemExit):
        seed_demo.seed(client)


def test_sample_files_are_written(demo, tmp_path):
    _, world = demo
    seed_demo.write_samples(world, tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert {
        "ready.pdf",
        "ready.qr.txt",
        "ready_forged_dose_800mg.png",
        "ready_forged_overlay.pdf",
        "ready_forged_qr.qr.txt",
    } <= names
    assert (tmp_path / "ready_forged_qr.qr.txt").read_text() != world.qr["ready"]
