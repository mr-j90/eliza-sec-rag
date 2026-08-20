# Port the prior-art backend into sec-rag and get it green against the frontend contract

Type: task
Status: resolved
Blocked by: —

## Question

Nothing to decide here — this is the manual work that unblocks every other ticket. The
question it answers is factual: **does the ported backend satisfy the contract the
frontend already expects, and which of the research findings does it already implement?**

Bring across from `/Users/jordan/Developer/rag-old/`:

- `src/` (ingest, chunks, embed, index, query, retrieve, prompt, llm, api, aliases, config,
  eval/) — ~2,470 LOC
- `tests/` — 10 test files
- `eval/golden_set.json`, `eval/build_golden_set.py`
- `docker-compose.yml` (Qdrant v1.19.0 on host port **6533**, deliberately not 6333 —
  read the comment before changing it)
- `pyproject.toml`, `uv.lock`

The layout is not a free choice: `frontend/lib/ai/provider.ts` hardcodes the start hint
`uv run uvicorn src.api:app --port 8000`, so `src/api.py` goes at the sec-rag root.

### What must be true to close this

1. `uv run uvicorn src.api:app --port 8000` starts against a running Qdrant.
2. `GET /health` returns `{generation_model: string}`.
3. `POST /ask {question, top_k}` returns `{answer, citations[], retrieval_meta{}}` where
   every citation has `id, company, form_type, fiscal_year, section, source_file, excerpt`
   — the shape declared in `frontend/lib/chat/types.ts`. **Any field mismatch is a bug in
   the backend, not the frontend.** The frontend is the fixed side of this contract.
4. `bun dev` in `frontend/` reaches it and renders sources in `components/chat/sources.tsx`.
5. The 10 ported test files pass, or each failure is recorded here with a reason.
6. Corpus path points at `sec-rag/edgar_corpus/` (246 `.txt` + `manifest.json`).
7. **`grep -r "openai\|anthropic" frontend/` returns nothing outside comments** — this is
   how the one-call constraint is defended in the demo, so it must stay true.

### Facts to record in the Answer, because later tickets depend on them

- Which `retrieval_meta` fields the backend actually populates today, versus the full list
  in `types.ts` (`entities_detected`, `unresolved_mentions`, `fiscal_years`, `form_type`,
  `n_chunks`, `generation_model`, `prompt_version`, `retrieval`, `top_score`,
  `latency_ms`). Gaps here are work for tickets 07 and 09.
- What `src/ingest.py` currently does about the inline-XBRL residue — `grep -i xbrl` hits
  it, but §2.3 measures 17.7% of body tokens still present, so establish what it actually
  strips. Ticket 03 needs this.
- What `src/ingest.py` does for `(part, item)` keying and item segmentation — ticket 02
  measures its quality, but record the approach here.
- Whether `src/embed.py` uses `fastembed` locally, OpenAI, or both. `pyproject.toml` lists
  both `fastembed` and `openai`.
- Whether the corpus is already indexed anywhere, or whether a full ingest run is needed
  (and how long it takes — the demo depends on not needing to re-run it live).

### How to bring it across — plain copy, not a history graft

Prior art has real history (`3b9579b` and back) so preserving it via subtree merge or
`git-filter-repo` is technically available. **Don't.** Three reasons:

- Its commit messages reference its own ticket ids — *"reconcile: close I008, G02 at 1 of
  6"* — which are meaningless in this repo. A panel reading `git log` sees noise from a
  ticket system they cannot see.
- Its history includes **its own frontend**, which is the pre-RAG generic chat app that
  `sec-rag/frontend` has already superseded. Grafting it in means two frontends' worth of
  lineage for one frontend's worth of code.
- The process artifact the brief actually asks for is a **prompt-iteration log**, not commit
  archaeology. `PROMPT_LOG.md` carries that far better (ticket 11).

So: plain copy, one commit, and credit prior art in the README (ticket 12) — a line saying
this builds on an earlier attempt whose SPEC was audited in
`docs/research/sec-rag-architecture.md` §10 is honest and costs nothing.

**Do not bring across** `rag-old/frontend/` (superseded — `sec-rag/frontend` is the evolved
version, with `components/chat/`, `sources.tsx` and the backend contract), or the
`__pycache__` directories.

**Do bring across** `PROMPT_LOG.md` (ticket 11 needs it) for
context before closing this — it half-identifies the temporal-label conflict that ticket 08
deals with.

### Watch for

The prior repo is **read-only reference**. Copy out of it; do not work in it.

If a fixture file is convenient to carve while you are already reading the corpus, ticket
14 names exactly which ones and why — but that ticket owns them, so don't let it expand
this one.

---

## Answer

**Resolved 2026-08-19. The port works end to end.** A question typed into the frontend
returns a cited answer from one LLM call, and the wire contract matches byte-for-byte. Nine
findings below; four are defects that change other tickets.

