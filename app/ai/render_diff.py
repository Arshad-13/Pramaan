"""Render the expected page and compare it with the straightened upload, zone by zone (Spec 11.2).

Why compare images instead of trusting OCR: OCR can misread a *genuine* digit and so accuse an
honest doctor, and it cannot say where an edit is. We know exactly what a genuine document looks
like (it is rendered deterministically from the signed payload), so we draw it and compare.

Pipeline per upload:
  1. render the expected page from the signed payload  -> canonical gray raster
  2. straighten the upload onto the same raster (rectify.py)
  3. even out the lighting, turn both into black/white "ink" masks
  4. per zone, measure how much expected ink is missing and how much unexpected ink appeared,
     allowing a small shift and a little blur
  5. zones that look different get a second opinion from OCR (ocr.py / extract.py)
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pymupdf

from app.ai.rectify import CANON_H, CANON_W, SCALE, zone_box

MAX_SHIFT = 3  # pixels of misalignment we forgive (at 200 dpi)
INK_FLOOR = 0.04  # expected-ink floor (share of zone area) for the distance denominators


def raster_pdf_gray(pdf_bytes: bytes) -> np.ndarray:
    """First page of a PDF as a canonical-size gray image."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(SCALE, SCALE), colorspace=pymupdf.csGRAY, alpha=False
    )
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    if arr.shape != (CANON_H, CANON_W):
        arr = cv2.resize(arr, (CANON_W, CANON_H), interpolation=cv2.INTER_AREA)
    return arr


def even_out_lighting(gray: np.ndarray) -> np.ndarray:
    """Divide by an estimate of the paper brightness so shadows and gradients disappear."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), 15)
    flat = cv2.divide(gray, background, scale=255)
    return flat


def ink_mask(gray: np.ndarray, *, adaptive: bool = True) -> np.ndarray:
    """255 where there is ink (dark), 0 elsewhere."""
    if adaptive:
        blur = cv2.GaussianBlur(gray, (0, 0), 0.8)
        _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return mask
    _, mask = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    return mask


@dataclass
class ZoneMetric:
    zone: str
    miss: float  # expected ink that is missing, as a fraction of expected ink
    extra: float  # unexpected ink, as a fraction of expected ink
    expected_ink: int
    actual_ink: int
    area: int
    extra_px: int = 0  # raw count of unexpected ink pixels (for zones that should be blank)

    @property
    def extra_ratio(self) -> float:
        """Unexpected ink as a share of the zone area."""
        return self.extra_px / max(self.area, 1)

    @property
    def distance(self) -> float:
        return max(self.miss, self.extra)

    @property
    def ink_ratio(self) -> float:
        """Actual ink as a share of the zone's area (used for zones that should be blank)."""
        return self.actual_ink / max(self.area, 1)


_CROSS = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))


def compare_zone(
    name: str, rect, expected_mask: np.ndarray, actual_mask: np.ndarray, *, tolerance: int = 1
) -> ZoneMetric:
    """Distance between the expected and actual ink in one zone, best over small shifts."""
    x0, y0, x1, y1 = zone_box(rect)
    e = expected_mask[y0:y1, x0:x1]
    pad = MAX_SHIFT
    ax0, ay0 = max(0, x0 - pad), max(0, y0 - pad)
    ax1, ay1 = min(CANON_W, x1 + pad), min(CANON_H, y1 + pad)
    a_pad = actual_mask[ay0:ay1, ax0:ax1]
    e_count = int(np.count_nonzero(e))
    area = e.size
    if tolerance:
        e_dil = cv2.dilate(e, _CROSS, iterations=tolerance)
    else:
        e_dil = e
    best = None
    h, w = e.shape
    for dy in range(-pad, pad + 1):
        for dx in range(-pad, pad + 1):
            sy, sx = (y0 + dy) - ay0, (x0 + dx) - ax0
            if sy < 0 or sx < 0 or sy + h > a_pad.shape[0] or sx + w > a_pad.shape[1]:
                continue
            a = a_pad[sy : sy + h, sx : sx + w]
            a_dil = cv2.dilate(a, _CROSS, iterations=tolerance) if tolerance else a
            a_count = int(np.count_nonzero(a))
            miss = int(np.count_nonzero(e & ~a_dil))
            extra = int(np.count_nonzero(a & ~e_dil))
            denom = max(e_count, int(INK_FLOOR * area))  # blank zones are judged against a floor
            metric = ZoneMetric(name, miss / denom, extra / denom, e_count, a_count, area, extra)
            if best is None or metric.distance < best.distance:
                best = metric
    assert best is not None
    return best
