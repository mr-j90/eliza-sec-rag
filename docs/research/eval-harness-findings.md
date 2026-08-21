# Eval harness findings — why the prior art's retrieval metrics can't power an ablation

**Date:** 2026-08-19
**Scope:** empirical audit of `/Users/jordan/Developer/eliza/rag/` (the earlier attempt at this
assessment), specifically its golden set and retrieval metrics. Companion to
[`sec-rag-architecture.md`](./sec-rag-architecture.md).

All numbers below are recomputed from the prior art's own committed artifacts
(`eval/golden_set.json`, `eval/results/retrieval_metrics.json`) — not re-run, not estimated.

---

## Summary

The prior repo states that the eval harness is "the differentiator… what converts assertions into
evidence" (`rag/SPEC.md` §7) and plans a five-row ablation table (§7.3) to prove hybrid retrieval
beats the baseline. **That table was never produced** — `eval/results/` contains exactly one file,
scoring exactly one configuration (`"config": "hybrid+quotas+prefix"`).

More importantly: if the ablation *were* run against this harness as built, it would most likely
report noise. Three independent defects:

1. `recall@k` has a per-question mathematical ceiling that varies from 0.139 to 1.000, so the
   average is dominated by label cardinality rather than retrieval quality.
2. `MRR@10` (0.977) and `nDCG@10` (0.963) are saturated at near-ceiling and cannot discriminate
   between configurations.
3. The retriever's near-duplicate suppression is **anti-correlated with the recall label** — the
   system is penalized by its own metric for a deliberate design choice.

Defect 3 is the interesting one and is the reason recall looks bad while nDCG looks excellent.

---

## 1. `recall@k` ceilings vary by 7x across questions

Labels are file-level: a filing is relevant if it contains the question's probe term and belongs to
a ticker the question names (`eval/build_golden_set.py` docstring). The number of relevant files per
question therefore ranges from **1 to 36**:

```
relevant-file counts across the 22 scored questions:
[1, 1, 1, 1, 1, 2, 2, 2, 4, 4, 5, 6, 12, 12, 13, 16, 16, 16, 16, 32, 32, 36]
```

Since `recall@k = hits / |R|` and you can retrieve at most `k` distinct files, the attainable
maximum is `min(k, |R|) / |R|`. Per question:

| id | category | #rel | ceil@5 | act@5 | ceil@10 | act@10 | ceil@20 | act@20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| sc-01 | single_company | 16 | 0.312 | 0.125 | 0.625 | 0.312 | 1.000 | 0.688 |
| sc-02 | single_company | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| sc-03 | single_company | 16 | 0.312 | 0.250 | 0.625 | 0.375 | 1.000 | 0.562 |
| sc-04 | single_company | 16 | 0.312 | 0.125 | 0.625 | 0.188 | 1.000 | 0.562 |
| sc-05 | single_company | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| sc-06 | single_company | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| cc-01 | cross_company | 36 | **0.139** | 0.083 | 0.278 | 0.222 | 0.556 | 0.306 |
| cc-02 | cross_company | 5 | 1.000 | 0.200 | 1.000 | 0.200 | 1.000 | 1.000 |
| cc-03 | cross_company | 32 | 0.156 | 0.125 | 0.312 | 0.250 | 0.625 | 0.469 |
| cc-04 | cross_company | 16 | 0.312 | 0.125 | 0.625 | 0.188 | 1.000 | 0.250 |
| cc-05 | cross_company | 2 | 1.000 | 0.500 | 1.000 | 0.500 | 1.000 | 1.000 |
| cc-06 | cross_company | 2 | 1.000 | 0.500 | 1.000 | 0.500 | 1.000 | 1.000 |
| cc-07 | cross_company | 13 | 0.385 | 0.308 | 0.769 | 0.462 | 1.000 | 0.538 |
| cc-08 | cross_company | 2 | 1.000 | 0.500 | 1.000 | 0.500 | 1.000 | 1.000 |
| tm-01 | temporal | 4 | 1.000 | 0.750 | 1.000 | 0.750 | 1.000 | 1.000 |
| tm-02 | temporal | 12 | 0.417 | 0.250 | 0.833 | 0.583 | 1.000 | 0.917 |
| tm-03 | temporal | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| tm-04 | temporal | 4 | 1.000 | 0.500 | 1.000 | 0.500 | 1.000 | 0.750 |
| tm-05 | temporal | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| sw-01 | sector | 32 | 0.156 | 0.094 | 0.312 | 0.188 | 0.625 | 0.219 |
| sw-02 | sector | 12 | 0.417 | 0.417 | 0.833 | 0.500 | 1.000 | 0.667 |
| sw-03 | sector | 6 | 0.833 | 0.333 | 1.000 | 0.500 | 1.000 | 0.667 |

Normalizing against the attainable maximum changes the story materially:

| metric | reported | mean attainable ceiling | % of attainable achieved |
|---|---:|---:|---:|
| recall@5 | 0.463 | 0.671 | **69.0%** |
| recall@10 | 0.533 | 0.811 | **65.7%** |
| recall@20 | 0.754 | 0.946 | **79.8%** |

The headline `recall@10 = 0.533` reads as a failing system. It is closer to 66% of what the label
design permits. Conversely, `recall@20 = 0.754` looks like the best result but is the *weakest*
relative performance-per-headroom of the three once you account for ceilings rising to 0.946.

**Consequence for the ablation:** on `cc-01`, no configuration change can move `recall@5` by more
than 0.139 in absolute terms. Averaging that alongside `sc-02`, where the same change has 1.000 of
range, means the ablation's per-row deltas are a weighted average of incommensurable quantities.

