"""The ten numbers the anomaly model looks at (Spec Section 11.5).

Purpose: turn a prescription plus the doctor's recent history into a fixed set of features. The
         SAME function builds the features for training data and for live prescriptions, so the
         model never sees a different definition at run time than it learned.
Notes  : counts of "recent" activity exclude the prescription being scored. A doctor with fewer
         than MIN_BASELINE_RX earlier prescriptions has no baseline yet, so the per-doctor
         "new drug" feature is 0 for them instead of calling every drug new (a limitation, listed
         in the docs: a brand-new stolen account is not caught by this one feature).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai import drug_match

FEATURE_NAMES = (
    "num_medicines",
    "max_daily_dose_ratio",
    "max_duration_days",
    "controlled_count",
    "doctor_rx_last_24h",
    "issue_hour",
    "patient_rx_last_7d",
    "new_drug_ratio_for_doctor",
    "controlled_ratio_doctor_30d",
    "distinct_patients_last_24h",
)
# The features that need no knowledge of the doctor's own habits (used for the ablation).
GENERIC_FEATURES = FEATURE_NAMES[:6] + ("patient_rx_last_7d",)

MIN_BASELINE_RX = 5
BASELINE_DAYS = 90
RECENT_DAYS = 30


@dataclass(frozen=True)
class DoctorHistory:
    """What the doctor (and the patient) did before this prescription."""

    rx_last_24h: int = 0
    distinct_patients_last_24h: int = 0
    patient_rx_last_7d: int = 0
    known_generics: frozenset[str] = frozenset()  # medicines prescribed in the last 90 days
    baseline_rx: int = 0  # prescriptions in that 90-day window
    meds_30d: int = 0  # medicine lines in the last 30 days
    controlled_meds_30d: int = 0


def generic_of(name: str, catalog: drug_match.Catalog) -> str | None:
    """Normalised generic name for a medicine as written, or None if it is not in the catalogue."""
    match = drug_match.match_drug(name, catalog)
    if match.kind == "KNOWN" and match.generic:
        return drug_match.normalise_name(match.generic)
    return None


def is_controlled(generic_key: str | None, catalog: drug_match.Catalog) -> bool:
    ref = catalog.reference.get(generic_key) if generic_key else None
    return bool(ref and ref.is_controlled)


def build_features(
    medicines: list[dict[str, Any]],
    issue_hour: int,
    history: DoctorHistory,
    catalog: drug_match.Catalog | None = None,
) -> dict[str, float]:
    catalog = catalog or drug_match.load_catalog()
    max_ratio = 0.0
    controlled = 0
    new_drugs = 0
    for med in medicines:
        match = drug_match.match_drug(str(med.get("name", "")), catalog)
        generic = match.generic if match.kind == "KNOWN" else None
        key = drug_match.normalise_name(generic) if generic else None
        if match.generic:
            max_ratio = max(
                max_ratio,
                drug_match.daily_dose_ratio(
                    match.generic,
                    float(med.get("dose_mg", 0)),
                    str(med.get("frequency", "OD")),
                    catalog,
                ),
            )
        if is_controlled(
            drug_match.normalise_name(match.generic) if match.generic else None, catalog
        ):
            controlled += 1
        if key is None or key not in history.known_generics:
            new_drugs += 1

    count = len(medicines)
    has_baseline = history.baseline_rx >= MIN_BASELINE_RX
    return {
        "num_medicines": float(count),
        "max_daily_dose_ratio": round(max_ratio, 4),
        "max_duration_days": float(
            max((int(m.get("duration_days", 0)) for m in medicines), default=0)
        ),
        "controlled_count": float(controlled),
        "doctor_rx_last_24h": float(history.rx_last_24h),
        "issue_hour": float(issue_hour),
        "patient_rx_last_7d": float(history.patient_rx_last_7d),
        "new_drug_ratio_for_doctor": (
            round(new_drugs / count, 4) if (count and has_baseline) else 0.0
        ),
        "controlled_ratio_doctor_30d": round(
            (history.controlled_meds_30d + controlled) / max(1, history.meds_30d + count), 4
        ),
        "distinct_patients_last_24h": float(history.distinct_patients_last_24h),
    }


def as_row(features: dict[str, float], names: tuple[str, ...] = FEATURE_NAMES) -> list[float]:
    return [float(features[name]) for name in names]
