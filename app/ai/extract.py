"""Turn OCR lines into per-zone readings and compare them with the signed text (Spec 11.2/11.3).

Purpose: assign each OCR line to the zone of the page it sits in, rebuild the zone's text in
         reading order, and compare it with what was signed.
Rule   : numbers and spellings are compared EXACTLY (after dropping spaces, punctuation and case).
         One changed digit is a different prescription, so there is no fuzzy matching of content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.ocr import OCRLine
from app.ai.rectify import zone_box
from app.core import pdf_layout as layout

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    """Lower case, letters and digits only: spacing and punctuation differences do not matter."""
    return _NON_ALNUM.sub("", text.casefold())


@dataclass(frozen=True)
class ZoneRead:
    text: str  # the zone's text in reading order, lines joined by a space
    confidence: float  # the weakest line's confidence (0 when nothing was read)
    lines: int


def assign_lines(
    lines: list[OCRLine], zone_names: list[str], pad: int = 4
) -> dict[str, list[OCRLine]]:
    """Group OCR lines by the zone containing the line's centre (a line belongs to one zone)."""
    boxes = {
        name: zone_box(layout.ZONES.get(name) or layout.BLANK_REGIONS[name], pad)
        for name in zone_names
    }
    assigned: dict[str, list[OCRLine]] = {name: [] for name in zone_names}
    for line in lines:
        cx, cy = line.centre
        for name, (x0, y0, x1, y1) in boxes.items():
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                assigned[name].append(line)
                break
    return assigned


def reading_order(lines: list[OCRLine]) -> list[OCRLine]:
    """Top to bottom; lines whose centres are within half a text height share a row (left to right)."""
    by_y = sorted(lines, key=lambda ln: ln.centre[1])
    rows: list[list[OCRLine]] = []
    for line in by_y:
        if rows:
            anchor = rows[-1][0]
            if abs(line.centre[1] - anchor.centre[1]) <= 0.5 * max(line.height, anchor.height, 1.0):
                rows[-1].append(line)
                continue
        rows.append([line])
    return [ln for row in rows for ln in sorted(row, key=lambda ln: ln.centre[0])]


def read_zone(lines: list[OCRLine]) -> ZoneRead:
    if not lines:
        return ZoneRead("", 0.0, 0)
    ordered = reading_order(lines)
    return ZoneRead(
        text=" ".join(ln.text.strip() for ln in ordered),
        confidence=min(ln.confidence for ln in ordered),
        lines=len(ordered),
    )


def same_text(read: str, signed_lines: list[str]) -> bool:
    return normalise(read) == normalise(" ".join(signed_lines))
