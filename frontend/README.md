# LLM Chat

A streaming AI chat app with persistent conversation history. One feature, done
properly: ask a question, watch the answer stream in, and find the conversation
again in the sidebar tomorrow.

- **Chat** — one fixed model, called through the OpenAI SDK. There is no model
  picker: the model is a deployment decision, not a per-message one. Falls back
  to a mock stream when nothing is configured, so the app is usable offline.
- **History** — conversations and messages are stored in SQLite via Node's
  built-in `node:sqlite`. No native module to compile, no extra dependency, no
  service to run.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript · Tailwind CSS v4 ·
shadcn/ui (new-york) · Auth.js v5 (single demo account) · OpenAI SDK · SQLite
(`node:sqlite`).

**Requires Node >= 22.5** for `node:sqlite` (Node 24+ recommended — that is
where `DatabaseSync` became stable). Note that Bun's runtime does not implement
`node:sqlite` as of 1.3, so `bun run --bun dev` will fail; plain `bun run dev`
is fine because it executes Next under Node.

## Getting started

```bash
bun install          # or: npm install
cp .env.example .env
echo "DEMO_PASSWORD=$(openssl rand -base64 24)" >> .env
bun dev              # http://localhost:3000
```

`DEMO_PASSWORD` is the only required value — without it nobody can sign in. With
just that set the app uses a **mock model**, so everything is clickable offline.
See `.env.example` for the rest.

| Task      | Command          |
| --------- | ---------------- |
| dev       | `bun dev`        |
| build     | `bun run build`  |
| test      | `bun run test`   |
| typecheck | `bun run typecheck` |
| lint      | `bun run lint`   |

`bun run test` shells out to `node --test` — see [Tests](#tests).

### The model

`gpt-5.6`, called via `openai.chat.completions.create({ stream: true })`.
`lib/ai/provider.ts` is the only file that talks to a provider, and
`lib/ai/config.ts` holds the model id:

| Env               | Effect                                                        |
| ----------------- | ------------------------------------------------------------- |
| `OPENAI_API_KEY`  | Enables real calls. Unset ⇒ mock stream.                      |
| `OPENAI_MODEL`    | Overrides the model. Defaults to `gpt-5.6`.                   |
| `OPENAI_BASE_URL` | Point at an OpenAI-compatible server instead of OpenAI.       |

The model id is **never accepted from the client** — `POST /api/chat` takes only
a message and a conversation id. It is stamped onto the conversation row from
config as a record of what answered.

Running fully local against LM Studio / vLLM / LiteLLM still works, since those
speak the same Chat Completions API:

```bash
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio   # any non-empty string
OPENAI_MODEL=local-model
```

An unconfigured or unreachable provider degrades to the mock stream rather than
erroring, so the app is always usable. A failure *mid*-stream can't be swallowed
that way, so the reason is appended to the partial answer instead of silently
truncating it.

### Auth

One account — username **`demoadmin`**, password from `DEMO_PASSWORD`. Auth.js v5
with a single Credentials provider and a JWT session; `middleware.ts` gates every
route except `/signin`, the Auth.js routes, and `/api/health`.

There is **no default password**. An unset `DEMO_PASSWORD` disables sign-in
altogether, and the sign-in page says so and prints the command to generate one —
a credential baked into a repo is worse than a demo that refuses to start. The
comparison is length-independent in time, using `TextEncoder` rather than
`node:crypto.timingSafeEqual` because `auth.ts` is bundled into edge middleware.

Set `AUTH_SECRET` in production to sign session cookies; outside production a
clearly-insecure fallback is used so the app runs without one.

History is filed under the account's email and every read and write is scoped by
it (`ownerKey` in `lib/auth.ts`) — a conversation id from one identity pasted into
another's URL bar is a 404, not a leak. That scoping stays a seam rather than
being hardcoded to the demo account, so adding real accounts later doesn't touch
the data layer.

## How history works

`SQLITE_PATH` (default `data/chat.db`) is created on first write, along with its
parent directory. Two tables: `conversations` and `messages`, the latter
cascading on delete.

The flow is deliberately server-authoritative:

1. The client posts **only the new message** plus a conversation id to
   `POST /api/chat`. Prior turns are read from SQLite rather than trusted from
   the request, so the transcript the model sees is always the persisted one.
2. On the first message of a chat there is no id yet — the route creates the
   conversation, titles it from that message (deterministically; naming a chat
   is not worth an LLM call), and returns the id in the `X-Conversation-Id`
   response header, leaving the body pure text.
3. Both turns are written before the response completes. An abandoned stream
   still persists its partial reply, so history never holds a user turn with no
   answer.
4. Once the stream finishes, the client swaps the URL to `/chat/{id}` and
   refreshes so the sidebar picks up the conversation. Navigation happens
   *after* the stream, never during it.

Rename and delete are server actions (`app/chat/actions.ts`) rather than route
handlers, so the conversation list — rendered in the root layout — revalidates in
the same round trip.

## Tests

`bun run test` runs Node's built-in test runner over the SQLite repository and
the sidebar grouping logic:

```bash
node --conditions=react-server --import ./test/setup.mjs --test "lib/**/*.test.ts"
```

Two flags earn their keep: `--conditions=react-server` satisfies the
`server-only` marker import, and `test/setup.mjs` registers a resolver hook for
the `@/` path alias and TypeScript's extensionless imports — both of which Next's
bundler normally provides. Bun's own runner can't be used here because it does
not implement `node:sqlite`.

## Layout

```
app/
  chat/                 New chat (no conversation row yet)
  chat/[id]/            An existing conversation, loaded from SQLite
  chat/actions.ts       Rename / delete server actions
  api/chat/             Streaming chat endpoint — the only writer of history
components/chat/        Composer, message view, markdown, rename/delete dialogs
components/app-sidebar  Conversation history: new chat, grouped list, rename, delete
lib/ai/                 Model id (config.ts), OpenAI streaming call, mock fallback
lib/chat/               Client-safe chat types + sidebar date grouping
lib/db/                 SQLite handle + conversation repository (the only SQL)
test/                   Node test-runner resolver hooks
```

Swapping SQLite for Postgres is a change to `lib/db/` only — nothing above it
writes SQL.
