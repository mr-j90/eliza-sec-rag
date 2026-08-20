# Map: SEC filings RAG — working demo

Label: `wayfinder:map`

## Destination

*Extended once after completion, at the user's request: an evals page in the front-end
(ticket 16), so the evaluation work is visible in the demo rather than only in prose.*

A **working demo** the interview panel can drive: they type one of their three business
questions into the existing `frontend/` input field, and get back a well-structured,
cited, coverage-honest answer produced by **exactly one LLM API call** — plus the brief's
seven deliverables and a walkthrough that defends business value and future state.

Reaching the end of this map means: `docker compose up` + `uv run uvicorn src.api:app
--port 8000` + `bun dev` from a clean checkout, all three named questions answered
correctly, and the walkthrough rehearsed.

## Notes

**Domain.** Retrieval-augmented generation over a fixed corpus of 246 SEC EDGAR 10-K/10-Q
filings (54 companies, 2023–2025) for private-equity-style diligence. This is an
interview assessment with a **live panel demo**, not a production system.

**Execution IS in scope.** This overrides wayfinder's plan-don't-do default. Tickets here
build as well as decide.

**Timebox: ~4 hours of build**, per the brief. The research is already paid for and does
not count against it. Budget discipline is itself a defensible answer to the panel — the
brief asks for future state precisely so that unbuilt work has a home.

**Read before working any ticket:**
- `docs/research/sec-rag-architecture.md` — 19 recommendations, all measured against this
  corpus. Section refs below point into it.
- `docs/research/eval-harness-findings.md` — why the prior art's retrieval metrics cannot
  power an ablation. This document *is* the quality-notes deliverable.
- `/Users/jordan/Developer/eliza/AI-RAG Assessment.pdf` — the brief. Seven named
  deliverables; re-read them before closing ticket 12.

**Skills:** `/grilling` and `/domain-modeling` for the decision tickets, `/tdd` for the
build tickets (prior art ships 10 test files — keep them green), `/prototype` for the
walkthrough.

**Test as you go — the loop exists now.** `make test` runs 93 python + 34 frontend tests in
14.4s with no Docker and no key; `make test-live` runs the 29 that need a key and cost money.
Run `make help` first. Every build ticket lands with tests, per
[14 — The test loop](issues/14-test-loop-and-fixtures.md). This is affordable here specifically because almost everything on
this map is a **pure function over text** — XBRL strip, reflow, segmentation,
table-caption binding, RRF arithmetic, citation enforcement, coverage computation. None of
it needs a running service to test. **The suite has three tiers, not two** — 53 unit + 34
frontend tests need nothing, 11 need Qdrant, and **29 need a live `OPENAI_API_KEY`, 11 of
those spending real money per run.** Keep the paying tier opt-in; it must never be the
command you run on every save.

### Scope decided while charting

These are standing constraints, not route steps. Every session respects them.

1. **Destination is a working demo system**, not a spec. Execution in scope.
2. **Port `/Users/jordan/Developer/rag-old/` rather than greenfield.** It is ~2,470 LOC
   of working implementation and already does the things §10 rates as correct: contextual
   prefix, RRF, BM25, per-entity quotas, `(part, item)` keying, aliases, FastAPI, and a
   genuinely good out-of-corpus refusal (five-part answer contract; the live
   `prompt_version` is **v4**, not the v2 its docstring describes). Spend the budget on the
   defects the research named, each traceable to a measurement.
3. **Hybrid retrieval with RRF fusion and a cross-encoder reranker are in scope**, not
   future state.
4. **Eval is a smoke gate plus a written critique**, not an ablation table.
   `eval-harness-findings.md` is the deliverable; ~15–20 questions are the regression gate.
5. **All three honesty mechanisms are in scope**: machine-generated coverage statement,
   10-K baseline anchoring for temporal questions, verifiable citation enforcement.
6. **The XBRL numeric router is future state** — talked, not built.
7. **Testing is a fast local loop, not a pipeline.** One command, layered by what each test
   needs, no API key at any layer. GitHub Actions and deployment are out of scope — see
   below.

### Constraints that are already fixed and are not open for decision

