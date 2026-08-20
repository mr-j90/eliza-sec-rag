# RRF k, and whether fusion happens in Qdrant or in application code

Type: grilling
Status: resolved
Blocked by: 01

## Question

**What ranking constant does fusion actually use, and where should fusion run?**

This ticket exists because the prior art's prose and its code disagree, and the prose is
what would be defended in the demo.

### The defect

The SPEC says: *"Keep `k=60` (the Cormack et al. default) and note weighted RRF as a tuning
knob you deliberately left at default rather than overfit."*

But the code calls `FusionQuery(fusion=Fusion.RRF)` on Qdrant, whose ranking constant
**defaults to 2** (`DEFAULT_RANKING_CONSTANT_K = 2`), configurable only from v1.16.0. And
`FusionQuery` in qdrant-client 1.19.0 — the pinned version — **exposes no k parameter at
all.**

So the system as shipped is running **k=2 while claiming k=60**. Being asked about this in
the demo and discovering it live would be bad; discovering it now is free.

Two further problems with the k=60 rationale itself (§6.1):

- k=60 is not "the default" in the sense implied. It is a value Cormack et al. **tuned on a
  pilot** and then reported as "near-optimal, but… not critical." In the paper's own
  Table 1, **k=80 scores higher than k=60**, and k=30–100 sit within .0009 MAP.
- The provenance is fusion of **30 configurations of one lexical engine** on 2009 TREC
  ad-hoc topics — not a two-leg dense+sparse hybrid.

And k is not portable: Qdrant defaults to **2**, Milvus to **100**, Elasticsearch to **60**
(§6.2). "k=60" as a cross-system constant is folklore.

### The fork

**Fuse server-side in Qdrant** — one round trip, less code, but on qdrant-client 1.19.0 you
cannot set or sweep k, so you are accepting k=2 and must say so.

**Fuse in application code** — you control k explicitly and can sweep it, at the cost of
hand-rolling the fusion. §9.9's counter-argument is worth weighing: fusion is the harder
thing to get right, and hand-rolling it to gain a tunable constant that the paper itself
calls "not critical" may not earn its keep.

Also in play, if fusion moves into app code:

- **BM25 `b` and `k1`** (§5.1). Corpus document length spans **20,626 → 396,452 tokens** —
  a 19× range — and `b` controls exactly that length normalisation. Robertson & Zaragoza
  state the model "provides no guidance" on these values. Prior art has BM25 in
  `config.py`/`embed.py`/`retrieve.py`; establish whether the values are considered or
  defaults.
- **DBSF vs RRF** (Q5, §6.3). RRF is robust and ignores score magnitude; DBSF and weighted
  fusion use magnitude and can win when one leg is confidently right — which, given how
  identifier-dense filings are, may be common here. Qdrant appears to be the only
  mainstream store shipping DBSF, and §10 item 2 says that — not "only store with native
  hybrid," which is **false** and would be caught by anyone who has used Weaviate or Milvus
  — is the honest justification for choosing Qdrant.

### Whichever way it goes

The answer must state the k value the system actually runs, so the walkthrough can say it
out loud. §10's suggested framing is the strong one: *"we measured k and it didn't matter
much, consistent with Cormack et al."* — which is both true and better than claiming a
folklore default. That framing requires actually measuring it, even roughly.

---

## Answer

**Resolved 2026-08-20.** Fusion stays **server-side**, with the ranking constant set
**explicitly to k=60**. The ticket's central fork — server-side versus application-code fusion
— **dissolved**, because its premise was out of date.

### The premise was wrong: k *is* settable server-side

The ticket, following §6.2, states that `FusionQuery` in qdrant-client 1.19.0 "exposes **no k
parameter at all**", making app-side fusion the only way to control it. `FusionQuery` indeed has
exactly one field. But the same client version ships a **second, newer query type**:

```python
models.RrfQuery(rrf=models.Rrf(k=60, weights=None))
```

`Rrf` exposes both `k` and `weights` — so weighted RRF is available too. Verified working
against the running Qdrant 1.19.0. **So there was never a reason to hand-roll fusion**, and
§9.9's counter-argument (fusion is the harder thing to get right) applies unopposed.

### The defect is confirmed, empirically

Prior art called `FusionQuery(fusion=Fusion.RRF)` while its prose claimed the Cormack et al.
`k=60`. Qdrant's default is **2**, and that was verified rather than cited: over this
collection, `FusionQuery(RRF)` and `RrfQuery(rrf=Rrf(k=2))` return an **identical id-set and an
identical score multiset**, with identical top-10 ordering. The only difference was tie-break
order among equal scores further down the list — which is what made a naive list equality check
say "different" and needed chasing down before the claim could be made.

