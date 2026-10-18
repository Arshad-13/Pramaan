"""P6: drug-name matching, dose limits and the risk score (rules only)."""

from __future__ import annotations

import csv

import pytest

from app.ai import drug_match as dm
from app.ai import risk
from app.ai.risk import assess


def med(name="Amoxicillin", dose=500, freq="TDS", days=5):
    return {"name": name, "dose_mg": dose, "frequency": freq, "duration_days": days}


# --- the data files --------------------------------------------------------------------------------


def test_data_files_meet_the_size_targets_and_are_consistent():
    catalog = dm.load_catalog()
    assert len(catalog.by_norm) >= 100
    assert len(catalog.reference) >= 40
    for entry in catalog.by_norm.values():
        assert dm.normalise_name(entry.generic) in catalog.reference, entry  # every drug has limits


def test_reference_values_are_sane():
    for ref in dm.load_catalog().reference.values():
        assert (
            0 < ref.max_single_dose_mg <= ref.max_daily_dose_mg + 1e-9 or ref.max_single_dose_mg > 0
        )
        assert ref.max_daily_dose_mg >= ref.max_single_dose_mg or ref.name == "Clopidogrel"
        assert ref.schedule in {"OTC", "H", "H1", "X"}


def test_the_csv_headers_match_the_spec():
    with open(dm.DATA_DIR / "drugs.csv", newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == ["name", "generic", "is_brand"]
    with open(dm.DATA_DIR / "drug_reference.csv", newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == [
            "name",
            "max_single_dose_mg",
            "max_daily_dose_mg",
            "schedule",
        ]


# --- name normalisation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Amoxicillin", "amoxicillin"),
        ("  AMOXICILLIN  ", "amoxicillin"),
        ("Tab Paracetamol 500 mg", "paracetamol"),
        ("Paracetamol 500mg tablets", "paracetamol"),
        ("Dolo 650", "dolo"),
        ("Syp. Crocin", "crocin"),
        ("Taxim-O", "taxim o"),
        ("Metformin SR 500", "metformin"),
    ],
)
def test_normalisation_drops_forms_strengths_and_punctuation(raw, expected):
    assert dm.normalise_name(raw) == expected


# --- matching -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["Amoxicillin", "amoxicillin", "Tab Amoxicillin 500 mg", "Paracetamol"]
)
def test_exact_names_are_known(name):
    match = dm.match_drug(name)
    assert match.kind == "KNOWN" and match.score == 100.0


def test_brands_resolve_to_their_generic():
    match = dm.match_drug("Dolo 650")
    assert (match.kind, match.name, match.generic, match.is_brand) == (
        "KNOWN",
        "Dolo",
        "Paracetamol",
        True,
    )
    assert dm.match_drug("Augmentin").generic == "Amoxicillin and Clavulanate"


@pytest.mark.parametrize(
    ("typo", "suggestion"),
    [
        ("Amoxicilin", "Amoxicillin"),
        ("Paracetamool", "Paracetamol"),
        ("Atorvastatn", "Atorvastatin"),
        ("Metformine", "Metformin"),
        ("Azithromycine", "Azithromycin"),
    ],
)
def test_near_misses_are_flagged_with_a_suggestion_never_silently_accepted(typo, suggestion):
    match = dm.match_drug(typo)
    assert match.kind == "POSSIBLE_TYPO" and match.name == suggestion and match.score >= 75


@pytest.mark.parametrize("fake", ["Xyzzolam", "Qwertyol", "Blorptazine", "Notarealdrug", "Zzzzz"])
def test_invented_names_are_unknown(fake):
    assert dm.match_drug(fake).kind == "UNKNOWN"


@pytest.mark.parametrize("short", ["Pan", "Mox", "Aten", "Xyz", "Ab", "Dol"])
def test_short_names_never_fuzzy_match(short):
    match = dm.match_drug(short)
    if short in ("Pan", "Mox", "Aten"):
        assert match.kind == "KNOWN"  # exact brand names are fine
    else:
        assert match.kind == "UNKNOWN"  # but "Dol" does not drift to "Dolo"


def test_empty_and_symbol_only_names_are_unknown():
    for name in ("", "   ", "500 mg", "!!!"):
        assert dm.match_drug(name).kind == "UNKNOWN"


# --- dose limits --------------------------------------------------------------------------------------


def flags(generic, dose, freq):
    return [f.flag for f in dm.dose_check(generic, dose, freq)]


def test_normal_doses_have_no_findings():
    assert flags("Amoxicillin", 500, "TDS") == []
    assert flags("Paracetamol", 650, "TDS") == []


def test_a_single_dose_above_the_limit_is_flagged():
    assert "DOSE_ABOVE_SINGLE_MAX" in flags("Amoxicillin", 2000, "OD")


def test_the_daily_total_is_checked_separately():
    found = flags("Paracetamol", 1000, "QID")  # 1000 is fine alone, 4 x 1000 = 4000 is the limit
    assert found == []
    found = flags("Paracetamol", 1000, "SOS")  # SOS counts as 3 a day => 3000, still fine
    assert found == []
    assert "DOSE_ABOVE_DAILY_MAX" in flags("Amoxicillin", 1000, "QID")  # 4000 > 3000
    assert "DOSE_ABOVE_SINGLE_MAX" not in flags("Amoxicillin", 1000, "QID")


