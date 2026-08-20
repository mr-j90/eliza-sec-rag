import "server-only";

import { RAG_API_URL } from "@/lib/ai/config";
import type { ChatMessage } from "@/lib/chat/types";

/**
 * The only place that talks to the answer backend.
 *
 * Under D001 this app makes **no LLM provider calls at all** — it asks the Python
 * service, which makes exactly one. That is why no provider SDK is imported in
 * this app at all — the one-call constraint (SPEC §5.2) is then checkable by
 * grep, not by trust.
 *
 * There is deliberately **no fallback to a canned answer**. The app used to
 * degrade to a mock stream so it was always usable; once the *backend* is what's
 * missing, that same kindness shows a fabricated answer during a demo while the
 * operator believes it is real. An error that says what broke is worth more.
 */

export type ChatTurn = ChatMessage;

/** SPEC §8's citation shape, as the backend sends it. */
export type Citation = {
  id: string;
  company: string;
  form_type: string;
  fiscal_year: number;
  /**
   * The period the filing reports on, e.g. "2025-10-26". Displayed in place of a bare
   * "FY2025", because for the 18 of 54 issuers in this corpus whose fiscal year does not
   * end in December the two disagree — NVIDIA calls the quarter ending 2025-10-26 "fiscal
   * year 2026", so a citation labelled FY2025 sat directly above an excerpt saying
   * otherwise. `fiscal_year` is kept because it is what the year filter runs on.
   *
   * Empty string for the one filing whose period end is not recoverable from its header.
   */
  period_end: string;
  section: string;
  source_file: string;
  excerpt: string;
};

export type AskResult = {
  answer: string;
  citations: Citation[];
  /** The model that actually answered, per the backend. */
  generationModel: string | null;
  retrievalMeta: Record<string, unknown>;
};

/** The backend could not be reached at all — usually it isn't running. */
export class BackendUnreachable extends Error {}

/** The backend answered, with a failure. Its reason is carried through verbatim. */
export class BackendRefused extends Error {}

const START_HINT = "uv run uvicorn src.api:app --port 8000";

async function reasonFrom(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body);
  } catch {
    return response.statusText || "no reason given";
  }
}

/** Ask the backend one question. One call in, one answer out. */
export async function askBackend(question: string, topK = 20): Promise<AskResult> {
  let response: Response;
  try {
    response = await fetch(`${RAG_API_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: topK }),
      cache: "no-store",
    });
  } catch (cause) {
    throw new BackendUnreachable(
      `Could not reach the answer backend at ${RAG_API_URL}. ` +
        `Is it running? Start it with: ${START_HINT}`,
      { cause },
    );
  }

  if (!response.ok) {
    throw new BackendRefused(
      `The answer backend at ${RAG_API_URL} returned ${response.status}: ` +
        `${await reasonFrom(response)}`,
    );
  }

  const body = (await response.json()) as {
    answer?: unknown;
    citations?: unknown;
    retrieval_meta?: Record<string, unknown>;
  };

  const meta = body.retrieval_meta ?? {};
  const model = meta["generation_model"];

  return {
    answer: typeof body.answer === "string" ? body.answer : "",
    citations: Array.isArray(body.citations) ? (body.citations as Citation[]) : [],
    generationModel: typeof model === "string" ? model : null,
    retrievalMeta: meta,
  };
}

/**
 * The model the backend would answer with, or null when it can't be asked.
 *
 * Null rather than a guess: a UI that names a model while the backend is down is
 * advertising something that did not answer.
 */
export async function backendHealth(): Promise<{ generationModel: string } | null> {
  try {
    const response = await fetch(`${RAG_API_URL}/health`, { cache: "no-store" });
    if (!response.ok) return null;
    const body = (await response.json()) as { generation_model?: unknown };
    return typeof body.generation_model === "string"
      ? { generationModel: body.generation_model }
      : null;
  } catch {
    return null;
  }
}
