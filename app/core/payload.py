"""Prescription payload v2 and the exact text printed from it (Spec Sections 7.1, 13.4).

Purpose: build the one dictionary that gets signed, and define precisely which text is printed
         for each part of it. The PDF generator and (later) the content verifier both use the
         text functions here, so "what you see is what you sign" holds by construction.
Rules  : every printed field comes from the payload; anything that cannot be printed faithfully
         (unsupported characters, text too wide for its box, too many lines) is rejected BEFORE
         signing, never truncated silently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core import pdf_layout as layout

PAYLOAD_VERSION = 2
FREQUENCIES = ("OD", "BD", "TDS", "QID", "HS", "SOS")
# Doses per day used for daily-dose arithmetic (Spec 7.1).
FREQUENCY_MULTIPLIER = {"OD": 1, "BD": 2, "TDS": 3, "QID": 4, "HS": 1, "SOS": 3}
FREQUENCY_LABEL = {
    "OD": "Once daily",
    "BD": "Twice daily",
    "TDS": "Three times daily",
    "QID": "Four times daily",
    "HS": "At bedtime",
    "SOS": "If needed",
}

MAX_NOTES_CHARS = 500
CELL_PADDING = 4.0


class PayloadError(ValueError):
    """The prescription cannot be signed as given. The message is safe to show to the doctor."""


def iso_z(moment: datetime) -> str:
    """UTC, seconds precision, `Z` suffix (Spec 7.1)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(
    *,
    rx_id: str,
    key_id: str,
    issued_at: datetime,
    expires_at: datetime,
    max_fills: int,
    doctor: dict[str, str],
    patient: dict[str, Any],
    medicines: list[dict[str, Any]],
    notes: str,
) -> dict[str, Any]:
    """Assemble and validate the payload. `doctor` has id/name/license_no/clinic; `patient` has
    id/name and optionally age_years. Raises PayloadError if it cannot be printed faithfully."""
    patient_block: dict[str, Any] = {"id": patient["id"], "name": patient["name"]}
    if patient.get("age_years") is not None:
        patient_block["age_years"] = int(patient["age_years"])
    payload = {
        "version": PAYLOAD_VERSION,
        "rx_id": rx_id,
        "key_id": key_id,
        "issued_at": iso_z(issued_at),
        "expires_at": iso_z(expires_at),
        "max_fills": max_fills,
        "doctor": {
            "id": doctor["id"],
            "name": doctor["name"],
            "license_no": doctor["license_no"],
            "clinic": doctor["clinic"],
        },
        "patient": patient_block,
        "medicines": [
            {
                "name": m["name"],
                "dose_mg": int(m["dose_mg"]),
                "frequency": m["frequency"],
                "duration_days": int(m["duration_days"]),
            }
            for m in medicines
        ],
        "notes": notes,
    }
    validate_printable(payload)
    return payload


# --- what gets printed ---------------------------------------------------------------------------


def _date_time(iso: str) -> str:
    """'2026-10-18T10:30:17Z' -> '2026-10-18 10:30 UTC' (printed to the minute)."""
    return iso[:16].replace("T", " ") + " UTC"


def clinic_text(p: dict[str, Any]) -> str:
    return p["doctor"]["clinic"]


def doctor_lines(p: dict[str, Any]) -> tuple[str, str]:
    return p["doctor"]["name"], f"Reg. No. {p['doctor']['license_no']}"


def patient_text(p: dict[str, Any]) -> str:
    age = p["patient"].get("age_years")
    return f"Patient: {p['patient']['name']}" + (f", {age} yrs" if age is not None else "")


def dates_lines(p: dict[str, Any]) -> tuple[str, str, str]:
    return (
        f"Issued: {_date_time(p['issued_at'])}",
        f"Valid until: {_date_time(p['expires_at'])}",
        f"Fills allowed: {p['max_fills']}",
    )


def medicine_cells(m: dict[str, Any]) -> tuple[str, str, str, str]:
    return m["name"], f"{m['dose_mg']} mg", m["frequency"], f"{m['duration_days']} days"


def notes_lines(p: dict[str, Any]) -> list[str]:
    notes = p.get("notes") or ""
    if not notes:
        return []
    zone = layout.ZONES["notes"]
    return layout.wrap_lines(notes, zone.w - 2 * CELL_PADDING)


def fingerprint(payload_hash: str) -> str:
    """First 12 hex characters grouped 4-4-4: a short, human-comparable fingerprint."""
    head = payload_hash[:12]
    return " ".join(head[i : i + 4] for i in range(0, 12, 4))


def footer_lines(rx_id: str, payload_hash: str) -> tuple[str, str]:
    return f"Rx ID: {rx_id}", f"Fingerprint: {fingerprint(payload_hash)}"


# --- validation ----------------------------------------------------------------------------------


def _check_fits(label: str, text: str, width: float, font: str, size: float) -> None:
    if layout.text_width(text, font, size) > width:
        raise PayloadError(f"{label} is too long to print on the prescription.")


def validate_printable(p: dict[str, Any]) -> None:
    meds = p["medicines"]
    if not 1 <= len(meds) <= layout.MAX_MEDICINES:
        raise PayloadError(f"A prescription needs 1 to {layout.MAX_MEDICINES} medicines.")
    if not 1 <= p["max_fills"] <= 5:
        raise PayloadError("Fills must be between 1 and 5.")
    notes = p.get("notes") or ""
    if len(notes) > MAX_NOTES_CHARS:
        raise PayloadError(f"Notes can be at most {MAX_NOTES_CHARS} characters.")

    texts: list[str] = [clinic_text(p), *doctor_lines(p), patient_text(p), notes]
    for m in meds:
        texts.extend(medicine_cells(m))
    bad = layout.unprintable_characters("".join(texts))
    if bad:
        raise PayloadError(
            "These characters cannot be printed on the prescription: " + " ".join(bad[:8])
        )

    zones = layout.ZONES
    _check_fits(
        "The clinic name", clinic_text(p), zones["clinic"].w, layout.FONT_BOLD, layout.CLINIC_SIZE
    )
    name, reg = doctor_lines(p)
    _check_fits("The doctor's name", name, zones["doctor"].w, layout.FONT_BOLD, layout.NAME_SIZE)
    _check_fits("The registration number", reg, zones["doctor"].w, layout.FONT, layout.BODY_SIZE)
    _check_fits(
        "The patient's name",
        patient_text(p),
        zones["patient"].w,
        layout.FONT_BOLD,
        layout.NAME_SIZE,
    )
    for i, m in enumerate(meds):
        cells = medicine_cells(m)
        for zone_name, text, what in zip(
            layout.zone_names_for_medicine(i),
            cells,
            ("medicine name", "dose", "frequency", "duration"),
            strict=True,
        ):
            _check_fits(
                f"Medicine {i + 1} {what}", text, zones[zone_name].w - 2 * CELL_PADDING,
                layout.FONT, layout.BODY_SIZE,
            )  # fmt: skip
    if len(notes_lines(p)) > layout.MAX_NOTE_LINES:
        raise PayloadError(f"Notes are too long: at most {layout.MAX_NOTE_LINES} printed lines.")
