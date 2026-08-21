# How this system's quality was evaluated

The brief asks for notes on how quality was evaluated. The short version: **there is a
pass/fail gate that runs on every change, one retrieval metric that can actually move, and
three widely-used metrics that were measured, understood, and then deliberately not relied
on.** Knowing why a metric misleads is worth more than a table of numbers that cannot move.

All figures below were produced by this system against this corpus. Reproduce with:

```bash
make eval          # the retrieval metrics, both configurations
make test-live     # the answer-contract gate (28 tests, 11 real generation calls)
```

---

## 1. The gate: what must never break

Quality is defended by a **pass/fail gate**, not by a dashboard. 28 live tests, run against
real Qdrant and a real model, covering:

| what | why it is the gate |
|---|---|
| **All three panel questions**, end to end | These are the questions that will be typed at the demo. Each must return the five-part answer with resolvable citations. |
| **The out-of-corpus refusal** | *"What is Shopify's China exposure?"* must name Shopify, state plainly that the corpus holds nothing for it, and produce **no Findings for anyone else**. |
| **No fabricated attribution** | No ticker may appear in an answer whose company was not retrieved. Checked against the full alias table. |
| **Exactly one generation call** | Asserted by a counting stub, including on the three-company question where per-company quotas issue several vector searches. |
| **Structural stability** | The five-part contract is asserted across repeated generations — one compliant sample is luck, not a property. |

Refusal correctness is checked **on the answer**, not on the alias lookup. That distinction
matters: the earlier attempt at this assessment tested only that the alias resolved to nothing,
which says nothing about what the model then wrote. For a diligence tool, "declines to answer
what it cannot support" is the single highest-value behaviour to verify.

---

## 2. The one retrieval metric that works

**`entity_coverage@k`** — of the companies a question named, what fraction appear in the
retrieved context.

| | @10 | @20 |
|---|---|---|
| overall | 0.798 | **1.000** |

It earns its place because it has range, it is not saturated, and it maps to a failure a
business audience recognises immediately: *"you asked about three companies and the answer
covers one."*

**Its caveat, stated because it would otherwise be misread.** The 1.000 at k=20 is a
*consequence of the per-company quota design*, which guarantees each named company a budget. It
will be pinned at 1.0 for any configuration with quotas on, so it is only informative as an
ablation metric across **quota-on versus quota-off** rows. It is not evidence that retrieval is
perfect.

---

## 3. Three metrics that were measured and then set aside

These are the numbers a reader will expect. They are reported, and they are not load-bearing.
Each reason is a measurement, not an opinion.

### `recall@k` has a per-question ceiling that varies 36-fold

Labels are file-level: a filing is relevant if it contains the question's probe term and
belongs to a named ticker. Relevant-file counts per question therefore run from **1 to 36**:

```
[1, 1, 1, 1, 1, 2, 2, 2, 4, 4, 5, 6, 12, 12, 13, 16, 16, 16, 16, 32, 32, 36]
```

Since at most `k` distinct files can be retrieved, the attainable maximum is `min(k,|R|)/|R|`:

| | min ceiling | mean ceiling | max ceiling |
|---|---|---|---|
| recall@5 | **0.139** | 0.671 | 1.000 |
| recall@10 | 0.278 | 0.811 | 1.000 |
| recall@20 | 0.556 | 0.946 | 1.000 |

On the worst question no configuration change can move `recall@5` by more than **0.139** in
absolute terms, while on another the same change has the full 1.000 of range. **Averaging those
together averages incommensurable quantities**, and the mean is then dominated by label
cardinality rather than by retrieval quality.

So `recall@10 = 0.521` does not mean "we find half the relevant filings". Against what the
labels permit it is **64%** of attainable. This is the one fix from the audit that was
implemented — **`normalized_recall@k = hits / min(k,|R|)`** — because without it the headline
number is not merely limited, it is misleading:

| | raw | normalized |
|---|---|---|
| @5 | 0.454 | **0.668** |
| @10 | 0.521 | **0.635** |
| @20 | 0.739 | **0.767** |

