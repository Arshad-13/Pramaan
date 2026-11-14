"""Drug-drug interaction rules (clinical extension, K2).

Purpose: warn the prescriber when two medicines on one prescription are known to be a poor mix.
Data   : `data/drug_classes.csv` (generic, class) and `data/interactions.csv` (a, b, severity,
         note). A rule side is either a generic name or `@class`. DEMO DATA ONLY: approximate,
         incomplete, and not for clinical use (same disclaimer as the dose limits).
Method : every pair of distinct generics on the prescription is checked against every rule; the
         most severe matching rule is kept for the pair. Rules between two members of one class
         (`@benzo,@benzo`) only fire for two different generics: the same generic twice is the
         existing DUPLICATE_THERAPY flag.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from app.ai.drug_match import DATA_DIR, normalise_name

SEVERITY_RANK = {"MAJOR": 2, "MODERATE": 1}


@dataclass(frozen=True)
class Rule:
    a: str
    b: str
    severity: str
    note: str


@dataclass(frozen=True)
class Interaction:
    first: str  # generic names, as written in the drug list
    second: str
    severity: str
    note: str
    indices: tuple[int, int]  # medicine lines involved


@dataclass(frozen=True)
class Rules:
    classes: dict[str, frozenset[str]]  # normalised generic -> classes
    rules: tuple[Rule, ...]


@lru_cache
def load_rules(data_dir: Path = DATA_DIR) -> Rules:
    classes: dict[str, set[str]] = {}
    with open(data_dir / "drug_classes.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            classes.setdefault(normalise_name(row["generic"]), set()).add(row["class"].strip())
    rules: list[Rule] = []
    with open(data_dir / "interactions.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            severity = row["severity"].strip().upper()
            if severity not in SEVERITY_RANK:
                raise ValueError(f"Unknown interaction severity: {severity!r}")
            rules.append(Rule(row["a"].strip(), row["b"].strip(), severity, row["note"].strip()))
    return Rules({k: frozenset(v) for k, v in classes.items()}, tuple(rules))


def _matches(token: str, generic_norm: str, rules: Rules) -> bool:
    if token.startswith("@"):
        return token[1:] in rules.classes.get(generic_norm, frozenset())
    return normalise_name(token) == generic_norm


def find_interactions(
    generics: list[tuple[int, str]], data_dir: Path = DATA_DIR
) -> list[Interaction]:
    """`generics` is (medicine line index, generic name) for each recognised medicine."""
    rules = load_rules(data_dir)
    found: list[Interaction] = []
    seen_pairs: set[frozenset[str]] = set()
    for (i, g1), (j, g2) in combinations(generics, 2):
        n1, n2 = normalise_name(g1), normalise_name(g2)
        pair = frozenset((n1, n2))
        if n1 == n2 or pair in seen_pairs:
            continue
        best: Rule | None = None
        for rule in rules.rules:
            hit = (_matches(rule.a, n1, rules) and _matches(rule.b, n2, rules)) or (
                _matches(rule.a, n2, rules) and _matches(rule.b, n1, rules)
            )
            if hit and (
                best is None or SEVERITY_RANK[rule.severity] > SEVERITY_RANK[best.severity]
            ):
                best = rule
        if best is not None:
            seen_pairs.add(pair)
            found.append(Interaction(g1, g2, best.severity, best.note, (i, j)))
    found.sort(key=lambda x: (-SEVERITY_RANK[x.severity], x.first, x.second))
    return found
