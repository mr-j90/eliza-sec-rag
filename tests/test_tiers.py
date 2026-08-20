"""The tier marking itself is tested, not asserted from a collection hook.

`conftest.py` marks a test as `live` when it requests one of the gating fixtures. One test
gates itself inline instead and so is listed by name — and a rename would slide it into the
free tier, where it would skip itself and still report green.

That check lives here rather than in `pytest_collection_modifyitems` because a collection hook
cannot distinguish "the test was renamed" from "the user selected a single test by node id".
An earlier version raised `UsageError` on the latter and broke
`pytest tests/test_ask.py::some_test`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from conftest import _LIVE_BY_NAME, _LIVE_FIXTURES

TESTS = Path(__file__).parent


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def test_every_named_live_test_still_exists():
    """If this fails, a paying test was renamed and is now silently in the free tier."""
    defined: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        defined |= _function_names(path)
    missing = _LIVE_BY_NAME - defined
    assert not missing, (
        f"_LIVE_BY_NAME names tests that no longer exist: {sorted(missing)}. "
        "They will now run in the free tier and skip themselves."
    )


def test_every_gating_fixture_still_exists():
    """The fixture-based marking is the primary mechanism; a renamed fixture disarms it."""
    defined: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        defined |= _function_names(path)
    missing = _LIVE_FIXTURES - defined
    assert not missing, (
        f"_LIVE_FIXTURES names fixtures that no longer exist: {sorted(missing)}. "
        "Tests that used them are no longer marked live."
    )
