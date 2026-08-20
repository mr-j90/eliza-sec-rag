# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **not-yet-implemented** RAG system over SEC filings, built as a timeboxed (~4h) assessment deliverable for a fictitious PE-firm client. Today the repo contains only `SPEC.md` (the full technical spec and build order) and `edgar_corpus/` (246 filings + `manifest.json`). No source, no toolchain, no tests, no git repo yet.

**`SPEC.md` is the authoritative design document — this file exists to execute it, never to override it.** The division of labor:

- **SPEC.md** carries rationale, the business-value narrative, and the demo argument. Read it before writing code, and re-read the relevant section before changing anything it decided.
- **CLAUDE.md** (here) carries the decided parameters in actionable form, plus **measured corpus facts** that resolve SPEC §11's open questions.
- **Where a measured fact below contradicts SPEC.md, the measured fact wins** — those cases are called out explicitly in "Corrections to SPEC.md". Everywhere else, SPEC.md governs. Do not re-litigate its decisions; implement them.

## The hard constraint

**Exactly one LLM API call produces the answer.** Everything else — entity extraction, time-scope parsing, form-type hints, query planning — must be deterministic/rule-based (SPEC §5.2). This is a demo-defensibility constraint, not a performance one: an interviewer will check it. Eval-time LLM-as-judge calls are exempt but must be labeled as such wherever they appear, in code and in the README.

Three things are never cut, whatever the timebox does: the **ablation table**, the **citation contract**, and the **out-of-corpus refusal case**.

## Decided stack (SPEC §2) — do not substitute

| Layer | Choice |
|---|---|
| Dense | OpenAI `text-embedding-3-small`, 1536d, cosine |
| Sparse | BM25 via Qdrant/FastEmbed sparse vectors, **same collection** as dense |
| Store | Qdrant, local Docker, collection `filings`, named vectors `dense` + `sparse` |
| Fusion | Server-side RRF, `k=60` (Cormack default — left at default deliberately, not tuned) |
| Generation | OpenAI `gpt-4.1` (fallback `gpt-4o`) |
| API | FastAPI — `POST /ask`, `GET /health` |

Provider access goes behind a thin `src/llm.py` so a swap is a one-file change. This is a demo talking point ("are we locked into OpenAI?"), so keep it genuinely true rather than nominally true.

## Chunking contract (SPEC §4)

Section-aware first, then recursive: split on SEC item headers, then ~**800 tokens with ~15% overlap** within a section, preferring paragraph → sentence boundaries. Fall back to whole-document chunking when headers don't parse. 800 is a tunable the eval harness can sweep, not a magic number — but don't change the default without a sweep to show.

**Contextual prefix — the highest-leverage piece of the ingest path.** Embed the chunk with a synthesized header prepended; **store raw text separately for display**:

```
Apple Inc. (AAPL) — 10-K, FY2024 (period ending 2024-09-28) — Item 1A Risk Factors:
<chunk text>
```

Every chunk carries this metadata, and it is the retrieval mechanism, not bookkeeping — cross-company questions depend on filtering by it:

```python
{"chunk_id": "AAPL-10K-2024-item1a-0007", "text": ..., "company": ..., "ticker": ...,
 "cik": ..., "form_type": ..., "fiscal_year": ..., "period_end": ..., "filing_date": ...,
 "item_section": ..., "chunk_index": ..., "source_file": ..., "token_count": ...}
```

Drop before chunking: the leading XBRL tag dump (see corpus facts), exhibit indexes, signature blocks, TOC.

## Retrieval contract (SPEC §5)