- **The one-call constraint is enforced structurally.** `frontend/lib/ai/provider.ts`
  imports no provider SDK at all; the frontend `POST`s to the Python backend, which makes
  exactly one call. Per its own comment: *"checkable by grep, not by trust."* Do not
  reintroduce an LLM call in the frontend.
- **The wire contract already exists** and the backend must satisfy it, not redefine it:
  `POST /ask {question, top_k}` → `{answer, citations[], retrieval_meta{}}`;
  `GET /health` → `{generation_model}`. Citation shape and every `retrieval_meta` field
  are declared in `frontend/lib/chat/types.ts`.
- **Backend location is dictated by the frontend**: `src/api.py` at the sec-rag root,
  uvicorn on port 8000 (`frontend/lib/ai/provider.ts` hardcodes the start hint).
- **No streaming, and no mock fallback.** Both were removed deliberately — a mock during a
  demo shows a fabricated answer while the operator believes it is real.
- **`frontend/README.md` is stale.** It describes the pre-RAG generic chat app. Ticket 12
  fixes it.

## Decisions so far

<!-- one line per closed ticket: gist + link. Zoom the ticket for detail. -->

- [01 — Port the prior-art backend into sec-rag](issues/01-port-backend.md) — **works end to
  end.** Wire contract matches byte-for-byte (7 citation fields, all 10 `retrieval_meta`
  fields); index was **already built and persisted at 29,499 points**, so no ingest is needed;
  53 unit + 11 integration + 34 frontend tests pass. Segmentation is already TOC-anchored and
  monotonic — better than §10 implied, so ticket 02 should measure rather than assume a
  rewrite. Four defects found: `fiscal_year` wrong on 37/246 filings (→ ticket 15), the XBRL
  strip is not §2.3's cover-page anchor and may be deleting real cover pages (→ 03), the
  sentence splitter requires whitespace the corpus does not have so text falls to raw-token
  cuts (→ 03, premise confirmed), and `bun dev` is broken on Node 25 (→ 12).

- [14 — The test loop](issues/14-test-loop-and-fixtures.md) — **`make test` = 93 python +
  34 frontend in 14.4s, no Docker, no key, no cost; `make test-live` = the 29 paying tests,
  which now pass for the first time in this repo.** Tiers are *deselected*, not skipped, so a
  green run is a readable claim. Two guards refuse to report green when untested: the live
  tier exits 1 without a key, and a missing corpus gives one message instead of 21 failures.
  Fixtures are a **manifest** (`tests/fixtures/pathologies.json`, 13 filings) rather than
  copies — truncation is unsafe because `_LATE_DETECTION` is a fraction of body length.
  Writing the claims down falsified four of them, including: the zero-space header fixture
  was the wrong file (it is the 10-Q, and the ticker is `GOOG` not `GOOGL`), and **only one of
  §2.3's two anchor misses is real** — `re.IGNORECASE` recovers `LLY` for free, so ticket 03
  needs a fallback for `NFLX` alone.

- [15 — `fiscal_year` is wrong for 37 of 246 filings](issues/15-fiscal-year-correctness.md) —
  **fixed, and it was a retrieval bug, not a labelling one.** `query.py` held a second copy of
  the derivation, so `LATEST_FISCAL_YEAR` read **2026** for a corpus ending in **2025**: the
  panel's NVIDIA question asked for two years and retrieved one. Now `[2024, 2025]` and two
  years of citations. One derivation (`ingest.fiscal_period`), preferring `Report Period` → the
  date embedded in `URL:` → filing month; 37 filings corrected, only `GE_10K_2015-02-27`
  unresolvable. Cause 2 fixed in the **display** — citations show `period ending 2025-10-26`
  rather than a bare `FY2025` that **26 of 67 chunks** in that filing openly contradicted;
  `PROMPT_VERSION` → **v5**. The ticket's "payload-only, no re-embed" note was **wrong** —
  `fiscal_year` sits inside the embedded prefix, so 54 filings / 9,926 chunks were re-embedded
  (~$0.13, in place, since point ids derive from position not `chunk_id`).

