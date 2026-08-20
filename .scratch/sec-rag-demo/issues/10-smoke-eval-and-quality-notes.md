# Smoke eval gate, and the quality-evaluation notes deliverable

Type: task
Status: open
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
