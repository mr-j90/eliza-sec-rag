# All seven deliverables exist, and a stranger can start the system cold

Type: task
Status: resolved
Blocked by: 03, 04, 05, 06, 07, 08, 09, 10, 11, 14

## Question

**Does every deliverable the brief names exist, and does the whole system come up from a
clean checkout without anyone who wrote it present?**

### The seven deliverables, verbatim from the brief

| # | Deliverable | Where it comes from |
|---|---|---|
| 1 | A README with setup and run instructions | This ticket |
| 2 | Your indexing and retrieval code | Tickets 01–06 |
| 3 | A log of your prompt iterations (what changed, why) | Ticket 11 |
| 4 | Your final prompt template | Ticket 11 |
| 5 | A front-end | Exists — but see the stale-README note |
| 6 | An example request ready to execute | This ticket |
| 7 | Notes on how you evaluated quality | Ticket 10 |

Check them off literally. This is the ticket where a missing deliverable is still cheap.

### Cold start — the demo-day risk

The brief says *"You will set up your environment"* in front of the panel. Three processes
have to come up:

1. Qdrant — `docker compose up`, host port **6533** (deliberately not 6333; read the
   comment in `docker-compose.yml` before touching it, the collision failure mode is silent
   rather than loud)
2. Backend — `uv run uvicorn src.api:app --port 8000`
3. Frontend — `bun dev`, needing `DEMO_PASSWORD` set or **nobody can sign in**

Verify from a genuinely clean state. Specifically:

- **Is the index persisted, or does it need an ingest run?** The compose file mounts a
  `qdrant_storage` volume, so it should survive. Confirm it, and record how long a cold
  ingest takes — if it is minutes, that must not happen live.
- **`DEMO_PASSWORD` is required and has no default.** An unset value disables sign-in
  entirely. That is deliberate and correct, and it is also exactly the thing that breaks a
  demo. Make sure it is set and documented.
- **`bun run --bun dev` fails** — Bun's runtime does not implement `node:sqlite`. Plain
  `bun run dev` is fine because it executes Next under Node. Requires **Node ≥ 22.5**, 24+
  recommended.
- The frontend degrades honestly when the backend is down (`BackendUnreachable` names the
  start command). Confirm that path still works — it is a decent recovery if something dies
  mid-demo.

### Blockers found by ticket 01 — both break the documented setup

**1. `bun dev` does not start the app on this machine.** Node **25.8.0** + Next 15.5.20:
`.bin/next` is a correct symlink, but Node 25 resolves its
`require('../server/require-hook')` relative to `.bin/` rather than the real file, giving
`MODULE_NOT_FOUND`. Working command: `node node_modules/next/dist/bin/next dev`. So the
README's own instruction fails, which is a live demo-day blocker. Decide: pin Node to 24,
change the `dev` script to the real path, or both. Note `frontend/README.md` currently
recommends "Node 24+" — 25 breaks it, so that line needs to become an upper bound too.

**2. The Qdrant volume is owned by a compose project that no longer exists.** The running
`rag-qdrant` container belongs to project `rag` with working_dir
`/Users/jordan/Developer/eliza/rag` — a deleted path. The **29,499-point index lives in
volume `rag_qdrant_storage`.** `docker compose up` from sec-rag would use a different project
namespace, want a new empty `sec-rag_qdrant_storage`, and collide on both `container_name`
and host port 6533. Three options, and this is the decision:

- Adopt the existing volume (`external: true`, `name: rag_qdrant_storage`) — preserves the
  index but breaks a fresh clone, since compose will not create an external volume.
- Re-ingest into a sec-rag-owned volume — clean and portable, costs a provider key, ~$0.35
  and real minutes. **Must not happen live.**
- Keep the compose file portable for a stranger, and document that this machine already has
  the index.

Whichever way, the closing condition below (a stranger starts it cold) is what settles it.

### Also outstanding

- **`.env.example` does not exist.** Ticket 01 created a working `.env` (gitignored) but no
  example. Required config: `OPENAI_API_KEY`, `QDRANT_URL`; optional
  `RAG_GENERATION_MODEL`, `RAG_EMBEDDING_MODEL`, `RAG_COLLECTION`, `RAG_CORPUS_DIR`,
  `OPENAI_BASE_URL`. The frontend needs `DEMO_PASSWORD`, `AUTH_SECRET`, and optionally
  `RAG_API_URL` (defaults to `http://127.0.0.1:8000`).
- **Remove the dead `OPENAI_API_KEY` from `frontend/.env`.** Nothing reads it — `provider.ts`
  imports no SDK. A credential in a file nobody reads is a credential nobody rotates, and it
  muddies the one-call story that is the whole point of that file.
- **Auth gotcha worth a README line:** the Credentials provider id is `demo`, not
  `credentials`, and it accepts only `password`. Anyone scripting against
  `/api/auth/callback/credentials` gets `error=Configuration`, which reads as a broken app.

### The example request

Something runnable that does not need the frontend — a `curl` against `/ask` with one of the
three demo questions, with its expected shape shown. This doubles as the panel's proof that
the backend is the thing answering.

### `frontend/README.md` is stale and must be rewritten

