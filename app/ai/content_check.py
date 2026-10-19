"""Check an uploaded photo or PDF of a prescription against the signed record (Spec 11.2).

Purpose: the signature proves what the doctor signed. This module asks a different question:
         does the PAPER in front of the pharmacist still say that? It redraws the expected page
         from the signed payload, straightens the upload onto it, and compares zone by zone.
Honesty rules (these decide every verdict):
  - a zone only counts as different when the alignment is trustworthy ("good");
  - a different-looking zone needs OCR to agree that the text really differs, unless the zone is
    clearly blank or clearly different, or the picture is a clean digital copy;
  - when we cannot tell, the answer is UNREADABLE (a review prompt), never an accusation.
Outputs: a `ContentReport` with per-zone findings (outlined on the upload in the UI), the reason
         codes the pipeline turns into TAMPERED / REVIEW_REQUIRED, and a downscaled overlay image.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from statistics import median
from typing import Any

import cv2
import numpy as np

from app.ai import extract
from app.ai.ocr import OCREngine, get_engine
from app.ai.rectify import Rectified, rectify, zone_box
from app.ai.render_diff import compare_zone, even_out_lighting, ink_mask, raster_pdf_gray
from app.core import payload as pl
from app.core import pdf_layout as layout
from app.core.pdf import render_prescription_pdf
from app.core.qr import qr_matrix
from app.core.uploads import LoadedUpload

T_MIN = 0.045  # smallest image distance that can count as "different"
T_ADAPT = 4.0  # ...or this many times the page's typical (median) distance, for noisy photos
T_CLEAR = 0.25  # a distance this large is a clear difference even if OCR is unsure
EXTRA_MIN_PX = 180  # ink pixels (after removing specks) that make a blank area "not blank"
OCR_CONFIDENT = 0.85
OVERLAY_WIDTH = 1100

MATCH, MISMATCH, UNREADABLE, EXTRA = "MATCH", "MISMATCH", "UNREADABLE", "EXTRA_CONTENT"
_CROSS = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_SPECK = np.ones((3, 3), np.uint8)


@dataclass
class Finding:
    zone: str
    label: str
    signed: str
    read: str | None
    status: str
    distance: float
    quad: list[list[float]]  # outline of the zone on the overlay image


@dataclass
class ContentReport:
    status: str  # MATCH, MISMATCH or UNREADABLE (overall)
    reasons: list[str]
    findings: list[Finding]  # only the zones that did not simply match
    zones_checked: int
    alignment: dict[str, Any]
    overlay: dict[str, Any] | None
    file_integrity: str | None
    used_ocr: bool = False
    warnings: list[str] = field(default_factory=list)


# --- labels ---------------------------------------------------------------------------------------

_CELL_LABEL = {"name": "name", "dose": "dose", "freq": "frequency", "days": "duration"}


def zone_label(zone: str) -> str:
    if zone.startswith("med_"):
        _, index, cell = zone.split("_")
        return f"Medicine {int(index) + 1} {_CELL_LABEL[cell]}"
    return {
        "clinic": "Clinic",
        "doctor": "Doctor",
        "dates": "Dates",
        "patient": "Patient",
        "notes": "Notes",
        "footer": "Prescription ID and fingerprint",
    }.get(zone, "Blank area")


def _is_critical(zone: str) -> bool:
    """Fields whose misreading matters: medicines, patient, doctor and dates."""
    return zone.startswith("med_") or zone in {"patient", "doctor", "dates"}


# --- helpers --------------------------------------------------------------------------------------


def _zone_rect(name: str) -> layout.Rect:
    return layout.ZONES.get(name) or layout.BLANK_REGIONS[name]


def _blank_extra_px(rect: layout.Rect, expected: np.ndarray, actual: np.ndarray) -> int:
    """Ink in an area that should be empty, ignoring specks and a 2 px halo around expected ink."""
    x0, y0, x1, y1 = zone_box(rect)
    e = cv2.dilate(expected[y0:y1, x0:x1], _CROSS, iterations=2)
    extra = actual[y0:y1, x0:x1] & ~e
    extra = cv2.morphologyEx(extra, cv2.MORPH_OPEN, _SPECK)
    return int(np.count_nonzero(extra))


def _quad_on_overlay(rect: Rectified, zone: str, scale: float) -> list[list[float]]:
    x0, y0, x1, y1 = zone_box(_zone_rect(zone), pad=3)
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
    pts = rect.to_image(corners) * scale
    return [[round(float(x), 1), round(float(y), 1)] for x, y in pts]


def _overlay(image: np.ndarray) -> tuple[dict[str, Any], float]:
    height, width = image.shape[:2]
    scale = min(1.0, OVERLAY_WIDTH / width)
    small = (
        cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1
        else image
    )
    ok, buffer = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 78])
    data = base64.b64encode(buffer.tobytes()).decode("ascii") if ok else ""
    return (
        {
            "image": f"data:image/jpeg;base64,{data}",
            "width": int(small.shape[1]),
            "height": int(small.shape[0]),
        },
        scale,
    )


def _text_layer_words(upload: LoadedUpload) -> list[tuple[float, float, str]]:
    """(centre x, centre y, word) in PDF points for every word in the PDF's text layer."""
    if upload.pdf_page is None:
        return []
    words = []
    for x0, y0, x1, y1, word, *_ in upload.pdf_page.get_text("words"):
        words.append(((x0 + x1) / 2, (y0 + y1) / 2, str(word)))
    return words


def _layer_text(words: list[tuple[float, float, str]], rect: layout.Rect) -> str:
    inside = [
        w for w in words if rect.x <= w[0] <= rect.x + rect.w and rect.y <= w[1] <= rect.y + rect.h
    ]
    inside.sort(key=lambda w: (round(w[1] / 6), w[0]))
    return " ".join(w[2] for w in inside)


