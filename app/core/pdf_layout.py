"""Single source of truth for the prescription page layout (Spec Section 13.4).

Purpose: the PDF generator draws using these positions, and (in Phase 7) the verifier crops the
         same zones from an uploaded photo to compare against a re-render. Keeping geometry in one
         place means "where is the dose of medicine 3?" has exactly one answer.
Units  : PDF points (1/72 inch), origin at the TOP-LEFT of the page, y grows downward.
Fonts  : Bitstream Vera (ships with reportlab, so no font downloads). It covers Latin scripts only,
         so text that cannot be printed is rejected before signing (what is printed must be what
         is signed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PAGE_W = 595.276  # A4
PAGE_H = 841.890
MAX_MEDICINES = 8
MAX_NOTE_LINES = 5
NOTE_LEADING = 15.0

FONT = "Vera"
FONT_BOLD = "VeraBd"
BODY_SIZE = 11.0  # at least 11 pt for OCR accuracy
NAME_SIZE = 12.0
CLINIC_SIZE = 16.0


@dataclass(frozen=True)
class Rect:
    x: float
    y: float  # from the top of the page
    w: float
    h: float


def _med_row(i: int) -> dict[str, Rect]:
    y = 210.0 + 26.0 * i
    return {
        f"med_{i}_name": Rect(40, y, 244, 24),
        f"med_{i}_dose": Rect(290, y, 70, 24),
        f"med_{i}_freq": Rect(366, y, 74, 24),
        f"med_{i}_days": Rect(446, y, 72, 24),
    }


ZONES: dict[str, Rect] = {
    "clinic": Rect(40, 44, 515, 26),
    "doctor": Rect(40, 84, 260, 44),
    "dates": Rect(310, 84, 245, 64),
    "patient": Rect(40, 148, 515, 22),
    "table_head": Rect(40, 186, 515, 20),
    **{name: rect for i in range(MAX_MEDICINES) for name, rect in _med_row(i).items()},
    "notes": Rect(40, 436, 515, 84),
    "footer": Rect(40, 770, 360, 52),
    "qr": Rect(455, 700, 100, 100),
    "qr_caption": Rect(405, 806, 150, 14),
}

# Corner fiducials: three black squares plus the QR give four known anchor points, so the
# verifier can straighten a photographed page (Phase 7).
FIDUCIAL_SIZE = 14.0
FIDUCIALS: dict[str, Rect] = {
    "fid_tl": Rect(24, 24, FIDUCIAL_SIZE, FIDUCIAL_SIZE),
    "fid_tr": Rect(PAGE_W - 24 - FIDUCIAL_SIZE, 24, FIDUCIAL_SIZE, FIDUCIAL_SIZE),
    "fid_bl": Rect(24, PAGE_H - 24 - FIDUCIAL_SIZE, FIDUCIAL_SIZE, FIDUCIAL_SIZE),
}

QR_QUIET_MODULES = 2  # white border inside the QR rectangle, in modules

TABLE_COLUMNS = {
    "name": ("Medicine", 40.0),
    "dose": ("Dose", 290.0),
    "freq": ("Frequency", 366.0),
    "days": ("Duration", 446.0),
}


def zone_names_for_medicine(i: int) -> tuple[str, str, str, str]:
    return (f"med_{i}_name", f"med_{i}_dose", f"med_{i}_freq", f"med_{i}_days")


# --- fonts and measurement ---------------------------------------------------------------------


@lru_cache
def register_fonts() -> None:
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(folder, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(folder, "VeraBd.ttf")))


def text_width(text: str, font: str = FONT, size: float = BODY_SIZE) -> float:
    register_fonts()
    return pdfmetrics.stringWidth(text, font, size)


@lru_cache
def _glyphs() -> frozenset[int]:
    register_fonts()
    return frozenset(pdfmetrics.getFont(FONT).face.charToGlyph)


def unprintable_characters(text: str) -> list[str]:
    """Characters the page font cannot draw (newlines are handled by the notes wrapper)."""
    glyphs = _glyphs()
    return sorted({ch for ch in text if ch != "\n" and ord(ch) not in glyphs})


def wrap_lines(text: str, width: float, font: str = FONT, size: float = BODY_SIZE) -> list[str]:
    """Greedy word wrap (deterministic: the verifier relies on the same result). Words longer than
    a line are split by character."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else f"{current} {word}"
            if text_width(candidate, font, size) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            while text_width(word, font, size) > width:  # an over-long word
                cut = len(word)
                while cut > 1 and text_width(word[:cut], font, size) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


# Static template text (labels, caption): not payload content, so never compared as evidence.
STATIC_ZONES = frozenset({"qr", "qr_caption", "table_head"})

# Areas of the page that are always empty on a genuine prescription. Ink here means somebody
# added something. (Unused medicine rows and an empty notes box are blank too; see payload.py.)
BLANK_REGIONS: dict[str, Rect] = {
    "blank_gap": Rect(40, 418, 515, 16),
    "blank_mid": Rect(40, 526, 515, 170),
}
