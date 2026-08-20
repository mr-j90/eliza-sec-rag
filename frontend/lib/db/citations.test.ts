import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, test } from "node:test";

// Point the store at a scratch file before the module under test opens it.
const dir = mkdtempSync(join(tmpdir(), "chat-citations-"));
process.env.SQLITE_PATH = join(dir, "test.db");

const { appendMessage, createConversation, getConversation } = await import(
  "@/lib/db/conversations"
);

const USER = "demoadmin@example.com";

after(() => rmSync(dir, { recursive: true, force: true }));

const CITATIONS = [
  {
    id: "C1",
    company: "Apple Inc",
    form_type: "10-K",
    fiscal_year: 2025,
    section: "Item 3 — Legal Proceedings",
    source_file: "AAPL_10K_2025-10-31_full.txt",
    excerpt: "Epic Games, Inc. filed a lawsuit in the U.S. District Court…",
  },
];

const META = {
  n_chunks: 20,
  generation_model: "gpt-4.1",
  retrieval: "hybrid dense+sparse, server-side RRF",
  latency_ms: { retrieval: 257.8, generation: 5075.7, total: 5333.6 },
};

describe("citations persist with the answer", () => {
  test("an assistant message round-trips its citations and retrieval meta", () => {
    const id = createConversation(USER, { title: "Legal proceedings", model: "gpt-4.1" });
    appendMessage(id, "user", "What legal proceedings does Apple disclose?");
    appendMessage(id, "assistant", "Apple discloses the Epic Games litigation [C1].", {
      citations: CITATIONS,
      retrievalMeta: META,
    });

    const conversation = getConversation(USER, id);
    assert.ok(conversation);

    const [, answer] = conversation.messages;
    assert.equal(answer.role, "assistant");
    assert.deepEqual(answer.citations, CITATIONS);
    assert.equal(answer.retrievalMeta?.n_chunks, 20);
  });

  test("a message with no citations comes back without them, not as an empty list", () => {
    const id = createConversation(USER, { title: "No sources", model: null });
    appendMessage(id, "user", "hello");
    // The backend-unreachable reply is the real case: an answer with nothing behind it.
    appendMessage(id, "assistant", "**The answer backend did not respond.**");

    const conversation = getConversation(USER, id);
    assert.ok(conversation);

    for (const message of conversation.messages) {
      assert.equal(message.citations, undefined);
      assert.equal(message.retrievalMeta, undefined);
    }
  });

  test("citations survive being read back in a later session", () => {
    const id = createConversation(USER, { title: "Reload", model: "gpt-4.1" });
    appendMessage(id, "assistant", "Grounded [C1].", { citations: CITATIONS });

    // Two independent reads: history has to be durable, not just in-request state.
    const first = getConversation(USER, id);
    const second = getConversation(USER, id);
    assert.deepEqual(first?.messages[0].citations, second?.messages[0].citations);
    assert.equal(second?.messages[0].citations?.[0].section, "Item 3 — Legal Proceedings");
  });
});
