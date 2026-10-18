"""P5: dispensing (atomic, PIN-protected, refills) including concurrency and races."""

from __future__ import annotations

import json
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.crypto import b64u_decode
from app.core.qr import build_qr
from app.main import app
from app.models import AuditLog, Dispense, Prescription, RxStatus
from tests.helpers import bearer, session
from tests.world import (
    build_world,
    dispense,
    get_pin,
    issue,
    med,
    qr_for,
    sql,
    stored,
    verify,
)


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        yield build_world(client)


def audit_actions():
    with session() as db:
        return [r.action for r in db.scalars(select(AuditLog).order_by(AuditLog.seq))]


def dispenses(rx_id):
    with session() as db:
        return list(
            db.scalars(select(Dispense).where(Dispense.rx_id == rx_id).order_by(Dispense.fill_no))
        )


# --- a normal dispense ---------------------------------------------------------------------------


def test_dispensing_with_the_patients_pin_consumes_the_prescription(w):
    rx_id = issue(w)
    response = dispense(w, rx_id, pin=get_pin(w, rx_id))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "rx_id": rx_id,
        "fill_no": 1,
        "fills_remaining": 0,
        "status": "DISPENSED",
    }
    row = stored(rx_id)
    assert row.status == RxStatus.DISPENSED and row.fills_used == 1
    assert [(d.fill_no, d.pharmacist_id) for d in dispenses(rx_id)][0][0] == 1
    assert "RX_DISPENSED" in audit_actions()


def test_a_dispensed_prescription_cannot_be_dispensed_again(w):
    rx_id = issue(w)
    pin_value = get_pin(w, rx_id)  # (the app stops showing the PIN once a prescription is used)
    assert dispense(w, rx_id, pin=pin_value).status_code == 200
    again = dispense(w, rx_id, pin=pin_value)
    assert again.status_code == 409 and "ALREADY_USED" in again.json()["detail"]
    assert len(dispenses(rx_id)) == 1


def test_the_audit_entry_records_the_fill_without_the_pin(w):
    rx_id = issue(w)
    pin_value = get_pin(w, rx_id)
    dispense(w, rx_id, pin=pin_value)
    with session() as db:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "RX_DISPENSED")).one()
        everything = json.dumps([r.details_json for r in db.scalars(select(AuditLog))])
    assert json.loads(entry.details_json) == {
        "fill_no": 1,
        "identity_checked": False,
        "pin_checked": True,
    }
    assert pin_value not in everything


# --- PIN rules -------------------------------------------------------------------------------------


def test_a_pin_is_required(w):
    rx_id = issue(w)
    response = dispense(w, rx_id)
    assert response.status_code == 400 and "PIN" in response.json()["detail"]
    assert stored(rx_id).fills_used == 0


def test_a_wrong_pin_is_refused_and_logged(w):
    rx_id = issue(w)
    right = get_pin(w, rx_id)
    wrong = "000000" if right != "000000" else "111111"
    response = dispense(w, rx_id, pin=wrong)
    assert response.status_code == 403 and response.json()["detail"] == "That PIN is not correct."
    assert stored(rx_id).fills_used == 0 and audit_actions().count("PIN_FAIL") == 1


@pytest.mark.parametrize(
    "bad", ["12345", "1234567", "abcdef", "12 456", "\u0661\u0662\u0663\u0664\u0665\u0666"]
)
def test_malformed_pins_are_just_wrong(w, bad):
    rx_id = issue(w)
    assert dispense(w, rx_id, pin=bad).status_code == 403


def test_three_wrong_pins_lock_dispensing_even_for_the_right_pin(w, frozen_clock):
    rx_id = issue(w)
    right = get_pin(w, rx_id)
    for _ in range(3):
        assert (
            dispense(w, rx_id, pin="999999" if right != "999999" else "888888").status_code == 403
        )
    locked = dispense(w, rx_id, pin=right)
    assert locked.status_code == 423
    assert stored(rx_id).fills_used == 0
    alert = w.client.get("/api/admin/security-events", headers=w.admin).json()
    assert [e["event_type"] for e in alert] == ["PIN_LOCKED"]

    frozen_clock.advance(timedelta(minutes=6))
    fresh_pin = get_pin(w, rx_id, headers=bearer(w.client, "ravi@example.test"))
    assert (
        dispense(
            w, rx_id, pin=fresh_pin, headers=bearer(w.client, "pharm.a@example.test")
        ).status_code
        == 200
    )


def test_the_pin_lock_applies_across_pharmacists(w):
    rx_id = issue(w)
    right = get_pin(w, rx_id)
    wrong = "999999" if right != "999999" else "888888"
    for headers in (w.pharmacist_a, w.pharmacist_b, w.pharmacist_a):
        dispense(w, rx_id, pin=wrong, headers=headers)
    assert dispense(w, rx_id, pin=right, headers=w.pharmacist_b).status_code == 423


def test_a_pin_from_another_prescription_does_not_work(w):
    first, second = issue(w), issue(w)
    assert dispense(w, first, pin=get_pin(w, second)).status_code == 403


