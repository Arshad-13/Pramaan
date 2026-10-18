"""Drug-name validation and dose limits (Spec Section 11.3).

Purpose: decide whether a prescribed medicine name is a real, known drug, spot probable typos, and
         compare the dose with an approximate adult reference range.
Data   : `data/drugs.csv` (name, generic, is_brand) and `data/drug_reference.csv` (dose limits and
         schedule). DEMO DATA ONLY: approximate and not for clinical use.

Matching rules (stricter than a plain fuzzy score, on purpose):
  - Names are normalised first: lower case, punctuation removed, dosage-form words (tab, syrup...)
    and strengths (500, mg) dropped, so "Tab Dolo 650" matches the brand "Dolo".
  - An exact match is KNOWN. Anything else is never silently accepted: a near match is a
    POSSIBLE_TYPO (with the suggested spelling) because one changed letter can be a different drug
    (look-alike names), and no close match at all is UNKNOWN.
  - Names shorter than 5 characters are only ever exact-matched: fuzzy scores on very short strings
    are meaningless ("Pan" would match almost anything).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MIN_FUZZY_LENGTH = 5
TYPO_CUTOFF = 75.0

FORM_WORDS = frozenset(
    {"tab", "tablet", "tablets", "cap", "caps", "capsule", "capsules", "syp", "syrup", "inj",
     "injection", "ip", "bp", "sr", "xr", "er", "mr", "forte", "dt"}  # fmt: skip
)
_STRENGTH_RE = re.compile(r"^\d+(\.\d+)?(mg|mcg|g|ml)?$")
_UNIT_WORDS = frozenset({"mg", "mcg", "g", "ml"})
CONTROLLED_SCHEDULES = frozenset({"H1", "X"})

# Doses per day for each frequency code (Spec Section 7.1).
FREQUENCY_MULTIPLIER = {"OD": 1, "BD": 2, "TDS": 3, "QID": 4, "HS": 1, "SOS": 3}


def normalise_name(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).casefold()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [
        t
        for t in text.split()
        if t not in FORM_WORDS and t not in _UNIT_WORDS and not _STRENGTH_RE.match(t)
    ]
    return " ".join(tokens)


@dataclass(frozen=True)
class Reference:
    name: str
    max_single_dose_mg: float
    max_daily_dose_mg: float
    schedule: str

    @property
    def is_controlled(self) -> bool:
        return self.schedule in CONTROLLED_SCHEDULES


@dataclass(frozen=True)
class Entry:
    name: str
    generic: str
    is_brand: bool


@dataclass(frozen=True)
class Catalog:
    by_norm: dict[str, Entry]
    reference: dict[str, Reference]  # key: generic name, normalised

    def names(self) -> list[Entry]:
        return sorted(self.by_norm.values(), key=lambda e: e.name.lower())


@lru_cache
def load_catalog(data_dir: Path = DATA_DIR) -> Catalog:
    reference: dict[str, Reference] = {}
    with open(data_dir / "drug_reference.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            reference[normalise_name(row["name"])] = Reference(
                name=row["name"],
                max_single_dose_mg=float(row["max_single_dose_mg"]),
                max_daily_dose_mg=float(row["max_daily_dose_mg"]),
                schedule=row["schedule"].strip().upper(),
            )
    by_norm: dict[str, Entry] = {}
    with open(data_dir / "drugs.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            by_norm[normalise_name(row["name"])] = Entry(
                row["name"], row["generic"], row["is_brand"] == "1"
            )
    return Catalog(by_norm=by_norm, reference=reference)


MatchKind = Literal["KNOWN", "POSSIBLE_TYPO", "UNKNOWN"]


@dataclass(frozen=True)
class DrugMatch:
    query: str
    kind: MatchKind
    name: str | None = None  # the catalogue spelling for KNOWN, the suggestion for POSSIBLE_TYPO
    generic: str | None = None
    is_brand: bool = False
    score: float = 0.0

    @property
    def reference_key(self) -> str | None:
        return normalise_name(self.generic) if self.generic else None


def match_drug(name: str, catalog: Catalog | None = None) -> DrugMatch:
    catalog = catalog or load_catalog()
    norm = normalise_name(name)
    if not norm:
        return DrugMatch(query=name, kind="UNKNOWN")
    entry = catalog.by_norm.get(norm)
    if entry:
        return DrugMatch(name, "KNOWN", entry.name, entry.generic, entry.is_brand, 100.0)
    if len(norm) < MIN_FUZZY_LENGTH:
        return DrugMatch(name, "UNKNOWN")
    best = process.extractOne(
        norm,
        [k for k in catalog.by_norm if len(k) >= MIN_FUZZY_LENGTH],
        scorer=fuzz.ratio,
        score_cutoff=TYPO_CUTOFF,
    )
    if best is None:
        return DrugMatch(name, "UNKNOWN")
    near = catalog.by_norm[best[0]]
    return DrugMatch(name, "POSSIBLE_TYPO", near.name, near.generic, near.is_brand, float(best[1]))


@dataclass(frozen=True)
class DoseFinding:
    flag: str
    detail: str


def dose_check(
    generic: str | None, dose_mg: float, frequency: str, catalog: Catalog | None = None
) -> list[DoseFinding]:
    """Compare one medicine's dose with the reference range for its generic name."""
    catalog = catalog or load_catalog()
    ref = catalog.reference.get(normalise_name(generic)) if generic else None
    if ref is None:
        return []
    findings: list[DoseFinding] = []
    daily = dose_mg * FREQUENCY_MULTIPLIER.get(frequency, 1)
    if dose_mg > ref.max_single_dose_mg:
        findings.append(
            DoseFinding(
                "DOSE_ABOVE_SINGLE_MAX",
                f"{ref.name} {dose_mg:g} mg is above the single-dose limit of {ref.max_single_dose_mg:g} mg.",
            )
        )
    if daily > ref.max_daily_dose_mg:
        findings.append(
            DoseFinding(
                "DOSE_ABOVE_DAILY_MAX",
                f"{ref.name} {dose_mg:g} mg {frequency} is {daily:g} mg a day, above the daily limit "
                f"of {ref.max_daily_dose_mg:g} mg.",
            )
        )
    if ref.is_controlled:
        findings.append(
            DoseFinding(
                "CONTROLLED_SUBSTANCE",
                f"{ref.name} is a controlled medicine (schedule {ref.schedule}).",
            )
        )
    return findings


def daily_dose_ratio(
    generic: str | None, dose_mg: float, frequency: str, catalog: Catalog | None = None
) -> float:
    """Daily dose divided by the daily maximum (0 when there is no reference)."""
    catalog = catalog or load_catalog()
    ref = catalog.reference.get(normalise_name(generic)) if generic else None
    if ref is None or ref.max_daily_dose_mg <= 0:
        return 0.0
    return dose_mg * FREQUENCY_MULTIPLIER.get(frequency, 1) / ref.max_daily_dose_mg
