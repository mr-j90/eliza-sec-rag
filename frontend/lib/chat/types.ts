/**
 * Chat shapes shared by the client and the server. Kept out of `lib/db/` so
 * client components can import them without reaching into a `server-only`
 * module.
 */
export type ChatRole = "user" | "assistant";

/**
 * One retrieved passage, as the backend describes it (SPEC §8). Snake_case because it
 * crosses the wire from Python untouched — renaming it here would mean two names for one
 * thing and a mapping layer to keep in step.
 */
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
   * Optional, for two distinct reasons: the backend sends an empty string for the one
   * filing whose period end is not recoverable, and this type also describes rows read
   * back from SQLite that were written before the field existed, where the key is absent
   * entirely. Both render as the `fiscal_year` fallback, so an old conversation still
   * displays correctly rather than showing `period ending undefined`.
   */
  period_end?: string;
  section: string;
  source_file: string;
  excerpt: string;
};

/** How the answer was retrieved. Provenance for the reader, not a debug dump. */
export type RetrievalMeta = {
  /** Tickers the question named, in mention order. Rule-based — no model call (SPEC §5.2). */
  entities_detected?: string[];
  /**
   * Capitalised names that look like companies but are not in this corpus. Heuristic, and
   * shown so a reader can see *what* the system could not speak about.
   */
  unresolved_mentions?: string[];
  /** Inclusive fiscal-year range the question was scoped to, if any. */
  fiscal_years?: number[] | null;
  form_type?: string | null;
  n_chunks?: number;
  generation_model?: string;
  prompt_version?: string;
  retrieval?: string;
  top_score?: number;
  latency_ms?: { retrieval?: number; generation?: number; total?: number };
};

export type ChatMessage = {
  role: ChatRole;
  content: string;
  /**
   * Absent rather than empty when there is nothing behind the answer — a user turn, or a
   * reply that reports the backend was unreachable. "No sources" and "an empty list of
   * sources" are different claims and the UI should not conflate them.
   */
  citations?: Citation[];
  retrievalMeta?: RetrievalMeta;
};
