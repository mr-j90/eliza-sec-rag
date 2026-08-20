import "server-only";

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";

/**
 * SQLite handle for chat history, using Node's built-in `node:sqlite` — no
 * native module to compile, no extra dependency. Requires Node >= 22.5
 * (`DatabaseSync` is stable as of Node 24).
 *
 * Everything that touches SQL lives in `lib/db/`; the rest of the app talks to
 * the repository functions in `lib/db/conversations.ts`. Swapping SQLite for
 * Postgres is a change to this directory only.
 */

const DEFAULT_PATH = "data/chat.db";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS conversations (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  title      TEXT NOT NULL,
  model      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS conversations_by_user
  ON conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL
                  REFERENCES conversations (id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content         TEXT NOT NULL,
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS messages_by_conversation
  ON messages (conversation_id, id);
`;

/**
 * Columns added after the first release, as (table, column, definition).
 *
 * `CREATE TABLE IF NOT EXISTS` adds nothing to a table that already exists, so the schema
 * above only ever runs in full on a fresh database. Anyone who used the app earlier has the
 * old shape, and the failure mode is a clean install that works and an existing one that
 * does not. Applied by inspection rather than a version counter — with this few columns,
 * asking SQLite what it already has is simpler and cannot get out of step.
 */
const ADDED_COLUMNS: [table: string, column: string, definition: string][] = [
  ["messages", "citations", "TEXT"],
  ["messages", "retrieval_meta", "TEXT"],
];

function migrate(db: DatabaseSync): void {
  for (const [table, column, definition] of ADDED_COLUMNS) {
    const existing = db
      .prepare(`SELECT name FROM pragma_table_info(?)`)
      .all(table)
      .map((row) => row.name as string);
    if (existing.length && !existing.includes(column)) {
      db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
    }
  }
}

function open(): DatabaseSync {
  const path = resolve(process.env.SQLITE_PATH ?? DEFAULT_PATH);
  mkdirSync(dirname(path), { recursive: true });

  const db = new DatabaseSync(path);
  // WAL keeps reads from blocking the write that persists a finished answer;
  // foreign_keys is off by default in SQLite and the messages cascade needs it.
  db.exec("PRAGMA journal_mode = WAL");
  db.exec("PRAGMA foreign_keys = ON");
  db.exec("PRAGMA busy_timeout = 5000");
  db.exec(SCHEMA);
  migrate(db);
  return db;
}

// Held on globalThis so route handlers and server components — which Next
// compiles into separate module graphs — share one handle, and so dev HMR
// doesn't leak a new connection on every edit.
const store = globalThis as unknown as { __chatDb?: DatabaseSync };

export function db(): DatabaseSync {
  return (store.__chatDb ??= open());
}