- **Query understanding is rule-based, no LLM.** Entities via a company/ticker alias dictionary; time scope via regex over years and phrases like "last two years" / "most recent quarter" → `fiscal_year` filter; form hints from "quarterly"/"annual".
- **Entity-quota retrieval is the single most important behavior to get right.** Given *n* detected companies, issue *n* filtered hybrid searches, one per company, each with budget `k/n` (floor ~6). No entities detected → one unfiltered hybrid search at full `k`. Merge, then order context by company → section → date. A global top-k on a comparative question returns whichever company writes the most vivid risk factors; quotas guarantee representation. Measure it with `entity_coverage@k`.
- **RRF runs server-side in one Qdrant query** — `prefetch=[Prefetch(using="dense", limit=40, filter=f), Prefetch(using="sparse", limit=40, filter=f)]`, `query=FusionQuery(fusion=Fusion.RRF)`. Rank-based fusion is chosen specifically to avoid reconciling cosine scores with unbounded BM25 scores; do not replace it with score normalization.
- **Context assembly:** ~40k token budget, near-duplicate suppression (filings repeat language verbatim across quarters — this genuinely fires on this corpus), and each chunk gets the citation handle the model must reuse: `[C3] Apple Inc. (AAPL) | 10-K FY2024 | Item 1A Risk Factors`.

## Answer contract (SPEC §6)

The single call returns five parts: **bottom line** (2–3 sentences) → **per-entity findings** (grouped, every claim carrying `[C#]`) → **comparison table** when comparative → **gaps & confidence** → **sources** (`[C#]` → company, form, period, section).

Non-negotiable prompt rules: answer only from provided context, never from parametric knowledge about these companies; every factual claim carries a handle; a named company with no retrieved context gets an explicit "not in corpus" rather than a substitute; never present a hedge as a finding or vice versa.

**`PROMPT_LOG.md` is a graded deliverable, not a byproduct** — version / what changed / why / observed effect. Start it at prompt v1 and log the failures as they happen; reconstructing it at the end is both visible and wasteful. Expect 4–6 iterations.

## Eval contract (SPEC §7) — the differentiator

