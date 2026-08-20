"""Citation handles are checked, not trusted.

Ticket 09. A `[C7]` in an answer where only six passages were retrieved is a **false claim of
groundedness** — worse than no citation, because it looks like provenance in a tool whose
entire value is provenance.

Measured across thirteen saved runs before this existed: **zero fabricated handles**. So this
guards a failure that has not occurred. It is worth having anyway, because "every citation
resolves" is the claim the system rests on, and a checked claim is worth more than one that has
merely held so far — and because it turns the count on screen into a verified number rather
than a reported one.

Free tier: no Qdrant, no key.
"""

from __future__ import annotations

import pytest

from src.verify import verify_citations


def test_a_fabricated_handle_is_caught():
    """The test the walkthrough leans on. Cheap, and it makes the claim credible."""
    check = verify_citations("Revenue grew [C1]. Margins fell [C99].", ["C1", "C2"])

    assert check.fabricated == ("C99",)
    assert check.cited == ("C1",)
    assert not check.ok


def test_every_handle_resolving_passes():
    check = verify_citations("Apple [C1] and Tesla [C2] both disclose this [C1].", ["C1", "C2"])
    assert check.ok
    assert check.cited == ("C1", "C2"), "repeats collapse, first-appearance order is kept"
    assert check.fabricated == ()


def test_a_correct_refusal_is_not_a_failure():
    """The behaviour this check must never penalise.

    The refusal path emits two sections and no handles, over twenty retrieved passages that are
    all about companies nobody asked about. Flagging that would penalise the single most
    important behaviour in the system.
    """
    answer = (
        "## Bottom line\nThere are no filings for Shopify in this corpus, so the question "
        "cannot be answered from it.\n\n## Gaps and confidence\nNo Shopify filings are present."
    )
    check = verify_citations(answer, [f"C{i}" for i in range(1, 21)])

    assert check.ok, "a refusal cites nothing and must not be reported as unverified"
    assert check.is_uncited
    assert check.available == 20


def test_uncited_is_reported_but_not_judged():
    """`is_uncited` deliberately does not say whether it is a refusal or a contract violation.

    Those cannot be told apart from the handles alone — the answer-contract tests judge it on
    the prose, which is where the evidence is.
    """
    check = verify_citations("No handles here at all.", ["C1", "C2"])
    assert check.is_uncited
    assert check.ok, "uncited is not the same as unverified"


def test_the_coverage_sentence_does_not_trip_the_check():
    """Ticket 07 appends a deterministic coverage sentence outside the model's output.

    It carries no handles by design, and the two mechanisms must not flag each other.
    """
    answer = (
        "Findings [C1].\n\nEvidence base — 2 companies, filings used: AAPL 1 of 16, "
        "TSLA 1 of 16."
    )
    assert verify_citations(answer, ["C1"]).ok


@pytest.mark.parametrize(
    "text,expected",
    [
        ("plain C1 with no brackets", ()),
        ("[C1] at the start", ("C1",)),
        ("trailing [C12]", ("C12",)),
        ("[c1] lowercase is not a handle", ()),
        ("[C1][C2] adjacent", ("C1", "C2")),
    ],
)
def test_handle_parsing_matches_the_emitted_format(text, expected):
    """The regex must match what `prompt.handle` emits and what `sources.tsx` parses.

    Three copies of one pattern is a drift risk; this pins the server's.
    """
    check = verify_citations(text, ["C1", "C2", "C12"])
    assert check.cited == expected


def test_the_dict_form_carries_what_the_ui_needs():
    check = verify_citations("a [C1] b [C9]", ["C1"])
    payload = check.as_dict()
    assert payload["fabricated"] == ["C9"]
    assert payload["n_cited"] == 1
    assert payload["n_available"] == 1
    assert payload["verified"] is False


def test_enforcement_does_not_edit_the_answer():
    """Flag, do not strip.

    A stripped answer looks identical whether or not the check ran, so stripping would make the
    guarantee unobservable — and it silently edits the model's words.
    """
    import inspect

    import src.verify as verify

    source = inspect.getsource(verify)
    assert ".replace(" not in source and "sub(" not in source, (
        "verify.py should only inspect the answer, never rewrite it"
    )