### `MRR@10` and `nDCG@10` are saturated

`MRR@10 = 0.977`, `nDCG@10 = 0.919`. A metric sitting at 0.92–0.98 has almost no room to show
improvement, so ablation rows differ in the third decimal on n=22 and nothing can be concluded.

The *reason* is diagnostic and worth more than the number: a file-level label restricted to the
named ticker makes almost **any** chunk from the right company relevant. These metrics are
measuring the **entity filter**, not the ranking. They will report near-perfect scores for a
system that retrieves the right companies and the wrong passages — which is precisely the
failure mode a diligence tool must not have.

### Near-duplicate suppression is anti-correlated with the recall label

This is the interesting one, and it is a design conflict rather than a tuning problem.

Filings repeat language across quarters — a 10-Q's risk factors are frequently the previous
quarter's with a few numbers changed. The retriever suppresses near-duplicates deliberately,
because twenty restatements of one risk factor is a worse context than one statement of twenty.

But the label counts each of those filings as separately relevant, largely **because** the text
is duplicated. So the two mechanisms pull against each other:

- the **label** counts 16 relevant files, which exist because the text repeats;
- the **retriever** exists specifically to collapse that repetition.

**Every correctly-suppressed duplicate lowers `recall@k` while improving the answer.** A high
`nDCG` next to a middling `recall` is the signature of exactly this: what is retrieved is
relevant and well-ordered, there is simply one passage per distinct idea rather than sixteen.

**The fix we would adopt** (not implemented — see §5): evaluate retrieval **pre-suppression**,
and measure suppression separately as a context-quality metric — redundancy rate in the final
context. That scores each mechanism on the axis it was designed for, rather than making one
look bad for doing its job. The alternatives — scoring over deduplicated content units, or
treating a near-duplicate cluster as one relevance class — both work but require relabelling.

---

## 4. Does reranking help? Measured, and reported as directional

A cross-encoder reranker was added, so the obvious question is whether it earns its cost. Both
configurations were run against the same index:

Both rows are measured at the shipped fusion constant, **RRF k=60** (§4b) — an earlier version
of this table was measured at k=2 and is not comparable to the system as shipped.

| metric | fusion only | + rerank | delta |
|---|---|---|---|
| normalized_recall@5 | 0.627 | 0.659 | **+0.032** |
| normalized_recall@10 | 0.605 | 0.617 | +0.011 |
| normalized_recall@20 | 0.765 | 0.759 | **−0.006** |
| recall@5 | 0.422 | 0.451 | +0.029 |
| recall@10 | 0.502 | 0.513 | +0.011 |
| MRR@10 | 0.943 | 1.000 | **+0.057** |
| nDCG@10 | 0.909 | 0.925 | +0.017 |
| entity_coverage@10 / @20 | 0.798 / 1.000 | 0.798 / 1.000 | 0.000 |

The gains concentrate in the **rank** metrics and at **small k** — MRR@10 reaches 1.000, and
normalized recall improves at k=5 while going marginally *negative* at k=20. That is the shape
reordering should have: it changes which candidates survive a tight cut and cannot add anything
the fusion stage never retrieved.

**But the means are not the honest report at n=22.** Per question:

> **reranking is better on 6, worse on 4, tied on 12.**

Twelve ties, and among the ten that moved the swings run to **±0.25–0.40** — far larger than any
mean here. A few points across 22 questions is well inside sampling noise. **This is directional
evidence, not proof**, and it is reported that way deliberately.

One pattern is worth flagging rather than smoothing away: the two questions that got
*materially worse* are **sector** questions (`sw-01`, `sw-02`). A sector question names no
company, so no quotas apply and a single unfiltered search runs — giving the reranker the most
freedom, and on 2 of 3 it used that freedom badly. If reranking is tuned further, sector
questions are where to look.

Reranking is kept, on the strength of the direction plus its cost profile (328 ms for 20
passages, local, no per-query charge) — and because `entity_coverage` being pinned by quotas
means the metric set cannot adjudicate it either way.

---

## 4b. Fusion: the ranking constant, measured rather than cited