- [03 — Inline-XBRL strip and text reflow](issues/03-xbrl-strip-and-reflow.md) — **step 1 was
  already done; step 2 removed a correctness defect entirely.** The existing strip already
  banks §2.3's headline 17.7%, landing within **1,498 tokens** of the arch doc's own claimed
  result — so the "single biggest preprocessing win" was never outstanding. It does delete the
  cover page in 143 files, as ticket 01 suspected, but that is **0.04% of the corpus** and
  checkbox boilerplate: quantified and accepted, not switched. Reflow was the real work:
  **0 of 55 sections contained a blank line**, so the preferred paragraph split never fired,
  and **3.6% of chunks fused two sections under one label**. Now **0%**, with block joins down
  88.8% → 36.3% (all residual are correctly-guarded abbreviations). Corrects ticket 01: the
  sentence splitter *does* work — §2.4 is about **block** boundaries. Re-indexed with
  `--recreate` to avoid orphans: **29,499 → 30,348 points**, ~$0.40. 185 tests green.

- [07 — Machine-generated coverage statement](issues/07-coverage-statement.md) — **the answer
  now states what it stands on**, computed once and used twice: fed to the model so its prose
  hedges proportionately, and returned in `retrieval_meta` so the UI renders the authoritative
  copy. Unit is **distinct filings, never passages** — the context held 7 Merck passages from
  *1* filing. `1 of 1` (thin corpus) is distinguished from `3 of 17` (budget choice), so
  `JPM 2 of 4` is shown without being flagged. `PROMPT_VERSION` → **v6**. Corrects this
  ticket's own claim that coverage was already computed in `ingest.py` — it was not.
  **The change made something worse first:** given counts alone the model wrote *"No filings
  are available for companies except…"*, which is false — ABBV and TMO exist but were not
  retrieved. Fixed by telling it the census is of the context, not the corpus.
- [06 — Table-caption binding](issues/06-table-caption-binding.md) — figures with no stated
  scale down from **113 of 405 (28%) to 15 of 405 (4%)**; on the NVIDIA question, **5 of 5**
  table-bearing citations now show `($ in millions)` beside the number. Carries the caption and
  period header into any window cut below them, using **only the filing's own lines**. The
  guard matters more than the feature: the walk stops at prose, because a caption in
  *thousands* bolted onto figures in *millions* reads as authoritative. Took three attempts to
  measure honestly (the cover page and the table of contents both look like tables), and the
  first version of the test flagged a share-count table that needed no caption at all.

- [02 — Measure what the existing item segmenter achieves](issues/02-measure-segmenter.md) —
  **verdict (a): keep it.** Across all 246 filings it puts a median **98%** of a 10-K body and
  **96%** of a 10-Q inside a named item, against the **78%** §2.5 reports for the aligner it
  recommends *building* — it already is that aligner, and rewriting it would have risked a
  regression for no gain. Found 27 filings detecting zero items, from two causes: a colon/dash
  header form §2.5 lists that the pattern never allowed (**11 filings, one character** — now
  27 → 15), and 15 that genuinely have no body item headers (JNJ structures its 10-Qs by
  `NOTE 11 — LEGAL PROCEEDINGS`; their text is still chunked under `UNLABELLED`). The widening
  regressed AMD — a quoted cross-reference `“Part I, Item 1A—Risk Factors”` cut Item 1 from 19
  chunks to 1 — caught by diffing every label against the live index, and fixed by making the
  quote guard walk back for an unclosed quote rather than checking one character.

- [04 — Reranker choice and chunk size](issues/04-reranker-and-chunk-size.md) — **chunks stay
  at 800; reranker is `Xenova/ms-marco-MiniLM-L-6-v2`, local via FastEmbed (no API, no key,
  328 ms/20 docs, apache-2.0).** The coupling resolved toward the chunker because the window
  turned out not to be a choice: **every FastEmbed reranker truncates at 512 tokens**, measured
  — a marker at token 300 moves the score, at token 600 it moves by exactly 0.0000, including
  for `jina-v1-turbo` which advertises 8192. So 74.5% of chunks are truncated and **26.8% of
  indexed text does not influence ranking**. Accepted: the reranker *orders* candidates rather
  than reading them, ticket 03's reflow means the first 512 tokens are a real block opening,
  and shrinking to ~480 would cut Item 1A mid-risk-factor (median risk factor 607 tokens,
  17 CFR 229.105(a)). Runs between suppression and the top-k cut so `retrieve_for`'s
  company-then-section grouping survives. `jina-reranker-v2` excluded on **CC-BY-NC**, pinned
  by a test. Retrieval 1.0s → 1.7s.

