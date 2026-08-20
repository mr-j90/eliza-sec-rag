# Reranker choice and chunk size — one decision, not two

Type: grilling
Status: open
Blocked by: 02, 03

## Question

**Which reranker, and what chunk size — resolved together, because the reranker's context
window is the binding constraint on the chunker?**

These look independent and are not. That coupling is the whole reason this is one ticket.

### The coupling

`bge-reranker-v2-m3` truncates at **512 tokens**. An 800-token chunk therefore has ~36% of
its text silently discarded before scoring — the reranker ranks a passage it only partly
read, and nothing errors. §4.7 makes the point that the embedding models impose no relevant
ceiling at all (8,192 tokens for `text-embedding-3-small`, 16,000 for `voyage-finance-2`),
so **the reranker is the only real upper bound on chunk size in this system.**

Note this also corrects the prior art's stated reasoning. The SPEC argued 800 tokens as a
"defensible middle" between a 500-token floor and a 1200-token ceiling where "the embedding
averages over too many topics." §10 item 3 finds both bounds asserted without evidence. The
defensible version is different and better:

- The **measured median risk factor in this corpus is ~607 tokens** (p90 1,706).
- So ~600–800 is not a compromise — it is an approximation of the natural semantic unit,
  which is *why* it works.
- [17 CFR 229.105(a)](https://www.ecfr.gov/current/title-17/section-229.105) requires each
  risk factor be "set forth under a subcaption that adequately describes the risk" — so the
  unit is real and regulator-mandated, not inferred.

### The forks to resolve

1. **Chunk size vs reranker window.** Either size chunks to fit 512 tokens, pick a
   longer-window reranker, or rerank a deliberately truncated view of a longer chunk and
   accept it. Each is defensible; pick one and be able to say why.
2. **Item 1A: per-risk-factor or fixed window?** (Q4) *For per-risk-factor:* mandated by
   229.105(a), matches the measured 607-token median, and self-contained chunks need no
   overlap. *Against:* subcaption detection is heuristic and §4.3 says it under-counts, so
   a fraction of chunks will be mis-bounded — and a mis-bounded chunk may be worse than a
   cleanly-cut arbitrary window. **Ticket 02's verdict on boundary reliability feeds
   directly into this.**
3. **Which reranker.** `bge-reranker-v2-m3` is the 512-token option. `jina-reranker-v2` is
   **CC-BY-NC and therefore unusable commercially** — worth naming in the walkthrough as a
   licensing trap you checked, whatever you pick.
4. **Do narrative and financial-statement chunks get the same policy?** §4.2 has a per-item
   table; the honest question under this budget is how much of it to implement versus one
   narrative default plus a table rule from ticket 06.

### Do not re-open

Whether to rerank at all. That was decided at charting — a cross-encoder is in scope.
Whether it measurably *helps on this corpus* is a separate matter and sits in the map's
Not-yet-specified until tickets 04 and 10 are both done. If it turns out to hurt, that is a
finding worth presenting, not a failure.

### Context that constrains the answer

- Whole-corpus embedding at `text-embedding-3-small` costs **$0.35** over ~21,675 chunks
  (§4.8). Re-embedding is cheap, so do not over-optimise to avoid it.
- But chunk size, chunk boundaries and the contextual prefix all sit **behind a full
  re-embed** (§9.6). Payload design does not future-proof any of them. Getting this
  decision roughly right now is worth more than a flexible schema.
