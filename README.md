# SEC filings RAG

Ask a business question about SEC 10-K/10-Q filings and get a cited, structured answer from
**exactly one LLM call**. Indexing, entity resolution, hybrid retrieval, fusion, reranking and
coverage analysis all run before that call; the call itself is one `chat.completions` request.

Corpus: 246 filings from 54 US public companies. The brief says 2023–2025; the filings themselves
span **fiscal years 2014–2025**, which is why nothing here hardcodes that window.

---

## Quickstart

Requires Docker, [uv](https://docs.astral.sh/uv/), and **Node ≥ 22.5** for `node:sqlite`
(tested on 25).

```bash
# 0. secrets — two files, both gitignored. Full variable list further down.
printf 'OPENAI_API_KEY=sk-...\nQDRANT_URL=http://127.0.0.1:6533\n' > .env
printf 'DEMO_PASSWORD=%s\n' "$(openssl rand -base64 24)" > frontend/.env

# 1. the corpus — 246 .txt filings plus manifest.json, into edgar_corpus/
#    (download link is in the assessment brief)

# 2. services and index
make up                              # Qdrant on host port 6533
make index                           # ~15 min, ~$0.40 of embedding calls. Once.

# 3. run it
make answers                         # backend on :8000
cd frontend && bun run dev           # UI on :3000, sign in as demoadmin
```

Then either drive the UI, or:

```bash
./example-request.sh                                   # the panel's comparative question
./example-request.sh "How has NVIDIA's revenue and growth outlook changed?"
```

`make help` lists every target, and [`docs/EXAMPLE_QUESTIONS.md`](docs/EXAMPLE_QUESTIONS.md)
has questions worth asking — grouped by the retrieval behaviour each one exercises, including
the ones where the right answer is a refusal.

---

## The seven deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Setup and run instructions | this file |
| 2 | Indexing and retrieval code | [`src/`](src/) — `ingest` → `chunks` → `embed` → `index`, then `query` → `retrieve` → `rerank` → `prompt` → `llm`, behind `api` |
| 3 | Log of prompt iterations | [`PROMPT_LOG.md`](PROMPT_LOG.md) — the answer prompt v1→v7, written as each change was made, plus the separate eval-summary prompt |
| 4 | Final prompt template | [`docs/PROMPT_TEMPLATE.md`](docs/PROMPT_TEMPLATE.md) — generated from the code, with a test that fails if it drifts |
| 5 | Front-end | [`frontend/`](frontend/) — Next.js, renders the answer with its sources |
| 6 | Example request ready to execute | [`example-request.sh`](example-request.sh) |
| 7 | Notes on how quality was evaluated | [`docs/EVALUATION.md`](docs/EVALUATION.md), and the `/evals` page — a generated summary of every run, with the metrics behind a disclosure |

Design research behind the decisions is in [`docs/research/`](docs/research/), and the
decision-by-decision record with its measurements is in `.scratch/sec-rag-demo/` — one file per
decision, each carrying the measurement that settled it and, where it applies, what the change
made worse.

Where this goes next is [`docs/future-state.md`](docs/future-state.md), and the demo
walkthrough is [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

---

## What the corpus turned out to be like

Every design decision below is downstream of a measurement, not of a preference. The ones that
changed the build most:

| finding | consequence |
|---|---|
| **17.7% of body tokens** are inline-XBRL tag residue — up to 86,721 on one line | stripped before chunking, or ~108 chunks of tag soup per filing enter the index |
| The HTML converter emitted **no block separators** — Tesla's Item 1A is one 90,033-char line | block boundaries are reconstructed; **88.8% → 36.3%** of chunks stopped fusing two blocks, and chunks spanning two *sections* went to **zero** |
| **40.5% of chunks never name their company**, 96.6% never contain the ticker | a company/period/section prefix is embedded with every chunk, or attribution cannot come from similarity |
| **28% of table chunks** carried figures with no stated scale | captions and period headers are bound to their tables — **now 4%** |
| **37 of 246 filings** had the wrong fiscal year | one derivation, from period end rather than filing date. It had also skewed *every* relative date question |
| **18 of 54 issuers** don't end their fiscal year in December | citations show the **period ending**, not a bare `FY2025` that contradicts the excerpt below it |
| JNJ has **17 filings**, ABBV/MRK/LLY/TMO have **1 each** | every answer states what it stands on, in distinct filings |
| Every available reranker truncates at **512 tokens** | measured, not read off a model card — one advertising 8192 does too |

The full research is in [`docs/research/`](docs/research/); how quality was measured is in
[`docs/EVALUATION.md`](docs/EVALUATION.md).

## How a question is answered

```
question
  │
  ├─ entity + period + form resolution ......... deterministic, no model call
  ├─ per-company retrieval quotas .............. every named company gets budget
  │    ├─ dense: text-embedding-3-small
  │    └─ sparse: BM25 (FastEmbed, local)
  ├─ fusion: server-side RRF, k=60 explicit
  ├─ near-duplicate suppression
  ├─ cross-encoder rerank ...................... local, no API call
  ├─ coverage analysis ......................... what the answer stands on
  │
  └─▶ ONE LLM call ─▶ answer ─▶ citation verification
```

**The one-call constraint is structural, not a promise.** The frontend imports no provider SDK
at all — `grep -r openai frontend/` returns nothing outside comments — so it cannot make a
model call even by accident. The backend has exactly one `complete()` call site. Embedding and
reranking are retrieval work that happens *before* that call, the same as a vector search.

**One exemption, and it is fenced off.** `src/eval/summarize.py` makes a generation call to
write the plain-English summary at the top of the `/evals` page. SPEC §5.2 exempts eval-time
calls, and the exemption is enforced rather than asserted: the call sites are counted per tier,
the answer path is proved not to import `src/eval/` at all
(`test_the_answer_path_cannot_reach_the_eval_time_tier`), and the summary is generated from the
command line and cached to disk, so serving the page makes no model call. It is labelled as
generated on the page itself, alongside which model wrote it.

Five behaviours exist to stop a confident wrong answer, each because a measurement showed it
was possible:

- **Out-of-corpus refusal.** A question about a company with no filings is refused by name, and
  produces no findings for anyone else.
- **Coverage statement.** Every answer says what it stands on — `JNJ 3 of 17 filings, MRK 1 of
  1` — because a question about "major pharmaceutical companies" otherwise answers for an
  industry from two companies.
- **Quarterly risk factors labelled as amendments.** A 10-Q's Item 1A carries only material
  changes from the 10-K; unlabelled, an answer built from one presents an amendment as a full
  risk profile.
- **Verified citations.** Every `[Cn]` is checked against what was actually retrieved. Handles
  that resolve to nothing are flagged, never quietly removed.
- **A period the corpus lacks is refused by period.** Ask what Apple disclosed in 2010 and the
  answer names the scope that emptied the result and the years the corpus actually covers,
  rather than answering from the nearest available filing. No model call is made — with no
  passages, a generated answer could only come from the model's own knowledge of the company.

---

## Testing

```bash
make test          # 249 python + 54 frontend. No Docker, no API key, no cost. ~18s
make test-live     # 31 tests needing a key. 11 make REAL generation calls — costs money
make check         # typecheck + lint
make eval          # retrieval metrics over the golden set, then the /evals page summary
make eval-summary  # just the page summary. One eval-time call, cached
```

`make test` **deselects** the paying tier rather than skipping it, so a green run reports
`249 passed, 31 deselected` — a claim you can read. A suite that quietly skipped its
answer-path tests would report green while testing nothing.

`make test-live` refuses to run without a key rather than skipping 31 tests and exiting 0.

---

## Configuration

Backend `.env` (repo root):

| variable | default | notes |
|---|---|---|
| `OPENAI_API_KEY` | — | **required** for embedding and generation |
| `QDRANT_URL` | `http://127.0.0.1:6533` | not 6333 — see `docker-compose.yml` |
| `RAG_GENERATION_MODEL` | `gpt-4.1` | the prompt was tuned against this model |
| `RAG_RRF_K` | `60` | fusion constant, set explicitly |
| `RAG_FUSION` | `rrf` | `dbsf` for score-magnitude fusion |
| `RAG_RERANK` | `1` | `0` disables the cross-encoder |
| `RAG_CORPUS_DIR` | `./edgar_corpus` | |

Frontend `frontend/.env`:

| variable | notes |
|---|---|
| `DEMO_PASSWORD` | **required** — no default, and sign-in is disabled without it |
| `AUTH_SECRET` | set in production |
| `RAG_API_URL` | defaults to `http://127.0.0.1:8000` |

---

## Things that will bite you

**Node version.** Requires **≥ 22.5** for `node:sqlite`. If `bun run dev` fails with
`Cannot find module '../server/require-hook'`, `node_modules` is partially installed — run
`bun install` to repair it. (That error was initially mistaken here for a Node 25
incompatibility; it isn't, and Node 25 works.) Note `bun run --bun dev` never works — Bun's
runtime does not implement `node:sqlite`; plain `bun run dev` runs Next under Node.

**Qdrant port 6533, not 6333.** Deliberate. Another project on the author's machine binds 6333,
and the collision fails *silently* — a client connects happily and writes into a stranger's
instance. `index.py` also refuses to write to a Qdrant holding collections it did not create.

**A fresh `make up` gives you an empty index.** `make index` is a one-time ~15-minute run. Until
then `/ask` returns 503 saying exactly that, rather than an empty answer. Check what you have
with `curl -s localhost:8000/health` — it reports the chunk count.

**Sign-in.** One account, `demoadmin`, password from `DEMO_PASSWORD`. There is deliberately no
default: a credential baked into a repo is worse than a demo that refuses to start.

**No mock fallback.** If the backend is down the UI says so and names the command to start it.
It will not show a fabricated answer — during a demo that is the worst possible failure, because
the operator believes it is real.

---

## Known limitations

Stated here rather than discovered in a review. Each is measured; see `docs/EVALUATION.md` and
`docs/research/`.

- **15 of 246 filings have no detectable item sections** — JNJ's 10-Qs structure by
  `NOTE 11 — LEGAL PROCEEDINGS` rather than by item. Their text is still indexed and
  retrievable, under `Unlabelled section`.
- **The reranker sees the first 512 tokens** of each passage. Every reranker FastEmbed exposes
  truncates there, so 26.8% of indexed text does not influence ranking. It still reaches the
  model in full.
- **The golden set is 22 scored questions** — too small for the ablation this deserves. Results
  are reported as directional, with per-question win/loss/tie rather than means alone.
- **Numeric answers come from table rows**, not from XBRL facts. Captions and period headers are
  bound to their tables so figures keep their scale, but routing numeric questions to
  `data.sec.gov` would be more precise. That is the top item of future state.
- **No sector taxonomy.** For "major pharmaceutical companies" the system reports the companies
  it stood on, but cannot name the ones it *should* have consulted and missed.
- **The corpus is a fixed snapshot.** Relative dates anchor to the newest filing in it (2025),
  not to today, so "the last two years" stays meaningful as the snapshot ages.