The prior attempt's prose claimed the Cormack et al. `k=60`. Its code called
`FusionQuery(fusion=Fusion.RRF)`, which accepts no ranking constant — **Qdrant defaults it to
2**. Verified here rather than taken from a changelog: `RrfQuery(rrf=Rrf(k=2))` returns an
identical id-set and an identical score multiset over this collection, so the default is 2 and
the prose was describing a system that was not running.

`RrfQuery` does take `k`, so it is now set explicitly at **60** and swept:

| configuration | norm_recall@5 | norm_recall@10 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| RRF k=2 *(the accidental default)* | 0.668 | 0.635 | **0.521** | 0.977 | 0.919 |
| RRF k=10 | 0.659 | 0.630 | 0.518 | 0.977 | 0.922 |
| **RRF k=60** *(chosen)* | 0.659 | 0.617 | 0.513 | **1.000** | 0.925 |
| RRF k=100 | 0.659 | 0.617 | 0.513 | **1.000** | 0.925 |
| DBSF *(score-magnitude fusion)* | 0.659 | 0.621 | 0.514 | **1.000** | **0.929** |

**The total spread across all five configurations is 0.008 to 0.023.** k=60 and k=100 are
identical on every metric. That reproduces the source paper's own finding — it reports k=60 as
"near-optimal, but not critical", with k=30–100 inside .0009 MAP — on this corpus rather than on
2009 TREC topics.

So the honest claim is not "we use the recommended constant". It is: **we set it explicitly,
measured 2 / 10 / 60 / 100, and it did not matter much — consistent with Cormack et al.** k=60
is chosen because it is best on the rank metrics and matches the literature, not because the
difference is meaningful.

Two things worth noting rather than glossing:

- **k=2 is marginally the best on recall** and the worst on MRR and nDCG. It trades rank quality
  for a little reach. Nothing here is strong enough to prefer it.
- **DBSF is competitive, not better.** It leads on nDCG by 0.003, which is noise. The
  architecture note speculated score-magnitude fusion might beat rank fusion on a corpus this
  identifier-dense; measured, it does not. So the `RAG_FUSION` switch was **removed** and RRF
  is the only fusion path in the code — a mode nobody selects is a question to answer in a
  review, not a capability. Re-testing it means restoring one line
  (`FusionQuery(fusion=Fusion.DBSF)`), which is cheaper than carrying the branch.

### BM25 parameters were checked, not tuned

`b=0.75`, `k1=1.2`, `avg_len=256` — FastEmbed's defaults, left alone deliberately.

The architecture note argues `b` deserves tuning because corpus document length spans
**20,626 → 396,452 tokens** and `b` controls length normalisation. That argument is about
*whole-document* BM25. **We index chunks**, and chunk length spans p10 **89** to p90 **381**
BM25 terms — a 4× spread rather than 19×. Chunking has already collapsed the variance the
concern is about.

Measured mean chunk length is **236 terms** against the 256 default: an **8% discrepancy**,
which does not justify re-indexing 30,383 points. Worth stating because "we left the defaults"
and "we measured the defaults and they fit" are different claims, and only the second one is
defensible.

---

## 5. What we would build next, and why it is not here

The honest limitation: **n=22 is too small for the ablation this system deserves.** With 22
questions across 5 categories — 3 to 8 per category — a few points between configurations
cannot be distinguished from noise, which is why §4 reports win/loss/tie rather than leaning on
means.

In priority order:

1. **40–60 questions**, weighted toward comparative and temporal, which is what makes the
   category-level numbers usable. Labelling at `source_file` + section granularity rather than
   chunk granularity is what keeps this affordable, and is a deliberate methodological choice —
   chunk-level labels would move every time the chunker changes.
2. **Section-level relevance**, so the metrics discriminate *within* a company's filings instead
   of measuring the entity filter.
