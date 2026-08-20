# All seven deliverables exist, and a stranger can start the system cold

Type: task
Status: open
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
