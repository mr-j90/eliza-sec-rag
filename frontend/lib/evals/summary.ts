import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";

import { RESULTS_DIR } from "@/lib/evals/runs";

/**
 * Reads the cached plain-English summary of the eval runs.
 *
 * **This app generates nothing.** The summary is written by
 * `uv run python -m src.eval.summarize` and read here as a file. That split is not incidental:
 * the Next app makes no model-provider calls of its own and has no `openai` dependency, which
 * is what makes SPEC §5.2's one-call constraint structural rather than conventional (D001).
 * Generating this text in a server component would have quietly ended that, for a paragraph
 * that changes only when a new eval run lands.
 *
 * It is also why the summary is *cached* rather than live: it describes files on disk that
 * change a few times a day at most, so regenerating it per page view would spend a call to
 * restate the same numbers.
 *
 * **Staleness is decided by the set of run filenames**, the same key the generator uses. A
 * content hash would have to be reimplemented here and could disagree with the Python one;
 * a filename set cannot. Run files are written once and never overwritten, so the set is a
 * sound identity for "the same runs".
 */

/**
 * One observation, and the metric keys it rests on.
 *
 * The split exists because the prose is written for a chief executive and carries no metric
 * names (`src/eval/summarize.py`, prompt v3). `metrics` is where that vocabulary went: the page
 * renders `point` at the top and the keys down in the technical section, so a plainly worded
 * claim is still traceable to a row of the table.
 */
export type SummaryFinding = {
  point: string;
  metrics: string[];
};

export type EvalSummary = {
  headline: string;
  findings: SummaryFinding[];
  caveat: string;
  /** Which model wrote it — named on the page, since a reader is entitled to know. */
  model: string;
  generatedAt: string;
  /** The runs it describes. */
  runFiles: string[];
  /** False when any check below failed. Surfaced on the page, not hidden. */
  verified: boolean;
  /** Figures in the prose that appear in no run. */
  unverifiedFigures: string[];
  /** Points that quote a figure but name no metric — the claim cannot be traced. */
  untracedFindings: string[];
  /** Metric keys a point cites that do not exist in the run data. */
  unknownMetrics: string[];
  /** True when runs exist that this summary never saw. */
  stale: boolean;
};

const SUMMARY_FILE = "summary.json";

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asTextList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asText).filter(Boolean) : [];
}

/**
 * Findings, tolerating a bare string where an object is expected.
 *
 * The Python side is lenient in the same place and for the same reason: a reply in the older
 * shape still renders, and dropping the whole summary over it would be a worse outcome than
 * showing a point with no metric beside it — which the generator has already flagged as
 * untraced.
 */
function asFindings(value: unknown): SummaryFinding[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (typeof entry === "string") return { point: entry.trim(), metrics: [] };
      if (typeof entry !== "object" || entry === null) return { point: "", metrics: [] };
      const record = entry as Record<string, unknown>;
      return { point: asText(record.point), metrics: asTextList(record.metrics) };
    })
    .filter((finding) => finding.point.length > 0);
}

/**
 * The cached summary, or `null` when there isn't a usable one.
 *
 * `null` covers "never generated", "unreadable", and "malformed" alike, because the page
 * response to all three is the same: show the numbers and say how to generate the summary.
 * A partially-parsed summary is deliberately **not** returned — on screen it would be
 * indistinguishable from a complete one.
 */
export async function readSummary(
  runFiles: string[],
  resultsDir: string = RESULTS_DIR,
): Promise<EvalSummary | null> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(path.join(resultsDir, SUMMARY_FILE), "utf8"));
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;

  const document = parsed as Record<string, unknown>;
  const summary = (document.summary ?? {}) as Record<string, unknown>;
  const verification = (document.verification ?? {}) as Record<string, unknown>;

  const headline = asText(summary.headline);
  const findings = asFindings(summary.findings);
  const caveat = asText(summary.caveat);
  if (!headline || findings.length === 0 || !caveat) return null;

  const runFilesCovered = asTextList(document.run_files);

  return {
    headline,
    findings,
    caveat,
    model: asText(document.model) || "unknown model",
    generatedAt: asText(document.generated_at),
    runFiles: runFilesCovered,
    // Absent verification is treated as unverified rather than as a pass. A summary written
    // before the check existed, or by something that skipped it, has not been checked.
    verified: verification.verified === true,
    unverifiedFigures: asTextList(verification.unverified_figures),
    untracedFindings: asTextList(verification.untraced_findings),
    unknownMetrics: asTextList(verification.unknown_metrics),
    stale: !sameSet(runFilesCovered, runFiles),
  };
}

function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const left = new Set(a);
  return b.every((name) => left.has(name));
}
