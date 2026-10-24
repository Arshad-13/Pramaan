"""Combined risk score with human-readable explanations (Spec Section 11.6).

Purpose: score how unusual a prescription looks so a doctor can double-check before signing and a
         pharmacist can see why one was flagged. This is a *safety net*, not a diagnosis: it never
         blocks issuing by itself (the doctor can confirm with a reason).
Method : risk = min(100, rule_points + anomaly_points), where anomaly_points runs from 0 (a typical
         prescription, score 0.5 or below) up to 40 (the rarest, score 1.0).
         Each distinct rule counts once (controlled substances count per medicine, capped).
         The anomaly term is 0 until the trained model exists (Phase 8); a MODEL_UNAVAILABLE
         warning says so.
Weights: UNKNOWN_DRUG equals the default review threshold of 60 on purpose, so a name that is not
in the drug list always needs a second look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai import drug_match

POINTS = {
    "UNKNOWN_DRUG": 60,
    "POSSIBLE_TYPO": 15,
    "DOSE_ABOVE_SINGLE_MAX": 35,
    "DOSE_ABOVE_DAILY_MAX": 35,
    "DUPLICATE_THERAPY": 10,
    "DOCTOR_BURST": 20,
}
CONTROLLED_POINTS_EACH = 10
CONTROLLED_POINTS_CAP = 20
BURST_THRESHOLD = 15  # prescriptions by one doctor in 24 hours
ANOMALY_WEIGHT = 40
ANOMALY_FLOOR = 0.5  # a typical prescription (the median of normal data) adds nothing
ANOMALY_FLAG_THRESHOLD = 0.95  # percentile of normal data at which ANOMALOUS_PATTERN is flagged
FLAG_ORDER = (
    "UNKNOWN_DRUG", "POSSIBLE_TYPO", "DOSE_ABOVE_SINGLE_MAX", "DOSE_ABOVE_DAILY_MAX",
    "CONTROLLED_SUBSTANCE", "DUPLICATE_THERAPY", "DOCTOR_BURST", "ANOMALOUS_PATTERN",
)  # fmt: skip


@dataclass
class MedicineNote:
    """What we learned about one line of the prescription (drives inline hints in the form)."""

    index: int
    name: str
    status: str  # KNOWN, POSSIBLE_TYPO, UNKNOWN
    suggestion: str | None = None
    generic: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class RiskResult:
    score: int
    flags: list[str]
    explanations: list[str]
    features: dict[str, Any]
    warnings: list[str]
    notes: list[MedicineNote]
    controlled: bool = False
    by_flag: dict[str, list[str]] = field(default_factory=dict)


def assess(
    medicines: list[dict[str, Any]],
    *,
    doctor_rx_last_24h: int = 0,
    issue_hour: int = 12,
    anomaly_score: float | None = None,
    anomaly_explanations: list[str] | None = None,
    model_features: dict[str, Any] | None = None,
    catalog: drug_match.Catalog | None = None,
) -> RiskResult:
    catalog = catalog or drug_match.load_catalog()
    flag_messages: dict[str, list[str]] = {}
    notes: list[MedicineNote] = []
    controlled_count = 0
    max_ratio = 0.0
    generics_seen: dict[str, list[str]] = {}

    def add(flag: str, message: str, note: MedicineNote | None = None) -> None:
        flag_messages.setdefault(flag, []).append(message)
        if note is not None:
            note.flags.append(flag)

    for i, med in enumerate(medicines):
        name = str(med.get("name", ""))
        match = drug_match.match_drug(name, catalog)
        note = MedicineNote(index=i, name=name, status=match.kind, generic=match.generic)
        if match.kind == "UNKNOWN":
            add("UNKNOWN_DRUG", f'"{name}" is not in the drug list.', note)
        elif match.kind == "POSSIBLE_TYPO":
            note.suggestion = match.name
            add("POSSIBLE_TYPO", f'"{name}" looks like "{match.name}". Check the spelling.', note)
        if match.generic:
            generics_seen.setdefault(drug_match.normalise_name(match.generic), []).append(name)
            dose = float(med.get("dose_mg", 0))
            frequency = str(med.get("frequency", "OD"))
            for finding in drug_match.dose_check(match.generic, dose, frequency, catalog):
                if finding.flag == "CONTROLLED_SUBSTANCE":
                    controlled_count += 1
                add(finding.flag, finding.detail, note)
            max_ratio = max(
                max_ratio, drug_match.daily_dose_ratio(match.generic, dose, frequency, catalog)
            )
        notes.append(note)

    for names in generics_seen.values():
        if len(names) > 1:
            add(
                "DUPLICATE_THERAPY",
                "The same medicine appears more than once: "
                + ", ".join(f'"{n}"' for n in names)
                + ".",
            )

    if doctor_rx_last_24h >= BURST_THRESHOLD:
        add(
            "DOCTOR_BURST",
            f"{doctor_rx_last_24h} prescriptions were issued from this account in the last 24 hours.",
        )

    warnings: list[str] = []
    anomaly_points = 0
    if anomaly_score is None:
        warnings.append("MODEL_UNAVAILABLE")
    else:
        above = (min(1.0, anomaly_score) - ANOMALY_FLOOR) / (1.0 - ANOMALY_FLOOR)
        anomaly_points = round(max(0.0, above) * ANOMALY_WEIGHT)
        if anomaly_score >= ANOMALY_FLAG_THRESHOLD:
            add(
                "ANOMALOUS_PATTERN",
                "This prescription is unusual compared with normal prescribing."
                + "".join(f" {text}" for text in (anomaly_explanations or [])),
            )

    rule_points = sum(
        POINTS[f] for f in flag_messages if f in POINTS
    )  # the anomaly term is separate
    if controlled_count:
        rule_points += min(CONTROLLED_POINTS_CAP, CONTROLLED_POINTS_EACH * controlled_count)
    flags = [f for f in FLAG_ORDER if f in flag_messages]
    explanations = [m for f in FLAG_ORDER for m in flag_messages.get(f, [])]

    features = {
        "num_medicines": len(medicines),
        "max_daily_dose_ratio": round(max_ratio, 3),
        "max_duration_days": max((int(m.get("duration_days", 0)) for m in medicines), default=0),
        "controlled_count": controlled_count,
        "doctor_rx_last_24h": doctor_rx_last_24h,
        "issue_hour": issue_hour,
    }
    if model_features:
        features = {**features, **model_features}
        if anomaly_score is not None:
            features["anomaly_score"] = round(anomaly_score, 4)
    return RiskResult(
        score=min(100, rule_points + anomaly_points),
        flags=flags,
        explanations=explanations,
        features=features,
        warnings=warnings,
        notes=notes,
        controlled=controlled_count > 0,
        by_flag=flag_messages,
    )