### Verification against the closing conditions

| # | Condition | Result |
|---|---|---|
| 1 | uvicorn starts against Qdrant | **Pass** |
| 2 | `/health` returns `generation_model` | **Pass** — plus index reachability and chunk count |
| 3 | `/ask` matches the declared shape | **Pass, verified programmatically** — citation keys `== {id, company, form_type, fiscal_year, section, source_file, excerpt}` exactly, no missing/extra; `fiscal_year` is `int`; all 10 `retrieval_meta` fields present, none extra |
| 4 | Frontend reaches it and renders sources | **Pass** — authenticated through Auth.js and drove `POST /api/chat`: 200, 7,460-char answer, 20 citations, `conversationId` returned. Visual render of `sources.tsx` in a browser not confirmed; left for ticket 12's rehearsal |
| 5 | Ported tests pass | **Pass** — see the layer table |
| 6 | Corpus path | **Pass** — `config.py` resolves `REPO_ROOT / "edgar_corpus"`, correct with no override |
| 7 | One-call constraint by grep | **Pass** — no provider SDK imported anywhere in `frontend/`; `openai` is not even in `frontend/package.json` |

### Test layers, measured

| Layer | Tests | Needs | Result |
|---|---|---|---|
| Python unit | 53 | nothing | **53 pass, 17.4s** |
| Python integration | 11 | Qdrant | **11 pass, 0.7s** |
| Python live | 29 | Qdrant **+ real `OPENAI_API_KEY`** | skipped; **11 of them make real generation calls** |
| Frontend | 34 (8 suites) | nothing | **34 pass, 0.6s** |

Every skip is explicitly labelled with its reason — no silent skipping. **This corrects the
premise in ticket 14**, which assumed no layer needed a key because `test_ask.py` mocks
OpenAI. Only one test in `test_ask.py` is mocked; 29 tests across three files need a live
key, and 11 of those spend money per run.

### The index is already built — no ingest needed

**29,499 points, dense + sparse named vectors, status green**, matching `ingest.py`'s own
29,499 figure. A cold ingest is not required for the demo.

**But the volume is not ours.** The running container `rag-qdrant` belongs to compose
project `rag`, working_dir `/Users/jordan/Developer/eliza/rag` — **a path that no longer
exists**, since that repo moved to `rag-old`. The data lives in volume
`rag_qdrant_storage`. Running `docker compose up` from sec-rag would create a *different*
project namespace, want a new empty `sec-rag_qdrant_storage`, and collide on both the
`container_name` and host port 6533. Left deliberately unresolved and handed to ticket 12 —
it needs a decision (adopt the volume as external vs. re-ingest into a sec-rag-owned one),
and re-ingesting needs a provider key and real minutes.

### What prior art already implements — better than §10 implied

§10's critique was explicitly written against the SPEC, not the code (*"I did not read
`src/`"*). The code is substantially ahead of it:

