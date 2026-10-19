"""Stress test: many simulated photos of UNALTERED prescriptions must never come out TAMPERED (Phase 7).

Usage: python scripts/stress_photos.py
"""

import sys

sys.path.insert(0, ".")
from collections import Counter

import scripts.evaluate_upload as ev
from app.ai import samples
from app.ai.content_check import check_content
from app.core.canonical import canonical_bytes, sha256_hex
from app.core.pdf import render_prescription_pdf
from app.core.qr import build_qr
from app.core.uploads import load_upload

c = Counter()
bad = []
for key, payload in ev.PAYLOADS.items():
    h = sha256_hex(canonical_bytes(payload))
    qr = build_qr(payload["rx_id"], ev.KEY, h, bytes.fromhex(h) * 2)
    pdf = render_prescription_pdf(payload, h, qr)
    page = samples.rasterize(pdf)
    for seed in range(200, 225):
        harsh = seed % 3 == 0
        kw = (
            dict(blur_sigma=(1.2, 2.0), noise_sigma=(6, 10), jpeg_quality=(40, 60)) if harsh else {}
        )
        data = samples.to_jpeg(samples.photograph(page, seed, **kw), 90)
        r = check_content(load_upload(data), data, payload, h, qr, "x")
        v = {"MATCH": "VALID", "MISMATCH": "TAMPERED"}.get(r.status, "REVIEW_REQUIRED")
        c[(harsh, v)] += 1
        if v == "TAMPERED":
            bad.append(
                (key, seed, harsh, [(f.zone, f.signed, f.read, f.distance) for f in r.findings])
            )
print(c)
for b in bad:
    print(b)