# --- the check ------------------------------------------------------------------------------------


def check_content(
    upload: LoadedUpload,
    data: bytes,
    payload: dict[str, Any],
    payload_hash: str,
    qr_string: str,
    pdf_sha256: str,
    engine: OCREngine | None = None,
) -> ContentReport:
    texts = pl.zone_texts(payload, payload_hash)
    blanks = pl.blank_zone_names(payload)
    zones_checked = len(texts) + len(blanks)

    expected_pdf = render_prescription_pdf(payload, payload_hash, qr_string)
    expected_gray = raster_pdf_gray(expected_pdf)
    expected_mask = ink_mask(even_out_lighting(expected_gray))
    overlay, scale = _overlay(upload.image)

    rect = rectify(upload.image, len(qr_matrix(qr_string)), expected_gray)
    if rect is None:
        return ContentReport(
            status=UNREADABLE,
            reasons=["LOW_ALIGNMENT", "UNREADABLE_CONTENT"],
            findings=[],
            zones_checked=zones_checked,
            alignment={"good": False, "fiducials": 0, "rms_px": None, "ecc": None},
            overlay=overlay,
            file_integrity=None,
        )

    actual = ink_mask(even_out_lighting(rect.gray))
    metrics = {name: compare_zone(name, _zone_rect(name), expected_mask, actual) for name in texts}
    typical = median(m.distance for m in metrics.values()) if metrics else 0.0
    threshold = max(T_MIN, T_ADAPT * typical)

    text_candidates = [n for n, m in metrics.items() if m.distance > threshold]
    blank_candidates = [
        n for n in blanks if _blank_extra_px(_zone_rect(n), expected_mask, actual) >= EXTRA_MIN_PX
    ]

    findings: list[Finding] = []
    used_ocr = False
    reasons: list[str] = []
    reads: dict[str, extract.ZoneRead] = {}
    if (text_candidates or blank_candidates) and rect.good:
        engine = engine or get_engine()
        lines = engine.read(even_out_lighting(rect.gray))
        used_ocr = True
        reads = {
            name: extract.read_zone(group)
            for name, group in extract.assign_lines(
                lines, text_candidates + blank_candidates
            ).items()
        }

    def add(zone: str, status: str, read: str | None, distance: float, signed: list[str]) -> None:
        findings.append(
            Finding(zone, zone_label(zone), " / ".join(signed), read, status, round(distance, 3),
                    _quad_on_overlay(rect, zone, scale))  # fmt: skip
        )

    for zone in text_candidates:
        distance = metrics[zone].distance
        if not rect.good:
            add(zone, UNREADABLE, None, distance, texts[zone])
            continue
        read = reads.get(zone)
        if read and read.lines and extract.same_text(read.text, texts[zone]):
            continue  # OCR agrees with the signed text: the image difference was noise
        if read and read.lines and read.confidence >= OCR_CONFIDENT:
            add(zone, MISMATCH, read.text, distance, texts[zone])
        elif distance >= T_CLEAR:
            add(zone, MISMATCH, read.text if read and read.lines else "", distance, texts[zone])
        else:
            add(zone, UNREADABLE, read.text if read and read.lines else None, distance, texts[zone])

    for zone in blank_candidates:
        if not rect.good:
            add(zone, UNREADABLE, None, 0.0, [""])
            continue
        read = reads.get(zone)
        add(zone, EXTRA, read.text if read and read.lines else "(marks)", 0.0, [""])

    # A PDF's text layer must agree with what is visibly drawn and with the signed text.
    if upload.kind == "pdf" and upload.has_text_layer:
        words = _text_layer_words(upload)
        already = {f.zone for f in findings}
        for zone in [*texts, *blanks]:
            layer = _layer_text(words, _zone_rect(zone))
            want = " ".join(texts.get(zone, []))
            if extract.normalise(layer) != extract.normalise(want):
                reasons.append("HIDDEN_TEXT_OR_OVERLAY")
                if zone not in already:
                    add(zone, MISMATCH, f"(text layer) {layer}".strip(), 0.0, texts.get(zone, [""]))

    if any(f.status == MISMATCH for f in findings):
        reasons.append("CONTENT_MISMATCH")
    if any(f.status == EXTRA for f in findings):
        reasons.append("EXTRA_CONTENT")
    unreadable = [f for f in findings if f.status == UNREADABLE]
    if unreadable and not rect.good:
        reasons.append("LOW_ALIGNMENT")
    critical_unreadable = [f for f in unreadable if _is_critical(f.zone) or f.zone in blanks]
    if critical_unreadable:
        reasons.append("UNREADABLE_CONTENT")
    reasons = list(dict.fromkeys(reasons))

    if any(f.status in (MISMATCH, EXTRA) for f in findings):
        status = MISMATCH
    elif critical_unreadable:
        status = UNREADABLE
    else:
        status = MATCH

    integrity = None
    if upload.kind == "pdf" and hashlib.sha256(data).hexdigest() == pdf_sha256:
        integrity = "ORIGINAL"
    elif status == MATCH:
        integrity = "REPRODUCTION"

    return ContentReport(
        status=status,
        reasons=reasons,
        findings=findings,
        zones_checked=zones_checked,
        alignment={
            "good": rect.good,
            "fiducials": rect.fiducials_found,
            "rms_px": round(rect.rms_px, 2),
            "ecc": None if rect.ecc_correlation is None else round(rect.ecc_correlation, 3),
        },
        overlay=overlay,
        file_integrity=integrity,
        used_ocr=used_ocr,
    )
