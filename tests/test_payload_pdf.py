"""P4: payload rules, page layout geometry, and the generated PDF (WYSIWYS)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pymupdf
import pytest

from app.core import payload as pl
from app.core import pdf_layout as layout
from app.core.canonical import CanonicalError, canonical_bytes, sha256_hex
from app.core.pdf import render_prescription_pdf
from app.core.qr import build_qr, decode_qr

RX = "3f0c1b2e-7d4a-4c1b-9e2f-0a1b2c3d4e5f"
KEY = "9a1c0e77b2d4f605"
ISSUED = datetime(2026, 10, 18, 10, 30, tzinfo=UTC)

MED = {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}


def make_payload(**overrides):
    args = dict(
        rx_id=RX,
        key_id=KEY,
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(days=30),
        max_fills=1,
        doctor={
            "id": "d-1",
            "name": "Dr. A. Shah",
            "license_no": "GJ-12345",
            "clinic": "Shah Clinic, Surat",
        },
        patient={"id": "p-1", "name": "Ravi Patel", "age_years": 34},
        medicines=[MED],
        notes="After food",
    )
    args.update(overrides)
    return pl.build_payload(**args)


def render(payload):
    canonical = canonical_bytes(payload)
    payload_hash = sha256_hex(canonical)
    # A fixed stand-in signature keeps the QR (and the PDF bytes) deterministic.
    qr = build_qr(RX, KEY, payload_hash, bytes.fromhex(payload_hash) * 2)
    return render_prescription_pdf(payload, payload_hash, qr), payload_hash, qr


# --- payload ---------------------------------------------------------------------------------


def test_payload_shape_and_timestamp_format():
    p = make_payload()
    assert p["version"] == 2 and p["rx_id"] == RX and p["key_id"] == KEY
    assert p["issued_at"] == "2026-10-18T10:30:00Z" and p["expires_at"] == "2026-11-17T10:30:00Z"
    assert p["doctor"]["clinic"] == "Shah Clinic, Surat" and p["patient"]["age_years"] == 34
    assert p["medicines"] == [MED] and p["notes"] == "After food" and p["max_fills"] == 1


def test_age_is_optional_and_omitted_when_absent():
    assert "age_years" not in make_payload(patient={"id": "p-1", "name": "Ravi Patel"})["patient"]


def test_canonical_bytes_are_stable():
    assert canonical_bytes(make_payload()) == canonical_bytes(make_payload())


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"medicines": []}, "1 to 8"),
        ({"medicines": [MED] * 9}, "1 to 8"),
        ({"max_fills": 0}, "Fills"),
        ({"max_fills": 6}, "Fills"),
        ({"notes": "x" * 501}, "at most 500"),
        ({"notes": "\n".join(["line"] * 6)}, "printed lines"),
        ({"medicines": [{**MED, "name": "\u092a\u0930\u093f\u0902"}]}, "cannot be printed"),
        ({"patient": {"id": "p", "name": "Ravi \u2603"}}, "cannot be printed"),
        ({"medicines": [{**MED, "name": "W" * 40}]}, "too long"),
        ({"patient": {"id": "p", "name": "M" * 60}}, "too long"),
        (
            {"doctor": {"id": "d", "name": "Dr. " + "W" * 30, "license_no": "L", "clinic": "C"}},
            "too long",
        ),
        ({"doctor": {"id": "d", "name": "Dr", "license_no": "L" * 60, "clinic": "C"}}, "too long"),
        ({"doctor": {"id": "d", "name": "Dr", "license_no": "L", "clinic": "C" * 80}}, "too long"),
    ],
)
def test_unprintable_or_oversized_content_is_refused_before_signing(override, message):
    with pytest.raises(pl.PayloadError, match=message):
        make_payload(**override)


@pytest.mark.parametrize("bad", ["a\u202eb", "tab\there", "zero\u200bwidth"])
def test_hidden_characters_never_reach_the_canonical_bytes(bad):
    with pytest.raises((CanonicalError, pl.PayloadError)):
        canonical_bytes(make_payload(medicines=[{**MED, "name": bad}]))


def test_max_boundary_values_still_fit():
    big = {
        "name": "Amoxicillin and Clavulanate",
        "dose_mg": 99999,
        "frequency": "QID",
        "duration_days": 365,
    }
    p = make_payload(medicines=[big] * 8, notes="\n".join(["A note line"] * 5))
    assert len(render(p)[0]) > 1000


def test_fingerprint_groups_first_twelve_hex_chars():
    assert pl.fingerprint("9a1c0e77b2d4f6053f0c") == "9a1c 0e77 b2d4"


# --- layout geometry -------------------------------------------------------------------------


def _intersects(a: layout.Rect, b: layout.Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_every_zone_is_inside_the_page():
    for name, r in {**layout.ZONES, **layout.FIDUCIALS}.items():
        assert 0 <= r.x and r.x + r.w <= layout.PAGE_W + 0.01, name
        assert 0 <= r.y and r.y + r.h <= layout.PAGE_H + 0.01, name


def test_no_two_zones_overlap():
    items = list({**layout.ZONES, **layout.FIDUCIALS}.items())
    for i, (name_a, a) in enumerate(items):
        for name_b, b in items[i + 1 :]:
            assert not _intersects(a, b), f"{name_a} overlaps {name_b}"


def test_there_are_eight_medicine_rows_with_four_cells_each():
    names = [n for n in layout.ZONES if n.startswith("med_")]
    assert len(names) == layout.MAX_MEDICINES * 4
    assert layout.zone_names_for_medicine(7) == (
        "med_7_name",
        "med_7_dose",
        "med_7_freq",
        "med_7_days",
    )


def test_three_fiducials_plus_the_qr_make_four_anchors_in_different_corners():
    assert set(layout.FIDUCIALS) == {"fid_tl", "fid_tr", "fid_bl"}
    qr = layout.ZONES["qr"]
    assert qr.x > layout.PAGE_W / 2 and qr.y > layout.PAGE_H / 2  # the fourth corner


def test_wrapping_is_deterministic_and_respects_width():
    text = "Take one tablet after food. " * 6
    lines = layout.wrap_lines(text, 300)
    assert lines == layout.wrap_lines(text, 300)
    assert all(layout.text_width(line) <= 300 for line in lines)
    assert layout.wrap_lines("a\nb", 300) == ["a", "b"]


def test_overlong_words_are_split_not_overflowed():
    lines = layout.wrap_lines("W" * 200, 100)
    assert len(lines) > 1 and all(layout.text_width(line) <= 100 for line in lines)


# --- the PDF itself --------------------------------------------------------------------------


def page_of(pdf: bytes) -> pymupdf.Page:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert doc.page_count == 1
    return doc[0]


def test_pdf_is_a_single_a4_page_and_deterministic():
    p = make_payload()
    first, _, _ = render(p)
    second, _, _ = render(p)
    assert first.startswith(b"%PDF") and first == second
    page = page_of(first)
    assert (
        abs(page.rect.width - layout.PAGE_W) < 0.5 and abs(page.rect.height - layout.PAGE_H) < 0.5
    )


def test_pdf_changes_when_any_signed_field_changes():
    base, _, _ = render(make_payload())
    for override in (
        {"medicines": [{**MED, "dose_mg": 800}]},
        {"notes": "Before food"},
        {"patient": {"id": "p-1", "name": "Ravi Patil", "age_years": 34}},
        {"max_fills": 2},
        {"expires_at": ISSUED + timedelta(days=31)},
    ):
        assert render(make_payload(**override))[0] != base


def expected_lines(p, payload_hash):
    lines = {pl.clinic_text(p), *pl.doctor_lines(p), pl.patient_text(p), *pl.dates_lines(p),
             *pl.footer_lines(p["rx_id"], payload_hash), *pl.notes_lines(p)}  # fmt: skip
    for m in p["medicines"]:
        lines.update(pl.medicine_cells(m))
    return lines


def test_every_visible_line_comes_from_the_payload_or_the_fixed_template():
    """WYSIWYS: nothing is printed that is not derived from the signed payload."""
    p = make_payload(
        medicines=[
            MED,
            {"name": "Paracetamol", "dose_mg": 650, "frequency": "SOS", "duration_days": 3},
        ]
    )
    pdf, payload_hash, _ = render(p)
    template = {label.upper() for label, _ in layout.TABLE_COLUMNS.values()} | {
        "Scan with Pramaan to verify"
    }
    shown = {line.strip() for line in page_of(pdf).get_text("text").splitlines() if line.strip()}
    derived = expected_lines(p, payload_hash)
    template_words = {word for label in template for word in label.split()}
    # PDF text extraction may join the static column labels onto one line, so judge by words.
    unexplained = {
        line for line in shown if line not in derived and not set(line.split()) <= template_words
    }
    assert not unexplained, unexplained
    assert derived <= shown  # and everything derived is actually shown


def test_each_cell_is_drawn_inside_its_own_zone():
    p = make_payload(medicines=[MED, {**MED, "name": "Ibuprofen", "dose_mg": 400}])
    pdf, _, _ = render(p)
    page = page_of(pdf)
    for i, med in enumerate(p["medicines"]):
        for zone_name, cell in zip(
            layout.zone_names_for_medicine(i), pl.medicine_cells(med), strict=True
        ):
            z = layout.ZONES[zone_name]
            clip = pymupdf.Rect(z.x - 1, z.y - 1, z.x + z.w + 1, z.y + z.h + 1)
            assert cell in page.get_text("text", clip=clip), (zone_name, cell)


def test_unused_medicine_rows_stay_blank():
    pdf, _, _ = render(make_payload())
    page = page_of(pdf)
    for i in range(1, layout.MAX_MEDICINES):
        for zone_name in layout.zone_names_for_medicine(i):
            z = layout.ZONES[zone_name]
            assert (
                page.get_text("text", clip=pymupdf.Rect(z.x, z.y, z.x + z.w, z.y + z.h)).strip()
                == ""
            )


def test_payload_derived_text_is_at_least_11_points():
    p = make_payload()
    pdf, payload_hash, _ = render(p)
    derived = expected_lines(p, payload_hash)
    small = []
    for block in page_of(pdf).get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() in derived and span["size"] < 10.9:
                    small.append((span["text"], span["size"]))
    assert not small, small


def raster(pdf: bytes, dpi: int = 200) -> np.ndarray:
    pix = page_of(pdf).get_pixmap(dpi=dpi)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR)


def test_the_qr_printed_on_the_page_decodes_to_the_signed_code():
    pdf, _, qr = render(make_payload())
    assert decode_qr(raster(pdf)) == qr


def test_fiducials_are_solid_black_at_their_layout_positions():
    pdf, _, _ = render(make_payload())
    image = raster(pdf, dpi=144)
    scale = 144 / 72
    for name, r in layout.FIDUCIALS.items():
        cx, cy = int((r.x + r.w / 2) * scale), int((r.y + r.h / 2) * scale)
        assert image[cy, cx].max() < 40, name
    # ...and the page around a fiducial is white.
    assert image[int(8 * scale), int(8 * scale)].min() > 200  # blank corner margin


def test_printed_dates_are_to_the_minute_even_when_seconds_are_not_zero():
    issued = datetime(2026, 10, 18, 10, 30, 17, tzinfo=UTC)
    p = make_payload(issued_at=issued, expires_at=issued + timedelta(days=30))
    assert p["issued_at"] == "2026-10-18T10:30:17Z"  # the signed value keeps the seconds
    assert pl.dates_lines(p) == (
        "Issued: 2026-10-18 10:30 UTC",
        "Valid until: 2026-11-17 10:30 UTC",
        "Fills allowed: 1",
    )
