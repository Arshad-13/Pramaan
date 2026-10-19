"""Straighten a photographed or rendered prescription page onto the canonical page (Spec 11.2).

Purpose: given any image of the page, find where the known marks are (the QR code plus three
         corner squares), compute the perspective transform that maps the image onto the exact
         canonical raster the generator uses, and report how trustworthy the alignment is.
Inputs : an image (BGR or gray), the number of QR modules of the expected code and, optionally,
         the expected page raster (used for a final fine alignment).
Outputs: `Rectified` with the straightened gray page, the transform (and its inverse, so zones can
         be drawn back onto the original photo) and an alignment-quality summary.

The canonical raster is A4 at 200 dpi. A digital render maps onto it with an (almost) identity
transform; a photo needs the full perspective correction. Everything is derived from
`pdf_layout`, the single source of truth for where things are on the page.

Safety rule: alignment quality is reported honestly (`good`). Callers must never treat a
difference as tampering when the alignment is not good.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core import pdf_layout as layout
from app.core.qr import locate_qr

DPI = 200
SCALE = DPI / 72.0  # canonical pixels per PDF point
CANON_W = round(layout.PAGE_W * SCALE)
CANON_H = round(layout.PAGE_H * SCALE)

GOOD_RMS_PX = 4.0  # anchor reprojection error (canonical pixels) below which alignment is "good"
OUTLIER_PX = 8.0  # a corner mark further than this from the fit is discarded as a false find
SEARCH_WINDOWS = (6.0, 3.6, 2.2)  # search radius (in mark sizes), narrowing as the fit improves


def px(value_pt: float) -> float:
    return value_pt * SCALE


def zone_box(rect: layout.Rect, pad: int = 0) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) in canonical pixels, clipped to the page."""
    x0 = max(0, int(round(px(rect.x))) - pad)
    y0 = max(0, int(round(px(rect.y))) - pad)
    x1 = min(CANON_W, int(round(px(rect.x + rect.w))) + pad)
    y1 = min(CANON_H, int(round(px(rect.y + rect.h))) + pad)
    return x0, y0, x1, y1


def expected_qr_corners(modules: int) -> np.ndarray:
    """Where the QR symbol's four corners (TL, TR, BR, BL) sit on the canonical page."""
    z = layout.ZONES["qr"]
    module = z.w / (modules + 2 * layout.QR_QUIET_MODULES)
    x0 = z.x + layout.QR_QUIET_MODULES * module
    y0 = z.y + layout.QR_QUIET_MODULES * module
    side = modules * module
    pts = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    return np.array([(px(x), px(y)) for x, y in pts], dtype=np.float64)


def fiducial_centres() -> dict[str, np.ndarray]:
    return {
        name: np.array([px(r.x + r.w / 2), px(r.y + r.h / 2)], dtype=np.float64)
        for name, r in layout.FIDUCIALS.items()
    }


@dataclass
class Rectified:
    gray: np.ndarray  # canonical-size gray image of the straightened page
    h: np.ndarray  # image -> canonical
    h_inv: np.ndarray  # canonical -> image
    qr_text: str
    fiducials_found: int
    rms_px: float
    source_size: tuple[int, int]  # (width, height) of the original image
    ecc_correlation: float | None = None  # how well the fine alignment matched the expected page
    notes: list[str] = field(default_factory=list)

    @property
    def good(self) -> bool:
        """Alignment is trustworthy enough that a visible difference means a real difference."""
        return self.fiducials_found == len(layout.FIDUCIALS) and self.rms_px <= GOOD_RMS_PX

    def to_image(self, points: np.ndarray) -> np.ndarray:
        """Map canonical-pixel points back onto the original image."""
        return _transform(self.h_inv, points)


