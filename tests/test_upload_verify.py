"""P7: verifying an uploaded photo or PDF against the signed record (Tier 1, render-and-diff + OCR)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai import samples
from app.main import app
from tests.world import build_world, dispense, issue, med, qr_for, sql, verify  # noqa: F401


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        yield build_world(client)


def fetch_pdf(w, rx_id: str) -> bytes:
    response = w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor)
    assert response.status_code == 200, response.text
    return response.content


def upload(w, data: bytes, name="file.bin", headers=None):
    return w.client.post(
        "/api/verify/upload",
        headers=w.pharmacist_a if headers is None else headers,
        files={"file": (name, data, "application/octet-stream")},
    )


def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def issued(w):
    rx_id = issue(w, medicines=[med(), med(name="Paracetamol", dose_mg=650, frequency="BD")])
    pdf = fetch_pdf(w, rx_id)
    return rx_id, pdf


# --- genuine files ----------------------------------------------------------------------------


def test_genuine_pdf_is_valid_and_original(w, issued):
    rx_id, pdf = issued
    body = ok(upload(w, pdf, "rx.pdf"))
    assert body["result"] == "VALID"
    assert body["checks"]["content_check"] == "MATCH"
    assert body["checks"]["file_integrity"] == "ORIGINAL"
    assert body["can_dispense"] is True
    assert body["qr_string"] == qr_for(rx_id)
    assert body["content_zones"] == []


def test_genuine_png_of_the_page_is_valid_reproduction(w, issued):
    _, pdf = issued
    body = ok(upload(w, samples.to_png(samples.rasterize(pdf)), "rx.png"))
    assert body["result"] == "VALID"
    assert body["checks"]["file_integrity"] == "REPRODUCTION"


def test_genuine_photo_is_never_tampered(w, issued):
    _, pdf = issued
    photo = samples.photograph(samples.rasterize(pdf), seed=3)
    body = ok(upload(w, samples.to_jpeg(photo), "photo.jpg"))
    assert body["result"] in ("VALID", "REVIEW_REQUIRED")
    assert body["result"] != "TAMPERED"


def test_dispense_works_after_an_upload_verification(w, issued):
    rx_id, pdf = issued
    body = ok(upload(w, pdf))
    pin = w.client.get(f"/api/prescriptions/{rx_id}/pin", headers=w.patient1_h).json()["pin"]
    response = dispense(w, rx_id, qr=body["qr_string"], pin=pin)
    assert response.status_code == 200, response.text


# --- forged pages -----------------------------------------------------------------------------


def forged_payload(w, rx_id):
    """The signed content, as the verifier sees it, for building forgeries."""
    from app.services import verification_service as vs
    from tests.helpers import session

    with session() as db:
        return vs.evaluate(db, qr_for(rx_id)).payload


def test_single_digit_dose_edit_is_tampered_and_located(w, issued):
    rx_id, pdf = issued
    payload = forged_payload(w, rx_id)
    page = samples.edit_medicine(samples.rasterize(pdf), payload, 0, dose_mg=800)
    body = ok(upload(w, samples.to_png(page)))
    assert body["result"] == "TAMPERED"
    assert "CONTENT_MISMATCH" in body["reason_codes"]
    assert body["can_dispense"] is False
    assert body["qr_string"] is None
    zones = {z["zone"]: z for z in body["content_zones"]}
    assert list(zones) == ["med_0_dose"]
    assert zones["med_0_dose"]["signed"] == "500 mg"
    assert zones["med_0_dose"]["read"].replace(" ", "") == "800mg"
    assert body["overlay"]["image"].startswith("data:image/jpeg;base64,")
    assert len(zones["med_0_dose"]["quad"]) == 4


def test_extra_medicine_row_is_tampered(w, issued):
    rx_id, pdf = issued
    payload = forged_payload(w, rx_id)
    forged = samples.add_medicine_row(
        samples.rasterize(pdf),
        2,
        {"name": "Alprazolam", "dose_mg": 10, "frequency": "TDS", "duration_days": 30},
    )
    body = ok(upload(w, samples.to_png(forged)))
    assert payload is not None
    assert body["result"] == "TAMPERED"
    assert any(z["zone"].startswith("med_2_") for z in body["content_zones"])


def test_extra_text_in_the_blank_area_is_tampered(w, issued):
    _, pdf = issued
    page = samples.add_margin_text(samples.rasterize(pdf), "Refill x10 - Dr A. Shah")
    body = ok(upload(w, samples.to_png(page)))
    assert body["result"] == "TAMPERED"
    assert "EXTRA_CONTENT" in body["reason_codes"]


def test_white_box_overlay_pdf_is_tampered(w, issued):
    _, pdf = issued
    forged = samples.pdf_overlay_edit(pdf, "med_0_dose", "900 mg")
    body = ok(upload(w, forged, "forged.pdf"))
    assert body["result"] == "TAMPERED"
    assert (
        "HIDDEN_TEXT_OR_OVERLAY" in body["reason_codes"]
        or "CONTENT_MISMATCH" in body["reason_codes"]
    )
    assert body["checks"]["file_integrity"] is None


def test_invisible_text_layer_edit_is_tampered(w, issued):
    _, pdf = issued
    forged = samples.pdf_hidden_text_edit(pdf, "med_0_dose", "900 mg")
    body = ok(upload(w, forged, "forged.pdf"))
    assert body["result"] == "TAMPERED"
    assert "HIDDEN_TEXT_OR_OVERLAY" in body["reason_codes"]


# --- unusable files ---------------------------------------------------------------------------


def test_image_without_a_qr_code_is_invalid(w):
    import cv2
    import numpy as np

    blank = np.full((900, 700, 3), 255, np.uint8)
    cv2.putText(blank, "hello", (100, 400), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 4)
    body = ok(upload(w, samples.to_png(blank)))
    assert body["result"] == "INVALID_QR"
    assert body["reason_codes"] == ["NO_QR_IN_FILE"]


def test_unknown_file_type_is_rejected(w):
    response = upload(w, b"MZ\x90\x00 not an image at all" * 20, "evil.exe")
    assert response.status_code == 400


def test_empty_upload_is_rejected(w):
    assert upload(w, b"").status_code == 400


def test_oversize_upload_is_rejected(w):
    assert upload(w, b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10)).status_code == 413


def test_pdf_with_attachment_is_rejected(w, issued):
    import pymupdf

    _, pdf = issued
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    doc.embfile_add("note.txt", b"hi")
    assert upload(w, doc.tobytes()).status_code == 400


def test_upload_requires_a_pharmacist(w, issued):
    _, pdf = issued
    assert upload(w, pdf, headers=w.doctor).status_code == 403
    assert upload(w, pdf, headers=w.patient1_h).status_code == 403
    w.client.cookies.clear()
    assert upload(w, pdf, headers={}).status_code == 401


def test_upload_is_audited_like_a_qr_scan(w, issued):
    _, pdf = issued
    ok(upload(w, pdf))
    from sqlalchemy import select

    from app.models import VerificationAttempt
    from tests.helpers import session

    with session() as db:
        attempts = list(db.scalars(select(VerificationAttempt)))
    assert [a.result for a in attempts] == ["VALID"]


def test_a_revoked_prescription_stays_revoked_when_uploaded(w, issued):
    rx_id, pdf = issued
    sql("UPDATE prescriptions SET status = 'REVOKED' WHERE id = :i", i=rx_id)
    body = ok(upload(w, pdf))
    assert body["result"] == "REVOKED"
    assert body["can_dispense"] is False


def test_a_tampered_upload_blocks_dispensing_by_that_pharmacist_only(w, issued):
    rx_id, pdf = issued
    payload = forged_payload(w, rx_id)
    forged = samples.to_png(samples.edit_medicine(samples.rasterize(pdf), payload, 0, dose_mg=800))
    assert ok(upload(w, forged))["result"] == "TAMPERED"
    pin = w.client.get(f"/api/prescriptions/{rx_id}/pin", headers=w.patient1_h).json()["pin"]

    refused = dispense(w, rx_id, pin=pin)  # pharmacist A, with the genuine QR and the right PIN
    assert refused.status_code == 409
    assert "did not match" in refused.json()["detail"]
    # a different pharmacist who has not seen a forged page is not held: the signed record decides
    assert dispense(w, rx_id, pin=pin, headers=w.pharmacist_b).status_code == 200


def test_a_genuine_upload_does_not_hold_dispensing(w, issued):
    rx_id, pdf = issued
    assert ok(upload(w, pdf))["result"] == "VALID"
    pin = w.client.get(f"/api/prescriptions/{rx_id}/pin", headers=w.patient1_h).json()["pin"]
    assert dispense(w, rx_id, pin=pin).status_code == 200
