"""A plain-English summary of the eval runs — generated once, cached on disk.

    uv run python -m src.eval.summarize          # regenerate if stale
    uv run python -m src.eval.summarize --check   # exit 1 if stale, spend nothing
    uv run python -m src.eval.summarize --force   # regenerate regardless

**This is an eval-time LLM call and it is not part of the answer path.** SPEC §5.2 allows
exactly one generation call per answer; eval-time calls are exempt but must be labelled
wherever they appear (see `src/llm.py`). Nothing here is reachable from `POST /ask` — this
module is imported by nothing in the answer path, runs from the command line, and writes a
file. The API never calls it and the frontend only reads what it wrote.

Three shapes here are deliberate.

**The summary is generated in Python, not in the frontend.** The Next app makes no provider
calls of its own and has no `openai` dependency — `grep -rn openai frontend/lib frontend/app`
is clean, which is what makes the one-call constraint structural rather than conventional
(D001). A summary generated server-side in the app would have quietly ended that. So the call
lives here and the page reads a file.

**The output is structured, not markdown.** `{headline, findings, caveat}` renders as plain
JSX with no markdown pipeline, and — the real reason — every field is short enough that each
figure in it can be checked against the run data. Free prose would have to be trusted.

Each finding is `{point, metrics}`: the sentence a chief executive reads, and the metric keys it
rests on. The prompt (v3) forbids metric names in the prose, so `metrics` is where the
vocabulary went — the page shows it in the technical section. It is also what keeps a plainly
worded claim checkable: a point quoting "62%" and naming no metric is flagged.

**Every figure is verified against the payload before the summary is cached.** Same rule as
`src/verify.py` applies to citations: a number that looks like a measurement but is not one is
worse than no number, because it reads as provenance. The check flags rather than strips —
unverified figures are named in the cache file and on the page, and the CLI exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import REPO_ROOT, settings
from src.eval.metrics import RESULTS_DIR
from src.llm import LLM, build_llm

SUMMARY_PATH = RESULTS_DIR / "summary.json"

# Bump on any change to the system prompt or the payload shape. It is part of the cache key,
# so a bump invalidates every cached summary — otherwise an edited prompt would keep serving
# text the current prompt would never have produced.
PROMPT_VERSION = "5"

# The metrics worth summarising, in the order they should be read. Mirrors
# `frontend/lib/evals/runs.ts:HEADLINE_METRICS` — the page and the summary must describe the
# same numbers or the toggle contradicts the prose above it.
HEADLINE_METRICS = (
    "normalized_recall@5",
    "normalized_recall@10",
    "normalized_recall@20",
    "recall@5",
    "recall@10",
    "recall@20",
    "mrr@10",
    "ndcg@10",
    "entity_coverage@10",
    "entity_coverage@20",
)

# What the numbers mean, handed to the model as given facts rather than left to it to infer.
#
# These are measured properties of this harness, documented in docs/EVALUATION.md §2-3. A model
# shown ten metrics and no context writes "MRR@10 of 0.977 shows excellent ranking", which is
# precisely the misreading the eval work exists to prevent. They are in the prompt so the
# summary carries the caveat instead of needing one.
HARNESS_FACTS = """\
Facts about this harness, established by measurement (docs/EVALUATION.md):

- `normalized_recall@k` (= hits / min(k, |relevant|)) is the honest recall figure. Raw
  `recall@k` has a per-question ceiling that varies 36-fold, because labelled relevant-file
  counts run from 1 to 36, so the raw mean is dominated by label cardinality rather than by
  retrieval quality. Prefer normalized recall whenever you cite a recall number.
- `mrr@10` and `ndcg@10` are saturated. Sitting at 0.92-1.0, they have almost no room to move,
  and they largely measure the entity filter rather than the ranking. They are not evidence of
  ranking quality.
- `entity_coverage@k` is the one metric with real range, and it maps to a failure a business
  audience recognises: "you asked about three companies and the answer covers one". At the
  retrieval budget it is pinned near 1.0 *by the per-company quota design*, so it is only
  informative when comparing quotas-on against quotas-off. It is not evidence that retrieval
  is perfect.