- [10 — Smoke eval gate and the quality-notes deliverable](issues/10-smoke-eval-and-quality-notes.md)
  — deliverable is **`docs/EVALUATION.md`**; gate is `make test-live` (28 tests), metrics are
  `make eval`. The gate largely already existed and is better than this ticket planned — the
  ported answer-contract tests check refusal **on the answer, not the alias**, which was the
  audit's actual complaint about the prior attempt. **Answered ticket 04's open question:**
  reranking is better on **8 questions, worse on 4, tied on 10** (n=22), mean +0.02 with
  per-question swings of ±0.25–0.40 — kept, reported as **directional, not evidence**, and both
  regressions are *sector* questions where no quotas apply. Implemented **`normalized_recall@k`**
  (the one fix worth having: |R| spans 1–36, so `recall@10 = 0.521` is really **64% of
  attainable**). Added `RAG_RERANK=0` so the comparison is a measurement, not an assertion.

- [11 — Prompt-iteration log](issues/11-prompt-iteration-log.md) — the log did its job by being
  written as the work happened: **363 lines, v1–v6 with no gaps**, plus three
  no-prompt-change entries recording context changes (reranking, table binding). Leaving it
  unblocked at charting was right — none of it needed reconstructing. The real work was fork 4,
  the brief's *separate* "final prompt template" deliverable, which did not exist as anything
  readable: now **`docs/PROMPT_TEMPLATE.md`**, showing both the answering and refusing forms,
  **generated from `src/prompt.py`** with a test that fails on any difference. That discipline
  earned its place — this repo has already been bitten twice by a drifting second copy
  (`frontend/README.md`, and `prompt.py`'s docstring claiming v2 while the code ran v4). Log
  conventions are now stated in its own header, including that an entry unable to say *why* and
  *what it made worse* is not worth writing.

- [05 — RRF k and where fusion happens](issues/05-rrf-k-and-fusion-location.md) — **fusion
  stays server-side; k is now explicit at 60.** The ticket's central fork *dissolved*: it
  assumed (following §6.2) that qdrant-client 1.19.0 exposes no ranking constant, but the same
  version ships **`RrfQuery(rrf=Rrf(k=..., weights=...))`** — so app-side fusion was never
  needed. The defect is confirmed empirically: `FusionQuery(RRF)` returns an identical id-set
  and score multiset to `RrfQuery(k=2)`, so prior art ran **k=2 while its prose claimed 60**.
  Swept 2/10/60/100 plus DBSF: **total spread 0.008–0.023**, and k=60 ≡ k=100 on every metric —
  reproducing Cormack et al.'s own "not critical" finding on this corpus. **DBSF is competitive,
  not better** (+0.003 nDCG), correcting §6.3's speculation. BM25 `b`/`k1` left at defaults with
  a reason: §5.1's 19× document-length argument does not apply to **chunks**, whose length spans
  4×, and measured mean 236 vs the 256 default is an 8% gap.

- [08 — 10-K baseline anchoring for temporal questions](issues/08-temporal-baseline-anchoring.md)
  — **both halves, and they only work together.** `PROMPT_VERSION` → **v7**. Two corrections to
  the premise: the gap is **4.9×** (12,876 vs 2,617 tokens), not §4.4's 12.7×; and the
  regulation is a floor, not practice — **3 of 15 issuers** (META 1.00×, AMZN 0.95×) restate
  their full risk factors quarterly, so a blanket "quarterly is incomplete" rule would be false
  for a fifth of the corpus. The bug is **latent**: the annual section is 5× larger so it wins on
  chunk volume and dominates retrieval unaided — it only fires when the *question* restricts the
  form, where Pfizer measured **1 chunk / 562 tokens** presented as a complete risk profile. Fix
  is correspondingly narrow: a 10-Q scope now admits 10-K *risk-factor* passages only (verified
  no leak — a quarterly *results* question still returns 10-Q only), and those quarterly
  passages are named in the prompt as amendments, because supplying the baseline unlabelled
  makes "newly disclosed this quarter" assertable about a years-old risk. Derived property, not
  a payload field — **no re-embed**.

- [09 — Verifiable citation enforcement](issues/09-citation-enforcement.md) — handles checked
  server-side, reported in `retrieval_meta.citation_check`, **flagged never stripped** (a
  stripped answer looks identical whether or not the check ran, so stripping makes the guarantee
  unobservable — asserted by a test that `verify.py` contains no `replace`/`sub`). Baseline
  measured first: **zero fabricated handles across 13 saved runs**, so this guards a failure that
  has not occurred — worth having because a *checked* claim beats one that has merely held. The
  refusal trap is handled: Shopify returns `n_cited: 0, n_available: 20, verified: true`.
- [12 — All seven deliverables, and a cold start](issues/12-deliverables-and-cold-start.md) —
  **all seven present**, with `README.md` and `example-request.sh` written here. Verified
  mechanically: every `make` target the README names exists, every relative link resolves, quoted
  test counts match collection. **Both of ticket 01's blockers are gone** — `bun dev` works (the
  Node 25 failure was a stale `node_modules`, not an incompatibility), and rather than document
  around the Qdrant volume footgun, the compose file was made self-consistent and **the 972.8 MB
  volume migrated with no re-embedding** — 30,383 points green, now served by `make up` from this
  repo. `frontend/README.md` rewritten; it still described the pre-RAG chat app.

