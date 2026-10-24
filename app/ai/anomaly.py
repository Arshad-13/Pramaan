"""Anomaly model: Isolation Forest scoring, explanations and safe loading (Spec Section 11.5).

Purpose: say how unusual a prescription is *for this kind of doctor and patient*, as a number in
         [0, 1] plus plain-language reasons. It adds to the rule-based risk score; it never blocks.
Score  : the percentile of the forest's anomaly score within the scores of the normal training
         data (0.5 = typical, 0.95 and above = rare), so the number means the same thing after
         retraining.
Reasons: for each feature, where the value falls among the normal training values. The two
         features furthest beyond the 99th percentile become sentences such as "12 controlled
         medicines in 24 hours (normal: up to 3)". No extra libraries, deterministic.
Safety : the model is a signed file (model_io). If it is missing or fails verification the system
         carries on with rules only and says so (`MODEL_UNAVAILABLE`); it never crashes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

from app.ai.features import FEATURE_NAMES, as_row
from app.ai.model_io import ModelError, load_model

N_ESTIMATORS = 200
RANDOM_STATE = 42
QUANTILE_POINTS = 1001
EXPLAIN_PERCENTILE = 99.0

# "{v}" is the observed value, "{n}" the largest normal value (99th percentile of normal data).
_TEMPLATES = {
    "num_medicines": "{v} medicines on one prescription (normal: up to {n}).",
    "max_daily_dose_ratio": "Daily dose is {v}x the usual maximum (normal: up to {n}x).",
    "max_duration_days": "Course of {v} days (normal: up to {n} days).",
    "controlled_count": "{v} controlled medicines on one prescription (normal: up to {n}).",
    "doctor_rx_last_24h": "{v} prescriptions from this doctor in 24 hours (normal: up to {n}).",
    "issue_hour": "Issued at {v}:00 UTC, an unusual hour (normal hours reach {n}:00).",
    "patient_rx_last_7d": "{v} prescriptions for this patient in 7 days (normal: up to {n}).",
    "new_drug_ratio_for_doctor": (
        "{p}% of these medicines are ones this doctor has not prescribed recently "
        "(normal: up to {q}%)."
    ),
    "controlled_ratio_doctor_30d": (
        "{p}% of this doctor's recent medicines are controlled (normal: up to {q}%)."
    ),
    "distinct_patients_last_24h": "{v} different patients in 24 hours (normal: up to {n}).",
}


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def train_bundle(
    rows: np.ndarray, feature_names: tuple[str, ...] = FEATURE_NAMES
) -> dict[str, Any]:
    """Fit on NORMAL rows only and keep everything needed to score and explain later."""
    forest = IsolationForest(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)
    forest.fit(rows)
    train_scores = np.sort(-forest.decision_function(rows))
    grid = np.linspace(0, 100, QUANTILE_POINTS)
    return {
        "version": 1,
        "feature_names": list(feature_names),
        "forest": forest,
        "score_quantiles": np.percentile(train_scores, grid),
        "feature_quantiles": {
            name: np.percentile(rows[:, i], grid) for i, name in enumerate(feature_names)
        },
        "n_training_rows": int(len(rows)),
    }


@dataclass(frozen=True)
class Scored:
    score: float  # percentile within normal data, 0..1
    explanations: list[str]


class AnomalyModel:
    def __init__(self, bundle: dict[str, Any]) -> None:
        self.forest: IsolationForest = bundle["forest"]
        self.feature_names: tuple[str, ...] = tuple(bundle["feature_names"])
        self.score_quantiles: np.ndarray = np.asarray(bundle["score_quantiles"])
        self.feature_quantiles: dict[str, np.ndarray] = {
            k: np.asarray(v) for k, v in bundle["feature_quantiles"].items()
        }
        self.n_training_rows: int = int(bundle["n_training_rows"])

    def score_many(self, rows: np.ndarray) -> np.ndarray:
        raw = -self.forest.decision_function(rows)
        ranks = np.searchsorted(self.score_quantiles, raw, side="right")
        return np.clip(ranks / len(self.score_quantiles), 0.0, 1.0)

    def score(self, features: dict[str, float]) -> float:
        return float(self.score_many(np.array([as_row(features, self.feature_names)]))[0])

    def explain(self, features: dict[str, float], limit: int = 2) -> list[str]:
        """The features furthest beyond the 99th percentile of normal values, as sentences."""
        findings: list[tuple[float, str]] = []
        for name in self.feature_names:
            quantiles = self.feature_quantiles[name]
            value = float(features[name])
            normal_max = float(np.percentile(quantiles, EXPLAIN_PERCENTILE))
            if value <= normal_max:
                continue
            spread = float(quantiles[-1] - quantiles[0]) or 1.0
            text = _TEMPLATES[name].format(
                v=_fmt(value),
                n=_fmt(normal_max),
                p=_fmt(round(value * 100)),
                q=_fmt(round(normal_max * 100)),
            )
            findings.append(((value - normal_max) / spread, text))
        findings.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in findings[:limit]]

    def assess(self, features: dict[str, float]) -> Scored:
        return Scored(self.score(features), self.explain(features))


# --- loading at run time -----------------------------------------------------------------------


@dataclass(frozen=True)
class ModelState:
    model: AnomalyModel | None
    status: str  # OK, MISSING, UNSIGNED, BAD_SIGNATURE, CORRUPT

    @property
    def tampered(self) -> bool:
        """The file exists but cannot be trusted: worth a security alert."""
        return self.status in ("UNSIGNED", "BAD_SIGNATURE", "CORRUPT")


_lock = threading.Lock()
_cache: dict[tuple[str, int, int, int], ModelState] = {}


def _fingerprint(path: Path) -> tuple[int, int, int]:
    def stat(p: Path) -> tuple[int, int]:
        try:
            info = p.stat()
            return info.st_mtime_ns, info.st_size
        except OSError:
            return (0, 0)

    from app.ai.model_io import sig_path

    (m1, s1), (m2, _s2) = stat(path), stat(sig_path(path))
    return (m1, s1, m2)


def current(path: str | Path, public_key: Any) -> ModelState:
    """The verified model at `path`, or the reason there is none. Cached until the files change."""
    path = Path(path)
    key = (str(path.resolve()), *_fingerprint(path))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        try:
            state = ModelState(AnomalyModel(load_model(path, public_key)), "OK")
        except ModelError as exc:
            state = ModelState(None, exc.kind)
        except (KeyError, TypeError, ValueError):  # verified file, but not a model bundle we know
            state = ModelState(None, "CORRUPT")
        _cache.clear()
        _cache[key] = state
        return state


def forget() -> None:
    with _lock:
        _cache.clear()
