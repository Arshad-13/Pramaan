"""P10: every attack in scripts/attack_suite.py must be detected or blocked.

The suite is the source of truth for the results table in the report and the deck; running it
here, on a freshly seeded database, means that table cannot claim more than the code delivers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import attack_suite  # noqa: E402
import seed_demo  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    from app import models
    from app.config import get_settings
    from app.db import get_engine

    engine = get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    get_settings().rate_limit_enabled = False
    with TestClient(app) as client:
        world = seed_demo.seed(client)
        yield attack_suite.Ctx(client, world)


@pytest.mark.parametrize("number", [n for n, _, _ in sorted(attack_suite.ATTACKS)])
def test_attack_is_detected_or_blocked(ctx, number):
    title, run = next((t, r) for n, t, r in attack_suite.ATTACKS if n == number)
    result = run(ctx)
    assert result.detected, f"#{number} {title}: NOT CAUGHT. {result.evidence}"


def test_all_sixteen_required_attacks_are_present():
    assert [n for n, _, _ in sorted(attack_suite.ATTACKS)] == list(range(1, 17))


def test_the_results_table_reports_every_attack(ctx):
    results = attack_suite.run_all(ctx, {1, 6})
    text = attack_suite.table(results)
    assert "BLOCKED" in text and "NOT CAUGHT" not in text