- [13 — The walkthrough](issues/13-walkthrough-and-future-state.md) — **`docs/WALKTHROUGH.md`**:
  six beats, ~20 min, opening on the failure a PE analyst fears rather than on architecture. The
  Shopify refusal is the set piece. Future state is split so the halves land with different people
  — the user's own `docs/future-state.md` list leads (inline citations linking back into the
  filing, CIK/date management, building the eval set from logged queries, streaming), engineering
  items follow. Scripts the honest re-index answer. **Rehearsed on all three panel questions —
  5/5 sections, citations verified, 12–22s — and the rehearsal changed the script twice:** quoting
  exact coverage numbers would have set up a live contradiction (runs returned `JNJ 3 of 17` and
  `JNJ 4 of 17` for the same question), so it now coaches reading the screen and the *shape*; and
  20 seconds of silence needs narrating. Carries a "things not to say" list, every entry of which
  is a plausible claim measured to be false.

- [16 — An evals page in the front-end](issues/16-evals-page.md) — **storage is JSON files, one
  per run, not SQLite**: the harness is Python and `frontend/lib/db/` is deliberately the only SQL
  in the app, so a second runtime writing that schema would mean cross-language migrations for
  data with no relational shape — while the operation that matters, comparing two runs, is what
  files do natively. The enabling fix: `metrics.py` **overwrote a single file**, so history did not
  exist and every before/after table in `docs/EVALUATION.md` had been produced by copying results
  out by hand. Now `<timestamp>--<config>.json`, never overwritten. `/evals` shows configurations
  side by side plus a footer carrying the point that three of the metrics on screen are **not**
  load-bearing. Rendering it caught two bugs `tsc` could not — the delta subtracted backwards,
  and then its "newest − oldest" label implied a progression that the run order does not
  represent. Both were wrong *meaning*, not wrong types.

## Not yet specified

In scope, but not yet sharp enough to ticket. Graduates as the frontier advances.