3. **Pre-suppression retrieval scoring** plus a separate context-redundancy metric (§3).
4. **Two domain metrics no library ships**: item-section precision, and temporal-scope
   correctness with an explicit *baseline-present* boolean — a 10-Q's Item 1A carries only
   material changes from the 10-K, so an answer built from 10-Qs alone can present an
   incremental amendment as a complete risk profile. That failure is invisible to every metric
   above.
5. **A paired significance test**, reported per question, so a future ablation table is evidence
   rather than decoration.

---

## Appendix — reproducing

```bash
make eval                      # both configurations, ~2 min, then the page summary
RAG_RERANK=0 make eval         # fusion only
make eval-summary              # just the page summary, if a run landed without one
make test-live                 # the 28-test answer-contract gate
```

Every run writes its own file to `eval/results/`, named
`<timestamp>--<config>.json`, plus `latest.json` as a stable path. Runs are **never
overwritten** — comparing configurations is the whole point of this harness, and every table
above is a before/after. They are also browsable at **`/evals`** in the front-end.

### The generated summary on `/evals`

The page leads with a plain-English summary of the runs and keeps every metric behind a
**Technical numbers** disclosure, because the failure this section documents is a *reading*
failure: a stakeholder who sees `mrr@10 = 1.0000` in a table concludes the opposite of what §3
says it means. Putting the numbers one click away and the interpretation on top inverts that.

The summary is written by `src/eval/summarize.py` — **one eval-time model call, cached to
`eval/results/summary.json`**, so viewing the page makes no call. It is written for a chief
executive reading it cold: no metric names, no `@k` notation, no configuration strings. A
representative finding, generated:

> When a question mentions several companies, filings from each of them are included in the
> evidence for every such question tested.

Five properties make it worth trusting on a page whose whole subject is not over-trusting
numbers:

- **The caveats above are given to it as facts**, not left to be inferred. The prompt states
  that normalized recall is the honest figure, that `mrr@10`/`ndcg@10` are saturated, and that
  `entity_coverage@k` is pinned by the quota design. Its `caveat` field is required output.
- **Every figure is checked against the run data** before caching. The prompt forbids computing
  new numbers — a rate may only be re-expressed as a percentage — and each numeral in the
  generated text must appear in the metrics it was given. Same rule `src/verify.py` applies to
  citation handles, for the same reason: a number that reads as a measurement and is not one is
  worse than no number. Failures are **named on the page**, not stripped, and the CLI exits
  non-zero.
- **Plain language did not cost traceability, it relocated it.** Each finding is
  `{point, metrics}` — the sentence, and the metric keys it rests on. The keys render under
  Technical numbers beside the table, so any claim can still be checked against a row. A point
  that quotes a figure and names no key is flagged as **untraced**; a key that does not exist in
  the run data is flagged too, which is the fabricated-`[C7]` failure in another costume.
- **Staleness is visible.** The cache records which run files it describes; a new run makes the
  page say so rather than showing prose that quietly predates the table beneath it.
- **It is not the answer path.** `POST /ask` cannot reach it — asserted, see the README.

**Two limits, stated because they are the honest ones.** The check verifies that every figure
*exists* in the run data, not that each is attributed to the right configuration — a summary
that swapped two real numbers between columns would pass. And translating a metric into plain
words is an act of interpretation that no check on numerals can police: prompt v4 glossed
`normalized_recall@10` as *"searching ten per question"*, conflating the metric's cutoff with
the retrieval budget of 20. Fluent, plausible, wrong, and invisible to every automated check
here. That is why §3's hand-written metric notes stay on the page next to the summary, and why
the table is one click away rather than absent.

All five versions of that prompt are logged in [`PROMPT_LOG.md`](../PROMPT_LOG.md) — including
the false positive the figure check produced on its first real run, and the `@10` gloss above. Golden-set labels are **re-derived from the corpus** by
`eval/build_golden_set.py` and a test re-derives every label at run time — a label that cannot
be reproduced from the filings fails rather than lingering. Labels written by looking at what
the current system returns would make every metric a measure of how closely a configuration
reproduces today's behaviour.

The full audit that produced §3, including the prior attempt's numbers, is in
[`research/eval-harness-findings.md`](research/eval-harness-findings.md).
