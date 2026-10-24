"""Synthetic prescribing data for training and evaluating the anomaly model (Spec Section 11.5).

Purpose: there is no real prescribing data to learn from, so this simulates doctors with habits
         (a specialty's usual medicines, working hours, patients) and injects unusual events.
Honesty: everything here is made up. The numbers it produces show that the METHOD works on data
         with these properties; they say nothing about accuracy on real prescriptions.
Data   : 130 simulated days for 24 doctors (6 specialties x 4).
           days 0-59    only history (so every doctor has a baseline)
           days 60-104  TRAIN: normal prescriptions (about 5,000 rows); the model sees only these
           days 105-129 TEST-NORMAL: held-out normal prescriptions
         Anomaly "families" are scenarios injected in the test window, each scored against the
         doctor's real history plus the events the scenario itself creates (a burst, a flood):
           TUNING (used to choose settings): huge_dose, many_medicines, night_controlled_burst
           UNSEEN (never tuned on):          specialty_switch, patient_flood, slow_controlled_drip
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.ai import drug_match
from app.ai.features import (
    BASELINE_DAYS,
    RECENT_DAYS,
    DoctorHistory,
    build_features,
    generic_of,
    is_controlled,
)

SPECIALTIES: dict[str, list[str]] = {
    "general": [
        "Paracetamol", "Ibuprofen", "Amoxicillin", "Azithromycin", "Cetirizine", "Omeprazole",
        "Pantoprazole", "Metronidazole", "Domperidone", "Ondansetron", "Loperamide", "Folic Acid",
        "Diclofenac", "Doxycycline", "Cefixime",
    ],
    "cardiology": [
        "Atorvastatin", "Rosuvastatin", "Amlodipine", "Telmisartan", "Losartan", "Metoprolol",
        "Atenolol", "Clopidogrel", "Aspirin", "Furosemide", "Enalapril", "Hydrochlorothiazide",
        "Warfarin",
    ],
    "diabetology": [
        "Metformin", "Glimepiride", "Gliclazide", "Atorvastatin", "Telmisartan", "Amlodipine",
        "Folic Acid", "Pantoprazole",
    ],
    "psychiatry": [
        "Sertraline", "Escitalopram", "Amitriptyline", "Alprazolam", "Clonazepam", "Zolpidem",
        "Pregabalin", "Diazepam",
    ],
    "pediatrics": [
        "Paracetamol", "Amoxicillin", "Cetirizine", "Salbutamol", "Montelukast", "Azithromycin",
        "Albendazole", "Ondansetron",
    ],
    "orthopedics": [
        "Diclofenac", "Naproxen", "Ibuprofen", "Pregabalin", "Gabapentin", "Tramadol",
        "Prednisolone", "Famotidine",
    ],
}  # fmt: skip
CHRONIC = {"cardiology", "diabetology", "psychiatry"}
CONTROLLED_POOL = ["Alprazolam", "Diazepam", "Clonazepam", "Zolpidem", "Tramadol", "Codeine"]

OFF_LIST_RATE = 0.03  # share of medicine lines outside the doctor's usual list
DAYS, WARMUP_DAYS, TRAIN_END_DAY = 130, 60, 105
FAMILIES_TUNING = ("huge_dose", "many_medicines", "night_controlled_burst")
FAMILIES_UNSEEN = ("specialty_switch", "patient_flood", "slow_controlled_drip")


@dataclass
class Doctor:
    index: int
    specialty: str
    start_hour: int
    end_hour: int
    rate: float  # prescriptions per working day
    drugs: list[str] = field(default_factory=list)
    weights: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class Event:
    ts: float  # hours since day 0
    doctor: int
    patient: int
    medicines: list[dict[str, Any]]
    generics: frozenset[str]
    n_controlled: int


@dataclass
class Row:
    features: dict[str, float]
    medicines: list[dict[str, Any]]
    hour: int
    doctor_rx_last_24h: int
    family: str  # "normal" or an anomaly family
    doctor: int


def _drug_reference() -> drug_match.Catalog:
    return drug_match.load_catalog()


def _make_medicine(
    rng: np.random.Generator,
    name: str,
    specialty: str,
    catalog: drug_match.Catalog,
    scale: float | None = None,
) -> dict[str, Any]:
    ref = catalog.reference[drug_match.normalise_name(name)]
    fraction = scale if scale is not None else float(rng.choice([0.25, 0.5, 0.5, 1.0]))
    frequencies = ["OD"] if ref.max_daily_dose_mg <= ref.max_single_dose_mg else ["OD", "BD", "TDS"]
    frequency = str(rng.choice(frequencies))
    multiplier = drug_match.FREQUENCY_MULTIPLIER[frequency]
    dose = max(1, round(ref.max_single_dose_mg * fraction))
    while dose * multiplier > ref.max_daily_dose_mg and dose > 1:
        dose = max(1, dose // 2)
    if specialty in CHRONIC:
        days = int(rng.choice([30, 30, 30, 60, 90]))
    else:
        days = int(rng.choice([3, 5, 5, 7, 7, 10, 14]))
    return {"name": name, "dose_mg": int(dose), "frequency": frequency, "duration_days": days}


def _event(
    rng: np.random.Generator,
    ts: float,
    doctor: int,
    patient: int,
    medicines: list[dict[str, Any]],
    catalog: drug_match.Catalog,
) -> Event:
    generics = set()
    controlled = 0
    for med in medicines:
        key = generic_of(med["name"], catalog)
        if key:
            generics.add(key)
            controlled += int(is_controlled(key, catalog))
    return Event(ts, doctor, patient, medicines, frozenset(generics), controlled)


def _doctors(rng: np.random.Generator) -> list[Doctor]:
    doctors = []
    for i in range(24):
        specialty = list(SPECIALTIES)[i % 6]
        start = int(rng.integers(8, 11))
        drugs = list(SPECIALTIES[specialty])
        rng.shuffle(drugs)  # each doctor has their own favourites
        weights = 1.0 / (np.arange(len(drugs)) + 1.5)
        doctors.append(
            Doctor(
                i,
                specialty,
                start,
                start + int(rng.integers(7, 10)),
                float(rng.uniform(3, 8)),
                drugs,
                weights / weights.sum(),
            )
        )
    return doctors


def _normal_medicines(
    rng: np.random.Generator, doctor: Doctor, catalog: drug_match.Catalog, count: int | None = None
) -> list[dict[str, Any]]:
    if count is None:
        count = int(rng.choice([1, 2, 3, 4, 5], p=[0.28, 0.38, 0.22, 0.09, 0.03]))
    count = min(count, len(doctor.drugs))
    picked = rng.choice(len(doctor.drugs), size=count, replace=False, p=doctor.weights)
    names = [doctor.drugs[i] for i in picked]
    # Real doctors now and then prescribe outside their usual list (a referral, an unusual case).
    # Without this, "new drug for this doctor" would be constant in the training data and the
    # forest could not learn from it at all.
    for slot in range(len(names)):
        if count and rng.random() < OFF_LIST_RATE:
            names[slot] = str(rng.choice(_everyday_drugs(catalog)))
    return [_make_medicine(rng, name, doctor.specialty, catalog) for name in names]


def _everyday_drugs(catalog: drug_match.Catalog) -> list[str]:
    return sorted(ref.name for ref in catalog.reference.values() if not ref.is_controlled)


def _working_time(rng: np.random.Generator, doctor: Doctor, day: int) -> float:
    hour = float(rng.uniform(doctor.start_hour, doctor.end_hour))
    if rng.random() < 0.03:  # a little evening work
        hour = float(rng.uniform(19, 22))
    return day * 24 + hour


def _normal_stream(
    rng: np.random.Generator, doctors: list[Doctor], catalog: drug_match.Catalog, patients: int
) -> list[Event]:
    events: list[Event] = []
    for doctor in doctors:
        own_patients = rng.integers(0, patients, size=300)
        for day in range(DAYS):
            weekday_factor = 0.3 if day % 7 == 6 else 1.0
            for _ in range(int(rng.poisson(doctor.rate * weekday_factor))):
                patient = (
                    int(rng.choice(own_patients))
                    if rng.random() < 0.85
                    else int(rng.integers(0, patients))
                )
                events.append(
                    _event(
                        rng,
                        _working_time(rng, doctor, day),
                        doctor.index,
                        patient,
                        _normal_medicines(rng, doctor, catalog),
                        catalog,
                    )
                )
    events.sort(key=lambda e: e.ts)
    return events


class _Index:
    """Lookups over the normal stream: per-doctor events and per-patient visit times."""

    def __init__(self, events: list[Event]) -> None:
        self.by_doctor: dict[int, list[Event]] = defaultdict(list)
        self.patient_times: dict[int, list[float]] = defaultdict(list)
        for e in events:
            self.by_doctor[e.doctor].append(e)
            self.patient_times[e.patient].append(e.ts)

    def history(
        self, doctor: int, ts: float, patient: int, extra: list[Event] | None = None
    ) -> DoctorHistory:
        prior = self.by_doctor[doctor]
        times = [e.ts for e in prior]
        cut = bisect.bisect_left(times, ts)
        window = prior[max(0, bisect.bisect_left(times, ts - BASELINE_DAYS * 24)) : cut]
        events = [*window, *(e for e in (extra or []) if e.ts < ts)]
        last24 = [e for e in events if ts - 24 <= e.ts < ts]
        recent = [e for e in events if e.ts >= ts - RECENT_DAYS * 24]
        visits = self.patient_times.get(patient, [])
        patient_7d = bisect.bisect_left(visits, ts) - bisect.bisect_left(visits, ts - 7 * 24)
        known = frozenset().union(*(e.generics for e in events)) if events else frozenset()
        return DoctorHistory(
            rx_last_24h=len(last24),
            distinct_patients_last_24h=len({e.patient for e in last24}),
            patient_rx_last_7d=int(patient_7d),
            known_generics=known,
            baseline_rx=len(events),
            meds_30d=sum(len(e.medicines) for e in recent),
            controlled_meds_30d=sum(e.n_controlled for e in recent),
        )


def _row(
    index: _Index,
    catalog: drug_match.Catalog,
    ev: Event,
    family: str,
    extra: list[Event] | None = None,
) -> Row:
    history = index.history(ev.doctor, ev.ts, ev.patient, extra)
    hour = int(ev.ts % 24)
    return Row(
        build_features(ev.medicines, hour, history, catalog),
        ev.medicines,
        hour,
        history.rx_last_24h,
        family,
        ev.doctor,
    )


# --- anomaly scenarios ----------------------------------------------------------------------------


def _scenario(
    rng: np.random.Generator,
    family: str,
    doctor: Doctor,
    doctors: list[Doctor],
    catalog: drug_match.Catalog,
    patients: int,
) -> tuple[Event, list[Event]]:
    day = int(rng.integers(TRAIN_END_DAY, DAYS))
    ts = _working_time(rng, doctor, day)
    patient = int(rng.integers(0, patients))
    extra: list[Event] = []

    def burst(count: int, hours: float, meds_for) -> None:
        for _ in range(count):
            extra.append(
                _event(
                    rng,
                    ts - float(rng.uniform(0.05, hours)),
                    doctor.index,
                    int(rng.integers(0, patients)),
                    meds_for(),
                    catalog,
                )
            )

    if family == "huge_dose":
        meds = _normal_medicines(rng, doctor, catalog)
        for med in meds[: int(rng.integers(1, 3))]:
            med["dose_mg"] = int(med["dose_mg"] * float(rng.uniform(4, 15)))
    elif family == "many_medicines":
        meds = _normal_medicines(rng, doctor, catalog, count=int(rng.integers(7, 9)))
    elif family == "night_controlled_burst":
        ts = day * 24 + float(rng.uniform(1, 4.5))
        pool = [d for d in CONTROLLED_POOL]
        pick = lambda: [  # noqa: E731
            _make_medicine(
                rng,
                str(rng.choice(pool)),
                doctor.specialty,
                catalog,
                scale=float(rng.uniform(0.5, 1.0)),
            )
            for _ in range(int(rng.integers(1, 4)))
        ]
        burst(int(rng.integers(10, 26)), 5.0, pick)
        meds = pick()
    elif family == "specialty_switch":
        others = [d for d in doctors if d.specialty != doctor.specialty]
        foreign = rng.choice(others).drugs
        pool = [d for d in foreign if d not in doctor.drugs] or foreign
        count = int(rng.choice([1, 2, 3]))
        meds = [
            _make_medicine(rng, str(n), doctor.specialty, catalog)
            for n in rng.choice(pool, size=min(count, len(pool)), replace=False)
        ]
    elif family == "patient_flood":
        burst(int(rng.integers(12, 31)), 6.0, lambda: _normal_medicines(rng, doctor, catalog))
        meds = _normal_medicines(rng, doctor, catalog)
    elif family == "slow_controlled_drip":
        drug = str(rng.choice(["Tramadol", "Alprazolam", "Zolpidem", "Diazepam"]))
        for _ in range(int(rng.integers(15, 26))):
            extra.append(
                _event(
                    rng,
                    ts - float(rng.uniform(1, RECENT_DAYS - 1)) * 24,
                    doctor.index,
                    int(rng.integers(0, patients)),
                    [_make_medicine(rng, drug, doctor.specialty, catalog, scale=0.25)],
                    catalog,
                )
            )
        meds = [_make_medicine(rng, drug, doctor.specialty, catalog, scale=0.25)]
    else:
        raise ValueError(family)
    return _event(rng, ts, doctor.index, patient, meds, catalog), extra


def generate(
    seed: int = 42, per_family_tuning: int = 100, per_family_unseen: int = 150, patients: int = 4000
) -> dict[str, list[Row]]:
    """Build the whole dataset. Deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    catalog = _drug_reference()
    doctors = _doctors(rng)
    stream = _normal_stream(rng, doctors, catalog, patients)
    index = _Index(stream)

    train, test_normal = [], []
    for ev in stream:
        day = ev.ts / 24
        if day < WARMUP_DAYS:
            continue
        (train if day < TRAIN_END_DAY else test_normal).append(_row(index, catalog, ev, "normal"))

    def families(names: tuple[str, ...], count: int) -> list[Row]:
        rows = []
        for family in names:
            eligible = [
                d
                for d in doctors
                if not (family == "slow_controlled_drip" and d.specialty == "psychiatry")
            ]
            for _ in range(count):
                doctor = eligible[int(rng.integers(0, len(eligible)))]
                ev, extra = _scenario(rng, family, doctor, doctors, catalog, patients)
                rows.append(_row(index, catalog, ev, family, extra))
        return rows

    return {
        "train": train,
        "test_normal": test_normal,
        "tuning": families(FAMILIES_TUNING, per_family_tuning),
        "unseen": families(FAMILIES_UNSEEN, per_family_unseen),
    }


def to_matrix(rows: list[Row], names: tuple[str, ...]) -> np.ndarray:
    return np.array([[r.features[n] for n in names] for r in rows], dtype=float)