- Relevance is file-level: a retrieved chunk contributes its filing, and recall counts distinct
  filings. Unanswerable questions are excluded from these metrics (they have no relevant
  filings, so recall over them is undefined) and counted separately.
- The golden set is small. At this n, a delta of a few points is inside sampling noise and is
  directional at best. Never describe a small delta as an improvement or a regression without
  saying it is directional.
- **The `@N` in a metric name is how many filings the *measure* looks at, not how many the
  system retrieves.** Every run here retrieves a budget of 20, and `@10` scores only the first
  10 distinct filings within that. If you put this into words, get the distinction right — or
  leave the number of results out of the sentence, which is usually clearer anyway.
"""

SYSTEM = f"""\
You write the summary that sits at the top of a retrieval-evaluation page in a demo of a RAG
system over SEC filings.

**Write for a CEO or a CTO reading this cold.** They will not read the metric tables underneath
and should not need to. The engineers have their own section further down the page, and every
metric name belongs there rather than in your prose.

{HARNESS_FACTS}

Write the summary. Rules, in order of importance:

1. **Use only the numbers in the data given to you.** Copy a figure exactly as it appears, or —
   for a rate between 0 and 1 — express it as a whole-number percentage (`0.6167` becomes
   `62%`). Nothing else may be computed: no ratios, no differences you worked out yourself, no
   "roughly a third". Every numeral you write is checked against the input, and the summary is
   flagged on the page if one does not appear there. If you want to say something you have no
   figure for, say it without a figure.
2. **Never claim more than the metric supports.** Apply the facts above. A saturated metric is
   not a success. A metric pinned by design is not evidence of quality. A difference of a few
   points at this sample size means nothing — say so in those words.
3. **No metric names, no notation, no configuration strings in the prose.** Not
   `normalized_recall@10`, not `entity_coverage@20`, not `mrr`, not `nDCG`, not `@k`, not
   `hybrid+quotas+prefix+rerank`. Name the *thing being measured* in ordinary words instead, and
   put the metric keys in each finding's `metrics` field, which the page shows in its technical
   section.

   Bad: `normalized_recall@10 was 0.6167 with rerank and 0.6053 without.`
   Bad: `Coverage of named entities (entity_coverage@20) reached 1.0.`
   Good: `When a question names several companies, filings from every one of them make it into
   the answer's evidence — that held for every question in the set.`
   Good: `Of the filings we had labelled as relevant, the system surfaced about 62% of the ones
   it could reach.`
4. **Plain English throughout, including in the caveat.** These words do not appear in your
   reply. Where you would reach for one, write the plain version instead:

   - saturated -> "has almost no room left to improve"
   - normalized -> say nothing; just describe what was counted
   - directional -> "too small to read anything into"
   - configuration / config / ablation -> "setup", or name the change in words
   - corpus -> "the filings we hold"
   - chunk / passage -> "an extract from a filing"
   - embedding / vector / retrieval budget / `k` -> "the search", "how many results we look at"
   - `n` / sample size -> "the number of test questions"

   No marketing tone either: not "robust", not "significant", not "cutting-edge". If a technical
   term genuinely has to appear, define it in the same breath.
5. **Say what it means for the business.** A finding is worth writing if it changes what someone
   would do, ask, or worry about. "The comparison is inconclusive at this sample size" is a
   useful finding. Restating a table row is not.

Reply with JSON only, no code fence, exactly this shape:

{{"headline": "...",
  "findings": [{{"point": "...", "metrics": ["..."]}}],
  "caveat": "..."}}

- `headline`: 1-2 sentences. What the evaluation shows and why it matters, in the terms a chief
  executive cares about.
- `findings`: 2 to 4 items, most decision-relevant first.
  - `point`: the observation, in the plain language rules 3-5 describe.
  - `metrics`: the exact metric keys from the input that this point rests on, spelled as they
    appear in the data (for example `["normalized_recall@10"]`). This is where the technical
    vocabulary goes; the page renders it beside the numbers so an engineer can check the claim.
    Every point that quotes a figure must name at least one key here.