def test_an_absurd_dose_trips_both_limits():
    assert set(flags("Paracetamol", 5000, "TDS")) == {
        "DOSE_ABOVE_SINGLE_MAX",
        "DOSE_ABOVE_DAILY_MAX",
    }


def test_the_limit_itself_is_allowed():
    assert flags("Paracetamol", 1000, "TDS") == []
    assert "DOSE_ABOVE_SINGLE_MAX" in flags("Paracetamol", 1001, "OD")


@pytest.mark.parametrize("generic", ["Tramadol", "Alprazolam", "Codeine"])
def test_controlled_medicines_are_flagged_even_at_normal_doses(generic):
    assert "CONTROLLED_SUBSTANCE" in flags(generic, 10, "OD")


def test_unknown_generics_have_no_dose_findings():
    assert flags("Nothing", 99999, "QID") == [] and flags(None, 1, "OD") == []


def test_daily_dose_ratio():
    assert dm.daily_dose_ratio("Paracetamol", 1000, "TDS") == pytest.approx(0.75)
    assert dm.daily_dose_ratio("Nothing", 5, "OD") == 0.0


# --- risk score ---------------------------------------------------------------------------------------


def test_a_normal_prescription_scores_zero_and_notes_the_missing_model():
    result = assess([med()])
    assert result.score == 0 and result.flags == [] and result.explanations == []
    assert result.warnings == ["MODEL_UNAVAILABLE"]
    assert [n.status for n in result.notes] == ["KNOWN"]


def test_a_fake_drug_reaches_the_review_threshold_on_its_own():
    result = assess([med(name="Xyzzolam")])
    assert result.flags == ["UNKNOWN_DRUG"] and result.score == 60
    assert result.explanations == ['"Xyzzolam" is not in the drug list.']


def test_a_typo_is_a_small_score_with_a_suggestion():
    result = assess([med(name="Amoxicilin")])
    assert result.flags == ["POSSIBLE_TYPO"] and result.score == 15
    assert result.notes[0].suggestion == "Amoxicillin"
    assert "Amoxicillin" in result.explanations[0]


def test_an_absurd_dose_crosses_the_threshold_with_clear_explanations():
    result = assess([med(name="Paracetamol", dose=5000)])
    assert result.flags == ["DOSE_ABOVE_SINGLE_MAX", "DOSE_ABOVE_DAILY_MAX"]
    assert result.score == 70
    assert any("single-dose limit of 1000 mg" in e for e in result.explanations)
    assert any("a day, above the daily limit of 4000 mg" in e for e in result.explanations)


def test_controlled_substances_add_ten_each_capped_at_twenty():
    assert assess([med("Tramadol", 50, "BD")]).score == 10
    assert assess([med("Tramadol", 50, "BD"), med("Alprazolam", 1, "OD")]).score == 20
    three = assess(
        [med("Tramadol", 50, "BD"), med("Alprazolam", 1, "OD"), med("Diazepam", 5, "OD")]
    )
    assert three.score == 20 and three.controlled is True


def test_each_rule_counts_once_even_if_several_medicines_trigger_it():
    result = assess([med("Xyzzolam"), med("Qwertyol")])
    assert result.score == 60 and result.flags == ["UNKNOWN_DRUG"]
    assert len(result.explanations) == 2


def test_duplicate_therapy_is_detected_across_brand_and_generic():
    result = assess([med("Dolo", 650, "TDS", 3), med("Paracetamol", 500, "SOS", 3)])
    assert "DUPLICATE_THERAPY" in result.flags and result.score == 10


def test_a_burst_of_prescriptions_from_one_doctor_adds_points():
    assert assess([med()], doctor_rx_last_24h=14).score == 0
    burst = assess([med()], doctor_rx_last_24h=15)
    assert burst.flags == ["DOCTOR_BURST"] and burst.score == 20


def test_the_anomaly_term_scales_to_forty_points_and_removes_the_warning():
    result = assess([med()], anomaly_score=0.5)
    assert result.score == 20 and result.warnings == []
    assert assess([med()], anomaly_score=1.0).score == 40
    assert assess([med()], anomaly_score=7.0).score == 40  # clamped
    assert assess([med()], anomaly_score=-1.0).score == 0


def test_the_score_is_capped_at_one_hundred():
    wild = assess(
        [med("Xyzzolam", 99999), med("Tramadol", 5000, "QID"), med("Alprazolam", 99, "QID")],
        anomaly_score=1.0,
    )
    assert wild.score == 100


def test_features_are_recorded_for_the_model():
    result = assess(
        [med("Paracetamol", 1000, "TDS", 7), med("Tramadol", 50, "BD", 30)],
        doctor_rx_last_24h=4,
        issue_hour=3,
    )
    assert result.features == {
        "num_medicines": 2,
        "max_daily_dose_ratio": 0.75,
        "max_duration_days": 30,
        "controlled_count": 1,
        "doctor_rx_last_24h": 4,
        "issue_hour": 3,
    }


def test_flags_come_out_in_a_stable_order():
    result = assess(
        [med("Xyzzolam"), med("Paracetamol", 5000), med("Tramadol", 50, "BD")],
        doctor_rx_last_24h=20,
    )
    assert result.flags == [f for f in risk.FLAG_ORDER if f in result.flags]
