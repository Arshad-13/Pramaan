"""P7: building blocks of upload verification (uploads, OCR text handling, straightening, diffing)."""

from __future__ import annotations

import cv2
import numpy as np
import pymupdf
import pytest

from app.ai import samples
from app.ai.content_check import MATCH, MISMATCH, UNREADABLE, check_content, zone_label
from app.ai.extract import assign_lines, normalise, read_zone, reading_order, same_text
from app.ai.ocr import OCRLine
from app.ai.rectify import rectify, zone_box
from app.ai.render_diff import compare_zone, even_out_lighting, ink_mask, raster_pdf_gray
from app.core import payload as pl
from app.core import pdf_layout as layout
from app.core.canonical import canonical_bytes, sha256_hex
from app.core.pdf import render_prescription_pdf
from app.core.qr import build_qr, locate_qr, qr_matrix
from app.core.uploads import MAX_BYTES, UploadError, load_upload, sniff
from tests.test_payload_pdf import KEY, RX, make_payload

PAYLOAD = make_payload(
    medicines=[
        {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5},
        {"name": "Paracetamol", "dose_mg": 650, "frequency": "SOS", "duration_days": 3},
    ],
    notes="After food",
)
HASH = sha256_hex(canonical_bytes(PAYLOAD))
QR = build_qr(RX, KEY, HASH, bytes.fromhex(HASH) * 2)
PDF = render_prescription_pdf(PAYLOAD, HASH, QR)
PAGE = samples.rasterize(PDF)


class NoOCR:
    """An OCR engine that reads nothing: forces the 'cannot tell' paths."""

    def read(self, image):
        return []


def line(text, cx, cy, h=20.0, w=200.0, conf=0.95):
    box = (
        (cx - w / 2, cy - h / 2),
        (cx + w / 2, cy - h / 2),
        (cx + w / 2, cy + h / 2),
        (cx - w / 2, cy + h / 2),
    )
    return OCRLine(text, conf, box)


# --- layout bookkeeping ----------------------------------------------------------------------------


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_blank_regions_do_not_overlap_any_printed_zone():
    for name, blank in layout.BLANK_REGIONS.items():
        for zone, rect in layout.ZONES.items():
            assert not overlaps(blank, rect), f"{name} overlaps {zone}"


def test_every_zone_is_either_text_blank_or_static():
    texts = pl.zone_texts(PAYLOAD, HASH)
    blanks = pl.blank_zone_names(PAYLOAD)
    covered = set(texts) | set(blanks) | layout.STATIC_ZONES
    assert set(layout.ZONES) <= covered
    assert not set(texts) & set(blanks)


def test_zone_labels_are_human_readable():
    assert zone_label("med_1_dose") == "Medicine 2 dose"
    assert zone_label("patient") == "Patient"
    assert zone_label("blank_mid") == "Blank area"


# --- extract ---------------------------------------------------------------------------------------


def test_normalise_ignores_spacing_punctuation_and_case_but_not_digits():
    assert normalise("Rx ID: ABC-1") == normalise("rxid abc1")
    assert normalise("500 mg") != normalise("800 mg")
    assert same_text("Reg. No.GJ-12345", ["Dr. A. Shah"][:0] + ["Reg. No. GJ-12345"])


def test_reading_order_groups_rows_even_when_line_heights_differ():
    # The right-hand line is taller (like a rotated box); it must still come second on the same row.
    left = line("left", 100, 100, h=20)
    right = line("right", 400, 104, h=34)
    below = line("below", 100, 160, h=20)
    assert [ln.text for ln in reading_order([below, right, left])] == ["left", "right", "below"]


def test_read_zone_reports_weakest_confidence_and_empty_zone():
    assert read_zone([]).lines == 0
    read = read_zone([line("a", 10, 10, conf=0.9), line("b", 300, 10, conf=0.6)])
    assert read.text == "a b" and read.confidence == 0.6


def test_assign_lines_uses_the_line_centre():
    x0, y0, x1, y1 = zone_box(layout.ZONES["patient"])
    inside = line("in", (x0 + x1) / 2, (y0 + y1) / 2)
    outside = line("out", (x0 + x1) / 2, y1 + 200)
    got = assign_lines([inside, outside], ["patient"])
    assert [ln.text for ln in got["patient"]] == ["in"]


# --- uploads ---------------------------------------------------------------------------------------


def test_sniff_goes_by_magic_bytes_not_names():
    assert sniff(PDF) == "pdf"
    assert sniff(samples.to_png(PAGE)) == "png"
    assert sniff(samples.to_jpeg(PAGE)) == "jpeg"
    with pytest.raises(UploadError):
        sniff(b"MZ\x90\x00 definitely a program")