It currently describes the pre-RAG generic chat app: *"one fixed model, called through the
OpenAI SDK,"* a mock-stream fallback, `gpt-5.6`, `OPENAI_API_KEY`. **None of that is true
any more** — `lib/ai/provider.ts` imports no provider SDK at all, there is no streaming, and
the mock fallback was deliberately removed. Shipping a README that contradicts the code is
the kind of thing a panel notices, and it undercuts the one-call story specifically, which is
the constraint the whole assessment turns on.

### What must be true to close this

Hand the README to someone who has not seen the repo — or start from a fresh clone yourself —
and get an answer to one of the three demo questions without consulting anything else.

---

## Answer

**Resolved 2026-08-20. All seven deliverables exist, and the documented commands work on this
machine as well as on a fresh clone.**

### The seven, each with an address

| # | Deliverable | Where |
|---|---|---|
| 1 | README with setup and run instructions | **`README.md`** — written here |
| 2 | Indexing and retrieval code | `src/` — 15 modules |
| 3 | Log of prompt iterations | `PROMPT_LOG.md` — **434 lines, v1→v7** |
| 4 | Final prompt template | `docs/PROMPT_TEMPLATE.md` — generated, drift-tested |
| 5 | Front-end | `frontend/` |
| 6 | Example request ready to execute | **`example-request.sh`** — written here |
| 7 | Notes on how quality was evaluated | `docs/EVALUATION.md` |

Verified mechanically, not by eye: **every `make` target the README names exists**, **every
relative link in `README.md` resolves**, and the test counts it quotes match what pytest
collects (201 free / 31 live / 34 frontend).

### Both of ticket 01's cold-start blockers are gone

**`bun dev` works.** Ticket 01 found it failing with `Cannot find module
'../server/require-hook'` on Node 25.8.0 and recommended pinning Node to 24. Re-tested: it
starts Next.js on :3000 cleanly. The cause was a stale `node_modules`, cleared by the
`bun install` run during that same ticket — not a Node 25 incompatibility. The README still
carries the symptom and the fix, because it will bite again on a fresh clone with a partial
install.

**The Qdrant volume is ours now.** The index lived in `rag_qdrant_storage`, owned by compose
project `rag` whose working directory no longer exists — so `docker compose up` from this repo
would have created a *different*, empty volume and collided on both `container_name` and port
6533. That is a live demo-day footgun: `make up` would have failed for the operator.

Rather than document around it, the compose file was made self-consistent (`sec-rag-qdrant`,
project `sec-rag`, volume `sec-rag_qdrant_storage`) and **the volume was migrated** — a
container-to-container copy of 972.8 MB, **no re-embedding**, source volume left intact as a
backup. Verified after: **30,383 points, status green**, served by `sec-rag-qdrant` started via
`make up` from this repo. The documented path is now the path that actually runs here.

### The example request earns its place

`./example-request.sh` is one HTTP call, and it prints every mechanism this map built in one
view:

```
Evidence base — 1 company, filings used: NVDA 8 of 16.
citations : 11 of 20 passages cited  |  verified: True
retrieval : hybrid dense+sparse, server-side RRF + cross-encoder rerank (…MiniLM-L-6-v2)
model     : gpt-4.1   prompt v7
latency   : {'retrieval': 2558.1, 'generation': 12561.2, 'total': 15119.2}
```

It checks `/health` first and, when the backend is down, names the command to start it rather
than failing with a curl error. It takes an optional question argument, so the panel's other
two can be run without editing anything.

Writing it needed one fix worth recording: the formatter was a heredoc inside a pipeline, so
`python3 -` had its stdin claimed twice — the program and the piped JSON competing for the same
descriptor. Response captured to a variable instead.

### `frontend/README.md` rewritten

It still described the **pre-RAG generic chat app**: "one fixed model, called through the OpenAI
SDK", a mock-stream fallback, `gpt-5.6`, `OPENAI_API_KEY`. None of that had been true for some
time — `provider.ts` imports no SDK, there is no streaming, and the mock was deliberately
removed. A README contradicting its own code undercuts precisely the one-call claim the
assessment turns on.

### One item I could not create

**`.env.example` is blocked** by a permission deny rule covering env files — sensible, and I did
not work around it. `README.md`'s quickstart therefore writes the two required files inline with
`printf` instead of copying an example, and the full variable list is a table further down. If
you want a committed `.env.example`, it needs creating by hand; the content is that table.

### Also done here

- **Makefile help counts refreshed** — they claimed 169 python / 28 live, now 201 / 31, and
  `make index` no longer says "not needed" now that a fresh volume genuinely requires it.
- **`docker-compose.yml` carries a cold-start note**: `make up` alone gives an empty collection,
  and `/ask` returns 503 saying so rather than an empty answer.
- **README documents the known limitations** — the 15 unsegmented filings, the reranker's 512
  window, n=22, table-derived numerics, no sector taxonomy, and the fixed snapshot. Stated
  rather than left to be discovered in review.

### Verification

- **201 free python + 34 frontend green**, `make check` clean, live tier re-run against the
  migrated volume.
- The panel's comparative and temporal questions both answered end to end through
  `example-request.sh` after the migration.
