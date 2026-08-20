# Reranker choice and chunk size — one decision, not two

Type: grilling
Status: resolved
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

---

## Answer

**Resolved 2026-08-20.** Chunk size stays at 800; the reranker is
`Xenova/ms-marco-MiniLM-L-6-v2`, run locally. The coupling resolved in the direction of the
chunker because **the reranker's window turned out not to be a choice**.

### The finding that settled it

The ticket assumed one option was "pick a longer-window reranker". **It is not available.**
Every reranker FastEmbed 0.8.0 exposes truncates at **512 tokens** — measured, not read off a
model card:

| marker position | MiniLM-L-6 | jina-v1-turbo |
|---|---|---|
| start (control) | +6.38 | +2.10 |
| ~token 300 | −3.68 | −1.44 |
| ~token 600 | **−10.61** | **−3.72** |
| no marker at all | **−10.61** | **−3.72** |

A relevant sentence at token 600 changes the score by **exactly 0.0000**, while the same
sentence at token 300 moves it substantially — so the test discriminates, and the verdict is
unambiguous. **`jinaai/jina-reranker-v1-turbo-en` advertises 8192 context and truncates at 512
through this ONNX export.** That headline must not be repeated in the walkthrough, and there is
a test pinning it.

### The exposure, and why it is accepted

| | |
|---|---|
| indexed chunks | 30,383 |
| token distribution | p25 506 · **median 715** · p75 799 · max 1,367 |
| chunks over 512 | **22,635 (74.5%)** |
| indexed text invisible to the reranker | **26.8%** |

Uniform across sections — 72–79% for every item type — so it is not confined to financial
tables. This is a stronger statement of the problem than §4.7's "36% of an 800-token chunk",
because it is a corpus-wide figure rather than a per-chunk one.

Accepted for three reasons:

1. **The reranker orders candidates; it does not read them.** The full chunk reaches the
   generation call untouched. Only the ordering signal is partial.
2. **Ticket 03 made head-truncation defensible.** After reflow, chunks begin at real block
   boundaries, so the first 512 tokens are a coherent opening carrying the topic rather than an
   arbitrary mid-sentence window. That was **not true before reflow landed** — the two tickets
   compound, which is worth saying in the walkthrough.
3. **The alternative makes the chunk unit worse where a regulator defines it.** Re-chunking at
   ~480 tokens cuts Item 1A mid-risk-factor: the measured median risk factor is **607 tokens**,
   and 17 CFR 229.105(a) requires each to sit under its own subcaption. Shrinking to fit a
   reranker would be letting a tooling limit override the domain.

### Model choice — latency and licence, since the window is common

| model | 20 docs | size | licence |
|---|---|---|---|
| **`Xenova/ms-marco-MiniLM-L-6-v2`** | **328 ms** | 0.08 GB | apache-2.0 |
| `jinaai/jina-reranker-v1-turbo-en` | 385 ms | 0.15 GB | apache-2.0 |
| `Xenova/ms-marco-MiniLM-L-12-v2` | 582 ms | 0.12 GB | apache-2.0 |
| `BAAI/bge-reranker-base` | 1,462 ms | 1.04 GB | mit |
| `jinaai/jina-reranker-v2-base-multilingual` | — | 1.11 GB | **cc-by-nc-4.0 — excluded** |

The arch doc's licensing warning is **confirmed**: the strongest multilingual option on offer
cannot be used commercially. A test asserts the configured model is not it, because "let's try
the better model" is exactly how a licence violation ships.

`bge-reranker-base` more than doubles retrieval latency for the *same* 512-token window.
Measured end to end: retrieval **1.0 s → 1.7 s**, generation ~15 s, so reranking is ~4% of the
wait.

*(Per IES process, adding these model artefacts to a production stack would need IT and
procurement sign-off; both selected licences are permissive, and nothing here leaves the
machine.)*

### Where it runs, and why there

Inside `_search`, **between near-duplicate suppression and the top-k cut**. Two reasons, both
structural:

- That is where there is something to choose — `OVERFETCH = 3` means 3k candidates compete for
  k slots. Reranking the final merged set would reorder an already-decided selection.
- `retrieve_for` orders its output **by company, then section, then period** on purpose;
  grouping a comparison by company is what makes it readable. Reranking after the merge would
  destroy that grouping. Reranking before it improves *which* chunks each company contributes
  while leaving the grouping intact — verified: quotas still return 6/6/6.

### Honesty about whether it ran

`retrieval_meta.retrieval` now reports
`"hybrid dense+sparse, server-side RRF + cross-encoder rerank (Xenova/ms-marco-MiniLM-L-6-v2)"`
— and reports plain fusion when the model could not load. A worse *ordering* is not a wrong
answer, so this degrades rather than refusing (unlike the provider path, where a canned answer
that reads as real is dangerous). What must not happen is claiming a step that did not run, and
the UI renders this string.

The fusion score on each result is deliberately **not** overwritten. `top_score` has always
been the fusion score; cross-encoder logits are unbounded and would silently change what that
field means while looking identical.

### Deferred, with reasons

- **Per-risk-factor chunking for Item 1A (Q4).** Most of what it was buying — chunks that start
  at a semantic boundary — arrived with reflow. §4.3 also notes subcaption detection
  under-counts, so a mis-bounded chunk may be worse than a cleanly-cut window. Left in fog.
- **Per-item chunking policy (§4.2's table).** Effectively settled by other tickets: one
  narrative default of 800, plus ticket 06's table rule for Item 8. A per-item table would add
  configuration without a measured gain.
- **Whether reranking helps *on this corpus*** — still fog, and now answerable by ticket 10.

### Incidental fix

Ticket 14's conftest guard raised `UsageError` when a single test was selected by node id from
`test_ask.py` — it could not distinguish "the test was renamed" from "the user narrowed the
collection". `pytest tests/test_ask.py::some_test` was broken. The check moved out of the
collection hook into `tests/test_tiers.py`, which also now asserts the gating *fixture* names
still exist, since a renamed fixture would silently disarm the primary marking mechanism.

### Verification

- `tests/test_rerank.py` — 8 tests, free tier, encoder stubbed so `make test` stays
  network-free (the real 0.08 GB model is exercised by the live tier through `retrieve`).
  Covers reordering, the untouched fusion score, the degradation path, the descriptor, the
  licence pin, and a grep proving no provider SDK in the reranking path.
- **231 tests green**: 169 free python + 28 live + 34 frontend. `make check` clean.
- `PROMPT_LOG.md` carries a no-prompt-change entry: reranking changes which passages reach v6,
  and it is the step most likely to be mistaken for a second LLM call.