def test_the_previous_time_step_pin_is_accepted_but_not_two_steps_old(w, frozen_clock):
    rx_id = issue(w)
    old = get_pin(w, rx_id)
    frozen_clock.advance(timedelta(seconds=120))
    pharmacist = bearer(w.client, "pharm.a@example.test")
    assert dispense(w, rx_id, pin=old, headers=pharmacist).status_code == 200  # one step old: ok

    other = issue(w)
    stale = get_pin(w, other, headers=bearer(w.client, "ravi@example.test"))
    frozen_clock.advance(timedelta(seconds=240))
    assert (
        dispense(w, other, pin=stale, headers=bearer(w.client, "pharm.a@example.test")).status_code
        == 403
    )


def test_without_a_pin_the_pharmacist_must_confirm_the_patients_identity(w):
    rx_id = issue(w, require_pin=False)
    assert dispense(w, rx_id).status_code == 400
    assert dispense(w, rx_id, patient_identity_checked=False).status_code == 400
    ok = dispense(w, rx_id, patient_identity_checked=True)
    assert ok.status_code == 200
    with session() as db:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "RX_DISPENSED")).one()
    assert json.loads(entry.details_json)["identity_checked"] is True


# --- the code is proof of possession ---------------------------------------------------------------


def test_the_code_must_belong_to_the_prescription_being_dispensed(w):
    first, second = issue(w), issue(w)
    response = dispense(w, first, qr=qr_for(second), pin=get_pin(w, first))
    assert response.status_code == 400 and "different prescription" in response.json()["detail"]
    assert stored(first).fills_used == 0 and stored(second).fills_used == 0


def test_a_prescription_id_alone_is_not_enough(w):
    rx_id = issue(w)
    assert dispense(w, rx_id, qr="garbage", pin=get_pin(w, rx_id)).status_code == 409
    assert stored(rx_id).fills_used == 0


def test_a_tampered_code_cannot_dispense(w):
    rx_id = issue(w)
    row = stored(rx_id)
    forged = build_qr(rx_id, row.key_id, "f" * 64, b64u_decode(row.signature_b64))
    response = dispense(w, rx_id, qr=forged, pin=get_pin(w, rx_id))
    assert response.status_code == 409 and "TAMPERED" in response.json()["detail"]
    assert stored(rx_id).fills_used == 0


def test_dispensing_rechecks_the_state_instead_of_trusting_an_earlier_verify(w, frozen_clock):
    rx_id = issue(w, validity_days=1)
    qr = qr_for(rx_id)
    pin_value = get_pin(w, rx_id)
    assert verify(w, qr).json()["result"] == "VALID"  # verified earlier...
    w.client.post(f"/api/prescriptions/{rx_id}/revoke", headers=w.doctor)  # ...then revoked
    assert dispense(w, rx_id, qr=qr, pin=pin_value).status_code == 409

    second = issue(w, validity_days=1)
    qr2, pin2 = qr_for(second), get_pin(w, second)
    frozen_clock.advance(timedelta(days=1, seconds=1))  # ...or expired
    fresh = bearer(w.client, "pharm.a@example.test")
    assert dispense(w, second, qr=qr2, pin=pin2, headers=fresh).status_code == 409


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE prescriptions SET risk_score = 90 WHERE id = :i",  # suspicious
        "UPDATE doctor_keys SET status = 'REVOKED'",  # key revoked
    ],
)
def test_only_valid_prescriptions_can_be_dispensed(w, statement):
    rx_id = issue(w)
    pin_value = get_pin(w, rx_id)
    sql(statement, i=rx_id) if ":i" in statement else sql(statement)
    assert dispense(w, rx_id, pin=pin_value).status_code == 409
    assert stored(rx_id).fills_used == 0


def test_only_pharmacists_can_dispense(w):
    rx_id = issue(w)
    pin_value = get_pin(w, rx_id)
    for headers in (w.doctor, w.patient1_h, w.admin, w.auditor):
        assert dispense(w, rx_id, pin=pin_value, headers=headers).status_code == 403
    assert stored(rx_id).fills_used == 0


# --- refills ----------------------------------------------------------------------------------------


def test_refills_are_numbered_and_the_last_one_closes_the_prescription(w):
    rx_id = issue(w, max_fills=3)
    qr = qr_for(rx_id)
    expected = [(1, 2, "ISSUED"), (2, 1, "ISSUED"), (3, 0, "DISPENSED")]
    for fill_no, remaining, status in expected:
        verified = verify(w, qr).json()
        assert (
            verified["result"] == "VALID" and verified["checks"]["fills_remaining"] == 4 - fill_no
        )
        last_pin = get_pin(w, rx_id)
        body = dispense(w, rx_id, qr=qr, pin=last_pin).json()
        assert (body["fill_no"], body["fills_remaining"], body["status"]) == (
            fill_no,
            remaining,
            status,
        )
    assert [d.fill_no for d in dispenses(rx_id)] == [1, 2, 3]
    assert verify(w, qr).json()["result"] == "ALREADY_USED"
    assert dispense(w, rx_id, qr=qr, pin=last_pin).status_code == 409
    assert len(dispenses(rx_id)) == 3


