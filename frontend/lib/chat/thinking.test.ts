import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { PHASES, statusWord, TICK_MS } from "@/lib/chat/thinking";

const wordsAt = (ms: number) => PHASES.filter((p) => ms >= p.afterMs).at(-1)!.words;

describe("statusWord", () => {
  test("opens on the first phase", () => {
    assert.equal(statusWord(0), "Thinking");
    assert.ok(wordsAt(0).includes(statusWord(1)));
  });

  test("rotates within a phase instead of sticking on one word", () => {
    const seen = new Set([0, 1, 2, 3].map(statusWord));
    assert.equal(seen.size, 4, `expected 4 distinct words, got ${[...seen]}`);
  });

  test("escalates as the wait grows", () => {
    // Just before vs. just after each threshold.
    for (const phase of PHASES.slice(1)) {
      const before = Math.floor(phase.afterMs / TICK_MS) - 1;
      const after = Math.ceil(phase.afterMs / TICK_MS);

      assert.ok(
        !phase.words.includes(statusWord(before)),
        `step ${before} should predate the "${phase.words[0]}" phase`,
      );
      assert.ok(
        phase.words.includes(statusWord(after)),
        `step ${after} should have reached the "${phase.words[0]}" phase`,
      );
    }
  });

  test("settles in the final phase and never runs out of words", () => {
    const last = PHASES.at(-1)!.words;
    for (const step of [20, 50, 500, 10_000]) {
      assert.ok(last.includes(statusWord(step)), `step ${step} fell out of the last phase`);
    }
  });

  test("never promises progress it cannot know", () => {
    const claims = /%|almost|nearly done|finishing up|\d+\s*(sec|min)/i;
    for (const phase of PHASES) {
      for (const word of phase.words) {
        assert.doesNotMatch(word, claims, `"${word}" implies progress we can't measure`);
      }
    }
  });

  test("tolerates junk steps rather than returning undefined", () => {
    for (const step of [-1, -100, 0.5, 3.9]) {
      assert.equal(typeof statusWord(step), "string");
      assert.ok(statusWord(step).length > 0);
    }
  });
});