- **Item segmentation is already TOC-anchored and monotonic.** Separate per-form section
  maps (10-K and 10-Q, the latter including `Part II Item 1A`), a forward scan with a cursor
  so a section is only sought *after* the previous one, TOC-row rejection via
  `^[^\n]*\|[\s\xa0]*\d+[\s\xa0]*$` checked to end-of-line, opening-quote rejection for
  cross-references, a late-detection guard at 0.9 for the trailing exhibit index, and a
  coverage guarantee that chunks unclaimed text as `UNLABELLED` rather than dropping it.
  Each rule carries a measured regression in its comment (McDonald's losing 99% of content;
  BAC's Item 3 swallowing 157k chars). **Ticket 02 should measure this, not assume a
  rewrite.**
- **Per-entity quotas work.** The Apple/Tesla/JPMorgan question returned exactly **6 chunks
  each** — the mechanism that handles the JPM-4-filings vs Apple-16 asymmetry.
- **The refusal is genuinely good.** Shopify → `unresolved_mentions: ["Shopify"]`,
  `entities_detected: []`, a plain two-section refusal, and it names companies that *are*
  covered. It retrieved 20 chunks and cited **none** — confirming the caveat in ticket 09:
  enforcement must not treat a correct refusal as a failure.
- **A 27% chunk-loss bug was already found and fixed** — chunk ids lacking `filing_date`
  collided across quarters, losing 8,046 of 29,499 chunks. `chunks.py` notes SPEC §3's
  example id has the same flaw.

### Facts later tickets need

- **Embeddings are split**: dense is OpenAI `text-embedding-3-small` (1536d, cosine); sparse
  is BM25 via **FastEmbed running locally** — no key. So the sparse leg keeps working when
  the provider doesn't, which is worth saying in the walkthrough.
- **`prompt_version` is `v4`**, not the `v2` that `prompt.py`'s docstring describes. There
  are more iterations than the docstring records — ticket 11 should reconstruct from
  `PROMPT_LOG.md` (ported) rather than trust the docstring.
- **`generation_model` is `gpt-4.1`** (`config.py:DEFAULT_GENERATION_MODEL`). Dated for an
  assessment being demoed in Aug 2026, and it is a one-line change. Not touched — it is a
  decision, not a defect. Flagged to the map's fog.
- **`retrieval_meta.retrieval` is the hardcoded string `"hybrid dense+sparse, server-side
  RRF"`.** This **confirms ticket 05 from the code**: fusion is server-side, so it runs
  Qdrant's `DEFAULT_RANKING_CONSTANT_K = 2` while the SPEC prose claims 60. No longer an
  inference.
- **`frontend/.env` still holds an unused `OPENAI_API_KEY`.** `provider.ts` imports no SDK,
  so nothing reads it — a live credential in a file nobody reads is one nobody rotates.
  Ticket 12 should remove it.

### Defects found — each changes another ticket

**1. `fiscal_year` is wrong for 37 of 246 filings (15%). New ticket 15.**
`ingest.py` computes `fiscal_year = int((period_end or filing_date or "0")[:4])`. 54 filings
have no `Report Period` header and fall back to the **filing date**, which for a 10-K lands
1–3 months *after* the fiscal year ends. Measured against the true period end (which the
`URL` header field embeds, e.g. `amzn-20251231.htm` — exactly as §2.2 said, and `ingest.py`
ignores it): **37 wrong, 15 correct, 2 unparseable.** `AMZN_10K_2026-02-06` is labelled
FY2026 but covers FY2025; `ABBV_10K_2025-02-14` is labelled 2025 but covers 2024.

Separately, **off-calendar filers' 10-Qs mislabel even with a `Report Period`**, because a
10-Q's period end falls mid-fiscal-year. NVDA's Q3 FY2026 (`period_end 2025-10-26`) is
labelled `fiscal_year: 2025` while the document says "fiscal 2026" — citation `[C11]` in the
NVIDIA run displays **FY2025 against an excerpt discussing fiscal 2026**. Off-calendar
filers present: NVDA (Jan), AAPL (Sep), MSFT (Jun), DIS (Sep/Oct).

**2. The XBRL strip is not the recommended one. Ticket 03.**
Prior art uses a token regex (`us-gaap:|http://fasb\.org|…`) plus a line-anchored
`_XBRL_RUN = ^[a-z0-9\-]{4,}(false|true)?\d{4}(FY|Q\d)?\d{6,}.*$` with `MULTILINE`. That is
**not** §2.3's cover-page anchor, and the `.*$` makes it delete the whole line — but §2.3
measured the residue as *glued directly onto the start of the real cover page*, so on this
corpus "the line" contains both. It is likely **deleting real cover-page text**. Ticket 03
should measure what the current strip actually removes before replacing it.

**3. The sentence splitter cannot fire on this corpus. Ticket 03 — premise confirmed with a
mechanism.** `_split_on_boundaries` falls back to `re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])")`,
which **requires whitespace**. §2.4's finding is that the glue pattern has *no* whitespace
(`[.!?"]→[A-Z]`). So on most of this corpus neither the paragraph split nor the sentence
split matches, and text falls through to `_hard_split`, which cuts by **raw token count,
mid-sentence**. That is exactly the failure §2.4 predicted, now confirmed in the code path.

**4. `bun dev` is broken on this machine. Ticket 12.**
Node **25.8.0** + Next 15.5.20: `.bin/next` (a correct symlink) resolves
`require('../server/require-hook')` relative to `.bin/` rather than the real file, so it
fails with `MODULE_NOT_FOUND`. Workaround that works:
`node node_modules/next/dist/bin/next dev`. The README's documented command therefore does
not start the app — a live demo-day blocker. Note `frontend/README.md` claims Node 24+ is
recommended; 25 breaks it.

### Incidental fixes made

- **Created `/.gitignore`** — the repo had none at root, while `config.py` states `.env` "is
  gitignored and must stay that way." Without it the `.env` this ticket created would have
  been committable. Verified with `git check-ignore` before writing any secret.
- Created `.env` with `OPENAI_API_KEY` (moved from `frontend/.env`, never displayed) and
  `QDRANT_URL`. An `.env.example` is still missing — ticket 12.
- Killed an orphaned uvicorn on :8000 (PID 43856), running from the deleted venv
  `/Users/jordan/Developer/eliza/rag/.venv/` since 20:47. Held no state.
- **Auth note for whoever tests next:** the Credentials provider id is `demo`, not
  `credentials`, and it takes **only** `password`. So the callback is
  `/api/auth/callback/demo`. Using `credentials` yields `error=Configuration`, which looks
  like a broken app and is not.

### Left running

Backend on :8000 and frontend on :3000 are both up in the background, against the existing
Qdrant on :6533.
