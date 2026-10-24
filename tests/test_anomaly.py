"""P8: features, the anomaly model, signed model files, and their use when issuing."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai import anomaly, drug_match, model_io, risk, synthetic
from app.ai.features import FEATURE_NAMES, DoctorHistory, build_features
from app.config import get_settings
from app.core.keys import load_signing_key_from_file
from app.main import app
from app.models import SecurityEvent
from tests.helpers import session
from tests.world import build_world, med

CATALOG = drug_match.load_catalog()


@pytest.fixture(scope="module")
def data():
    return synthetic.generate(seed=7, per_family_tuning=25, per_family_unseen=25)


@pytest.fixture(scope="module")
def model(data):
    return anomaly.AnomalyModel(
        anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES))
    )


# --- features -------------------------------------------------------------------------------------


def history(**o):
    base = dict(
        rx_last_24h=4,
        distinct_patients_last_24h=4,
        patient_rx_last_7d=1,
        known_generics=frozenset({"amoxicillin", "paracetamol"}),
        baseline_rx=40,
        meds_30d=50,
        controlled_meds_30d=5,
    )
    return DoctorHistory(**{**base, **o})


def test_features_have_the_documented_meaning():
    meds = [
        {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5},
        {"name": "Alprazolam", "dose_mg": 1, "frequency": "BD", "duration_days": 10},
    ]
    f = build_features(meds, 14, history(), CATALOG)
    assert list(f) == list(FEATURE_NAMES)
    assert f["num_medicines"] == 2 and f["max_duration_days"] == 10 and f["issue_hour"] == 14
    assert f["controlled_count"] == 1
    assert f["max_daily_dose_ratio"] == pytest.approx(0.5, abs=0.01)  # 1500 of 3000 mg Amoxicillin
    assert f["new_drug_ratio_for_doctor"] == 0.5  # Alprazolam is new for this doctor
    assert f["controlled_ratio_doctor_30d"] == pytest.approx(6 / 52, abs=1e-3)
    assert f["doctor_rx_last_24h"] == 4 and f["distinct_patients_last_24h"] == 4
    assert f["patient_rx_last_7d"] == 1


def test_a_doctor_without_a_baseline_has_a_neutral_new_drug_feature():
    f = build_features(
        [{"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}],
        9,
        history(baseline_rx=2, known_generics=frozenset()),
        CATALOG,
    )
    assert f["new_drug_ratio_for_doctor"] == 0.0


def test_unknown_drug_names_count_as_new_and_have_no_dose_ratio():
    f = build_features(
        [{"name": "Zzyzxol", "dose_mg": 50, "frequency": "OD", "duration_days": 5}],
        9,
        history(),
        CATALOG,
    )
    assert f["new_drug_ratio_for_doctor"] == 1.0 and f["max_daily_dose_ratio"] == 0.0


# --- synthetic data -------------------------------------------------------------------------------


def test_synthetic_data_is_deterministic_and_shaped_as_documented(data):
    again = synthetic.generate(seed=7, per_family_tuning=25, per_family_unseen=25)
    assert [r.features for r in again["train"][:50]] == [r.features for r in data["train"][:50]]
    assert 4000 < len(data["train"]) < 7000
    assert {r.family for r in data["tuning"]} == set(synthetic.FAMILIES_TUNING)
    assert {r.family for r in data["unseen"]} == set(synthetic.FAMILIES_UNSEEN)
    assert all(r.family == "normal" for r in data["train"] + data["test_normal"])


def test_normal_training_prescriptions_are_unremarkable_by_the_rules(data):
    flagged = sum(
        risk.assess(r.medicines, doctor_rx_last_24h=r.doctor_rx_last_24h, issue_hour=r.hour).score
        >= 60
        for r in data["train"][:400]
    )
    assert flagged / 400 < 0.02


# --- scoring and explanations -----------------------------------------------------------------------


def test_scores_are_percentiles_of_normal_data(model, data):
    normal = model.score_many(synthetic.to_matrix(data["test_normal"], FEATURE_NAMES))
    assert 0.0 <= normal.min() and normal.max() <= 1.0
    assert 0.4 < float(np.median(normal)) < 0.6
    assert 0.02 < float(np.mean(normal >= 0.95)) < 0.12


def test_obvious_anomalies_score_high_and_say_why(model, data):
    burst = [r for r in data["tuning"] if r.family == "night_controlled_burst"]
    scores = model.score_many(synthetic.to_matrix(burst, FEATURE_NAMES))
    assert float(np.mean(scores >= 0.95)) > 0.9
    reasons = model.explain(burst[0].features)
    assert 1 <= len(reasons) <= 2
    assert all("normal" in text for text in reasons)


def test_explanations_name_the_feature_and_the_normal_range(model):
    extreme = {name: 0.0 for name in FEATURE_NAMES} | {
        "distinct_patients_last_24h": 90.0,
        "controlled_count": 7.0,
    }
    text = " ".join(model.explain(extreme, limit=4))
    assert "90 different patients in 24 hours (normal: up to" in text
    assert "7 controlled medicines" in text


def test_a_typical_prescription_has_no_explanations(model, data):
    typical = data["test_normal"][0].features
    assert (
        model.explain(
            {
                **typical,
                "num_medicines": 1.0,
                "issue_hour": 11.0,
                "doctor_rx_last_24h": 2.0,
                "distinct_patients_last_24h": 2.0,
            }
        )
        == []
    )


def test_flagged_prescriptions_carry_the_reasons_into_the_risk_result(model, data):
    row = [r for r in data["tuning"] if r.family == "night_controlled_burst"][0]
    scored = model.assess(row.features)
    result = risk.assess(
        row.medicines,
        doctor_rx_last_24h=row.doctor_rx_last_24h,
        issue_hour=row.hour,
        anomaly_score=scored.score,
        anomaly_explanations=scored.explanations,
        model_features=row.features,
    )
    assert "ANOMALOUS_PATTERN" in result.flags and "MODEL_UNAVAILABLE" not in result.warnings
    assert (
        result.features["anomaly_score"] >= 0.95 and "distinct_patients_last_24h" in result.features
    )
    assert any("normal:" in text for text in result.explanations)


def test_anomaly_term_is_at_most_forty_points():
    result = risk.assess(
        [{"name": "Paracetamol", "dose_mg": 500, "frequency": "BD", "duration_days": 3}],
        anomaly_score=1.0,
    )
    assert result.score == 40


# --- signed model files ---------------------------------------------------------------------------


@pytest.fixture
def keys(tmp_path):
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key(), tmp_path / "m" / "iforest.joblib"


def test_signed_model_round_trips(keys, model):
    private, public, path = keys
    model_io.save_model({"hello": [1, 2, 3]}, path, private)
    assert model_io.load_model(path, public) == {"hello": [1, 2, 3]}


@pytest.mark.parametrize(
    "damage", ["flip_byte", "drop_signature", "other_key", "garbage_signature", "delete"]
)
def test_model_that_fails_verification_is_never_unpickled(keys, monkeypatch, damage):
    private, public, path = keys
    model_io.save_model({"ok": True}, path, private)
    called = []
    monkeypatch.setattr(joblib, "load", lambda *a, **k: called.append(1))
    if damage == "flip_byte":
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
    elif damage == "drop_signature":
        model_io.sig_path(path).unlink()
    elif damage == "other_key":
        model_io.save_model({"ok": True}, path, ec.generate_private_key(ec.SECP256R1()))
    elif damage == "garbage_signature":
        model_io.sig_path(path).write_text("not-a-signature")
    else:
        path.unlink()
    with pytest.raises(model_io.ModelError) as err:
        model_io.load_model(path, public)
    assert (
        err.value.kind
        == {
            "flip_byte": "BAD_SIGNATURE",
            "drop_signature": "UNSIGNED",
            "other_key": "BAD_SIGNATURE",
            "garbage_signature": "BAD_SIGNATURE",
            "delete": "MISSING",
        }[damage]
    )
    assert called == []


def test_a_signed_file_that_is_not_a_model_bundle_is_corrupt(keys):
    private, public, path = keys
    model_io.save_model({"not": "a model"}, path, private)
    assert anomaly.current(path, public).status == "CORRUPT"
    anomaly.forget()


def test_model_signature_uses_its_own_domain(keys):
    """A signature made for another purpose (audit checkpoints) must not validate a model."""
    from app.core import crypto

    private, public, path = keys
    model_io.save_model({"ok": True}, path, private)
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).digest()
    model_io.sig_path(path).write_text(
        crypto.b64u_encode(crypto.sign(private, digest, crypto.AUDIT_CONTEXT))
    )
    with pytest.raises(model_io.ModelError):
        model_io.load_model(path, public)


# --- use when issuing -----------------------------------------------------------------------------


@pytest.fixture
def w(fresh_db):
    anomaly.forget()
    with TestClient(app) as client:
        yield build_world(client)
    path = Path(get_settings().anomaly_model_path)
    path.unlink(missing_ok=True)
    model_io.sig_path(path).unlink(missing_ok=True)
    anomaly.forget()


def install(bundle, key=None):
    s = get_settings()
    key = key or load_signing_key_from_file(s.audit_signing_key_path)
    model_io.save_model(bundle, Path(s.anomaly_model_path), key)
    anomaly.forget()


def many_medicines():
    """Eight medicines, three of them controlled, all for 90 days: unlike anything in normal data."""
    plain = ["Amoxicillin", "Paracetamol", "Ibuprofen", "Cetirizine", "Omeprazole"]
    controlled = ["Alprazolam", "Diazepam", "Clonazepam"]
    return [med(name=n, dose_mg=1, frequency="OD", duration_days=90) for n in plain + controlled]


def risk_check(w, medicines):
    response = w.client.post(
        "/api/prescriptions/risk-check", headers=w.doctor, json={"medicines": medicines}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_without_a_model_the_system_runs_on_rules_alone(w):
    body = risk_check(w, [med()])
    assert "MODEL_UNAVAILABLE" in body["warnings"]


def test_with_a_signed_model_the_anomaly_score_is_used(w, data):
    install(anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES)))
    typical = risk_check(w, [med()])
    assert "MODEL_UNAVAILABLE" not in typical["warnings"]
    odd = risk_check(w, many_medicines())
    assert odd["risk"]["score"] > typical["risk"]["score"]
    assert "ANOMALOUS_PATTERN" in odd["risk"]["flags"]
    assert any("medicines on one prescription" in t for t in odd["risk"]["explanations"])


def test_issuing_stores_the_feature_snapshot_with_the_anomaly_score(w, data):
    from tests.world import issue, stored

    install(anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES)))
    rx_id = issue(w)
    import json

    snapshot = json.loads(stored(rx_id).risk_features_json)
    assert "anomaly_score" in snapshot and set(FEATURE_NAMES) <= set(snapshot)


def test_a_tampered_model_means_rules_only_and_one_high_alert(w, data):
    from tests.world import issue

    install(anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES)))
    path = Path(get_settings().anomaly_model_path)
    blob = bytearray(path.read_bytes())
    blob[100] ^= 0x01
    path.write_bytes(bytes(blob))  # modified after signing

    assert "MODEL_UNAVAILABLE" in risk_check(w, [med()])["warnings"]  # never crashes
    first = issue(w)
    second = issue(w)
    assert first != second
    with session() as db:
        alerts = list(
            db.scalars(
                select(SecurityEvent).where(SecurityEvent.event_type == "MODEL_FILE_INVALID")
            )
        )
    assert len(alerts) == 1  # not one per prescription
    assert alerts[0].severity.value == "HIGH" and '"BAD_SIGNATURE"' in alerts[0].details_json


def test_a_model_signed_with_another_key_is_refused(w, data):
    install(
        anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES)),
        key=ec.generate_private_key(ec.SECP256R1()),
    )
    assert "MODEL_UNAVAILABLE" in risk_check(w, [med()])["warnings"]


def test_replacing_the_model_file_takes_effect_without_a_restart(w, data):
    install(anomaly.train_bundle(synthetic.to_matrix(data["train"], FEATURE_NAMES)))
    assert "MODEL_UNAVAILABLE" not in risk_check(w, [med()])["warnings"]
    Path(get_settings().anomaly_model_path).unlink()
    assert "MODEL_UNAVAILABLE" in risk_check(w, [med()])["warnings"]
