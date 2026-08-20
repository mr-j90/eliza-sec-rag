import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { groupConversations } from "@/lib/chat/history";
import type { ConversationSummary } from "@/lib/db/conversations";

const DAY = 24 * 60 * 60 * 1000;

function at(msAgo: number, id: string): ConversationSummary {
  const iso = new Date(Date.now() - msAgo).toISOString();
  return { id, title: id, model: null, createdAt: iso, updatedAt: iso };
}

describe("groupConversations", () => {
  test("buckets by recency and emits groups newest-first", () => {
    // 12 days lands in "Previous 30 days"; 40 days in "Older". The 1.5-day and
    // 4-day entries avoid midnight-boundary ambiguity in calendar-day math.
    const groups = groupConversations([
      at(60_000, "now"),
      at(4 * DAY, "four-days"),
      at(12 * DAY, "twelve-days"),
      at(40 * DAY, "forty-days"),
    ]);

    assert.deepEqual(
      groups.map((g) => g.label),
      ["Today", "Previous 7 days", "Previous 30 days", "Older"],
    );
    assert.deepEqual(
      groups.map((g) => g.conversations.map((c) => c.id)),
      [["now"], ["four-days"], ["twelve-days"], ["forty-days"]],
    );
  });

  test("keeps input order within a group", () => {
    const groups = groupConversations([
      at(60_000, "first"),
      at(120_000, "second"),
      at(180_000, "third"),
    ]);

    assert.equal(groups.length, 1);
    assert.deepEqual(groups[0].conversations.map((c) => c.id), [
      "first",
      "second",
      "third",
    ]);
  });

  test("omits empty groups", () => {
    assert.deepEqual(groupConversations([]), []);
    assert.deepEqual(
      groupConversations([at(60_000, "only")]).map((g) => g.label),
      ["Today"],
    );
  });

  test("treats an unparseable timestamp as Older rather than throwing", () => {
    const groups = groupConversations([
      { id: "bad", title: "bad", model: null, createdAt: "", updatedAt: "not-a-date" },
    ]);
    assert.deepEqual(groups.map((g) => g.label), ["Older"]);
  });
});