So the system was running k=2 while its documentation described k=60. It now runs 60, stated in
`config.DEFAULT_RRF_K` where a reviewer can see it, with `RAG_RRF_K` to override.

### The sweep §6.1 asked for

| configuration | norm_recall@5 | norm_recall@10 | recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| RRF k=2 *(the accidental default)* | 0.668 | 0.635 | **0.521** | 0.977 | 0.919 |
| RRF k=10 | 0.659 | 0.630 | 0.518 | 0.977 | 0.922 |
| **RRF k=60** *(chosen)* | 0.659 | 0.617 | 0.513 | **1.000** | 0.925 |
| RRF k=100 | 0.659 | 0.617 | 0.513 | **1.000** | 0.925 |
| DBSF | 0.659 | 0.621 | 0.514 | **1.000** | **0.929** |

**Total spread across all five: 0.008 to 0.023.** k=60 and k=100 are identical on every metric.

That reproduces the source paper's own finding — k=60 reported as "near-optimal, but not
critical", k=30–100 within .0009 MAP — on this corpus rather than on 2009 TREC ad-hoc topics.
§10's suggested framing is now literally true: **"we set it explicitly, measured 2/10/60/100,
and it didn't matter much, consistent with Cormack et al."** k=60 wins on the rank metrics and
matches the literature; it is not chosen because the difference is meaningful.

Worth noting rather than hiding: **k=2 is marginally the best on recall** and the worst on MRR
and nDCG. Nothing here is strong enough to prefer the accident.

### DBSF (Q5): competitive, not better — a measured correction

§6.3 speculated that score-magnitude fusion could beat rank fusion on a corpus this
identifier-dense, and §10 called DBSF a real differentiator for Qdrant. **Measured, it is not
better here** — it leads on nDCG by 0.003, which is noise, and trails k=2 on recall. It stays
switchable via `RAG_FUSION=dbsf` so the claim can be re-tested rather than repeated.

Qdrant remains the right choice on fit, and DBSF's availability is still a genuine
differentiator — it just should not be sold as a measured win on this corpus.

### BM25 `b` and `k1`: checked, not tuned — and §5.1's argument does not apply

Left at FastEmbed's defaults `b=0.75`, `k1=1.2`, `avg_len=256`, deliberately and with a reason.

§5.1 argues `b` deserves tuning because corpus document length spans **20,626 → 396,452
tokens** and `b` controls length normalisation. **That argument is about whole-document BM25.**
We index chunks, and chunk length spans p10 **89** to p90 **381** BM25 terms — a **4× spread,
not 19×**. Chunking has already collapsed the variance the concern is about.

Measured mean chunk length is **236 terms** against the 256 default: an **8% discrepancy**,
which does not justify re-indexing 30,383 points. Recorded because "we left the defaults" and
"we measured the defaults and they fit" are different claims, and only the second is defensible.

Getting to that number needed one correction mid-ticket: a first measurement compared `avg_len`
against the count of *unique* terms per chunk (129) and looked like a 2× discrepancy. BM25's
`avg_len` is document length **with multiplicity**, so the comparison was meaningless. The
spurious finding was caught before it was written down.

### A consistency fix this forced in the deliverable

`docs/EVALUATION.md` §4 compared fusion-only against +rerank — measured at the **old k=2
default**. With the constant now 60, those two tables described different systems. Both rows
were re-measured at k=60:

| | fusion only | + rerank | delta |
|---|---|---|---|
| MRR@10 | 0.943 | **1.000** | **+0.057** |
| nDCG@10 | 0.909 | 0.925 | **+0.017** |
| normalized_recall@5 | 0.627 | 0.659 | +0.032 |
| normalized_recall@20 | 0.765 | 0.759 | **−0.006** |

**Reranking looks better at k=60 than it did at k=2** — nDCG moves from −0.007 to +0.017 and MRR
gains 0.057. That is coherent: a larger constant flattens the fusion ordering, leaving the
cross-encoder more to contribute. Per question it is better on 6, worse on 4, **tied on 12** —
still directional, still reported as such.

### Verification

- 2 new tests: the ranking constant is not Qdrant's default, and DBSF is selectable. The
  existing fusion-shape test now asserts `RrfQuery` with the configured `k` rather than a bare
  `FusionQuery`.
- **181 free python + 34 frontend green**; live tier re-run because retrieval ordering changed.
- The sweep is reproducible: `RAG_RRF_K=<k> make eval`, `RAG_FUSION=dbsf make eval`.