- **Per-item chunking policy** (§4.2's table). Cannot be specified until
  [02 — Measure what the existing item segmenter actually achieves](issues/02-measure-segmenter.md)
  reports whether item boundaries are reliable enough to chunk against. May graduate into
  one ticket or several.
- **Why reranking hurts sector questions.** [10](issues/10-smoke-eval-and-quality-notes.md)
  measured reranking as better on 8 questions and worse on 4 — and both material regressions are
  sector questions (`sw-01`, `sw-02`), which name no company, so no quotas apply and a single
  unfiltered search gives the reranker the most freedom. Whether that is the reranker, the lack
  of a quota floor, or the three-question sample cannot be told apart at n=22.
- **Per-risk-factor chunking for Item 1A** (Q4). Deferred by [04](issues/04-reranker-and-chunk-size.md):
  most of what it was buying — chunks starting at a semantic boundary — arrived with reflow, and
  §4.3 notes subcaption detection under-counts, so a mis-bounded chunk may be worse than a
  cleanly-cut window. Would need the detector's precision measured against hand-labelled ground
  truth to settle, which §4.3 puts at half a day.
- **A part-level fallback for the 15 filings with no body item headers.** [02](issues/02-measure-segmenter.md)
  established these are not a regex gap — JNJ's 10-Qs structure by `NOTE 11 — LEGAL PROCEEDINGS`
  and never repeat item headers in the body. §2.5's graded fallback (item → **part** →
  whole-document) would give them `PART I` / `PART II` boundaries, which is better than nothing
  for 12 JNJ filings. Real new work; not yet clear whether any demo question needs it.
- **Item 3 Legal Proceedings pointer-chasing** (Q7). Median Item 3 is 57 tokens and
  §229.103 permits it to point elsewhere. The cheap middle path is an `is_pointer: true`
  tag. Not yet clear whether any demo question needs it.
- **Which generation model answers.** `config.py` pins `gpt-4.1`. Dated for an assessment
  demoed in Aug 2026, and it is a one-line change. [11](issues/11-prompt-iteration-log.md) has
  now established what the prompt history depends on: six versions of tuning, three of them
  measured against `gpt-4.1`'s specific failures — v3 exists because instruction adherence
  degraded with distance from the end of the prompt, and v2 because the five-part contract "did
  not take". A newer model might not need v3 at all, or might break v4's refusal. So this is a
  decision plus a re-run of the 28-test gate, not a one-line change — and it is a fair question
  for the panel rather than a defect.
- **Near-duplicate suppression policy.** Prior art suppresses globally before top-k
  (`retrieve.py:159`), which `eval-harness-findings.md` §3 shows is anti-correlated with
  its own recall label. The suppression is probably right and the label wrong — but the
  interaction with the new reranker is unexamined.

## Out of scope

Ruled beyond the destination. Does not graduate; returns only as a fresh effort.

- **XBRL numeric router** (Q1) — routing numeric questions to `data.sec.gov` XBRL facts.
  Cut to future state at charting: a second data path to build, test and explain, against
  a ~4h budget already carrying rerank plus three honesty mechanisms. It becomes the
  strongest item in the future-state narrative the brief asks for. Consequence:
  [06 — Table-caption binding](issues/06-table-caption-binding.md) is now demo-critical,
  because NVIDIA's figures come from pipe-table rows instead.
- **Full eval harness** — 40–60 question golden set, section-level labels, `ItemPrec@k`,
  temporal-scope correctness, 10-row ablation, paired significance test (§7). Exceeds the
  whole timebox on its own. Presented as future state.
- **Self-hosted embeddings and late chunking** (Q2). Managed `text-embedding-3-small`
  embeds the whole corpus for $0.35. The query-confidentiality argument for self-hosting
  is real for a PE firm and belongs in the future-state narrative, not the build.
- **Store re-evaluation** (Q9). Qdrant is already wired in prior art with a compose file.
  Weaviate/Milvus/Postgres comparison is a talking point (§5.4 corrects the SPEC's
  overreach), not a build task.
- **CI automation and deployment.** No GitHub Actions, no hosted demo. The build-time value
  of CI here is identical to the local loop's — the suites already exist, 53 Python tests
  and all 6 frontend suites need no infrastructure, and no layer needs an API key. What a
  pipeline adds over
  [14 — The test loop](issues/14-test-loop-and-fixtures.md) is a badge and a runner to
  debug, neither of which helps the demo. Deployment is a larger surface still — secrets, a
  hosted vector store, CORS, cold starts — and the brief expects a local setup anyway
  (*"You will set up your environment"*). A deployed fallback as demo-day insurance is a
  fair argument and was weighed; it lost on budget. Worth mentioning in the walkthrough as a
  deliberate omission rather than an oversight.
- **Conversational follow-up.** Already a stated non-goal in
  `frontend/app/api/chat/route.ts` — prior turns are deliberately not sent to the backend,
  because feeding uncited assistant output back as context breaks the answer contract.