def _transform(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    arr = np.asarray(pts, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(arr, h).reshape(-1, 2)


def _find_fiducial(
    gray: np.ndarray, h_inv: np.ndarray, name: str, window: float = 2.6
) -> np.ndarray | None:
    """Look for one corner square near where the current transform says it should be.

    A candidate must be a solid, nearly square dark blob of about the right size with a clear
    white margin around it. That rules out letters, table edges and shadows."""
    r = layout.FIDUCIALS[name]
    corners_c = np.array(
        [
            (px(r.x), px(r.y)),
            (px(r.x + r.w), px(r.y)),
            (px(r.x + r.w), px(r.y + r.h)),
            (px(r.x), px(r.y + r.h)),
        ]
    )
    quad = _transform(h_inv, corners_c)
    centre = quad.mean(axis=0)
    expected_area = abs(cv2.contourArea(quad.astype(np.float32)))
    if expected_area < 16:
        return None
    side = float(np.sqrt(expected_area))
    half = int(side * window) + 4
    cx, cy = int(round(centre[0])), int(round(centre[1]))
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(gray.shape[1], cx + half), min(gray.shape[0], cy + half)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = cv2.GaussianBlur(gray[y0:y1, x0:x1], (0, 0), max(0.8, side / 25))
    # Local contrast normalisation: robust to shadows and gradients across the window.
    background = cv2.GaussianBlur(crop, (0, 0), max(4.0, side))
    flat = cv2.divide(crop, np.maximum(background, 1), scale=200)
    _, mask = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    margin = max(2, int(0.6 * side))
    best, best_dist = None, 1e9
    for contour in contours:
        area = cv2.contourArea(contour)
        if not (0.5 * expected_area <= area <= 2.0 * expected_area):
            continue
        (_, _), (w, hh), _ = cv2.minAreaRect(contour)
        if min(w, hh) < 1 or max(w, hh) / min(w, hh) > 1.25:
            continue
        if area / max(w * hh, 1) < 0.9:  # solid, not a letter
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        rx0, ry0 = max(0, bx - margin), max(0, by - margin)
        rx1, ry1 = min(mask.shape[1], bx + bw + margin), min(mask.shape[0], by + bh + margin)
        ring = mask[ry0:ry1, rx0:rx1].copy()
        ring[by - ry0 : by - ry0 + bh, bx - rx0 : bx - rx0 + bw] = 0
        if ring.size and np.count_nonzero(ring) / ring.size > 0.06:  # not isolated: reject
            continue
        m = cv2.moments(contour)
        if m["m00"] == 0:
            continue
        c = np.array([m["m10"] / m["m00"] + x0, m["m01"] / m["m00"] + y0])
        dist = float(np.linalg.norm(c - centre))
        if dist < best_dist:
            best, best_dist = c, dist
    return best


def _fit(src: list[np.ndarray], dst: list[np.ndarray]) -> np.ndarray | None:
    src_a, dst_a = np.array(src, dtype=np.float64), np.array(dst, dtype=np.float64)
    if len(src_a) == 3:
        affine = cv2.getAffineTransform(src_a.astype(np.float32), dst_a.astype(np.float32))
        return np.vstack([affine, [0, 0, 1]])
    h, _ = cv2.findHomography(src_a, dst_a, 0)
    return h


def _residuals(h: np.ndarray, src: list[np.ndarray], dst: list[np.ndarray]) -> np.ndarray:
    src_a, dst_a = np.array(src, dtype=np.float64), np.array(dst, dtype=np.float64)
    return np.linalg.norm(_transform(h, src_a) - dst_a, axis=1)


def _robust_fit(
    base_src: list[np.ndarray],
    base_dst: list[np.ndarray],
    found: dict[str, np.ndarray],
    centres: dict[str, np.ndarray],
) -> tuple[np.ndarray | None, dict[str, np.ndarray], list[np.ndarray], list[np.ndarray]]:
    """Fit using the QR corners plus the corner marks, discarding any mark that disagrees."""
    kept = dict(found)
    while True:
        src = list(base_src) + [kept[n] for n in kept]
        dst = list(base_dst) + [centres[n] for n in kept]
        h = _fit(src, dst)
        if h is None or len(kept) < 2:
            return h, kept, src, dst
        res = _residuals(h, src, dst)[len(base_src) :]
        worst = int(np.argmax(res))
        if res[worst] <= OUTLIER_PX:
            return h, kept, src, dst
        del kept[list(kept)[worst]]


def ecc_refine(
    expected_gray: np.ndarray,
    warped_gray: np.ndarray,
    scale: float = 0.5,
    iterations: int = 30,
) -> tuple[np.ndarray, float] | None:
    """Fine-tune the alignment by registering the straightened page against the expected one.

    Returns (W_full, correlation) where aligned(x) = warped(W_full x), or None if it cannot
    converge. Only the geometry changes: nothing here can make a different-looking field match."""

    def prepare(img: np.ndarray) -> np.ndarray:
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(small, (0, 0), 1.6).astype(np.float32) / 255.0

    template, moving = prepare(expected_gray), prepare(warped_gray)
    warp = np.eye(3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iterations, 1e-6)
    try:
        cc, warp = cv2.findTransformECC(
            template, moving, warp, cv2.MOTION_HOMOGRAPHY, criteria, None, 5
        )
    except cv2.error:
        return None
    s = np.diag([scale, scale, 1.0])
    return np.linalg.inv(s) @ warp.astype(np.float64) @ s, float(cc)


def rectify(
    image: np.ndarray, expected_modules: int, expected_gray: np.ndarray | None = None
) -> Rectified | None:
    """Return the straightened page, or None if the QR code (the main anchor) cannot be found.

    Steps: (1) find the QR code; (2) a rough affine fit from its three accurate corners (OpenCV
    estimates the fourth, bottom-right one, loosely, so it is not trusted); (3) find the corner
    squares, widening then narrowing the search as the fit improves, and drop any that disagree;
    (4) optionally fine-tune against the expected page with ECC."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    located = locate_qr(gray)
    if located is None:
        return None
    qr_text, qr_pts = located
    dst_qr = expected_qr_corners(expected_modules)

    keep = [0, 1, 3]  # TL, TR, BL: the corners backed by finder patterns
    base_src = [qr_pts[i] for i in keep]
    base_dst = [dst_qr[i] for i in keep]
    h = _fit(base_src, base_dst)
    if h is None:
        return None

    centres = fiducial_centres()
    kept: dict[str, np.ndarray] = {}
    src, dst = list(base_src), list(base_dst)
    for window in SEARCH_WINDOWS:
        h_inv = np.linalg.inv(h)
        found = {}
        for name in centres:
            point = _find_fiducial(gray, h_inv, name, window)
            if point is not None:
                found[name] = point
        refit, kept, src, dst = _robust_fit(base_src, base_dst, found, centres)
        if refit is not None and found:
            h = refit
    rms = float(np.sqrt(np.mean(_residuals(h, src, dst) ** 2)))

    cc = None
    if expected_gray is not None:
        warped = cv2.warpPerspective(
            gray, h, (CANON_W, CANON_H), flags=cv2.INTER_CUBIC, borderValue=255
        )
        refined = ecc_refine(expected_gray, warped)
        if refined is not None and refined[1] > 0.5:
            w_full, cc = refined
            h = np.linalg.inv(w_full) @ h

    final = cv2.warpPerspective(gray, h, (CANON_W, CANON_H), flags=cv2.INTER_CUBIC, borderValue=255)
    return Rectified(
        gray=final,
        h=h,
        h_inv=np.linalg.inv(h),
        qr_text=qr_text,
        fiducials_found=len(kept),
        rms_px=rms,
        source_size=(gray.shape[1], gray.shape[0]),
        ecc_correlation=cc,
    )