- **Golden set ~25 questions:** 6 single-company factual, 8 cross-company comparative, 5 temporal/trend, 3 sector-wide, **3 unanswerable/out-of-corpus** (absent by design — graceful refusal is the highest-value behavior to demo). Label each with relevant `chunk_id`s, or at minimum `source_file` + section.
- **Retrieval metrics:** `Recall@k` for k ∈ {5,10,20}, `MRR@10`, `nDCG@10`, and `entity_coverage@k` (custom — the one that explains to a business audience why the engineering was needed).
- **Ablation table, five rows, run early:** BM25 only → dense only → hybrid+RRF → +entity quotas → +contextual prefix. Results under `eval/results/` are meant to be committed.
- **Answer quality:** deterministic checks every run (every `[C#]` resolves to a real chunk; no ticker appears that isn't in the retrieved set; numeric strings appear verbatim in context), plus LLM-as-judge 1–5 on groundedness / citation precision / completeness / refusal correctness.

## API contract (SPEC §8)

```
POST /ask  { "question": str, "top_k": int = 20 }
→ { "answer": str,
    "citations": [{"id","company","form_type","fiscal_year","section","source_file","excerpt"}],
    "retrieval_meta": {"entities_detected": [...], "n_chunks": int, "latency_ms": {...}} }
```

`retrieval_meta` must be returned **and surfaced in the UI** — showing the panel live which chunks drove the answer is worth more than any architecture slide.

## Corpus facts (measured — these resolve SPEC §11)

Measured against `edgar_corpus/` on 2026-08-19:

- **246 `.txt` filings, 54 tickers, ~82 MB, ≈20M tokens** (chars/4 estimate). Every ticker has at least one 10-K, so no ticker is 10-Q-only (**§11 Q3: resolved, no impact on temporal questions**). Filings per ticker range 1–17 (AAPL/AMZN deepest) — lopsided enough that per-company quotas matter (**§11 Q2**).
- **Filename grammar:** `{TICKER}_{10K|10Q}_[{YYYY}Q{N}_]{FILING_DATE}_full.txt`. The quarter segment is **optional** — exactly 54 files (one 10-K per ticker, the most recent) omit it. Any filename parser must handle both shapes.
- **Per-file metadata comes from a plain-text header block**, not from the manifest and not from parsing the filing body. Every file opens with `Company:`, `Ticker:`, `Filing Type:`, `Filing Date:`, `CIK:`, `Source:`, `URL:`, terminated by a `============...` separator. `Report Period:` and `Quarter:` are present in 192 files and **absent in the same 54** that lack the quarter segment — so `period_end` must be derivable from `Filing Date` as a fallback.
- **`Quarter:` is the calendar quarter of the period end, not the fiscal quarter.** Apple's FY2024 10-K (period ending 2024-09-28) is tagged `2024Q3`. Derive `fiscal_year` from `Report Period` / filing date, never from the quarter tag.
- **Item-header parsing needs care (§11 Q1: fallback is required).** `Item 1A` is line-anchored in only **180 of 246** files but appears somewhere in **245 of 246** — filing text is run together, so section headers land mid-line (`...Item 6.    [Reserved]Apple Inc. | 2024 Form 10-K | 20Item 7.    Management's Discussion...`). An `^Item` anchored regex silently degrades to TOC-only on ~27% of the corpus. Use a non-anchored regex and discriminate TOC rows from real section starts: **TOC rows are pipe-delimited with a page number** (`Item 1A. | Risk Factors | 5`), real body headers are followed by narrative prose. 10-Qs put risk factors under `Part II Item 1A`. **A TOC check alone is not enough — measured 2026-08-19 while building I001.** Filings also contain *cross-references* to their own sections: `"...those discussed in Part I, Item 1A of this Form 10-K under the heading “Risk Factors.”"` in the forward-looking-statements paragraph. It carries no pipe, so it survives TOC discrimination; it sits **earlier** in the file than the real header (char 21521 vs 38099 in `AAPL_10K_2025-10-31_full.txt`); and the text it yields is plausible boilerplate, so structural assertions pass against the wrong section. The fix that excludes TOC rows and cross-references together is to require the **section title adjacent to the item number** — `Item\s+1A\.?[\s\xa0]*Risk\s+Factors` — since a TOC row puts a pipe between them and a cross-reference puts prose between them.
- **Section detection needs four rules, not one — measured 2026-08-19 across all 246 filings while building I004.** Requiring the title adjacent to the item number (above) is necessary but not sufficient. Each of these was found by a wrong result, and the counts are what an `^Item`-style approach costs:
  1. **The pipe is not the discriminator; the trailing page number is.** Apple writes the body header `Item 1A.\xa0\xa0\xa0\xa0Risk Factors`, but **Amazon writes `Item 1A. | Risk Factors`** — pipe and all, identical in form to its own TOC row. Only the absent `| <page>` separates them. Rejecting on the pipe sent **33 of 246 filings (13.4%)** to the fallback. And the page number must be checked **to end of line**: these patterns match a *prefix* of the title, so BAC's `Item 7A. | Quantitative and Qualitative Disclosures about Market Risk | 86` puts it ~50 characters past the match. A 24-character lookahead accepted three TOC rows there, and the resulting span left **425 of 469 chunks mislabelled "Legal Proceedings"**.
  2. **Filings quote their own section names mid-sentence.** PepsiCo's FY2026 10-K contains `“Item 1A. Risk Factors” and “Item 7. Management's Discussion…`, which has the title adjacent, carries no page number, and sits *before* Item 1's real header. An opening quote before the match is the tell.
  3. **The trailing exhibit index re-lists every item.** McDonald's FY2025 10-K matched all six sections inside its last 4k characters. If the first detected header sits past ~90% of the body, the matches are the index, not the body.
  4. **Sections must be matched in document order**, each sought only after the previous one was found. Without it, one early false match leaves a later section swallowing the gap — PepsiCo's Item 3 span ran 282k characters.
- **Coverage is an invariant, and violating it is silent.** An early chunker kept only text *between* detected headers; McDonald's lost **99% of its body** while reporting six tidy sections — a filing that looks indexed and can answer nothing. Chunk the whole body and label unclaimed regions instead. `tests/test_ingest.py` asserts no filing drops below 85% coverage.
- **10-K and 10-Q number their items differently, and 10-Qs are the majority (157 of 246).** A 10-Q's Item 1 is *Financial Statements* (not Business), MD&A is *Item 2* (not 7), and risk factors sit under *Part II Item 1A*. With only a 10-K map, **91 of 157 10-Qs detected no sections at all**. Using both maps: filings with no detection fell from 96 (39%) to **27 (11%)**.
- **Whole-corpus chunking totals (2026-08-19):** 246 filings → **29,499 chunks**, 19.2M tokens, ~**$0.38** to embed with `text-embedding-3-small`. Section mix: Item 8 Financial Statements 30%, 10-Q Item 1 Financial Statements 16%, unlabelled 14%, 10-Q MD&A 14%, 10-K MD&A 7%, Item 1A 6%, Part II Item 1A 5%. Financial-statement tables dominate the index — a retrieval-quality question worth measuring in the ablation rather than guessing at.
- **Leading boilerplate is a large XBRL context dump.** Immediately after the header separator most filings carry thousands of characters of concatenated `us-gaap:` / `0000320193…` tags before real text.

## Corrections to SPEC.md

Five places where the spec and the actual corpus/repo disagree. Follow the correction, and note it in the README rather than silently diverging:

1. **Alias dictionary source (§5.2).** The spec says build it from `manifest.json`; the manifest has no company names — only `file_count`, `filing_types`, and a flat `files` array. Build it from the `Company:`/`Ticker:` header lines instead (`"NVIDIA Corporation" → NVDA`, `"General Electric Company" → GE`).
2. **Date range (§3).** The spec says 2023–2025 (so does the assessment PDF). Filing dates actually span **2015–2026**, and the spread is wider than an outlier story suggests — measured 2026-08-19: `2015:1, 2022:37, 2023:50, 2024:52, 2025:79, 2026:27`. So 65 of 246 filings (26%) fall outside the stated window, including a substantial 2022 block. Temporal golden-set questions and "most recent" resolution must not hardcode 2023–2025.
3. **Corpus path (§8).** Corpus lives at `edgar_corpus/` with `manifest.json` inside it, not `data/raw/` + `data/manifest.json`. Prefer adapting code to the existing path over relocating 82 MB.
4. **Frontend (§8, §11 Q4).** The spec lists `frontend/  # existing` — and as of 2026-08-19 it **does** exist: a Next.js 15 chat app at `frontend/` (see its own README). It was scoped down that day to chat-only (Home / Connections / Workflows removed) with conversation history in SQLite, and its auth reduced to a **single password-gated `demoadmin` account** (Entra SSO, the dev-bypass provider, and all role machinery deleted). `DEMO_PASSWORD` is required — unset disables sign-in rather than falling back to a default, so a fresh clone cannot run until it is set. **It is now wired to the RAG backend** — done under I001 on 2026-08-19, per [D001](.eng/decisions/D001-frontend-proxies-to-ask.md). `POST /api/chat` proxies to FastAPI `POST /ask`; the app makes **no LLM provider calls of its own** and the `openai` dependency has been removed from `package.json`, so `grep -rn "openai" lib app` is clean and the one-call constraint is structural rather than conventional. The `gpt-5.6` / `gpt-4.1` divergence is resolved in favour of §2: the backend owns generation, and the composer's model label is read from the backend's `GET /health` so the UI cannot advertise a model that did not answer. `lib/ai/mock.ts` was deleted — a canned answer that reads as real is the failure the citation contract exists to prevent. Prior turns are deliberately **not** sent to `/ask` (follow-ups are a stated non-goal), though history is still persisted for the sidebar.

Still unmet: the frontend renders assistant turns as markdown but has **no citation or `retrieval_meta` UI** — §8's "surfaced in the UI" requirement is the next route entry, not done. And because `/ask` returns JSON rather than a token stream, the answer arrives as one burst rather than streaming in.

5. **Chunk id shape (§3).** The spec's example `chunk_id` is `AAPL-10K-2024-item1a-0007` — ticker, form, fiscal year, section, index. That collides for any company filing **more than one 10-Q in a fiscal year**, which is most of them: Apple's three FY2022 10-Qs each produced `AAPL-10Q-2022-item1-0002`. Because Qdrant point ids are derived deterministically from the chunk id, the collisions overwrote each other and **8,046 of 29,499 chunks (27%) never landed, with no error** — the loss falling entirely on multi-quarter history, i.e. exactly what temporal questions need. Chunk ids must carry the filing date: `AAPL-10Q-FY2022-2022-04-29-item1-0002`. Point ids are separately derived from `(source_file, chunk_index)`, which is unique by construction. `uv run python -m src.index` now reconciles sent-vs-stored counts and exits non-zero on a mismatch.

## Build order and what to cut

Follow SPEC §10's sequence: profile corpus → ingest/chunk → index → retrieval → prompt v1 + single call → API/frontend → **golden set + eval + ablation** → README and rehearsal. If time runs short, cut in this order: LLM-as-judge answer eval → sector-wide golden questions → SSE streaming.

Toolchain (added 2026-08-19): **uv** + **pytest**, project root at the repo root, `src/` as the package dir (`from src.llm import ...`), tests in `tests/`.

Backend (project root):

| Task | Command |
|---|---|
| install | `uv sync` |
| test | `uv run pytest` |
| test-one | `uv run pytest {path}` |
| vector store up | `docker compose up -d` (Qdrant on **6533**, not 6333) |
| build index (seed filing) | `uv run python -m src.index` |
| build index (all 246) | `uv run python -m src.index --all` |
| rebuild from scratch | `uv run python -m src.index --recreate --all` |
| serve API | `uv run uvicorn src.api:app --port 8000` |
| lint / typecheck / build | none configured |

Frontend (`frontend/`, verified 2026-08-19 — all four green):

| Task | Command |
|---|---|
| install | `bun install` |
| dev | `bun dev` |
| build | `bun run build` |
| test | `bun run test` |
| typecheck | `bun run typecheck` |
| lint | `bun run lint` |

Frontend gotchas worth not rediscovering: chat history uses Node's built-in
`node:sqlite`, so it needs **Node >= 22.5** and cannot run under Bun's runtime
(`bun run --bun dev` fails; plain `bun run dev` is fine since it executes Next
under Node). For the same reason `bun test` cannot run those tests — `bun run
test` shells out to `node --test` with `--conditions=react-server` (satisfies the
`server-only` marker) and a resolver hook in `frontend/test/setup.mjs` (supplies
the `@/` alias). Deleting a route leaves stale `.next/types` behind that fail
typecheck — `rm -rf .next tsconfig.tsbuildinfo` first.

`docker-compose.yml` exists (added 2026-08-19 under I002) and binds Qdrant to host port
**6533**. That is deliberate: another project on this machine has run a Qdrant on 6333, and
colliding fails *silently* — a client connects happily and creates its collection inside a
stranger's instance. `src/index.py` also refuses to write when the target holds collections this
project did not create.

Still missing: the eval entry points (`eval/run_retrieval_eval.py`, `eval/run_answer_eval.py`)
and the golden set. When you add them, add their invocations to the table above — a future
instance has no other way to discover them.

Source assessment prompt: `../AI-RAG Assessment.pdf` (outside this repo). Branding assets: `../branding/`.

## The engineering loop

This repo runs the `/eng-*` loop: read `.eng/HARNESS.md` for the contract, `.eng/STATE.md` for where things stand, and `.eng/config.md` for this repo's verified commands and gates.
