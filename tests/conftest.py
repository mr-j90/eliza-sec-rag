"""Test tiers, so the fast loop is genuinely fast and the paying loop is honest.

The suite has **two** tiers, measured rather than assumed (ticket 01 got this wrong twice
before measuring):

- **93 tests need nothing.** No Qdrant, no key. Verified by running the whole suite with
  `QDRANT_URL` pointed at a dead port *and* with the key emptied — the same set passed both
  times. (64 inherited, plus the 29 fixture-verification tests added with this loop.)
- **29 tests need a live `OPENAI_API_KEY`.** 17 need dense query embeddings, 11 make **real
  generation calls**, and 1 needs both. There is no Qdrant-only tier: with Qdrant up and the
  key removed, all 29 still skip.

Two problems this file solves.

**Silent green.** Left alone, `pytest` runs all 122 and reports "93 passed, 29 skipped" — a
green result that tested none of the answer path. Nothing distinguishes "the paying tier was
deliberately excluded" from "the paying tier quietly did not run." So the tiers are
*selectable*: `-m "not live"` deselects them and the run reports 93 passed and **0 skipped**,
which is a claim you can read.

**Silent green, expensively.** `-m live` without a key would skip all 29 and still report
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
# fixture name. Listed explicitly; the assertion in `pytest_collection_modifyitems` fails
# loudly if it is ever renamed, rather than silently dropping it into the free tier.
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
    seen_by_name: set[str] = set()

    for item in items:
        needs_live = bool(_LIVE_FIXTURES & set(getattr(item, "fixturenames", ())))
        if item.name in _LIVE_BY_NAME:
            needs_live = True
            seen_by_name.add(item.name)
        if needs_live:
            item.add_marker(pytest.mark.live)

    # A rename would otherwise move a paying test into the free tier, where it would skip
    # itself and still report green — exactly the failure this file exists to prevent.
    #
    # Only enforced when the module that defines it was actually collected. Checking the
    # collection instead of the command line means this stays correct under `-k`, a single
    # file path, `-m`, or any other selection, rather than guessing at argv.
    if not any(item.path.name == "test_ask.py" for item in items):
        return
    if missing := _LIVE_BY_NAME - seen_by_name:
        raise pytest.UsageError(
            f"conftest expected to find live test(s) {sorted(missing)} but collection did "
            "not contain them. If a test was renamed, update _LIVE_BY_NAME in "
            "tests/conftest.py."
        )


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