**Fix:** report normalized recall (`hits / min(k, |R|)`) alongside raw recall, or switch to
R-precision, or cap `|R|` at label time. Do not average raw `recall@k` over questions whose `|R|`
spans 1–36.

---

## 2. MRR and nDCG are saturated

From `retrieval_metrics.json`:

| category | n | MRR@10 | nDCG@10 |
|---|---:|---:|---:|
| single_company | 6 | 1.000 | 1.000 |
| cross_company | 8 | 1.000 | 0.989 |
| sector | 3 | 1.000 | 0.954 |
| temporal | 5 | 0.900 | 0.883 |
| **overall** | 22 | **0.977** | **0.963** |

`MRR@10 = 1.000` in three of four categories means the rank-1 result is relevant essentially always.
That is expected — and uninformative — because a file-level label restricted to the named ticker
makes almost any chunk from the right company "relevant." These metrics are measuring the entity
filter, not the ranking.

A metric pinned at 0.96–1.00 has no room to show improvement. Rows 1–5 of the planned ablation
would differ in the third decimal place, on n=22, with no significance test. That is not evidence.

**Fix:** the labels need to discriminate *within* a company's filings — section-level or
chunk-level relevance, not file-level. `sc-02` ("CHIPS Act", one filing corpus-wide) is the model to
follow; the harness's own docstring already recognizes narrow probes are better, but ticker-scoping
re-widens the label.

---

## 3. Near-duplicate suppression is anti-correlated with the recall label

This is the root cause of the recall/nDCG divergence, and it is a design-level conflict rather than
a tuning issue.

`rag/src/retrieve.py:159` applies suppression to the whole fused candidate set *before* truncating
to `k`:

```python
return suppress_near_duplicates(candidates)[:k]
```

with `SHINGLE = 5`, `NEAR_DUPLICATE = 0.8`, `OVERFETCH = 3` (`retrieve.py:84–88`). Its docstring
states the target explicitly:

> filings repeat language across quarters: a 10-Q's risk factors are frequently the previous
> quarter's with a few numbers changed

The suppression is **global, not scoped per file**. So when NVIDIA's export-control risk factor
recurs near-verbatim across 16 filings, suppression keeps the highest-ranked instance and drops the
other 15 — each of which is a *distinct relevant file* under the label.

The two mechanisms are therefore in direct opposition:

- The **label** counts 16 relevant files, which exist largely *because* the text is duplicated.
- The **retriever** exists specifically to remove that duplication.

Every correctly-suppressed duplicate lowers `recall@k` while improving the answer. `nDCG@10 = 0.963`
alongside `recall@10 = 0.533` is exactly the signature of this: what is retrieved is highly
relevant and well-ordered, there is simply one passage per distinct idea rather than sixteen.

The prior repo's own half-identifies this for the temporal row:

> `tm-01` labels 16 NVIDIA filings for "how has this changed over the last two years". A *correct*
> answer applies the time filter and retrieves from two years of them, so file-level recall will
> look poor for the right behaviour.

The same defect applies to every multi-filing question, not just temporal ones, and the cause is
near-duplicate suppression as much as time filtering.

**Fix — pick one, deliberately:**
- Score recall over *distinct relevant content units* (probe-bearing sections deduplicated by text
  similarity) rather than distinct files; or
- Evaluate retrieval **pre-suppression** and evaluate suppression separately as a context-quality
  metric (redundancy rate in the final context); or
- Treat the set of near-duplicate filings as a single relevance class where retrieving any one
  member scores full credit.

Option 2 is the cleanest: it measures each mechanism on the axis it was designed for.

---

## What this means for the new build

1. **Design the metric before the ablation, not after.** The ablation table is only evidence if its
   metrics can move. Two of the three current metrics cannot.
2. **`entity_coverage@k` is the one metric here that works.** It goes 0.798 @10 → 1.000 @20 overall
   and 0.521 @10 → 1.000 @20 on cross-company questions. It has range, it is not saturated, and it
   maps to a failure a business audience recognizes. Keep it. Note the reported @20 = 1.000 is a
   consequence of the entity-quota design guaranteeing per-company budget — so it validates the
   quota mechanism but will be pinned at 1.0 for any config that includes quotas, and should be read
   as an ablation metric only across quota-on vs quota-off rows.
3. **Unanswerable questions are excluded from retrieval metrics** (3 of 25, correctly — recall is
   undefined with no relevant files). But refusal correctness is then measured nowhere in
   `eval/results/`. confirms the gap: the only Shopify assertion tests that the
   *alias* resolves to nothing, not that the answer refuses. For a diligence tool this is the single
   highest-value behavior to measure.
4. **n=22 needs a significance test.** With 22 questions, a 2–3 point difference between ablation
   rows is well inside sampling noise. Report per-question deltas and a paired test, or report the
   ablation as directional only and say so.

---

## Artifacts audited

| file | what it establishes |
|---|---|
| `rag/eval/golden_set.json` | 25 questions, 22 scored, per-question `source_files` labels |
| `rag/eval/build_golden_set.py` | labels = probe-term match ∩ named tickers, file-level |
| `rag/eval/results/retrieval_metrics.json` | one config only; no ablation rows |
| `rag/src/retrieve.py:84–88, 98–159` | global near-duplicate suppression before top-k cut |
| `rag/SPEC.md` §7 | states eval is the differentiator; defines the unbuilt 5-row table |
