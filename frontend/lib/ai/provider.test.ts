import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";

// Read before the module under test captures it.
process.env.RAG_API_URL = "http://127.0.0.1:9999";

const { askBackend, BackendUnreachable } = await import("@/lib/ai/provider");

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function respondWith(body: unknown, status = 200) {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;
}

const ANSWER = {
  answer: "Apple reports supplier concentration [C1].",
  citations: [
    {
      id: "C1",
      company: "Apple Inc",
      form_type: "10-K",
      fiscal_year: 2025,
      section: "Item 1A — Risk Factors",
      source_file: "AAPL_10K_2025-10-31_full.txt",
      excerpt: "Item 1A.    Risk Factors...",
    },
  ],
  retrieval_meta: { entities_detected: [], n_chunks: 3, generation_model: "gpt-4.1" },
};

describe("askBackend", () => {
  test("returns the backend's answer and citations", async () => {
    respondWith(ANSWER);

    const result = await askBackend("What are Apple's primary risk factors?");

    assert.equal(result.answer, "Apple reports supplier concentration [C1].");
    assert.equal(result.citations.length, 1);
    assert.equal(result.citations[0].id, "C1");
    assert.equal(result.generationModel, "gpt-4.1");
  });

  test("an answer with no citations comes back cleanly rather than throwing", async () => {
    // The backend can legitimately answer with nothing attached; the UI distinguishes that
    // from "zero sources were found", so the client must not invent an empty list.
    respondWith({ answer: "No context matched.", citations: [], retrieval_meta: {} });

    const result = await askBackend("anything");

    assert.equal(result.answer, "No context matched.");
    assert.deepEqual(result.citations, []);
    assert.equal(result.generationModel, null);
  });

  test("citations survive the hop with their SPEC \u00a78 fields intact", async () => {
    respondWith(ANSWER);

    const [citation] = (await askBackend("anything")).citations;

    for (const field of [
      "id",
      "company",
      "form_type",
      "fiscal_year",
      "section",
      "source_file",
      "excerpt",
    ] as const) {
      assert.ok(field in citation, `citation lost its ${field}`);
    }
  });

  test("an unreachable backend fails loudly and names the backend", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;

    const error = await askBackend("anything").then(
      () => null,
      (e: unknown) => e,
    );

    assert.ok(error instanceof BackendUnreachable, "expected BackendUnreachable");
    assert.match(error.message, /127\.0\.0\.1:9999/, "must name the backend it could not reach");
  });

  test("an unreachable backend never yields a mock answer", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;

    const error = await askBackend("anything").then(
      () => null,
      (e: unknown) => e,
    );

    // The app used to degrade to a canned stream so it was "always usable". Once
    // the backend is what's missing, that same behaviour shows a fabricated answer
    // during a demo while the operator believes it is real.
    assert.doesNotMatch((error as Error).message, /mock/i);
  });

  test("a backend error status is reported, not swallowed", async () => {
    respondWith({ detail: "No LLM provider is configured." }, 503);

    const error = await askBackend("anything").then(
      () => null,
      (e: unknown) => e,
    );

    assert.ok(error instanceof Error);
    assert.match(error.message, /No LLM provider is configured/);
  });
});
