"""Train, evaluate and sign the anomaly model (Phase 8).

Steps: simulate prescribing data -> fit an Isolation Forest on NORMAL rows only -> measure it on
       anomaly families it never saw -> compare with other methods and with the rules alone ->
       write the signed model, figures (docs/evaluation/) and a section of docs/evaluation.md.
Run  : python scripts/train_anomaly.py [--out models/iforest.joblib] [--report docs/evaluation.md]
Signs the model with the audit signing key (secrets/audit_signing.pem), so run it on the machine
(or with the keys) that will serve the API: a model signed with another key is refused.
All data is synthetic: the numbers show the method works on data with these properties, not how
accurate it would be on real prescriptions.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
)
from sklearn.neighbors import LocalOutlierFactor  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.svm import OneClassSVM  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import anomaly, risk, synthetic  # noqa: E402
from app.ai.features import FEATURE_NAMES, GENERIC_FEATURES  # noqa: E402
from app.ai.model_io import save_model  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.core.keys import load_signing_key_from_file  # noqa: E402

START, END = "<!-- anomaly-eval:start -->", "<!-- anomaly-eval:end -->"
ALL_FAMILIES = synthetic.FAMILIES_TUNING + synthetic.FAMILIES_UNSEEN
FLAG_AT = risk.ANOMALY_FLAG_THRESHOLD


def prf(truth: np.ndarray, flagged: np.ndarray) -> dict[str, float]:
    p, r, f, _ = precision_recall_fscore_support(truth, flagged, average="binary", zero_division=0)
    tp = int(np.sum((truth == 1) & (flagged == 1)))
    fp = int(np.sum((truth == 0) & (flagged == 1)))
    fn = int(np.sum((truth == 1) & (flagged == 0)))
    tn = int(np.sum((truth == 0) & (flagged == 0)))
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def rule_and_combined(rows, scores, threshold):
    """Risk points from the rules alone, and with the anomaly term added."""
    rules, combined = [], []
    for row, score in zip(rows, scores, strict=True):
        args = dict(doctor_rx_last_24h=row.doctor_rx_last_24h, issue_hour=row.hour)
        rules.append(risk.assess(row.medicines, **args).score)
        combined.append(risk.assess(row.medicines, anomaly_score=float(score), **args).score)
    return np.array(rules), np.array(combined)


def pooled_auc_by_model(seed: int) -> dict[str, float]:
    """Pooled unseen-family ROC-AUC of each method for one simulated world (robustness check)."""
    data = synthetic.generate(seed=seed)
    train = synthetic.to_matrix(data["train"], FEATURE_NAMES)
    normal = synthetic.to_matrix(data["test_normal"], FEATURE_NAMES)
    anomalous = synthetic.to_matrix(data["unseen"], FEATURE_NAMES)
    y = np.r_[np.zeros(len(normal)), np.ones(len(anomalous))]
    forest = anomaly.AnomalyModel(anomaly.train_bundle(train))
    results = {
        "Isolation Forest (used)": roc_auc_score(
            y, forest.score_many(np.vstack([normal, anomalous]))
        )
    }
    for name, make in (
        (
            "Local Outlier Factor",
            lambda: make_pipeline(
                StandardScaler(), LocalOutlierFactor(n_neighbors=35, novelty=True)
            ),
        ),
        (
            "One-Class SVM",
            lambda: make_pipeline(StandardScaler(), OneClassSVM(nu=0.05, gamma="scale")),
        ),
    ):
        est = make().fit(train)
        results[name] = roc_auc_score(y, -est.score_samples(np.vstack([normal, anomalous])))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=get_settings().anomaly_model_path)
    parser.add_argument("--report", default="docs/evaluation.md")
    parser.add_argument("--figures", default="docs/evaluation")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    threshold = get_settings().risk_threshold
    started = time.time()

    print("generating synthetic data ...")
    data = synthetic.generate(seed=args.seed)
    train = synthetic.to_matrix(data["train"], FEATURE_NAMES)
    normal_test = synthetic.to_matrix(data["test_normal"], FEATURE_NAMES)
    print({k: len(v) for k, v in data.items()})

    print("training the Isolation Forest ...")
    bundle = anomaly.train_bundle(train)
    model = anomaly.AnomalyModel(bundle)
    key = load_signing_key_from_file(get_settings().audit_signing_key_path)
    digest = save_model(bundle, Path(args.out), key)
    print(f"model written to {args.out} (sha256 {digest[:16]}...), signature next to it")

    # ---- scores ----
    s_normal = model.score_many(normal_test)
    by_family = {
        f: [r for r in data["tuning"] + data["unseen"] if r.family == f] for f in ALL_FAMILIES
    }
    s_family = {
        f: model.score_many(synthetic.to_matrix(rows, FEATURE_NAMES))
        for f, rows in by_family.items()
    }
    unseen_rows = [r for f in synthetic.FAMILIES_UNSEEN for r in by_family[f]]
    s_unseen = np.concatenate([s_family[f] for f in synthetic.FAMILIES_UNSEEN])

    def curves(scores_normal, scores_anom):
        y = np.r_[np.zeros(len(scores_normal)), np.ones(len(scores_anom))]
        s = np.r_[scores_normal, scores_anom]
        return y, s, roc_auc_score(y, s), average_precision_score(y, s)

    y_u, sc_u, auc_u, ap_u = curves(s_normal, s_unseen)
    per_family = {f: curves(s_normal, s_family[f])[2:] for f in ALL_FAMILIES}

    # ---- operating points: rules only, forest only, combined ----
    rows_eval = data["test_normal"] + unseen_rows
    rules_pts, comb_pts = rule_and_combined(rows_eval, np.r_[s_normal, s_unseen], threshold)
    truth = np.r_[np.zeros(len(s_normal)), np.ones(len(s_unseen))].astype(int)
    points = {
        f"Rules only (risk >= {threshold})": prf(truth, (rules_pts >= threshold).astype(int)),
        f"Forest only (score >= {FLAG_AT})": prf(
            truth, (np.r_[s_normal, s_unseen] >= FLAG_AT).astype(int)
        ),
        f"Combined, production (risk >= {threshold})": prf(
            truth, (comb_pts >= threshold).astype(int)
        ),
        f"Combined, review band (risk >= {threshold - 20})": prf(
            truth, (comb_pts >= threshold - 20).astype(int)
        ),
    }

    # per-family recall for the same operating points (+ false-alarm rate on normal rows)
    fam_recall: dict[str, dict[str, float]] = {}
    for f in ALL_FAMILIES:
        rows = by_family[f]
        rp, cp = rule_and_combined(rows, s_family[f], threshold)
        fam_recall[f] = {
            "rules": float(np.mean(rp >= threshold)),
            "forest": float(np.mean(s_family[f] >= FLAG_AT)),
            "combined": float(np.mean(cp >= threshold)),
            "combined_review": float(np.mean(cp >= threshold - 20)),
        }
    normal_fpr = {
        "rules": float(np.mean(rules_pts[: len(s_normal)] >= threshold)),
        "forest": float(np.mean(s_normal >= FLAG_AT)),
        "combined": float(np.mean(comb_pts[: len(s_normal)] >= threshold)),
        "combined_review": float(np.mean(comb_pts[: len(s_normal)] >= threshold - 20)),
    }

    # ---- other models ----
    others_fitted = {}

    def fit_other(make, label):
        est = make().fit(train)
        others_fitted[label] = est
        return -est.score_samples(normal_test), {
            f: -est.score_samples(synthetic.to_matrix(by_family[f], FEATURE_NAMES))
            for f in ALL_FAMILIES
        }

    others = {
        "Isolation Forest (used)": (s_normal, s_family),
        "Local Outlier Factor": fit_other(
            lambda: make_pipeline(
                StandardScaler(), LocalOutlierFactor(n_neighbors=35, novelty=True)
            ),
            "Local Outlier Factor",
        ),
        "One-Class SVM": fit_other(
            lambda: make_pipeline(StandardScaler(), OneClassSVM(nu=0.05, gamma="scale")),
            "One-Class SVM",
        ),
    }
    comparison = {}
    for name, (sn, sf) in others.items():
        y, s, auc, ap = curves(sn, np.concatenate([sf[f] for f in synthetic.FAMILIES_UNSEEN]))
        comparison[name] = (auc, ap, roc_curve(y, s))

    # ---- the same comparison on five other simulated worlds ----
    seeds = [args.seed + k for k in range(1, 6)]
    repeats = [pooled_auc_by_model(sd) for sd in seeds]
    spread = {name: np.array([r[name] for r in repeats]) for name in repeats[0]}

    # ---- cost of scoring one prescription ----
    sample = synthetic.to_matrix(data["test_normal"][:1], FEATURE_NAMES)
    one_ms = {}
    for label, call in (
        ("forest", lambda: model.score_many(sample)),
        ("svm", lambda: -others_fitted["One-Class SVM"].score_samples(sample)),
        ("lof", lambda: -others_fitted["Local Outlier Factor"].score_samples(sample)),
    ):
        t0 = time.perf_counter()
        for _ in range(50):
            call()
        one_ms[label] = (time.perf_counter() - t0) / 50 * 1000

    # ---- feature ablation: no per-doctor features ----
    idx = [FEATURE_NAMES.index(n) for n in GENERIC_FEATURES]
    generic_model = anomaly.AnomalyModel(anomaly.train_bundle(train[:, idx], GENERIC_FEATURES))
    ablation = {}
    for label, mdl, cols in (
        ("All 10 features", model, slice(None)),
        ("Without per-doctor features", generic_model, idx),
    ):
        sn = mdl.score_many(normal_test[:, cols])
        ablation[label] = {
            f: roc_auc_score(
                np.r_[np.zeros(len(sn)), np.ones(len(by_family[f]))],
                np.r_[
                    sn, mdl.score_many(synthetic.to_matrix(by_family[f], FEATURE_NAMES)[:, cols])
                ],
            )
            for f in synthetic.FAMILIES_UNSEEN
        }

    # ---- tuning-set check of the flag threshold ----
    tuning_rows = [(f, s_family[f]) for f in synthetic.FAMILIES_TUNING]
    threshold_table = []
    for cut in (0.90, 0.95, 0.99):
        threshold_table.append(
            (
                cut,
                float(np.mean(s_normal >= cut)),
                *[float(np.mean(s >= cut)) for _, s in tuning_rows],
            )
        )

    # ---- figures ----
    fig_dir = Path(args.figures)
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    for name, (auc, _ap, (fpr, tpr, _)) in comparison.items():
        ax.plot(fpr, tpr, label=f"{name} (AUC {auc:.2f})", lw=2 if "used" in name else 1.3)
    ax.plot([0, 1], [0, 1], color="#999", lw=0.8, ls="--")
    ax.set(
        xlabel="False alarm rate",
        ylabel="Detection rate",
        title="Unseen anomaly families vs. normal prescriptions",
    )
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(fig_dir / "roc_unseen.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    bins = np.linspace(0, 1, 26)
    ax.hist(
        s_normal,
        bins=bins,
        histtype="stepfilled",
        alpha=0.35,
        color="#4a5a78",
        density=True,
        label="Normal (held out)",
    )
    for f in synthetic.FAMILIES_UNSEEN:
        ax.hist(
            s_family[f], bins=bins, histtype="step", lw=1.8, density=True, label=f.replace("_", " ")
        )
    ax.axvline(FLAG_AT, color="#b3261e", lw=1, ls="--")
    ax.set(
        xlabel="Anomaly score (percentile within normal data)",
        ylabel="Density",
        title="Where the model puts each kind of prescription",
    )
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "score_distribution.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    width = 0.26
    positions = np.arange(len(ALL_FAMILIES))
    for i, (key_name, label, colour) in enumerate(
        (
            ("rules", "Rules only", "#8a8f98"),
            ("forest", f"Forest only (>= {FLAG_AT})", "#4a5a78"),
            ("combined", f"Combined (risk >= {threshold})", "#0f766e"),
        )
    ):
        ax.bar(
            positions + (i - 1) * width,
            [fam_recall[f][key_name] for f in ALL_FAMILIES],
            width,
            label=label,
            color=colour,
        )
    ax.set_xticks(positions, [f.replace("_", "\n") for f in ALL_FAMILIES], fontsize=8)
    ax.axvline(len(synthetic.FAMILIES_TUNING) - 0.5, color="#bbb", lw=0.8)
    ax.set(
        ylabel="Share flagged",
        ylim=(0, 1.05),
        title="What each layer catches (left: tuning families, right: unseen)",
    )
    ax.legend(frameon=False, fontsize=8, loc="upper center", ncol=3)
    fig.tight_layout()
    fig.savefig(fig_dir / "recall_by_family.png", dpi=160)
    plt.close(fig)

    # ---- the report ----
    def pct(x):
        return f"{100 * x:.0f}%"

    lines = [
        "## Anomaly model (Phase 8)",
        "",
        f"Generated by `scripts/train_anomaly.py` on {datetime.now(UTC):%Y-%m-%d}, seed {args.seed}.",
        "",
        "> **Read this first.** All data is *synthetic*: 24 simulated doctors in 6 specialties, "
        "with invented habits, hours and patients. The numbers below show that the method works "
        "on data with these properties. They are **not** a claim about accuracy on real "
        "prescriptions, and the anomaly families were written by the same person who built the "
        "model, so they are easier to separate than genuine misuse would be.",
        "",
        "### Setup",
        "",
        f"- Isolation Forest, `n_estimators=200`, `random_state=42`, fitted on **{len(train):,} normal** "
        "prescriptions only (simulated days 60-104). Ten features, including four that compare a "
        "prescription with the doctor's own recent habits.",
        f"- Held-out normal prescriptions: {len(normal_test):,} (days 105-129).",
        f"- **Tuning families** (used to choose the flag threshold): {', '.join(synthetic.FAMILIES_TUNING)}, "
        f"{len(by_family[synthetic.FAMILIES_TUNING[0]])} each.",
        f"- **Unseen families** (never used for any choice): {', '.join(synthetic.FAMILIES_UNSEEN)}, "
        f"{len(by_family[synthetic.FAMILIES_UNSEEN[0]])} each.",
        "- The score is a percentile of the forest's raw score within the normal training data "
        "(0.5 typical, 0.95 and above rare). It adds up to 40 points to the rule-based risk score; "
        f"a prescription reaches the review threshold ({threshold}) only when rules and model together say so.",
        "",
        "### Unseen families: ranking quality (forest score)",
        "",
        f"Pooled: **ROC-AUC {auc_u:.3f}**, **PR-AUC {ap_u:.3f}** (anomalies are "
        f"{pct(len(s_unseen) / (len(s_unseen) + len(s_normal)))} of the evaluated rows, so PR-AUC "
        "should be read against that base rate).",
        "",
        "| Family | Set | ROC-AUC vs. normal |",
        "|---|---|---|",
        *[
            f"| {f.replace('_', ' ')} | {'unseen' if f in synthetic.FAMILIES_UNSEEN else 'tuning'} | {per_family[f][0]:.3f} |"
            for f in ALL_FAMILIES
        ],
        "",
        "### Operating points (unseen families + held-out normal rows)",
        "",
        "| Method | Precision | Recall | F1 | TP | FP | FN | TN |",
        "|---|---|---|---|---|---|---|---|",
        *[
            f"| {name} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |"
            for name, m in points.items()
        ],
        "",
        "Because the model adds at most 40 points and the review threshold is "
        f"{threshold}, an unusual-but-otherwise-ordinary prescription cannot reach it on the "
        "model's say-so alone (that is deliberate: the model nudges, the rules decide). Such a "
        f"prescription still shows `ANOMALOUS_PATTERN` with reasons once its score is {FLAG_AT} or "
        f"more, and sits in the review band (risk >= {threshold - 20}) shown above.",
        "",
        "### What each layer catches (share of each family flagged)",
        "",
        f"| Family | Set | Rules only | Forest only | Combined (>= {threshold}) | Combined (>= {threshold - 20}) |",
        "|---|---|---|---|---|---|",
        *[
            f"| {f.replace('_', ' ')} | {'unseen' if f in synthetic.FAMILIES_UNSEEN else 'tuning'} | "
            f"{pct(fam_recall[f]['rules'])} | {pct(fam_recall[f]['forest'])} | {pct(fam_recall[f]['combined'])} | {pct(fam_recall[f]['combined_review'])} |"
            for f in ALL_FAMILIES
        ],
        f"| *false alarms on normal rows* | | {pct(normal_fpr['rules'])} | {pct(normal_fpr['forest'])} | {pct(normal_fpr['combined'])} | {pct(normal_fpr['combined_review'])} |",
        "",
        "![What each layer catches](evaluation/recall_by_family.png)",
        "",
        "### Does the forest earn its place? (model comparison on the unseen families)",
        "",
        "| Model | ROC-AUC | PR-AUC |",
        "|---|---|---|",
        *[f"| {name} | {auc:.3f} | {ap:.3f} |" for name, (auc, ap, _) in comparison.items()],
        "",
        f"Five other simulated worlds (seeds {seeds[0]}-{seeds[-1]}), pooled unseen-family ROC-AUC, mean +- standard deviation:",
        "",
        "| Model | ROC-AUC |",
        "|---|---|",
        *[f"| {name} | {v.mean():.3f} +- {v.std():.3f} |" for name, v in spread.items()],
        "",
        "On this synthetic data the forest ranks about 0.03 AUC *below* the one-class SVM and "
        "Local Outlier Factor, consistently across worlds. It is kept anyway, and this is a "
        "judgement, not a measured win: it needs no feature scaling, it scores one prescription in "
        f"{one_ms['forest']:.1f} ms (one-class SVM {one_ms['svm']:.1f} ms, LOF {one_ms['lof']:.1f} ms, "
        "measured here), the specification calls for it, and its per-feature percentile "
        "explanations do not depend on the model type. A swap to the one-class SVM would be a "
        "small change if real data pointed that way.",
        "",
        "![ROC curves](evaluation/roc_unseen.png)",
        "",
        "### Do the per-doctor features matter? (ablation, ROC-AUC on unseen families)",
        "",
        "| Features | " + " | ".join(f.replace("_", " ") for f in synthetic.FAMILIES_UNSEEN) + " |",
        "|---|" + "---|" * len(synthetic.FAMILIES_UNSEEN),
        *[
            f"| {label} | "
            + " | ".join(f"{values[f]:.3f}" for f in synthetic.FAMILIES_UNSEEN)
            + " |"
            for label, values in ablation.items()
        ],
        "",
        "![Score distribution](evaluation/score_distribution.png)",
        "",
        "### Choosing the flag threshold on the tuning families",
        "",
        "| Score threshold | False alarms on normal rows | "
        + " | ".join(f"{f.replace('_', ' ')} caught" for f in synthetic.FAMILIES_TUNING)
        + " |",
        "|---|---|" + "---|" * len(synthetic.FAMILIES_TUNING),
        *[
            f"| {c:.2f} | {pct(fp)} | " + " | ".join(pct(x) for x in rest) + " |"
            for c, fp, *rest in threshold_table
        ],
        "",
        f"{FLAG_AT} was kept: about one normal prescription in twenty is shown a note, which a "
        "doctor can ignore, while the strongest anomalies stay clearly above it.",
        "",
        "### Limits to keep in mind",
        "",
        "- **Huge single-field values dilute in a forest.** A tenfold dose is one extreme number "
        "among ten features, so the forest ranks it only modestly; the rules catch it directly "
        "(`DOSE_ABOVE_SINGLE_MAX`, `DOSE_ABOVE_DAILY_MAX`). That is the reason for combining both.",
        "- **A slow, low-dose controlled-drug drip is mostly missed at the alert level.** Each "
        "prescription is a single low-dose controlled medicine, so little stands out; the forest "
        "gives it a raised score (see the AUC) but few reach the flag threshold. The review band "
        "catches more, at the cost of more false alarms. A psychiatrist, for whom controlled drugs "
        "are normal, was left out of this family because the pattern is invisible for them.",
        "- **A brand-new account has no baseline.** Doctors with fewer than 5 earlier prescriptions "
        'get a neutral "new drug" feature, so a freshly created stolen account is not caught by it.',
        "- Patient visits are counted across all simulated doctors, as in production, but the "
        "simulated patient population is much simpler than a real one.",
        "",
        f"_Training and evaluation took {time.time() - started:.0f} s on one CPU core._",
    ]
    block = f"{START}\n" + "\n".join(lines) + f"\n{END}\n"
    report = Path(args.report)
    existing = report.read_text(encoding="utf-8") if report.exists() else "# Evaluation\n\n"
    if START in existing and END in existing:
        head, rest = existing.split(START, 1)
        text = head + block.rstrip("\n") + rest.split(END, 1)[1]
    else:
        text = existing.rstrip("\n") + "\n\n" + block
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")
    print(f"report -> {report}; figures -> {fig_dir}")
    print(f"pooled unseen ROC-AUC {auc_u:.3f}, PR-AUC {ap_u:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
