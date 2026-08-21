import "server-only";

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

/**
 * Reads eval runs off disk.
 *
 * They are **JSON files, not rows in the app's SQLite database**, deliberately. The harness
 * that produces them is Python; `lib/db/` is the only SQL in this app and having a second
 * runtime write that schema would mean coordinating migrations across two languages for data
 * with no relational shape — eval runs are append-only artefacts with no update, no delete and
 * no joins. The operation that matters is comparing two runs, and files diff natively.
 *
 * Read at request time rather than at build time: a run written after the app started must
 * appear on the next page load, which is the whole point of having the page.
 */

/** `eval/results/` at the repo root — one level up from the Next app. */
export const RESULTS_DIR =
  process.env.EVAL_RESULTS_DIR ?? path.join(process.cwd(), "..", "eval", "results");

/** Metrics worth putting on screen, in the order they should be read. */
export const HEADLINE_METRICS = [
  "normalized_recall@5",
  "normalized_recall@10",
  "normalized_recall@20",
  "recall@5",
  "recall@10",
  "recall@20",
  "mrr@10",
  "ndcg@10",
  "entity_coverage@10",
  "entity_coverage@20",
] as const;

export type Overall = Record<string, number | null>;

export type PerQuestion = {
  id: string;
  category: string;
  n_relevant?: number;
  suspect?: string;
} & Record<string, unknown>;

export type EvalRun = {
  /** The filename, used as the stable id in URLs. */
  file: string;
  config: string;
  k: number;
  generated_at: string;
  n_scored: number;
  n_unanswerable: number;
  note?: string;
  overall: Overall;
  by_category?: Record<string, Overall>;
  per_question?: PerQuestion[];
};

function isRunFile(name: string): boolean {
  // `latest.json` is a duplicate of the newest run, kept as a stable path for scripts. Listing
  // it would show every newest run twice. `summary.json` is the cached prose *about* these
  // runs (see `lib/evals/summary.ts`), not a run.
  return name.endsWith(".json") && name !== "latest.json" && name !== "summary.json";
}

/**
 * Every run, newest first.
 *
 * Returns `[]` when the directory does not exist — that is the state before anyone has run
 * `make eval`, and it is not an error. The page says so rather than throwing.
 */
export async function listRuns(resultsDir: string = RESULTS_DIR): Promise<EvalRun[]> {
  let names: string[];
  try {
    names = (await readdir(resultsDir)).filter(isRunFile);
  } catch {
    return [];
  }

  const runs = await Promise.all(
    names.map(async (file) => {
      try {
        const parsed = JSON.parse(await readFile(path.join(resultsDir, file), "utf8"));
        return { ...parsed, file } as EvalRun;
      } catch {
        // A truncated file — a run killed mid-write — should not take the page down with it.
        return null;
      }
    }),
  );

  return runs
    .filter((run): run is EvalRun => run !== null)
    .sort((a, b) => (a.generated_at < b.generated_at ? 1 : -1));
}

/** Percentage points, for a delta column. `null` when either side is missing. */
export function delta(current: number | null, previous: number | null): number | null {
  if (current === null || previous === null) return null;
  if (current === undefined || previous === undefined) return null;
  return current - previous;
}

/**
 * Runs grouped by configuration, so a comparison shows like against like.
 *
 * Comparing `+rerank` against `fusion only` is the question the harness exists to answer;
 * comparing two runs of the *same* config only shows retrieval nondeterminism.
 */
export function groupByConfig(runs: EvalRun[]): Map<string, EvalRun[]> {
  const grouped = new Map<string, EvalRun[]>();
  for (const run of runs) {
    const existing = grouped.get(run.config);
    if (existing) existing.push(run);
    else grouped.set(run.config, [run]);
  }
  return grouped;
}
