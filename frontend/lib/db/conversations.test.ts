import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";

// Point the store at a scratch file before the module under test opens it.
const dir = mkdtempSync(join(tmpdir(), "chat-db-"));
process.env.SQLITE_PATH = join(dir, "test.db");

const {
  appendMessage,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  ownsConversation,
  renameConversation,
  titleFromMessage,
} = await import("@/lib/db/conversations");
const { db } = await import("@/lib/db/client");

const ALICE = "alice@example.com";
const BOB = "bob@example.com";

after(() => rmSync(dir, { recursive: true, force: true }));

describe("titleFromMessage", () => {
  test("collapses whitespace and keeps short messages whole", () => {
    assert.equal(titleFromMessage("  What is\n  RAG?  "), "What is RAG?");
  });

  test("falls back for an empty message", () => {
    assert.equal(titleFromMessage("   \n "), "New chat");
  });

  test("truncates long messages on a word boundary", () => {
    const title = titleFromMessage(
      "Compare the risk factors disclosed by Apple and Microsoft in their most recent annual filings",
    );
    assert.ok(title.endsWith("…"));
    assert.ok(title.length <= 61, `title too long: ${title.length}`);
    assert.doesNotMatch(title, / …$/);
  });

  test("still truncates when there is no usable word boundary", () => {
    const title = titleFromMessage("x".repeat(200));
    assert.equal(title, `${"x".repeat(60)}…`);
  });
});

describe("conversation lifecycle", () => {
  let id: string;

  before(() => {
    id = createConversation(ALICE, { title: "First chat", model: "mock" });
    appendMessage(id, "user", "hello");
    appendMessage(id, "assistant", "hi there");
  });

  test("round-trips the transcript in order", () => {
    const conversation = getConversation(ALICE, id);
    assert.equal(conversation?.title, "First chat");
    assert.equal(conversation?.model, "mock");
    assert.deepEqual(conversation?.messages, [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi there" },
    ]);
  });

  test("appending bumps updated_at past created_at", () => {
    const conversation = getConversation(ALICE, id)!;
    assert.ok(conversation.updatedAt >= conversation.createdAt);
  });

  test("renames", () => {
    assert.equal(renameConversation(ALICE, id, "  Renamed   chat "), true);
    assert.equal(getConversation(ALICE, id)?.title, "Renamed chat");
  });

  test("refuses a blank rename", () => {
    assert.equal(renameConversation(ALICE, id, "   "), false);
    assert.equal(getConversation(ALICE, id)?.title, "Renamed chat");
  });

  test("lists most recently active first", () => {
    const older = createConversation(ALICE, { title: "Older", model: null });
    appendMessage(older, "user", "first");
    appendMessage(id, "user", "newest turn");

    assert.equal(listConversations(ALICE).map((c) => c.id)[0], id);
    assert.equal(listConversations(ALICE).length, 2);
  });

  test("deletes the conversation and cascades its messages", () => {
    const doomed = createConversation(ALICE, { title: "Doomed", model: null });
    appendMessage(doomed, "user", "goodbye");

    assert.equal(deleteConversation(ALICE, doomed), true);
    assert.equal(getConversation(ALICE, doomed), null);

    const orphans = db()
      .prepare("SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?")
      .get(doomed) as { n: number };
    assert.equal(Number(orphans.n), 0, "messages should cascade with the row");
  });
});

describe("user scoping", () => {
  let aliceId: string;

  before(() => {
    aliceId = createConversation(ALICE, { title: "Alice only", model: null });
    appendMessage(aliceId, "user", "private");
  });

  test("another user cannot read it", () => {
    assert.equal(getConversation(BOB, aliceId), null);
    assert.equal(ownsConversation(BOB, aliceId), false);
    assert.equal(ownsConversation(ALICE, aliceId), true);
  });

  test("another user cannot rename or delete it", () => {
    assert.equal(renameConversation(BOB, aliceId, "hijacked"), false);
    assert.equal(deleteConversation(BOB, aliceId), false);
    assert.equal(getConversation(ALICE, aliceId)?.title, "Alice only");
  });

  test("lists are per-user", () => {
    createConversation(BOB, { title: "Bob's chat", model: null });
    assert.deepEqual(listConversations(BOB).map((c) => c.title), ["Bob's chat"]);
    assert.ok(!listConversations(ALICE).some((c) => c.title === "Bob's chat"));
  });
});
