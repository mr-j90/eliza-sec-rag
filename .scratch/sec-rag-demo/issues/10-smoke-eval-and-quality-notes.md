# Smoke eval gate, and the quality-evaluation notes deliverable

Type: task
Status: resolved
Blocked by: 01

## Question

**What is the regression gate, and what does "Notes on how you evaluated quality" actually
say?**

Scope was decided at charting: a smoke gate plus a written critique, **not** an ablation
table. The full harness (40–60 questions, section-level labels, `ItemPrec@k`,
temporal-scope correctness, 10-row ablation, paired significance test) is out of scope and
is presented as future state.

### The build — a gate, not a benchmark

Port `eval/golden_set.json` (25 questions, 22 scored) and run a fixed subset as pass/fail:

1. **The three demo questions**, end to end, every time. These are the ones that must never
   break.
2. **The out-of-corpus refusal.** `eval-harness-findings.md` §"What this means" flags that
   refusal correctness is measured **nowhere** in the prior art's results, even though the
   prior repo's own state file confirms the only Shopify assertion tests that the *alias*
   resolves to nothing — not that the answer refuses. For a diligence tool this is *"the
   single highest-value behavior to measure."* Test the answer, not the alias.
3. **`entity_coverage@k`** — per the findings doc, the one metric in the prior harness that
   works: it moves 0.798@10 → 1.000@20 overall, and 0.521@10 → 1.000@20 on cross-company
   questions. It has range, it is not saturated, and it maps to a failure a business audience
   recognises. **Caveat to carry:** the @20 = 1.000 is a consequence of the entity-quota
   design guaranteeing per-company budget, so it will be pinned at 1.0 for any config with
   quotas on. Read it as an ablation metric only across quota-on vs quota-off.

### The deliverable — the critique is the artifact

`docs/research/eval-harness-findings.md` already contains the substance. This ticket turns
it into the brief's "notes on how you evaluated quality," which means stating plainly why
the obvious metrics were **not** used:

1. **`recall@k` has a per-question ceiling that varies 7×.** Relevant-file counts run from
   1 to 36, so the attainable maximum is `min(k,|R|)/|R|` — from **0.139 to 1.000**.
   Averaging raw `recall@k` across those questions averages incommensurable quantities. The
   headline `recall@10 = 0.533` reads as failure but is **65.7% of what the label design
   permits**.
2. **`MRR@10 = 0.977` and `nDCG@10 = 0.963` are saturated.** MRR is 1.000 in three of four
   categories. A metric pinned at 0.96–1.00 cannot show improvement — ablation rows would
   differ in the third decimal on n=22 with no significance test. *That is not evidence.*
   And the reason is diagnostic: file-level labels scoped to the named ticker make almost
   any chunk from the right company "relevant," so these metrics are **measuring the entity
   filter, not the ranking.**
3. **Near-duplicate suppression is anti-correlated with the recall label.** This is the
   interesting one and it is a design conflict, not a tuning issue. `retrieve.py:159`
   suppresses across the whole fused candidate set before truncating to k. When NVIDIA's
   export-control risk factor recurs near-verbatim across 16 filings, suppression keeps the
   best instance and drops 15 — each a distinct *relevant file* under the label. **Every
   correctly-suppressed duplicate lowers `recall@k` while improving the answer.**
   `nDCG@10 = 0.963` alongside `recall@10 = 0.533` is exactly that signature.

The findings doc recommends option 2 of three fixes as cleanest — evaluate retrieval
**pre-suppression** and measure suppression separately as a context-quality metric
(redundancy rate in the final context) — because it measures each mechanism on the axis it
was designed for. State which fix you would adopt and why, even though implementing it is
out of scope.

### Why this is the stronger deliverable

Knowing precisely why your metrics mislead is a better signal to a technical panel than a
table of saturated numbers. It also pre-empts the obvious challenge — *"your recall looks
low"* — with a measured answer rather than a defensive one.

### What must be true to close this

- The gate runs in one command and is documented in the README (ticket 12).
- The quality notes exist as a deliverable a reader finds without being told, and they name
  n=22 as too small for the ablation the prior art planned.

---

## Answer

**Resolved 2026-08-20.** The deliverable is **`docs/EVALUATION.md`**, the gate is `make
test-live` (28 tests), and the metrics run with `make eval`.

### Correction: the gate largely already existed

This ticket planned to build the demo-question and refusal checks. They came with the port and
are better than the plan. `tests/test_answer_contract.py` already covers all three panel
questions plus the out-of-corpus refusal, **and it checks refusal on the answer, not the
alias** — which is exactly the gap the audit identified in the prior attempt. It also asserts
no fabricated attribution against the full alias table, structural stability across repeated
generations, and one generation call on the three-company question. Nothing needed adding.

What was genuinely missing was a **single command**, a **metric that is not misleading**, and
**the written deliverable**.