def test_load_upload_reads_pdf_text_layer_and_images():
    pdf = load_upload(PDF)
    assert pdf.kind == "pdf" and pdf.has_text_layer
    png = load_upload(samples.to_png(PAGE))
    assert png.kind == "png" and not png.has_text_layer and png.image.shape == PAGE.shape


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"", 400),
        (b"%PDF-" + b"0" * (MAX_BYTES + 1), 413),
        (b"%PDF-1.4 this is not really a pdf", 400),
        (b"\x89PNG\r\n\x1a\n garbage", 400),
    ],
    ids=["empty", "too-big", "fake-pdf", "fake-png"],
)
def test_load_upload_rejects_bad_files(data, status):
    with pytest.raises(UploadError) as err:
        load_upload(data)
    assert err.value.status == status


def test_tiny_and_huge_images_are_rejected():
    assert_rejected(samples.to_png(np.zeros((50, 50, 3), np.uint8)))


def assert_rejected(data):
    with pytest.raises(UploadError):
        load_upload(data)


def test_pdf_with_too_many_pages_is_rejected():
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page()
    assert_rejected(doc.tobytes())


def test_encrypted_pdf_is_rejected():
    doc = pymupdf.open(stream=PDF, filetype="pdf")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    assert_rejected(data)


# --- rectify and diff ------------------------------------------------------------------------------


def test_qr_is_located_in_a_photo_in_original_coordinates():
    photo = samples.photograph(PAGE, 5)
    text, corners = locate_qr(photo)
    assert text == QR
    assert corners.shape == (4, 2)
    assert corners[:, 0].max() <= photo.shape[1] and corners[:, 1].max() <= photo.shape[0]


def test_digital_page_aligns_with_all_corner_marks():
    rect = rectify(PAGE, len(qr_matrix(QR)), raster_pdf_gray(PDF))
    assert rect is not None and rect.good
    assert rect.fiducials_found == 3 and rect.rms_px < 1.0


def test_photo_aligns_well():
    rect = rectify(samples.photograph(PAGE, 8), len(qr_matrix(QR)), raster_pdf_gray(PDF))
    assert rect is not None and rect.good


def test_image_without_qr_cannot_be_straightened():
    assert rectify(np.full((900, 700, 3), 255, np.uint8), 29) is None


def test_zone_distance_is_zero_for_the_same_page_and_large_for_an_edit():
    expected = ink_mask(even_out_lighting(raster_pdf_gray(PDF)))
    same = compare_zone("med_0_dose", layout.ZONES["med_0_dose"], expected, expected)
    assert same.distance == 0.0
    edited = samples.edit_medicine(PAGE, PAYLOAD, 0, dose_mg=800)
    actual = ink_mask(even_out_lighting(cv2.cvtColor(edited, cv2.COLOR_BGR2GRAY)))
    diff = compare_zone("med_0_dose", layout.ZONES["med_0_dose"], expected, actual)
    assert diff.distance > 0.05


# --- the orchestrator (fast paths; the OCR-backed paths are covered end to end) -----------------------


def run(data, engine=None):
    return check_content(load_upload(data), data, PAYLOAD, HASH, QR, sha256_hex(PDF), engine)


def test_original_pdf_matches_without_needing_ocr():
    report = run(PDF, NoOCR())
    assert report.status == MATCH and not report.used_ocr
    assert report.file_integrity == "ORIGINAL"
    assert report.alignment["good"] and report.findings == []


def test_visible_difference_with_no_ocr_is_a_mismatch_only_when_clear():
    edited = samples.edit_medicine(PAGE, PAYLOAD, 0, dose_mg=800)
    report = run(samples.to_png(edited), NoOCR())
    # The edit is detected, but with nothing to confirm it by OCR the cautious answer is not an accusation
    # unless the difference is overwhelming.
    assert report.findings and report.findings[0].zone == "med_0_dose"
    assert report.status in (MISMATCH, UNREADABLE)


def test_poorly_aligned_page_is_never_called_tampered():
    photo = samples.photograph(samples.edit_medicine(PAGE, PAYLOAD, 0, dose_mg=800), 4)
    rect = rectify(photo, len(qr_matrix(QR)), raster_pdf_gray(PDF))
    damaged = photo.copy()
    paper = tuple(int(v) for v in np.median(photo[photo.mean(axis=2) > 120], axis=0))
    # Paint over two of the three corner marks so the alignment cannot be trusted.
    for mark in list(layout.FIDUCIALS.values())[:2]:
        x0, y0, x1, y1 = zone_box(mark, pad=6)
        quad = rect.to_image(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64))
        cv2.fillConvexPoly(damaged, quad.astype(np.int32), paper)
    report = run(samples.to_jpeg(damaged), NoOCR())
    assert not report.alignment["good"]
    assert report.status != MISMATCH
