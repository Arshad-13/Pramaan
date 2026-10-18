"""Prescription PDF generation (Spec Section 13.4).

Purpose: draw the prescription page from the SIGNED PAYLOAD ONLY (plus the QR text and hash).
Inputs : the payload dict, its SHA-256 hex, and the QR string.
Outputs: PDF bytes. Output is deterministic (fixed document dates/IDs), so identical input gives
         identical bytes; that makes `pdf_sha256` and the Phase 7 re-render comparison meaningful.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.pdfgen.canvas import Canvas

from app.core import payload as text
from app.core import pdf_layout as layout
from app.core.qr import qr_matrix

INK = (0.07, 0.10, 0.20)
MUTED = (0.35, 0.38, 0.45)
RULE = (0.80, 0.82, 0.86)


def _y(top: float) -> float:
    """Convert a top-origin y to reportlab's bottom-origin coordinate."""
    return layout.PAGE_H - top


def _draw(
    c: Canvas,
    s: str,
    zone: layout.Rect,
    *,
    baseline: float,
    font: str,
    size: float,
    dx: float = 0.0,
    color: tuple[float, float, float] = INK,
) -> None:
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    c.drawString(zone.x + dx, _y(zone.y + baseline), s)


def render_prescription_pdf(payload: dict[str, Any], payload_hash: str, qr_string: str) -> bytes:
    layout.register_fonts()
    buffer = io.BytesIO()
    c = Canvas(
        buffer,
        pagesize=(layout.PAGE_W, layout.PAGE_H),
        invariant=1,  # fixed dates and IDs: deterministic bytes
        pageCompression=0,
        initialFontName=layout.FONT,
    )
    c.setTitle("Pramaan prescription")
    c.setAuthor("Pramaan")
    c.setSubject("Digitally signed prescription")

    z = layout.ZONES

    # Corner fiducials (used to straighten photographs of the page).
    c.setFillColorRGB(0, 0, 0)
    for rect in layout.FIDUCIALS.values():
        c.rect(rect.x, _y(rect.y + rect.h), rect.w, rect.h, stroke=0, fill=1)

    # Header and parties
    _draw(
        c,
        text.clinic_text(payload),
        z["clinic"],
        baseline=19,
        font=layout.FONT_BOLD,
        size=layout.CLINIC_SIZE,
    )
    c.setStrokeColorRGB(*RULE)
    c.setLineWidth(0.8)
    c.line(
        z["clinic"].x, _y(z["clinic"].y + 30), z["clinic"].x + z["clinic"].w, _y(z["clinic"].y + 30)
    )

    doc_name, doc_reg = text.doctor_lines(payload)
    _draw(c, doc_name, z["doctor"], baseline=14, font=layout.FONT_BOLD, size=layout.NAME_SIZE)
    _draw(
        c, doc_reg, z["doctor"], baseline=32, font=layout.FONT, size=layout.BODY_SIZE, color=MUTED
    )

    for i, line in enumerate(text.dates_lines(payload)):
        _draw(c, line, z["dates"], baseline=14 + 18 * i, font=layout.FONT, size=layout.BODY_SIZE)

    _draw(
        c,
        text.patient_text(payload),
        z["patient"],
        baseline=16,
        font=layout.FONT_BOLD,
        size=layout.NAME_SIZE,
    )

    # Medicines table
    head = z["table_head"]
    for label, x in layout.TABLE_COLUMNS.values():
        c.setFont(layout.FONT_BOLD, 9)
        c.setFillColorRGB(*MUTED)
        c.drawString(x + text.CELL_PADDING, _y(head.y + 14), label.upper())
    c.setStrokeColorRGB(*RULE)
    c.line(head.x, _y(head.y + head.h), head.x + head.w, _y(head.y + head.h))
    for i, med in enumerate(payload["medicines"]):
        for zone_name, cell in zip(
            layout.zone_names_for_medicine(i), text.medicine_cells(med), strict=True
        ):
            _draw(
                c,
                cell,
                z[zone_name],
                dx=text.CELL_PADDING,
                baseline=17,
                font=layout.FONT,
                size=layout.BODY_SIZE,
            )
        row = z[f"med_{i}_name"]
        c.line(row.x, _y(row.y + row.h), row.x + head.w, _y(row.y + row.h))

    # Notes
    notes = z["notes"]
    for i, line in enumerate(text.notes_lines(payload)):
        _draw(
            c,
            line,
            notes,
            dx=text.CELL_PADDING,
            baseline=13 + layout.NOTE_LEADING * i,
            font=layout.FONT,
            size=layout.BODY_SIZE,
        )

    # Footer: id and fingerprint
    f1, f2 = text.footer_lines(payload["rx_id"], payload_hash)
    _draw(c, f1, z["footer"], baseline=14, font=layout.FONT, size=layout.BODY_SIZE, color=MUTED)
    _draw(c, f2, z["footer"], baseline=32, font=layout.FONT, size=layout.BODY_SIZE, color=MUTED)

    # QR code as vector squares (sharp at any resolution, deterministic)
    qr = z["qr"]
    matrix = qr_matrix(qr_string)
    modules = len(matrix) + 2 * layout.QR_QUIET_MODULES
    size = qr.w / modules
    c.setFillColorRGB(1, 1, 1)
    c.rect(qr.x, _y(qr.y + qr.h), qr.w, qr.h, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(matrix):
        for col_index, dark in enumerate(row):
            if dark:
                x = qr.x + (col_index + layout.QR_QUIET_MODULES) * size
                top = qr.y + (row_index + layout.QR_QUIET_MODULES) * size
                c.rect(x, _y(top + size), size, size, stroke=0, fill=1)
    cap = z["qr_caption"]
    c.setFont(layout.FONT, 8)
    c.setFillColorRGB(*MUTED)
    c.drawRightString(cap.x + cap.w, _y(cap.y + 10), "Scan with Pramaan to verify")

    c.showPage()
    c.save()
    return buffer.getvalue()
