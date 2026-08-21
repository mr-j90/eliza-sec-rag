import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, test } from "node:test";

import { readSummary } from "@/lib/evals/summary";

const dir = mkdtempSync(join(tmpdir(), "eval-summary-"));
after(() => rmSync(dir, { recursive: true, force: true }));

/** A cache document as `src/eval/summarize.py` writes it. */
function write(document: unknown, into: string = dir): string {
  const target = mkdtempSync(join(into, "case-"));
  writeFileSync(join(target, "summary.json"), JSON.stringify(document));
  return target;
}

const GOOD = {
  prompt_version: "3",
  model: "gpt-4.1",
  generated_at: "2026-08-20T20:00:00+00:00",
  run_files: ["a.json", "b.json"],
  summary: {
    headline: "The system reaches every company a question names.",
    findings: [
      {
        point: "It surfaced about 62% of the filings it could have reached.",
        metrics: ["normalized_recall@10"],
      },
      {
        point: "Every company named in a question had filings in the evidence.",
        metrics: ["entity_coverage@20"],
      },
    ],
    caveat: "The sample is small, so small differences mean nothing.",
  },
  verification: {
    verified: true,
    n_figures: 2,
    figures: ["62%", "22"],
    unverified_figures: [],
    untraced_findings: [],
    unknown_metrics: [],
  },
};

describe("readSummary", () => {
  test("parses a cache document and reports it current for the runs it covers", async () => {
    const summary = await readSummary(["b.json", "a.json"], write(GOOD));

    assert.ok(summary);
    assert.equal(summary.headline, GOOD.summary.headline);
    assert.equal(summary.findings.length, 2);
    // The metric key stays out of the prose and beside it — the page renders them apart.
    assert.deepEqual(summary.findings[0].metrics, ["normalized_recall@10"]);
    assert.ok(!summary.findings[0].point.includes("normalized_recall"));
    assert.equal(summary.model, "gpt-4.1");
    assert.equal(summary.verified, true);
    // Order must not matter — the key is the *set* of run files.
    assert.equal(summary.stale, false);
  });

  test("is stale when a run exists that the summary never saw", async () => {
    // The case the page exists to handle honestly: `make eval` ran again, so the prose on
    // screen describes fewer runs than the table below it.
    const summary = await readSummary(["a.json", "b.json", "c.json"], write(GOOD));

    assert.equal(summary?.stale, true);
  });

  test("is stale when a run it covers has been deleted", async () => {
    const summary = await readSummary(["a.json"], write(GOOD));

    assert.equal(summary?.stale, true);
  });

  test("surfaces unverified figures rather than dropping them", async () => {
    // Flag, do not strip: the same rule the citation check follows. A number no run produced
    // reads exactly like one that did.
    const summary = await readSummary(
      ["a.json"],
      write({
        ...GOOD,
        run_files: ["a.json"],
        verification: { verified: false, unverified_figures: ["0.8412"] },
      }),
    );

    assert.equal(summary?.verified, false);
    assert.deepEqual(summary?.unverifiedFigures, ["0.8412"]);
  });

  test("treats a missing verification block as unverified, not as a pass", async () => {
    const { verification, ...withoutCheck } = GOOD;
    void verification;
    const summary = await readSummary(["a.json", "b.json"], write(withoutCheck));

    assert.equal(summary?.verified, false);
  });

  test("returns null when no summary has been generated", async () => {
    assert.equal(await readSummary(["a.json"], join(dir, "does-not-exist")), null);
  });

  test("returns null for a malformed file rather than rendering half a summary", async () => {
    const target = mkdtempSync(join(dir, "case-"));
    writeFileSync(join(target, "summary.json"), '{"summary": {"headline"');

    assert.equal(await readSummary(["a.json"], target), null);
  });

  test("returns null when a required field is empty", async () => {
    // On screen, a summary missing its caveat looks identical to a complete one — and the
    // caveat is the field that stops a reader over-trusting the numbers.
    const point = { point: "a point", metrics: ["mrr@10"] };
    for (const summary of [
      { headline: "", findings: [point], caveat: "b" },
      { headline: "a", findings: [], caveat: "b" },
      { headline: "a", findings: [point], caveat: "" },
      { headline: "a", findings: [{ point: "", metrics: [] }], caveat: "b" },
      { headline: "a", findings: [{ metrics: ["mrr@10"] }], caveat: "b" },
    ]) {
      assert.equal(await readSummary(["a.json"], write({ ...GOOD, summary })), null);
    }
  });

  test("surfaces an untraceable point and an unknown metric key", async () => {
    // Both are the price of taking metric names out of the prose: the claim has to stay
    // checkable somewhere, and when it isn't, the page says so rather than reading clean.
    const summary = await readSummary(
      ["a.json"],
      write({
        ...GOOD,
        run_files: ["a.json"],
        verification: {
          verified: false,
          untraced_findings: ["It surfaced about 62% of what it could reach."],
          unknown_metrics: ["normalized_recall@15"],
        },
      }),
    );

    assert.equal(summary?.verified, false);
    assert.equal(summary?.untracedFindings.length, 1);
    assert.deepEqual(summary?.unknownMetrics, ["normalized_recall@15"]);
  });

  test("accepts a bare-string finding as a point with no metrics", async () => {
    // Lenient in the same place the Python parser is: the reply still renders, and the
    // generator has already flagged the missing citation.
    const summary = await readSummary(
      ["a.json", "b.json"],
      write({ ...GOOD, summary: { ...GOOD.summary, findings: ["a plain point"] } }),
    );

    assert.deepEqual(summary?.findings, [{ point: "a plain point", metrics: [] }]);
  });

  test("names the model as unknown rather than omitting it", async () => {
    const { model, ...withoutModel } = GOOD;
    void model;
    const summary = await readSummary(["a.json", "b.json"], write(withoutModel));

    assert.equal(summary?.model, "unknown model");
  });
});
