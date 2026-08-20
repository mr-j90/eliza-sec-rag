# RRF k, and whether fusion happens in Qdrant or in application code

Type: grilling
Status: open
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
