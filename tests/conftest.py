"""Test tiers, so the fast loop is genuinely fast and the paying loop is honest.

The suite has **two** tiers, measured rather than assumed (ticket 01 got this wrong twice
before measuring):

- **253 tests need nothing.** No Qdrant, no key. Verified by running the whole suite with
  `QDRANT_URL` pointed at a dead port *and* with the key emptied — the same set passed both
  times.
- **31 tests need a live `OPENAI_API_KEY`.** 17 need dense query embeddings, 11 make **real
  generation calls**, and 1 needs both. There is no Qdrant-only tier: with Qdrant up and the
  key removed, all 31 still skip.

Counts re-measured 2026-08-20. They are quoted in three places (here, the `Makefile` header,
`README.md`) and had drifted in all three, which is what happens to a number that is
incremented by hand rather than read off a run.

Two problems this file solves.

**Silent green.** Left alone, `pytest` runs all 285 and reports "253 passed, 32 skipped" — a
green result that tested none of the answer path. Nothing distinguishes "the paying tier was
deliberately excluded" from "the paying tier quietly did not run." So the tiers are
*selectable*: `-m "not live"` deselects them and the run reports 253 passed and **0 skipped**,
which is a claim you can read.

**Silent green, expensively.** `-m live` without a key would skip all 31 and still report
green. `RAG_REQUIRE_LIVE=1` turns that into a loud exit instead, so the paying tier cannot
pass by not running.

Tests are marked by the **fixture they request** rather than by hand, so a new test inherits
the right tier from the fixture it uses and nobody has to remember to label it.
"""

from __future__ import annotations

import os

import pytest

# Requesting one of these means a test needs a live provider key.
#
# `indexed` is the module-scoped fixture in test_retrieve.py and test_quotas.py; `live` is
# the autouse fixture in test_answer_contract.py — being autouse, it lands in every test in
# that module's `fixturenames`, so all 11 are caught without naming them.
_LIVE_FIXTURES = frozenset({"indexed", "live"})

# One test gates itself inline rather than through a fixture, so it cannot be caught by
# fixture name. Listed explicitly, and `tests/test_tiers.py` asserts the name still exists —
# a rename would otherwise drop it silently into the free tier, where it skips itself.
_LIVE_BY_NAME = frozenset({"test_three_company_question_still_makes_exactly_one_llm_call"})


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: needs a real OPENAI_API_KEY. 17 of these embed queries; 11 make real "
        "generation calls and cost money. Deselected by the default loop.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Attach `live` by fixture usage, then verify nothing slipped through."""
    for item in items:
        needs_live = bool(_LIVE_FIXTURES & set(getattr(item, "fixturenames", ())))
        if item.name in _LIVE_BY_NAME:
            needs_live = True
        if needs_live:
            item.add_marker(pytest.mark.live)

    # A rename would move a paying test into the free tier, where it would skip itself and
    # still report green. That is checked by `tests/test_tiers.py` rather than here: a
    # collection hook cannot tell "the test was renamed" from "the user selected one test by
    # node id", and an earlier version of this guard failed the run for the latter.


def pytest_collection_finish(session: pytest.Session) -> None:
    """Fail fast, and once, on a missing prerequisite.

    Two guards, both of which exist because the alternative reports something misleading.
    """
    if not session.items:
        return

    from src.config import settings

    # The corpus is a prerequisite of the *free* tier, not just the live one — 21 of the
    # inherited free tests read it, all 29 fixture tests do, and test_smoke.py asserts it.
    # Without this guard they fail with assorted AssertionErrors and a newcomer has to
    # deduce that one missing directory caused all of them. Say it once instead.
    corpus = settings().corpus_dir
    if not corpus.is_dir() or not any(corpus.glob("*.txt")):
        pytest.exit(
            f"The filings corpus is missing or empty at {corpus}.\n"
            "\nThe whole suite depends on it — most free-tier tests read it directly.\n"
            "Download `edgar_corpus.zip` (linked in the assessment brief) and unzip it "
            "there, or point RAG_CORPUS_DIR at an existing copy.",
            returncode=1,
        )

    if os.environ.get("RAG_REQUIRE_LIVE") != "1":
        return

    from src.index import qdrant_reachable

    reasons = []
    if not settings().provider_configured:
        reasons.append(
            "no provider key — set OPENAI_API_KEY (or OPENAI_BASE_URL for a local "
            "OpenAI-compatible server)"
        )
    if not qdrant_reachable():
        reasons.append(
            f"Qdrant not reachable at {settings().qdrant_url} — `docker compose up -d`"
        )

    if reasons:
        detail = "".join(f"\n  - {r}" for r in reasons)
        pytest.exit(
            f"RAG_REQUIRE_LIVE=1 but the live tier cannot run:{detail}\n"
            "\nThese tests would otherwise skip and the run would report green.",
            returncode=1,
        )
