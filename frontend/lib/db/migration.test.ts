import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { after, describe, test } from "node:test";

/**
 * `CREATE TABLE IF NOT EXISTS` adds nothing to a table that already exists, so new
 * columns need a real migration. This test builds a database with the *pre-citations*
 * schema and a row in it, then opens it through the app's client — which is the exact
 * situation of anyone who used the app before this change.
 *
 * Without the migration this passes on a fresh clone and fails on their machine.
 */

const dir = mkdtempSync(join(tmpdir(), "chat-migration-"));
const path = join(dir, "legacy.db");

// The schema as it stood before citations existed.
const legacy = new DatabaseSync(path);
legacy.exec(`
CREATE TABLE conversations (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
  model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL
);
INSERT INTO conversations VALUES ('old-1','demoadmin@example.com','Older chat',NULL,'2026-08-01','2026-08-01');
INSERT INTO messages (conversation_id, role, content, created_at)
  VALUES ('old-1','user','asked before citations existed','2026-08-01');
INSERT INTO messages (conversation_id, role, content, created_at)
  VALUES ('old-1','assistant','answered before citations existed','2026-08-01');
`);
legacy.close();

process.env.SQLITE_PATH = path;

const { appendMessage, getConversation } = await import("@/lib/db/conversations");

after(() => rmSync(dir, { recursive: true, force: true }));

describe("opening a pre-citations database", () => {
  test("adds the columns without losing existing rows", () => {
    const conversation = getConversation("demoadmin@example.com", "old-1");
    assert.ok(conversation, "the existing conversation must still be readable");
    assert.equal(conversation.messages.length, 2);
    assert.equal(conversation.messages[0].content, "asked before citations existed");
    // Rows written before the columns existed simply have nothing to report.
    assert.equal(conversation.messages[1].citations, undefined);
  });

  test("and can then store citations against the same conversation", () => {
    appendMessage("old-1", "assistant", "Now with sources [C1].", {
      citations: [
        {
          id: "C1",
          company: "Apple Inc",
          form_type: "10-K",
          fiscal_year: 2025,
          section: "Item 1A — Risk Factors",
          source_file: "AAPL_10K_2025-10-31_full.txt",
          excerpt: "…",
        },
      ],
    });

    const messages = getConversation("demoadmin@example.com", "old-1")!.messages;
    assert.equal(messages.length, 3);
    assert.equal(messages[2].citations?.[0].company, "Apple Inc");
  });
});