def test_the_database_itself_refuses_a_duplicate_fill_number(w):
    rx_id = issue(w)
    assert dispense(w, rx_id, pin=get_pin(w, rx_id)).status_code == 200
    from sqlalchemy.exc import IntegrityError

    with session() as db, pytest.raises(IntegrityError):
        db.add(Dispense(rx_id=rx_id, fill_no=1, pharmacist_id=1))
        db.commit()


def test_the_database_refuses_more_fills_than_allowed(w):
    rx_id = issue(w)
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with session() as db, pytest.raises(IntegrityError):
        db.execute(text("UPDATE prescriptions SET fills_used = 5 WHERE id = :i"), {"i": rx_id})
        db.commit()


# --- concurrency -------------------------------------------------------------------------------------


def run_in_threads(jobs):
    """Start all jobs behind a barrier so they hit the server at the same moment."""
    barrier = threading.Barrier(len(jobs))
    results: list = [None] * len(jobs)

    def runner(index, job):
        client = TestClient(app)  # one client per thread
        barrier.wait()
        results[index] = job(client)

    pool = [threading.Thread(target=runner, args=(i, j)) for i, j in enumerate(jobs)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    return results


def test_twenty_simultaneous_dispenses_give_exactly_one_success(w, frozen_clock):
    rx_id = issue(w)
    qr, pin_value, headers = qr_for(rx_id), get_pin(w, rx_id), w.pharmacist_a

    def attempt(client):
        return client.post(
            f"/api/prescriptions/{rx_id}/dispense",
            headers=headers,
            json={"qr_string": qr, "patient_pin": pin_value},
        ).status_code

    codes = run_in_threads([attempt] * 20)
    assert sorted(codes).count(200) == 1, codes
    assert set(codes) <= {200, 409}
    assert stored(rx_id).fills_used == 1 and len(dispenses(rx_id)) == 1


def test_simultaneous_dispenses_never_exceed_the_allowed_fills(w, frozen_clock):
    rx_id = issue(w, max_fills=3)
    qr, pin_value, headers = qr_for(rx_id), get_pin(w, rx_id), w.pharmacist_a

    def attempt(client):
        return client.post(
            f"/api/prescriptions/{rx_id}/dispense",
            headers=headers,
            json={"qr_string": qr, "patient_pin": pin_value},
        ).status_code

    codes = run_in_threads([attempt] * 20)
    assert codes.count(200) == 3, codes
    assert stored(rx_id).fills_used == 3 and stored(rx_id).status == RxStatus.DISPENSED
    assert [d.fill_no for d in dispenses(rx_id)] == [1, 2, 3]


def test_revoke_and_dispense_racing_have_exactly_one_winner(w, frozen_clock):
    for _ in range(6):
        rx_id = issue(w)
        qr, pin_value = qr_for(rx_id), get_pin(w, rx_id)

        def do_dispense(client, rx_id=rx_id, qr=qr, pin_value=pin_value):
            return client.post(
                f"/api/prescriptions/{rx_id}/dispense",
                headers=w.pharmacist_a,
                json={"qr_string": qr, "patient_pin": pin_value},
            ).status_code

        def do_revoke(client, rx_id=rx_id):
            return client.post(f"/api/prescriptions/{rx_id}/revoke", headers=w.doctor).status_code

        dispensed, revoked = run_in_threads([do_dispense, do_revoke])
        assert (dispensed, revoked) in {(200, 409), (409, 200)}, (dispensed, revoked)
        row = stored(rx_id)
        assert (row.status, row.fills_used) in {(RxStatus.DISPENSED, 1), (RxStatus.REVOKED, 0)}


def test_the_audit_chain_survives_concurrent_dispensing(w, frozen_clock):
    rx_id = issue(w, max_fills=2)
    qr, pin_value, headers = qr_for(rx_id), get_pin(w, rx_id), w.pharmacist_a

    def attempt(client):
        return client.post(
            f"/api/prescriptions/{rx_id}/dispense",
            headers=headers,
            json={"qr_string": qr, "patient_pin": pin_value},
        ).status_code

    run_in_threads([attempt] * 10)
    check = w.client.get("/api/admin/audit/verify", headers=w.auditor).json()
    assert check["ok"] is True and check["first_bad_seq"] is None
    assert audit_actions().count("RX_DISPENSED") == 2


def test_nothing_else_changed_on_the_prescription(w):
    rx_id = issue(w)
    before = stored(rx_id)
    dispense(w, rx_id, pin=get_pin(w, rx_id))
    after = stored(rx_id)
    for column in (
        "payload_enc",
        "payload_hash",
        "signature_b64",
        "wrapped_dek",
        "issued_at",
        "expires_at",
        "doctor_id",
    ):
        assert getattr(before, column) == getattr(after, column), column
    with session() as db:
        assert db.get(Prescription, rx_id).max_fills == 1
    assert med()  # silence unused-import guard for the helper
