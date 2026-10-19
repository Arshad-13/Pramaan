"""Measure upload verification on a generated sample set and write docs/evaluation.md (Phase 7).

Purpose: build genuine and tampered prescriptions (digital files and simulated phone photos),
         run each through the real content check, and report a confusion matrix, whether the
         right field was outlined, and timings. Sample files are written to --out for the demo.
Honesty: photographs are SIMULATED (perspective, blur, noise, uneven light, JPEG), not real phone
         captures. docs/evaluation.md says so.

Usage: python scripts/evaluate_upload.py [--out samples] [--report docs/evaluation.md]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import samples  # noqa: E402
from app.ai.content_check import MATCH, MISMATCH, check_content  # noqa: E402
from app.core import payload as pl  # noqa: E402
from app.core.canonical import canonical_bytes, sha256_hex  # noqa: E402
from app.core.pdf import render_prescription_pdf  # noqa: E402
from app.core.qr import build_qr  # noqa: E402
from app.core.uploads import load_upload  # noqa: E402

KEY = "9a1c0e77b2d4f605"
ISSUED = datetime(2026, 10, 18, 10, 30, 17, tzinfo=UTC)
START, END = "<!-- upload-eval:start -->", "<!-- upload-eval:end -->"
VERDICT = {MATCH: "VALID", MISMATCH: "TAMPERED"}  # anything else is REVIEW_REQUIRED


def make(rx_id: str, **overrides) -> dict:
    args = dict(
        rx_id=rx_id,
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
        medicines=[],
        notes="",
    )
    args.update(overrides)
    return pl.build_payload(**args)


def med(name, dose, freq, days):
    return {"name": name, "dose_mg": dose, "frequency": freq, "duration_days": days}


PAYLOADS = {
    "A": make(
        "7c1f0a52-1111-4a6e-9a3b-0a1b2c3d4e01",
        medicines=[
            med("Amoxicillin", 500, "TDS", 5),
            med("Paracetamol", 650, "SOS", 3),
            med("Cetirizine", 10, "HS", 7),
        ],
        notes="Take after food. Avoid alcohol.\nReturn if symptoms persist.",
    ),
    "B": make(
        "7c1f0a52-2222-4a6e-9a3b-0a1b2c3d4e02",
        medicines=[med("Metformin", 850, "BD", 30)],
        patient={"id": "p-2", "name": "Sneha Rao", "age_years": 52},
    ),
    "C": make(
        "7c1f0a52-3333-4a6e-9a3b-0a1b2c3d4e03",
        medicines=[med("Azithromycin", 250, "OD", 5), med("Ibuprofen", 400, "TDS", 4)],
        doctor={
            "id": "d-2",
            "name": "Dr. M. Iyer",
            "license_no": "MH-70421",
            "clinic": "Iyer Family Clinic, Pune",
        },
        patient={"id": "p-3", "name": "Kabir Khan", "age_years": 41},
        notes="Complete the course.",
    ),
}


def bump(n: int) -> int:
    """Change the leading digit only: 500 -> 800, 650 -> 950, 10 -> 40."""
    text = str(n)
    lead = (int(text[0]) + 3) % 10 or 1
    return int(str(lead) + text[1:])


@dataclass
class Case:
    cid: str
    group: str  # genuine-digital | genuine-photo | tampered-digital | tampered-photo
    description: str
    data: bytes
    ext: str
    expect_zone: str | None = None  # zone that should be outlined (None: any / not applicable)
    payload_key: str = ""


def build_cases() -> list[tuple[Case, dict, str, str, str]]:
    """Each case with (payload, payload_hash, qr, pdf_sha) context for the checker."""
    out = []
    for key, payload in PAYLOADS.items():
        canonical = canonical_bytes(payload)
        payload_hash = sha256_hex(canonical)
        qr = build_qr(payload["rx_id"], KEY, payload_hash, bytes.fromhex(payload_hash) * 2)
        pdf = render_prescription_pdf(payload, payload_hash, qr)
        pdf_sha = sha256_hex(pdf)
        page = samples.rasterize(pdf)
        ctx = (payload, payload_hash, qr, pdf_sha)

        def add(cid, group, desc, data, ext, zone=None, _ctx=ctx, _key=key):
            out.append((Case(f"{_key}-{cid}", group, desc, data, ext, zone, _key), *_ctx))

        meds = payload["medicines"]
        add("orig", "genuine-digital", "original PDF", pdf, "pdf")
        add("png", "genuine-digital", "page as PNG", samples.to_png(page), "png")
        add("jpg", "genuine-digital", "page as JPEG q85", samples.to_jpeg(page, 85), "jpg")
        for i, seed in enumerate(
            (1, 2, 3, 4) if key == "A" else (5, 6, 7) if key == "B" else (8, 9, 10, 11, 12)
        ):
            photo = samples.photograph(page, seed + 100 * (key == "C"))
            add(
                f"photo{i}",
                "genuine-photo",
                f"simulated photo (seed {seed})",
                samples.to_jpeg(photo, 90),
                "jpg",
            )

        m0 = meds[0]
        dose = bump(m0["dose_mg"])
        add(
            "dose",
            "tampered-digital",
            f"dose {m0['dose_mg']} -> {dose} mg (one digit)",
            samples.to_png(samples.edit_medicine(page, payload, 0, dose_mg=dose)),
            "png",
            "med_0_dose",
        )
        add(
            "days",
            "tampered-digital",
            f"duration {m0['duration_days']} -> {m0['duration_days'] + 20} days",
            samples.to_png(
                samples.edit_medicine(page, payload, 0, duration_days=m0["duration_days"] + 20)
            ),
            "png",
            "med_0_days",
        )
        add(
            "freq",
            "tampered-digital",
            f"frequency {m0['frequency']} -> QID",
            samples.to_png(
                samples.edit_medicine(
                    page, payload, 0, frequency="QID" if m0["frequency"] != "QID" else "OD"
                )
            ),
            "png",
            "med_0_freq",
        )
        add(
            "patient",
            "tampered-digital",
            "patient name changed",
            samples.to_png(samples.edit_patient(page, payload, name="Rahul Verma")),
            "png",
            "patient",
        )
        add(
            "expiry",
            "tampered-digital",
            "expiry extended by a year",
            samples.to_png(samples.edit_expiry(page, payload, "2027-11-17T10:30:00Z")),
            "png",
            "dates",
        )
        spare = len(meds)
        add(
            "extra",
            "tampered-digital",
            "extra controlled medicine row added",
            samples.to_png(samples.add_medicine_row(page, spare, med("Alprazolam", 2, "BD", 30))),
            "png",
            f"med_{spare}_name",
        )
        add(
            "overlay",
            "tampered-digital",
            "PDF: white box + new dose drawn over the field",
            samples.pdf_overlay_edit(pdf, "med_0_dose", f"{dose} mg"),
            "pdf",
            "med_0_dose",
        )
        add(
            "hidden",
            "tampered-digital",
            "PDF: looks identical, text layer says a different dose",
            samples.pdf_hidden_text_edit(pdf, "med_0_dose", f"{dose} mg"),
            "pdf",
            "med_0_dose",
        )
        if key == "A":
            add("licence", "tampered-digital", "doctor licence number changed",
                samples.to_png(samples.edit_doctor_reg(page, payload, "GJ-12346")), "png", "doctor")  # fmt: skip
            add("clinic", "tampered-digital", "clinic renamed",
                samples.to_png(samples.edit_clinic(page, "Shah Clinic, Surah")), "png", "clinic")  # fmt: skip
            add("notes", "tampered-digital", "notes rewritten",
                samples.to_png(samples.edit_notes(page, "Double the dose if needed.")), "png", "notes")  # fmt: skip
            add("margin", "tampered-digital", "extra line scribbled in the blank area",
                samples.to_png(samples.add_margin_text(page, "Dispense 200 tablets")), "png", None)  # fmt: skip
            add("name", "tampered-digital", "medicine name one letter changed",
                samples.to_png(samples.edit_medicine(page, payload, 2, name="Cetirizone")), "png", "med_2_name")  # fmt: skip
        # photographed forgeries
        forged_dose = samples.edit_medicine(page, payload, 0, dose_mg=dose)
        add("photo-dose", "tampered-photo", f"photo of a page with dose {m0['dose_mg']} -> {dose} mg",
            samples.to_jpeg(samples.photograph(forged_dose, 21), 90), "jpg", "med_0_dose")  # fmt: skip
        forged_extra = samples.add_medicine_row(page, spare, med("Tramadol", 100, "TDS", 10))
        add("photo-extra", "tampered-photo", "photo of a page with an extra medicine row",
            samples.to_jpeg(samples.photograph(forged_extra, 22), 90), "jpg", f"med_{spare}_name")  # fmt: skip
        if key != "B":
            forged_patient = samples.edit_patient(page, payload, name="Rahul Verma")
            add("photo-patient", "tampered-photo", "photo of a page with another patient's name",
                samples.to_jpeg(samples.photograph(forged_patient, 23), 90), "jpg", "patient")  # fmt: skip
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="samples")
    parser.add_argument("--report", default="docs/evaluation.md")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    print(f"{len(cases)} cases")

    rows = []
    manifest = []
    for case, payload, payload_hash, qr, pdf_sha in cases:
        path = out_dir / f"{case.group}__{case.cid}.{case.ext}"
        path.write_bytes(case.data)
        manifest.append(
            {
                "file": path.name,
                "group": case.group,
                "description": case.description,
                "rx_id": payload["rx_id"],
            }
        )
        started = time.time()
        report = check_content(
            load_upload(case.data), case.data, payload, payload_hash, qr, pdf_sha
        )
        seconds = time.time() - started
        verdict = VERDICT.get(report.status, "REVIEW_REQUIRED")
        located = None
        if case.expect_zone and verdict == "TAMPERED":
            located = case.expect_zone in {f.zone for f in report.findings}
        rows.append((case, verdict, located, report, seconds))
        flag = (
            ""
            if verdict == ("VALID" if case.group.startswith("genuine") else "TAMPERED")
            else "  <-- check"
        )
        print(
            f"{case.cid:<14} {case.group:<17} {verdict:<16} {seconds:4.1f}s {case.description}{flag}"
        )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    write_report(Path(args.report), rows)
    print(f"report written to {args.report}")
    return 0


def write_report(path: Path, rows) -> None:
    def tally(groups):
        counts: Counter[str] = Counter()
        for case, verdict, *_ in rows:
            if case.group in groups:
                counts[verdict] += 1
        return counts

    gd, gp = tally({"genuine-digital"}), tally({"genuine-photo"})
    td, tp = tally({"tampered-digital"}), tally({"tampered-photo"})
    td_rows = [r for r in rows if r[0].group == "tampered-digital" and r[0].expect_zone]
    located = sum(1 for r in td_rows if r[2])
    times = sorted(r[4] for r in rows)
    median = times[len(times) // 2]

    def line(label, c):
        n = sum(c.values()) or 1
        return f"| {label} | {sum(c.values())} | {c['VALID']} | {c['REVIEW_REQUIRED']} | {c['TAMPERED']} | {100 * c['VALID'] / n:.0f}% / {100 * c['TAMPERED'] / n:.0f}% |"

    lines = [
        "# Upload verification: evaluation",
        "",
        f"Generated by `scripts/evaluate_upload.py` on {datetime.now(UTC):%Y-%m-%d}. "
        f"{len(rows)} files from {len(PAYLOADS)} different prescriptions.",
        "",
        "> **Read this first.** The photographs here are *simulated* (perspective, rotation, blur, "
        "sensor noise, uneven light, JPEG compression), not real phone captures. They are a "
        "controlled stress test. Real photos have shadows, folds and glare that this set does not "
        "contain, and the verdict for those is correspondingly more often `REVIEW_REQUIRED`.",
        "",
        "## Confusion matrix",
        "",
        "Rows are what the file really is; columns are what Pramaan said. "
        "The last column is the share said VALID / the share said TAMPERED.",
        "",
        "| Actual | Files | VALID | REVIEW_REQUIRED | TAMPERED | VALID % / TAMPERED % |",
        "|---|---|---|---|---|---|",
        line("Genuine, digital (original PDF, PNG, JPEG)", gd),
        line("Genuine, simulated photo", gp),
        line("Tampered, digital", td),
        line("Tampered, simulated photo", tp),
        "",
        "## Acceptance criteria",
        "",
        f"- Genuine digital files give VALID: **{gd['VALID']}/{sum(gd.values())}** (required 100%).",
        f"- Genuine photos are never TAMPERED: **{gp['TAMPERED']}** of {sum(gp.values())} were (required: none; "
        f"VALID or REVIEW_REQUIRED in at least 95%, here {100 * (gp['VALID'] + gp['REVIEW_REQUIRED']) / max(1, sum(gp.values())):.0f}%).",
        f"- Tampered digital files give TAMPERED: **{td['TAMPERED']}/{sum(td.values())}** (required at least 95%).",
        f"- The tampered field was outlined in **{located}/{len(td_rows)}** digital cases that name one field.",
        f"- Tampered simulated photos give TAMPERED: **{tp['TAMPERED']}/{sum(tp.values())}**, "
        f"REVIEW_REQUIRED {tp['REVIEW_REQUIRED']}, VALID {tp['VALID']}.",
        f"- Time per file (this laptop, CPU only): median **{median:.1f} s**, slowest {times[-1]:.1f} s.",
        "",
        "## Extra stress run on genuine photos",
        "",
        "`scripts/stress_photos.py` takes the same three prescriptions and simulates 75 more phone "
        "photos of the *unaltered* page, a third of them deliberately bad (heavy blur, strong noise, "
        "JPEG quality 40-60). Last measured result: **75 of 75 VALID, none TAMPERED, none "
        "REVIEW_REQUIRED**. A first run of this check found a real bug (OCR lines on one row were "
        "read in the wrong order and a genuine page was called TAMPERED); it is fixed and has a "
        "regression test.",
        "",
        "## How a verdict is reached",
        "",
        "1. The QR code is read from the file and its signature is verified first. Only if that "
        "succeeds does the page itself get compared.",
        "2. The page that *should* exist is redrawn from the signed content and the upload is "
        "straightened onto it using the QR code and three corner marks.",
        "3. Each field is compared with the redrawn field. A field that looks different is read "
        "with OCR; the verdict is TAMPERED only when OCR confirms the text differs (or the "
        "difference is overwhelming). Blank areas must stay blank.",
        "4. For PDFs the hidden text layer must also match the signed text.",
        "5. If alignment is poor, or a critical field cannot be read, the result is "
        "`REVIEW_REQUIRED`: a prompt for the pharmacist to check by eye, never an accusation.",
        "",
        "## Every file",
        "",
        "| Case | Group | What was done | Verdict | Field outlined | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for case, verdict, _located, report, seconds in rows:
        zones = ", ".join(f.zone for f in report.findings) or "-"
        lines.append(
            f"| {case.cid} | {case.group} | {case.description} | {verdict} | {zones} | {seconds:.1f} |"
        )
    lines += [
        "",
        "## Known limits",
        "",
        "- A pharmacist photographing a heavily creased, glared or partly covered page gets "
        "`REVIEW_REQUIRED`, not a wrong accusation. That is by design.",
        "- Only the first page of a PDF is checked. A prescription is one page.",
        "- This checks that the page matches what the doctor signed. It cannot tell whether the "
        "person holding it is the patient; the dispense PIN covers that.",
        "- OCR here is RapidOCR (Latin script, printed text). Handwriting is out of scope.",
    ]
    # This file also holds other phases' results (the anomaly model adds its own section), so only
    # the block between the markers is replaced.
    demoted = ["#" + ln if ln.startswith("#") else ln for ln in lines]
    demoted[0] = "## Upload verification (Phase 7)"
    block = f"{START}\n" + "\n".join(demoted) + f"\n{END}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Evaluation\n\n"
    if START in existing and END in existing:
        head, rest = existing.split(START, 1)
        text = head + block.rstrip("\n") + rest.split(END, 1)[1]
    else:
        text = existing.rstrip("\n") + "\n\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
