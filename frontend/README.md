# Front-end

The answer surface for the SEC filings RAG system. Start here: [`../README.md`](../README.md).

Next.js 15 (App Router) · React 19 · TypeScript · Tailwind v4 · shadcn/ui · Auth.js v5 ·
SQLite via `node:sqlite`.

```bash
bun install
# create .env with DEMO_PASSWORD set, or nobody can sign in
bun run dev                   # http://localhost:3000
```

| task | command |
| --- | --- |
| dev | `bun run dev` |
| build | `bun run build` |
| test | `bun run test` (34 tests, `node --test`) |
| typecheck | `bun run typecheck` |
| lint | `bun run lint` |

## This app makes no model calls

`lib/ai/provider.ts` imports **no provider SDK**, and `openai` is not in `package.json`. The
app `POST`s a question to the Python backend, which makes exactly one LLM call and returns the
answer with its citations. That is what makes the one-call constraint checkable by `grep`
rather than by trust — and it is why there is no model picker: the model is a deployment
decision, read from the backend's `/health`, not a per-message one.

`POST /api/chat` takes only a message and a conversation id. The response is **JSON, not a
stream** — `/ask` produces a finished answer in one piece, and re-emitting it through a
`ReadableStream` would only make it look like tokens while leaving nowhere to put the
citations.

**There is no mock fallback.** An earlier version degraded to a canned stream so the app was
always clickable. Once the *backend* is what's missing, that same kindness shows a fabricated
answer during a demo while the operator believes it is real. An error naming the start command
is worth more.

## What the answer panel shows

`components/chat/sources.tsx` renders more than a source list, and each element is there
because a measurement showed it was needed:

- **Provenance per passage** — company, form, *period ending* (not a bare fiscal year: for the
  18 of 54 issuers whose year does not end in December, a `FY2025` label sat directly above an
  excerpt naming a different year), section, excerpt, source file.
- **Coverage** — what the answer stood on, counted in distinct filings rather than passages.
  Amber when a company rests on a single filing.
- **Verified citation count** — from the backend's server-side check, not from parsing the
  answer. A handle that resolves to nothing is flagged in red, never silently removed.
- **Retrieval provenance** — the pipeline that actually ran, so a reader can tell whether
  reranking happened rather than assuming it did.

## History

Conversations and messages live in SQLite (`SQLITE_PATH`, default `data/chat.db`), created on
first write. Prior turns are **not** sent to the backend: each question is retrieved and
answered independently, because feeding uncited assistant output back as context would put
unsourced text in front of a model whose first rule is to answer only from cited passages.

History is filed under the signed-in identity and every read and write is scoped by it, so a
conversation id from one identity pasted into another's URL bar is a 404, not a leak.

## Auth

One account — `demoadmin`, password from `DEMO_PASSWORD`. **No default**: an unset password
disables sign-in entirely and the page says so. A credential baked into a repo is worse than a
demo that refuses to start.

Note for anyone scripting against it: the Credentials provider id is `demo`, not `credentials`,
and it accepts only `password`. Posting to `/api/auth/callback/credentials` returns
`error=Configuration`, which looks like a broken app and is not.

## Layout

```
app/chat/                 new chat, and /chat/[id] for an existing one
app/chat/actions.ts       rename / delete server actions
app/api/chat/             the only writer of history; calls the backend
components/chat/          composer, message view, markdown, sources panel
lib/ai/provider.ts        the only file that talks to the backend
lib/chat/types.ts         the wire contract, shared by client and server
lib/db/                   SQLite handle + conversation repository (the only SQL)
```

Swapping SQLite for Postgres is a change to `lib/db/` only.
