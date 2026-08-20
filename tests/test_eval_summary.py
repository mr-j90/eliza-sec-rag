"""The cached eval summary, and the figure check that decides whether to trust it.

The summary is prose a reader will believe. The one thing that must not happen is a number in
it that no run produced — the same failure `tests/test_verify.py` guards for citations, in a
place where nothing else would catch it: a fabricated `normalized_recall@10` reads exactly like
a real one, and the tables are behind a toggle.

Free tier: no Qdrant, no key. The provider is a stub, which is also the point — the real call
is one function away from these tests and everything around it is pure.
"""

from __future__ import annotations

import json

import pytest

from src.eval.summarize import (
    PROMPT_VERSION,
    Finding,
    RunDoc,
    Summary,
    allowed_figures,
    build_payload,
    cache_is_current,
    generate,
    known_metric_keys,
    load_runs,
    newest_per_config,
    parse_summary,
    verify_figures,
)


class StubLLM:
    """Returns a fixed reply and records the prompts. No network, no key."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


def run_doc(
    file: str,
    config: str,
    generated_at: str,
    *,
    normalized_recall_10: float = 0.6167,
    suspects: int = 0,
) -> RunDoc:
    return RunDoc(
        file=file,
        doc={
            "config": config,
            "k": 20,
            "generated_at": generated_at,
            "n_scored": 22,
            "n_unanswerable": 3,
            "overall": {
                "normalized_recall@5": 0.6591,
                "normalized_recall@10": normalized_recall_10,
                "normalized_recall@20": 0.7566,
                "recall@5": 0.4511,
                "recall@10": 0.5131,
                "recall@20": 0.7267,
                "mrr@10": 1.0,
                "ndcg@10": 0.9187,
                "entity_coverage@10": 0.7976,
                "entity_coverage@20": 1.0,
            },
            "by_category": {
                "cross_company": {"n": 8, "normalized_recall@10": 0.4875, "entity_coverage@20": 1.0}
            },
            "per_question": [
                {"id": f"q-{i}", "category": "single_company", "suspect": "retrieval missed"}
                for i in range(suspects)
            ],
        },
    )


GOOD_REPLY = json.dumps(
    {
        "headline": "The system reaches every company a question names.",
        "findings": [
            {
                "point": "Across the 22 questions scored, the system surfaced about 62% of the "
                "filings it could have reached.",
                "metrics": ["normalized_recall@10"],
            },
            {
                "point": "Every company named in a question had filings in the evidence.",
                "metrics": ["entity_coverage@20"],
            },
        ],
        "caveat": "The sample is small, so small differences mean nothing.",
    }
)


def check_prose(text: str, payload: dict):
    """The figure check over one sentence, with the traceability rules held constant.

    `verify_figures` takes a whole `Summary` because it also checks that findings name the
    metrics they rest on. The tests below are about *figures*, so the finding here is
    deliberately figure-free and correctly cited; the untraced and unknown-metric rules have
    their own tests.
    """
    return verify_figures(
        Summary(
            headline=text,
            findings=(Finding(point="A point.", metrics=("mrr@10",)),),
            caveat="A caveat.",
        ),
        payload,
    )


# --- the figure check ---------------------------------------------------------------------


def test_a_fabricated_figure_is_caught():
    """The test this module exists for. A plausible metric value that no run produced."""
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    check = check_prose("normalized_recall@10 improved to 0.8412 from 0.6167.", payload)

    assert check.unverified == ("0.8412",)
    assert not check.ok
    # The real figure is still recognised, so the flag names only what is wrong.
    assert "0.6167" in check.figures


def test_figures_present_in_the_run_data_verify():
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    check = check_prose(
        "normalized_recall@10 is 0.6167 over 22 questions, with 3 excluded as unanswerable.",
        payload,
    )

    assert check.ok
    assert check.unverified == ()


def test_a_rate_may_be_quoted_as_a_percentage():
    """`0.6167` written as `61.7%` is a rendering, not a new measurement."""
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    assert check_prose("Recall sits at 61.7% of what the labels allow.", payload).ok


def test_a_derived_number_is_not_excused_by_the_percentage_rule():
    """Scaling is allowed only for values that are themselves rates in the payload."""
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    # 22 questions * 100 is not a figure, and neither is an invented count.
    assert check_prose("Across 47 questions", payload).unverified == ("47",)


def test_trailing_zeros_and_rounding_are_accepted():
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    check = check_prose("entity_coverage@20 is 1.000 and mrr@10 is 1.0.", payload)
    assert check.ok


def test_derived_counts_are_in_the_payload_so_stating_them_is_not_flagged():
    """A summary saying 'two configurations' must not be flagged for it.

    The check is strict about numerals, so any count the summary can reasonably state has to be
    given to the model rather than derived by it.
    """
    runs = [
        run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00"),
        run_doc("b.json", "hybrid+rerank", "2026-08-20T19:10:00+00:00"),
    ]
    payload = build_payload(runs)

    assert payload["n_configurations"] == 2
    assert check_prose("2 configurations were compared over 2 result files.", payload).ok


def test_allowed_figures_reads_dates_out_of_timestamps():
    """A summary naming the run date is quoting the payload, not computing."""
    allowed = allowed_figures({"generated_at": "2026-08-20T19:18:55+00:00"})

    assert {"2026", "08", "20"} <= allowed


# --- reply parsing ------------------------------------------------------------------------


def test_a_well_formed_reply_parses():
    summary = parse_summary(GOOD_REPLY)

    assert summary.headline.startswith("The system reaches")
    assert len(summary.findings) == 2
    assert summary.findings[0].metrics == ("normalized_recall@10",)
    assert summary.caveat


def test_a_fenced_reply_parses():
    """A code fence is a formatting artefact, not a content problem."""
    assert parse_summary(f"```json\n{GOOD_REPLY}\n```").findings


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        "[]",
        json.dumps({"headline": "x", "findings": [], "caveat": "y"}),
        json.dumps({"headline": "", "findings": ["a"], "caveat": "y"}),
        json.dumps({"findings": ["a"], "caveat": "y"}),
    ],
)
def test_an_unusable_reply_raises_rather_than_half_parsing(reply: str):
    """No repair and no partial acceptance: a half-summary looks identical to a good one."""
    with pytest.raises(ValueError):
        parse_summary(reply)


def test_generate_makes_exactly_one_call_and_is_handed_only_the_payload():
    """The summary cannot cite a filing, a chunk, or anything else it was not given."""
    stub = StubLLM(GOOD_REPLY)
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])

    generate(payload, stub)

    assert len(stub.calls) == 1
    system, user = stub.calls[0]
    assert json.loads(user) == payload
    # The metric caveats are given as facts rather than left to the model to infer.
    assert "saturated" in system and "quota design" in system


# --- payload shape ------------------------------------------------------------------------


def test_only_the_newest_run_of_each_configuration_is_summarised():
    """Two runs of one config differ by retrieval nondeterminism — noise, not a result."""
    runs = [
        run_doc("new.json", "hybrid", "2026-08-20T19:10:00+00:00", normalized_recall_10=0.7),
        run_doc("old.json", "hybrid", "2026-08-20T19:00:00+00:00", normalized_recall_10=0.6),
    ]

    columns = newest_per_config(runs)
    assert [c[1].file for c in columns] == ["new.json"]

    payload = build_payload(runs)
    assert payload["n_result_files"] == 2
    assert payload["n_configurations"] == 1
    assert payload["configurations"][0]["metrics"]["normalized_recall@10"] == 0.7


def test_configurations_are_ordered_by_when_each_was_first_tried():
    """So the comparison reads left-to-right as the progression happened."""
    runs = [
        run_doc("c.json", "second", "2026-08-20T19:20:00+00:00"),
        run_doc("b.json", "first", "2026-08-20T19:10:00+00:00"),
        run_doc("a.json", "first", "2026-08-20T19:00:00+00:00"),
    ]

    assert [c["config"] for c in build_payload(runs)["configurations"]] == ["first", "second"]


def test_a_single_configuration_gets_no_comparison_block():
    """Nothing to compare against — better absent than a column of zero deltas."""
    payload = build_payload([run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")])
    assert "comparison" not in payload


def test_deltas_subtract_baseline_from_latest_and_are_rounded_to_the_reported_precision():
    """Rounded to 4dp because that is how the numbers are reported — an unrounded
    0.08330000000000004 would be flagged as an unverifiable figure by the check above."""
    runs = [
        run_doc("a.json", "fusion-only", "2026-08-20T19:00:00+00:00", normalized_recall_10=0.5),
        run_doc("b.json", "rerank", "2026-08-20T19:10:00+00:00", normalized_recall_10=0.5833),
    ]

    comparison = build_payload(runs)["comparison"]

    assert comparison["baseline_config"] == "fusion-only"
    assert comparison["latest_config"] == "rerank"
    assert comparison["deltas"]["normalized_recall@10"] == 0.0833
    assert check_prose("normalized_recall@10 moved by 0.0833.", build_payload(runs)).ok


def test_flagged_questions_reach_the_payload_with_their_reason():
    payload = build_payload(
        [run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00", suspects=2)]
    )

    config = payload["configurations"][0]
    assert config["n_flagged_questions"] == 2
    assert config["flagged_questions"][0]["suspect"] == "retrieval missed"


# --- the cache ----------------------------------------------------------------------------


def cache_for(runs: list[RunDoc], *, model: str = "gpt-4.1") -> dict:
    return {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "run_files": sorted(r.file for r in runs),
    }


def test_a_cache_covering_exactly_these_runs_is_current():
    runs = [run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")]
    assert cache_is_current(cache_for(runs), runs, "gpt-4.1")


def test_a_new_run_makes_the_cache_stale():
    """The reason the page can say 'new runs since this was written' rather than lying."""
    runs = [run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")]
    cached = cache_for(runs)

    runs.append(run_doc("b.json", "hybrid+rerank", "2026-08-20T19:10:00+00:00"))
    assert not cache_is_current(cached, runs, "gpt-4.1")


def test_a_prompt_change_invalidates_the_cache():
    """Otherwise an edited prompt keeps serving text it would never have produced."""
    runs = [run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")]
    stale = {**cache_for(runs), "prompt_version": "0"}

    assert not cache_is_current(stale, runs, "gpt-4.1")


def test_a_different_model_invalidates_the_cache():
    runs = [run_doc("a.json", "hybrid", "2026-08-20T19:00:00+00:00")]
    assert not cache_is_current(cache_for(runs), runs, "gpt-4o")


def test_a_missing_cache_is_not_current():
    assert not cache_is_current(None, [run_doc("a.json", "h", "2026-08-20T19:00:00+00:00")], "m")


# --- reading the directory ----------------------------------------------------------------


def test_load_runs_skips_latest_json_so_the_newest_run_is_not_counted_twice(tmp_path):
    document = run_doc("x.json", "hybrid", "2026-08-20T19:00:00+00:00").doc
    (tmp_path / "20260820T190000--hybrid.json").write_text(json.dumps(document))
    (tmp_path / "latest.json").write_text(json.dumps(document))
    (tmp_path / "summary.json").write_text(json.dumps({"summary": {}}))

    assert [r.file for r in load_runs(tmp_path)] == ["20260820T190000--hybrid.json"]


def test_load_runs_skips_a_truncated_file_rather_than_failing(tmp_path):
    """A run killed mid-write must not take the summary — or the page — down with it."""
    (tmp_path / "good.json").write_text(
        json.dumps(run_doc("good.json", "hybrid", "2026-08-20T19:00:00+00:00").doc)
    )
    (tmp_path / "truncated.json").write_text('{"config": "hybrid", "overall"')

    assert [r.file for r in load_runs(tmp_path)] == ["good.json"]


def test_load_runs_returns_nothing_when_the_directory_is_absent(tmp_path):
    assert load_runs(tmp_path / "nope") == []


def test_load_runs_orders_newest_first(tmp_path):
    for name, stamp in (("a.json", "19:00:00"), ("b.json", "19:20:00"), ("c.json", "19:10:00")):
        (tmp_path / name).write_text(
            json.dumps(run_doc(name, name, f"2026-08-20T{stamp}+00:00").doc)
        )

    assert [r.file for r in load_runs(tmp_path)] == ["b.json", "c.json", "a.json"]


def test_summary_text_covers_every_field_a_reader_sees():
    """The figure check runs over `text`; a field left out of it would be unchecked."""
    summary = Summary(
        headline="a 1.0",
        findings=(Finding("b 2.0", ()), Finding("c 3.0", ())),
        caveat="d 4.0",
    )

    for figure in ("1.0", "2.0", "3.0", "4.0"):
        assert figure in summary.text


def test_summary_text_excludes_the_metric_keys():
    """`entity_coverage@20` holds a `20` that is a metric name, not a claim.

    If the keys were part of the checked text, citing that metric would silently license a bare
    `20` in the prose — a figure nobody measured, waved through by the check meant to catch it.
    """
    summary = Summary(
        headline="No figures here.",
        findings=(Finding("None here either.", ("entity_coverage@20",)),),
        caveat="Nor here.",
    )

    assert "20" not in summary.text


def test_a_negative_delta_quoted_as_a_magnitude_verifies():
    """Found by the first real run of this check, not by inspection.

    `FIGURE` does not capture the sign, so "a -0.0114 difference" yields the token `0.0114`,
    and the payload holds -0.0114. Prose carries direction in words as often as in punctuation,
    so the magnitude is the checkable part.
    """
    runs = [
        run_doc("a.json", "with-rerank", "2026-08-20T19:00:00+00:00", normalized_recall_10=0.6167),
        run_doc("b.json", "no-rerank", "2026-08-20T19:10:00+00:00", normalized_recall_10=0.6053),
    ]
    payload = build_payload(runs)

    assert payload["comparison"]["deltas"]["normalized_recall@10"] == -0.0114
    assert check_prose("normalized_recall@10 fell by 0.0114.", payload).ok
    assert check_prose("a -0.0114 difference in normalized_recall@10", payload).ok


# --- traceability, which is what pays for the plain language -------------------------------


def payload_for_two_configs() -> dict:
    return build_payload(
        [
            run_doc("a.json", "with-rerank", "2026-08-20T19:00:00+00:00"),
            run_doc("b.json", "no-rerank", "2026-08-20T19:10:00+00:00"),
        ]
    )


def test_a_plainly_worded_finding_that_names_its_metric_verifies():
    """The shape the v3 prompt is for: no metric name in the prose, the key alongside it."""
    summary = Summary(
        headline="The system reaches every company a question names.",
        findings=(
            Finding(
                point="It surfaced about 62% of the filings it could have reached.",
                metrics=("normalized_recall@10",),
            ),
        ),
        caveat="The sample is small.",
    )

    check = verify_figures(summary, payload_for_two_configs())

    assert check.ok
    assert check.untraced == ()
    assert check.unknown_metrics == ()


def test_a_finding_that_quotes_a_figure_and_names_nothing_is_flagged():
    """The cost of taking metric names out of the prose, and the guard against it.

    Plain language is only an improvement while the claim stays checkable. A point saying "62%"
    with an empty `metrics` list is a number a reader cannot trace to any row of the table —
    exactly what moving the vocabulary into a separate field was supposed to preserve.
    """
    summary = Summary(
        headline="A headline with no figures.",
        findings=(Finding(point="It surfaced about 62% of what it could reach.", metrics=()),),
        caveat="A caveat.",
    )

    check = verify_figures(summary, payload_for_two_configs())

    assert not check.ok
    assert check.untraced == ("It surfaced about 62% of what it could reach.",)
    # The figure itself is fine — 0.6167 scaled. It is the missing citation that fails.
    assert check.unverified == ()


def test_a_finding_with_no_figure_needs_no_metric():
    """"The comparison is inconclusive at this sample size" is a useful finding and cites
    nothing. Requiring a metric of it would push the model to attach a spurious one."""
    summary = Summary(
        headline="A headline.",
        findings=(Finding(point="The comparison is inconclusive.", metrics=()),),
        caveat="A caveat.",
    )

    assert verify_figures(summary, payload_for_two_configs()).ok


def test_a_metric_key_that_does_not_exist_is_flagged():
    """A citation to a plausible-but-absent metric is the `[C7]` failure in another costume."""
    summary = Summary(
        headline="A headline.",
        findings=(Finding(point="Recall was about 62%.", metrics=("normalized_recall@15",)),),
        caveat="A caveat.",
    )

    check = verify_figures(summary, payload_for_two_configs())

    assert check.unknown_metrics == ("normalized_recall@15",)
    assert not check.ok


def test_known_metric_keys_covers_headline_category_and_delta_keys():
    """Read off the payload, so adding a metric cannot leave this list behind."""
    keys = known_metric_keys(payload_for_two_configs())

    assert "normalized_recall@10" in keys          # headline
    assert "entity_coverage@20" in keys            # headline
    assert "n_flagged_questions" in keys           # a count a finding may rest on
    assert "normalized_recall@15" not in keys


def test_a_bare_string_finding_is_accepted_and_then_flagged_if_it_quotes_a_figure():
    """Lenient parse, strict check.

    An older-shaped reply is still renderable, so rejecting it outright would throw away a good
    summary over a shape mismatch. It is the *claim* that has to be traceable, and that is
    caught downstream where it can be shown on the page instead of aborting the run.
    """
    summary = parse_summary(
        json.dumps(
            {
                "headline": "A headline.",
                "findings": ["It surfaced about 62% of what it could reach."],
                "caveat": "A caveat.",
            }
        )
    )

    assert summary.findings[0].metrics == ()
    assert verify_figures(summary, payload_for_two_configs()).untraced == (
        "It surfaced about 62% of what it could reach.",
    )