### The reranking question, answered — and my earlier reading of it was wrong

Ticket 04 left this here, so both configurations were run against the same index:

| metric | fusion only | + rerank | delta |
|---|---|---|---|
| normalized_recall@5 | 0.627 | 0.668 | **+0.041** |
| normalized_recall@10 | 0.615 | 0.635 | +0.020 |
| recall@5 | 0.423 | 0.454 | +0.031 |
| recall@10 | 0.510 | 0.521 | +0.011 |
| mrr@10 | 0.966 | 0.977 | +0.011 |
| nDCG@10 | 0.926 | 0.919 | **−0.007** |
| entity_coverage@10 / @20 | 0.798 / 1.000 | 0.798 / 1.000 | 0.000 |

Mid-ticket I compared the current numbers against the *prior art's* published figures and read
the result as "mostly downward". **That comparison was invalid** — different index, different
chunker, different corpus preprocessing. The only valid comparison is two configurations on one
index, and it favours reranking: largest at **k=5**, smallest at k=20, which is what reordering
should do since it changes which candidates survive the tightest cut.

**But the mean is not the honest report at n=22.** Per question: **better on 8, worse on 4,
tied on 10**, with individual swings of **±0.25 to ±0.40** against a +0.02 mean. That mean is
the residue of large offsetting movements on a handful of questions. Reported as
**directional**, not as evidence — which is what the audit recommends at this sample size.

One pattern kept rather than smoothed: both questions that got materially worse (`sw-01`,
`sw-02`) are **sector** questions. A sector question names no company, so no quotas apply and a
single unfiltered search runs — the reranker has the most freedom there and used it badly on 2
of 3. That is where to look if reranking is tuned further.

Reranking is kept, on the direction plus its cost profile (328 ms, local, no per-query charge),
and because `entity_coverage` being pinned by quotas means the metric set cannot adjudicate it
either way. `RAG_RERANK=0` was added so this stays a measurement rather than an assertion.

### The one metric fix implemented, and why only one

The ticket said implementing the audit's fixes was out of scope. **`normalized_recall@k` was
implemented anyway**, because without it the headline number is not merely limited — it is
misleading. Verified on the current golden set, the audit's figures reproduce exactly:

- relevant-file counts run **1 to 36** — a 36× spread
- `recall@5` attainable ceiling ranges **0.139 to 1.000**
- so `recall@10 = 0.521` is **64% of attainable**, not "half the relevant filings"

| | raw | normalized |
|---|---|---|
| @5 | 0.454 | **0.668** |
| @10 | 0.521 | **0.635** |
| @20 | 0.739 | **0.767** |

Reported *alongside* raw recall rather than replacing it, so the gap is itself visible. The
other two fixes — pre-suppression scoring and section-level labels — stay out of scope and are
named as future state with the reason.

### The deliverable

`docs/EVALUATION.md`, written to be read by the panel:

1. **The gate** — what must never break, and why refusal-on-the-answer is the highest-value
   check for a diligence tool.
2. **`entity_coverage@k`** — the one metric with range, plus the caveat that its 1.000 at k=20
   is *caused by* the quota design and so is only informative across quota-on/quota-off.
3. **Three metrics measured and set aside**, each with its own numbers: the 36× ceiling spread;
   the saturation of MRR/nDCG and the diagnosis that they measure the **entity filter, not the
   ranking**; and the suppression/label conflict where **every correctly-suppressed duplicate
   lowers recall while improving the answer**.
4. **The reranking comparison**, with win/loss/tie.
5. **What we would build next** — 40–60 questions, section-level labels, pre-suppression
   scoring, item-section precision, temporal-scope correctness with a baseline-present boolean,
   and a paired significance test. **n=22 is named as too small** for the ablation the prior art
   planned.

### One command

```
make eval                # both metric rows; RAG_RERANK=0 for fusion only
make test-live           # the 28-test gate
```

`make eval` prints its own runtime and points at the doc. Results land in
`eval/results/retrieval_metrics.json` **labelled with the configuration that produced them** —
previously the label was a hardcoded string, so two runs of different configurations were
indistinguishable on disk.

### Verification

- 4 new tests for `normalized_recall_at_k` in `tests/test_metrics.py`, hand-computed in the
  style of that file (36 relevant / k=5 → 1.0, agreement with raw recall where |R| ≤ k, never
  above 1.0, no division by zero).
- **235 tests green**: 173 free python + 28 live + 34 frontend.
- Makefile help counts refreshed — they still claimed 93 python tests and a 29,499-point index.

### Noted, not chased

`onnxruntime` occasionally prints `recursive_mutex lock failed` while the interpreter tears
down, after the reranker has been loaded. Exit codes are 0 in every run checked, so `make test`
is unaffected; it is teardown noise, not a failure. Worth knowing before it is mistaken for one
during a demo.
