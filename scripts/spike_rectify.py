"""Phase 7 feasibility spike: can we tell a genuine page from an edited one by redrawing it?

Measures, on simulated captures, how large the per-zone image distance is for
  - genuine pages (digital render, JPEG, and simulated photos), versus
  - pages where ONE field was redrawn in the same font (the careful forger).
If the genuine distances stay clearly below the forged ones, render-and-diff is a go.

Usage: python scripts/spike_rectify.py [--photos 20]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import samples  # noqa: E402
from app.ai.rectify import rectify  # noqa: E402
from app.ai.render_diff import (
    compare_zone,
    even_out_lighting,
    ink_mask,
    raster_pdf_gray,
)  # noqa: E402
from app.core import pdf_layout as layout  # noqa: E402
from app.core.canonical import canonical_bytes, sha256_hex  # noqa: E402
from app.core.pdf import render_prescription_pdf  # noqa: E402
from app.core.qr import build_qr, qr_matrix  # noqa: E402
from tests.test_payload_pdf import KEY, RX, make_payload  # noqa: E402


def build_sample():
    payload = make_payload(
        medicines=[
            {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5},
            {"name": "Paracetamol", "dose_mg": 650, "frequency": "SOS", "duration_days": 3},
            {"name": "Cetirizine", "dose_mg": 10, "frequency": "HS", "duration_days": 7},
        ],
        notes="Take after food. Avoid alcohol.\nReturn if symptoms persist.",
    )
    canonical = canonical_bytes(payload)
    payload_hash = sha256_hex(canonical)
    qr = build_qr(RX, KEY, payload_hash, bytes.fromhex(payload_hash) * 2)
    return payload, payload_hash, qr, render_prescription_pdf(payload, payload_hash, qr)


def measure(image, expected_mask, modules, expected_gray):
    started = time.time()
    rect = rectify(image, modules, expected_gray)
    if rect is None:
        return None, {}
    flat = even_out_lighting(rect.gray)
    actual = ink_mask(flat)
    zones = {
        n: compare_zone(n, r, expected_mask, actual) for n, r in layout.ZONES.items() if n != "qr"
    }
    rect.notes.append(f"{time.time() - started:.1f}s")
    return rect, zones


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos", type=int, default=20)
    args = parser.parse_args()

    payload, payload_hash, qr, pdf = build_sample()
    modules = len(qr_matrix(qr))
    expected_gray = raster_pdf_gray(pdf)
    expected = ink_mask(even_out_lighting(expected_gray))
    page = samples.rasterize(pdf)
    print(f"QR modules: {modules}; page raster {page.shape[1]}x{page.shape[0]}")

    used = [n for n in layout.ZONES if n not in ("qr",) and layout.ZONES[n] is not None]
    text_zones = [n for n in used if int(np.count_nonzero(expected[_slice(layout.ZONES[n])])) > 0]
    blank_zones = [n for n in used if n not in text_zones]
    print(f"{len(text_zones)} text zones, {len(blank_zones)} blank zones")

    def report(label, image):
        rect, zones = measure(image, expected, modules, expected_gray)
        if rect is None:
            print(f"{label:<34} QR NOT FOUND")
            return None
        worst = max(zones[n].distance for n in text_zones)
        blank = max(zones[n].extra_ratio for n in blank_zones)
        cc = rect.ecc_correlation or 0.0
        print(
            f"{label:<34} fid={rect.fiducials_found}/3 rms={rect.rms_px:5.2f}px ecc={cc:4.2f} "
            f"worst-text-zone={worst:5.3f} blank-extra={blank:6.4f} [{rect.notes[-1]}]"
        )
        return zones

    print("\n== GENUINE")
    report("digital raster", page)
    report("digital JPEG q90", _decode(samples.to_jpeg(page, 90)))
    genuine_worst = []
    for seed in range(args.photos):
        z = report(f"photo seed {seed}", samples.photograph(page, seed))
        if z:
            genuine_worst.append(max(z[n].distance for n in text_zones))
    if genuine_worst:
        print(
            f"\ngenuine photos: worst-zone distance min={min(genuine_worst):.3f} "
            f"median={np.median(genuine_worst):.3f} max={max(genuine_worst):.3f}"
        )

    print("\n== FORGED (one field redrawn in the same font)")
    forged = {
        "dose 500 -> 800 mg": (samples.edit_medicine(page, payload, 0, dose_mg=800), "med_0_dose"),
        "dose 650 -> 850 mg": (samples.edit_medicine(page, payload, 1, dose_mg=850), "med_1_dose"),
        "days 5 -> 9": (samples.edit_medicine(page, payload, 0, duration_days=9), "med_0_days"),
        "frequency TDS -> OD": (
            samples.edit_medicine(page, payload, 0, frequency="OD"),
            "med_0_freq",
        ),
        "name Cetirizine -> Cetirizone": (
            samples.edit_medicine(page, payload, 2, name="Cetirizone"),
            "med_2_name",
        ),
        "patient Patel -> Patil": (
            samples.edit_patient(page, payload, name="Ravi Patil"),
            "patient",
        ),
        "age 34 -> 54": (samples.edit_patient(page, payload, age=54), "patient"),
        "expiry +1 year": (samples.edit_expiry(page, payload, "2027-11-17T10:30:00Z"), "dates"),
        "licence GJ-12345 -> GJ-12346": (
            samples.edit_doctor_reg(page, payload, "GJ-12346"),
            "doctor",
        ),
        "clinic renamed": (samples.edit_clinic(page, "Shah Clinic, Surah"), "clinic"),
        "notes changed": (samples.edit_notes(page, "Double the dose if needed."), "notes"),
    }
    forged_extra = {
        "extra medicine row": (
            samples.add_medicine_row(
                page,
                3,
                {"name": "Alprazolam", "dose_mg": 2, "frequency": "BD", "duration_days": 30},
            ),
            "med_3_name",
        ),
        "margin scribble": (samples.add_margin_text(page, "Dispense 200 tablets"), None),
    }
    print("\n-- digital")
    for label, (image, zone) in {**forged, **forged_extra}.items():
        rect, zones = measure(image, expected, modules, expected_gray)
        if rect is None:
            print(f"{label:<32} QR NOT FOUND")
            continue
        edited = zones[zone].distance if zone else 0.0
        others = max(zones[n].distance for n in text_zones if n != zone)
        blank = max(zones[n].extra_ratio for n in blank_zones)
        print(
            f"{label:<32} edited-zone={edited:5.3f}  others-max={others:5.3f}  blank-extra={blank:6.4f}"
        )

    print("\n-- photographed (seed 7)")
    for label, (image, zone) in {**forged, **forged_extra}.items():
        rect, zones = measure(samples.photograph(image, 7), expected, modules, expected_gray)
        if rect is None:
            print(f"{label:<32} QR NOT FOUND")
            continue
        edited = zones[zone].distance if zone else 0.0
        others = max(zones[n].distance for n in text_zones if n != zone)
        blank = max(zones[n].extra_ratio for n in blank_zones)
        print(
            f"{label:<32} edited-zone={edited:5.3f}  others-max={others:5.3f}  blank-extra={blank:6.4f}"
        )
    return 0


def _slice(rect):
    from app.ai.rectify import zone_box

    x0, y0, x1, y1 = zone_box(rect)
    return slice(y0, y1), slice(x0, x1)


def _decode(jpeg: bytes):
    import cv2

    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


if __name__ == "__main__":
    sys.exit(main())