- `caveat`: 1-2 sentences, same plain language. What these numbers do *not* establish. This
  field is load-bearing: a reader who stops after the summary must not walk away
  over-confident.
"""


@dataclass(frozen=True)
class Finding:
    """One observation, and the metric keys it rests on.

    The split is the whole point of the v3 prompt: `point` is written for a chief executive and
    carries no metric names, while `metrics` carries the vocabulary that was taken out of it.
    The page renders `point` at the top and `metrics` in its technical section, so the claim is
    still traceable to a row of the table without the prose reading like one.
    """

    point: str
    metrics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"point": self.point, "metrics": list(self.metrics)}


@dataclass(frozen=True)
class Summary:
    """The generated text, plus everything needed to judge whether to trust it."""

    headline: str
    findings: tuple[Finding, ...]
    caveat: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "findings": [f.as_dict() for f in self.findings],
            "caveat": self.caveat,
        }

    @property
    def text(self) -> str:
        """Every generated word a reader sees, for the figure check.

        Deliberately **excludes** `metrics`: those are metric keys, and `entity_coverage@20`
        contains a `20` that is not a claim about anything. Including them would have the check
        wave through a `20` in the prose as verified.
        """
        return " ".join([self.headline, *(f.point for f in self.findings), self.caveat])


@dataclass(frozen=True)
class Verification:
    """Which figures in the summary were found in the run data, and what is untraceable."""

    figures: tuple[str, ...]
    unverified: tuple[str, ...] = ()
    untraced: tuple[str, ...] = ()
    """Findings that quote a figure but name no metric — the claim cannot be checked."""

    unknown_metrics: tuple[str, ...] = ()
    """Metric keys named by a finding that do not exist in the run data."""

    @property
    def ok(self) -> bool:
        return not (self.unverified or self.untraced or self.unknown_metrics)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified": self.ok,
            "n_figures": len(self.figures),
            "figures": list(self.figures),
            "unverified_figures": list(self.unverified),
            "untraced_findings": list(self.untraced),
            "unknown_metrics": list(self.unknown_metrics),
        }


@dataclass
class RunDoc:
    """One results file: the parsed document plus the filename it came from."""

    file: str
    doc: dict[str, Any] = field(default_factory=dict)


def load_runs(results_dir: Path | None = None) -> list[RunDoc]:
    """Every run file, newest first.

    `latest.json` is excluded: it is a copy of the newest run kept as a stable path for
    scripts, and counting it would summarise that run twice. Same exclusion as
    `frontend/lib/evals/runs.ts`, for the same reason.
    """
    directory = results_dir or RESULTS_DIR
    if not directory.is_dir():
        return []

    runs: list[RunDoc] = []
    for path in sorted(directory.glob("*.json")):
        if path.name in {"latest.json", SUMMARY_PATH.name}:
            continue
        try:
            runs.append(RunDoc(file=path.name, doc=json.loads(path.read_text("utf-8"))))
        except (json.JSONDecodeError, OSError):
            # A run killed mid-write should not stop the summary. The page skips it too.
            continue

    runs.sort(key=lambda r: str(r.doc.get("generated_at", "")), reverse=True)
    return runs


def newest_per_config(runs: list[RunDoc]) -> list[tuple[str, RunDoc, str]]:
    """`(config, newest run, first-seen timestamp)`, ordered by when the config was first run.

    Two runs of the same configuration differ only by retrieval nondeterminism, which is noise
    rather than a result — so only the newest of each is summarised. Ordering by first-seen
    makes the sequence read as the progression actually happened, matching the page's columns.
    """
    grouped: dict[str, list[RunDoc]] = {}
    for run in runs:
        grouped.setdefault(str(run.doc.get("config", "unknown")), []).append(run)

    columns = [
        (config, all_runs[0], str(all_runs[-1].doc.get("generated_at", "")))
        for config, all_runs in grouped.items()
    ]
    columns.sort(key=lambda c: c[2])
    return columns


def build_payload(runs: list[RunDoc]) -> dict[str, Any]:
    """The facts the summary may draw on. Nothing else is available to the model.

    Deliberately includes the derived counts — `n_configurations`, `n_flagged_questions` — even
    though they are trivially computable. The figure check is strict about numerals, so a count
    the model would otherwise have to derive has to be given to it, or an accurate summary gets
    flagged for stating one.
    """
    columns = newest_per_config(runs)
    configurations = []
    for config, run, first_seen in columns:
        doc = run.doc
        flagged = [
            {"id": q.get("id"), "suspect": q.get("suspect")}
            for q in doc.get("per_question", [])
            if q.get("suspect")
        ]
        configurations.append(
            {
                "config": config,
                "file": run.file,
                "first_run_at": first_seen,
                "latest_run_at": doc.get("generated_at"),
                "k": doc.get("k"),
                "n_questions_scored": doc.get("n_scored"),
                "n_unanswerable_excluded": doc.get("n_unanswerable"),
                "metrics": {
                    metric: doc.get("overall", {}).get(metric) for metric in HEADLINE_METRICS
                },
                "by_category": {
                    name: {
                        "n": values.get("n"),
                        "normalized_recall@10": values.get("normalized_recall@10"),
                        "entity_coverage@20": values.get("entity_coverage@20"),
                    }
                    for name, values in (doc.get("by_category") or {}).items()
                },
                "n_flagged_questions": len(flagged),
                "flagged_questions": flagged,
            }
        )

    payload: dict[str, Any] = {
        "n_result_files": len(runs),
        "n_configurations": len(configurations),
        "configurations": configurations,
    }

    if len(configurations) >= 2:
        baseline, latest = configurations[0], configurations[-1]
        payload["comparison"] = {
            "baseline_config": baseline["config"],
            "latest_config": latest["config"],
            "note": (
                "Deltas are latest minus baseline, where baseline is the configuration tried "
                "first. Run order is not a progression; no direction is implied."
            ),
            "deltas": {
                metric: (
                    round(latest["metrics"][metric] - baseline["metrics"][metric], 4)
                    if isinstance(latest["metrics"].get(metric), (int, float))
                    and isinstance(baseline["metrics"].get(metric), (int, float))
                    else None
                )
                for metric in HEADLINE_METRICS
            },
        }
    return payload


# --- the figure check --------------------------------------------------------------------

# `0.6167`, `22`, `1.000`, `80%`. Leading `-`/`+` is excluded so a delta's sign is not a figure
# in its own right; the magnitude is what gets checked.
FIGURE = re.compile(r"\d+(?:\.\d+)?%?")


def _numeral_forms(value: float) -> set[str]:
    """Every spelling of one payload number a summary might legitimately use.

    Includes the magnitude of a negative value, because `FIGURE` deliberately does not capture
    the sign: a summary writing "a -0.0114 difference" yields the token `0.0114`, and the first
    real run of this check flagged exactly that. Prose carries the direction in words as often
    as in punctuation, so the magnitude is what can be checked.
    """
    forms = set()
    for signed in {value, -value} if value < 0 else {value}:
        forms.add(str(signed))
        for places in (0, 1, 2, 3, 4):
            forms.add(f"{signed:.{places}f}")
        if isinstance(signed, float) and abs(signed) <= 1.0:
            # A rate is often quoted as a percentage. Allowed, but only for values that *are*
            # rates — this is what stops an arbitrary derived number passing as one.
            scaled = signed * 100
            for places in (0, 1, 2):
                forms.add(f"{scaled:.{places}f}")
                forms.add(f"{scaled:.{places}f}%")
    return {f.rstrip(".") for f in forms}


def allowed_figures(payload: Any) -> set[str]:
    """Numerals that appear in, or are a faithful rendering of, the run data."""
    allowed: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            allowed.update(_numeral_forms(node))
        elif isinstance(node, str):
            # Digit runs inside strings: dates in timestamps, `@10` in a metric name, the
            # `20` in a filename. A summary naming one of those is quoting, not computing.
            allowed.update(FIGURE.findall(node))
        elif isinstance(node, dict):
            for key, item in node.items():
                allowed.update(FIGURE.findall(str(key)))
                walk(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(payload)
    return allowed


def known_metric_keys(payload: Any) -> set[str]:
    """Every metric key a finding may legitimately cite.

    Read off the payload rather than hardcoded, so adding a metric to `HEADLINE_METRICS` or to
    the per-category block cannot leave this list behind and start rejecting valid citations.
    """
    keys = set(HEADLINE_METRICS)
    for configuration in payload.get("configurations", []) if isinstance(payload, dict) else []:
        keys.update(configuration.get("metrics", {}).keys())
        for values in configuration.get("by_category", {}).values():
            keys.update(values.keys())
        # Counts a finding might reasonably rest on without there being a metric for them.
        keys.update(
            {
                "n_questions_scored",
                "n_unanswerable_excluded",
                "n_flagged_questions",
                "flagged_questions",
                "by_category",
            }
        )
    if isinstance(payload, dict) and "comparison" in payload:
        keys.update(payload["comparison"].get("deltas", {}).keys())
    return keys


def verify_figures(summary: Summary, payload: Any) -> Verification:
    """Check the summary against the run data: figures, and whether claims stay traceable.

    Three things can go wrong, and each is **flagged, never stripped**. A summary with an
    unexplained number is still shown — with the number named — because silently removing it
    would leave prose that reads identically whether or not the check ran.

    1. **A figure that appears in no run.** The original reason this function exists.
    2. **A figure with no metric named.** The v3 prompt moved metric names out of the prose and
       into each finding's `metrics` field, which is what makes the summary readable. That trade
       only holds if the field is actually populated: a point quoting `62%` and citing nothing
       is a number a reader cannot check, which is the failure this whole page guards against.
    3. **A metric key that does not exist.** A citation to `normalized_recall@15` looks
       authoritative and resolves to nothing — the same class of failure as a fabricated `[C7]`.
    """
    allowed = allowed_figures(payload)
    known = known_metric_keys(payload)

    figures: list[str] = []
    unverified: list[str] = []
    for match in FIGURE.finditer(summary.text):
        figure = match.group(0)
        if figure in figures:
            continue
        figures.append(figure)
        if figure not in allowed and figure.rstrip("%") not in allowed:
            unverified.append(figure)

    untraced = [
        finding.point
        for finding in summary.findings
        if FIGURE.search(finding.point) and not finding.metrics
    ]
    unknown = [
        metric
        for finding in summary.findings
        for metric in finding.metrics
        if metric not in known
    ]

    return Verification(
        figures=tuple(figures),
        unverified=tuple(unverified),
        untraced=tuple(untraced),
        unknown_metrics=tuple(dict.fromkeys(unknown)),
    )


# --- generation and cache ---------------------------------------------------------------


def parse_summary(raw: str) -> Summary:
    """Parse the model's JSON reply, or fail loudly.

    No repair, no partial acceptance: a malformed reply means no cached summary and a non-zero
    exit. A half-parsed summary would be indistinguishable on the page from a good one.
    """
    text = raw.strip()
    if text.startswith("```"):
        # Tolerated because it is a formatting artefact, not a content problem.
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"summary reply was not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"summary reply was {type(parsed).__name__}, expected an object")

    headline = str(parsed.get("headline", "")).strip()
    caveat = str(parsed.get("caveat", "")).strip()

    findings: list[Finding] = []
    for raw_finding in parsed.get("findings") or []:
        # A bare string is accepted as a point with no metrics rather than rejected: the reply is
        # usable, and `verify_figures` already flags an untraceable point. Failing here would
        # throw away a good summary over a shape the page can render.
        if isinstance(raw_finding, str):
            point, metrics = raw_finding.strip(), []
        elif isinstance(raw_finding, dict):
            point = str(raw_finding.get("point", "")).strip()
            metrics = [str(m).strip() for m in (raw_finding.get("metrics") or []) if str(m).strip()]
        else:
            continue
        if point:
            findings.append(Finding(point=point, metrics=tuple(metrics)))

    missing = [
        name
        for name, value in (("headline", headline), ("findings", findings), ("caveat", caveat))
        if not value
    ]
    if missing:
        raise ValueError(f"summary reply is missing required field(s): {', '.join(missing)}")
    return Summary(headline=headline, findings=tuple(findings), caveat=caveat)


def generate(payload: dict[str, Any], llm: LLM) -> Summary:
    """One eval-time call. Not the answer path — see the module docstring."""
    return parse_summary(
        llm.complete(system=SYSTEM, user=json.dumps(payload, indent=2, sort_keys=True))
    )


def cache_is_current(cached: dict[str, Any] | None, runs: list[RunDoc], model: str) -> bool:
    """Whether a cached summary describes exactly the runs on disk, under this prompt.

    The key is the **set of run filenames**, not a content hash, so that the frontend can make
    the same judgement without reimplementing a hash in TypeScript. Run files are written once
    and never overwritten (`metrics.py` names each by timestamp), so the filename set is a
    sound identity for "the same runs".
    """
    if not cached:
        return False
    if cached.get("prompt_version") != PROMPT_VERSION:
        return False
    if cached.get("model") != model:
        return False
    return sorted(cached.get("run_files") or []) == sorted(r.file for r in runs)


def read_cache(path: Path | None = None) -> dict[str, Any] | None:
    target = path or SUMMARY_PATH
    try:
        return json.loads(target.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def build_document(
    runs: list[RunDoc], summary: Summary, verification: Verification, model: str
) -> dict[str, Any]:
    return {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_files": sorted(r.file for r in runs),
        "n_configurations": len({str(r.doc.get("config")) for r in runs}),
        "note": (
            "Generated by an eval-time LLM call from the metrics in run_files, and cached. "
            "This is NOT the answer path: SPEC §5.2's one-call-per-answer constraint covers "
            "POST /ask, and nothing in the answer path imports src/eval/summarize.py. Every "
            "numeral was checked against the run data; see verification."
        ),
        "summary": summary.as_dict(),
        "verification": verification.as_dict(),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.eval.summarize",
        description="Generate the cached plain-English summary of eval/results/.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the cached summary is missing or stale. Makes no API call.",
    )
    parser.add_argument(
        "--force", action="store_true", help="regenerate even if the cache is current"
    )
    args = parser.parse_args(argv)

    runs = load_runs()
    if not runs:
        print(f"no eval runs in {RESULTS_DIR} — run `make eval` first", flush=True)
        return 1

    model = settings().generation_model
    cached = read_cache()
    current = cache_is_current(cached, runs, model)

    if args.check:
        if current:
            print(f"summary is current ({len(runs)} run files)", flush=True)
            return 0
        print(
            "summary is stale or missing — run `make eval-summary`"
            if cached
            else "no cached summary — run `make eval-summary`",
            flush=True,
        )
        return 1

    if current and not args.force:
        print(
            f"summary is current ({len(runs)} run files); nothing to do. --force to regenerate",
            flush=True,
        )
        return 0

    payload = build_payload(runs)
    summary = generate(payload, build_llm())
    verification = verify_figures(summary, payload)
    document = build_document(runs, summary, verification, model)

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"\n{summary.headline}\n", flush=True)
    for finding in summary.findings:
        print(f"  - {finding.point}", flush=True)
        print(f"      rests on: {', '.join(finding.metrics) or 'NOTHING NAMED'}", flush=True)
    print(f"\n  caveat: {summary.caveat}", flush=True)
    print(
        f"\nwrote {SUMMARY_PATH.relative_to(REPO_ROOT)} "
        f"({len(verification.figures)} "
        f"figure{'' if len(verification.figures) == 1 else 's'} checked, model {model})",
        flush=True,
    )

    if not verification.ok:
        # Written anyway, and flagged on the page. A non-zero exit is what makes it impossible
        # to miss from the command line.
        problems = [
            ("FIGURES NOT FOUND IN THE RUN DATA", verification.unverified),
            ("METRIC KEYS THAT DO NOT EXIST", verification.unknown_metrics),
            ("FINDINGS QUOTING A FIGURE WITH NO METRIC NAMED", verification.untraced),
        ]
        for label, items in problems:
            if items:
                print(f"\n{label}: " + "; ".join(items), flush=True)
        print(
            "\nThe summary was cached and is flagged on the page. Re-run to regenerate.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
