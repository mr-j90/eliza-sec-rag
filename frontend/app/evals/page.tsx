import { IconAlertTriangle, IconChartBar, IconSparkles } from "@tabler/icons-react";

import { HEADLINE_METRICS, groupByConfig, listRuns } from "@/lib/evals/runs";
import type { EvalRun } from "@/lib/evals/runs";
import { readSummary } from "@/lib/evals/summary";
import type { EvalSummary } from "@/lib/evals/summary";

export const metadata = { title: "Evals" };

// Read at request time. A run written after the server started must show up on the next load.
export const dynamic = "force-dynamic";

function format(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function Delta({ value }: { value: number | null }) {
  if (value === null || Math.abs(value) < 1e-9) {
    return <span className="text-muted-foreground/50">—</span>;
  }
  const better = value > 0;
  return (
    <span className={better ? "text-emerald-600 dark:text-emerald-500" : "text-amber-600 dark:text-amber-500"}>
      {better ? "+" : ""}
      {value.toFixed(4)}
    </span>
  );
}

function when(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
}

/**
 * The plain-English summary, generated once per set of runs and read from disk.
 *
 * It sits above the tables because the numbers underneath need context that most readers of
 * this page do not have — three of the five metrics are reported specifically *not* to be
 * relied on, and a stakeholder reading `mrr@10 = 1.0000` off a table concludes the opposite of
 * what it means.
 *
 * Four things are stated on screen rather than left implicit, because a generated paragraph
 * that looks authored is worth less than one whose provenance is visible:
 *
 * - **that a model wrote it**, and which model;
 * - **that it is not the answer path** — SPEC §5.2 allows one generation call per answer, and
 *   an interviewer who sees an LLM summary on an eval page is right to ask;
 * - **whether every figure in it was found in the run data** (`src/eval/summarize.py` checks
 *   each numeral against the metrics it was given, and flags rather than strips);
 * - **whether new runs have landed since it was written**, in which case it describes fewer
 *   runs than the table below it.
 */
function Summary({ summary, newRuns }: { summary: EvalSummary; newRuns: number }) {
  // Three ways the generated text can fail its own checks. Collected into one list so the page
  // has a single amber box rather than three near-identical ones, and so a summary that fails
  // two checks says both things.
  const problems: string[] = [];
  if (summary.unverifiedFigures.length > 0) {
    problems.push(
      `${summary.unverifiedFigures.length} figure${
        summary.unverifiedFigures.length === 1 ? "" : "s"
      } above (${summary.unverifiedFigures.join(", ")}) could not be found in the run data. ` +
        "Trust the numbers, not the prose, for those.",
    );
  }
  if (summary.unknownMetrics.length > 0) {
    problems.push(
      `${summary.unknownMetrics.join(", ")} — cited by the summary, but no such measurement ` +
        "exists in these runs.",
    );
  }
  if (summary.untracedFindings.length > 0) {
    problems.push(
      `${summary.untracedFindings.length} point${
        summary.untracedFindings.length === 1 ? "" : "s"
      } quote a number without naming which measurement it came from, so it cannot be checked ` +
        "against the table.",
    );
  }
  if (!summary.verified && problems.length === 0) {
    problems.push(
      "This summary's figures were never checked against the run data — it predates the check, " +
        "or was written by something that skipped it.",
    );
  }

  return (
    <section className="mt-6 rounded-lg border bg-muted/30 p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <IconSparkles className="size-4 text-muted-foreground" aria-hidden />
        <h2 className="text-sm font-semibold">What the evaluation shows</h2>
        <span className="text-xs text-muted-foreground">
          written by <span className="font-mono">{summary.model}</span> from the run data below
          {summary.generatedAt ? `, ${when(summary.generatedAt)}` : null}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed">{summary.headline}</p>

      <ul className="mt-3 space-y-1.5 text-sm">
        {summary.findings.map((finding) => (
          <li key={finding.point} className="flex gap-2 leading-relaxed">
            <span aria-hidden className="select-none text-muted-foreground">
              &bull;
            </span>
            <span>{finding.point}</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">What this does not establish. </span>
        {summary.caveat}
      </p>

      {problems.length > 0 && (
        <div className="mt-3 flex gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <IconAlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">This summary did not pass its own checks.</p>
            <ul className="mt-1 space-y-1">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
            <p className="mt-1">
              Regenerate with <code>make eval-summary</code>.
            </p>
          </div>
        </div>
      )}

      {summary.stale && (
        <p className="mt-3 flex gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <IconAlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            Written before {newRuns > 0 ? `${newRuns} of the runs` : "the current runs"} below.
            The numbers in the table are current; this summary is not. Regenerate with{" "}
            <code>make eval-summary</code>.
          </span>
        </p>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground/80">
        Written for a non-technical reader — the measurement names, and which one each point
        rests on, are in <strong>Technical numbers</strong> below. Generated by one eval-time
        call and cached, so it costs nothing per view, and it is <strong>not</strong> part of the
        answer path: SPEC §5.2&apos;s single-generation-call rule covers <code>POST /ask</code>,
        which never touches this. Every figure above is checked against the run data before it is
        cached.
      </p>
    </section>
  );
}

/** No cached summary. Says how to make one rather than leaving a gap. */
function SummaryMissing() {
  return (
    <section className="mt-6 rounded-lg border border-dashed bg-muted/20 p-4 text-sm">
      <h2 className="font-medium">No summary generated yet</h2>
      <p className="mt-1 text-muted-foreground">
        Run <code className="font-mono">make eval-summary</code> to write the plain-English
        summary of the runs below. It makes one eval-time model call and caches the result, so
        it needs a key once and then costs nothing per view.
      </p>
    </section>
  );
}

/**
 * The comparison table — configurations across the top, metrics down the side.
 *
 * This orientation on purpose: the question the harness answers is "did this configuration
 * change help", so the thing being compared belongs in the columns where two numbers sit side
 * by side. One column per run, with metrics as rows, would put the comparison in the wrong axis.
 *
 * Only the newest run of each configuration is shown. Two runs of the *same* config differ only
 * by retrieval nondeterminism, which is noise here rather than a result.
 */
function Comparison({ runs }: { runs: EvalRun[] }) {
  // Ordered by when each configuration was *first* run, so the columns read left-to-right as
  // the progression actually happened. `groupByConfig` preserves newest-first order, which
  // would otherwise put the most recent experiment in the baseline column.
  const columns = [...groupByConfig(runs)]
    .map(([config, all]) => ({ config, run: all[0], firstSeen: all[all.length - 1].generated_at }))
    .sort((a, b) => (a.firstSeen < b.firstSeen ? -1 : 1));
  if (columns.length < 2) return null;

  const baseline = columns[0];
  const latest = columns[columns.length - 1];

  return (
    <section>
      <h3 className="text-sm font-semibold">Configurations compared</h3>
      <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
        Newest run of each configuration, columns ordered by when that configuration was first
        tried. The delta names exactly what it subtracts — run order is not a progression, so no
        direction is implied. At n={baseline.run.n_scored} a few points is inside sampling noise:
        read these as <strong>directional</strong> and check the per-question win/loss counts in{" "}
        <code>docs/EVALUATION.md</code> before concluding anything.
      </p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[42rem] text-xs">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2 pr-4 font-medium">metric</th>
              {columns.map(({ config, run }) => (
                <th key={config} className="py-2 pr-4 font-medium">
                  <span className="font-mono">{config}</span>
                  <span className="block font-normal text-muted-foreground">
                    k={run.k} · {when(run.generated_at)}
                  </span>
                </th>
              ))}
              <th className="py-2 font-medium">
                Δ
                <span className="block font-normal text-muted-foreground">
                  <span className="font-mono">{latest.config}</span>
                  {" − "}
                  <span className="font-mono">{baseline.config}</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {HEADLINE_METRICS.map((metric) => {
              const newest = latest.run.overall[metric] ?? null;
              const oldest = baseline.run.overall[metric] ?? null;
              return (
                <tr key={metric} className="border-b border-border/40">
                  <td className="py-1.5 pr-4 font-mono">{metric}</td>
                  {columns.map(({ config, run }) => (
                    <td key={config} className="py-1.5 pr-4 tabular-nums">
                      {format(run.overall[metric])}
                    </td>
                  ))}
                  <td className="py-1.5 tabular-nums">
                    <Delta value={newest === null || oldest === null ? null : newest - oldest} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RunCard({ run }: { run: EvalRun }) {
  const categories = Object.entries(run.by_category ?? {});
  const suspect = (run.per_question ?? []).filter((q) => q.suspect);

  return (
    <details className="rounded-lg border bg-muted/20 px-3 py-2">
      <summary className="cursor-pointer text-xs">
        <span className="font-mono font-medium">{run.config}</span>
        <span className="text-muted-foreground">
          {" "}
          · k={run.k} · {run.n_scored} scored, {run.n_unanswerable} unanswerable excluded ·{" "}
          {when(run.generated_at)}
        </span>
      </summary>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          <h4 className="text-xs font-medium">Overall</h4>
          <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {HEADLINE_METRICS.map((metric) => (
              <div key={metric} className="contents">
                <dt className="font-mono text-muted-foreground">{metric}</dt>
                <dd className="tabular-nums">{format(run.overall[metric])}</dd>
              </div>
            ))}
          </dl>
        </div>

        {categories.length > 0 && (
          <div>
            <h4 className="text-xs font-medium">By category</h4>
            <div className="mt-1.5 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pr-3 font-normal">category</th>
                    <th className="pr-3 font-normal">n</th>
                    <th className="pr-3 font-normal">norm_recall@10</th>
                    <th className="font-normal">entity_cov@20</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map(([name, metrics]) => (
                    <tr key={name}>
                      <td className="pr-3">{name}</td>
                      <td className="pr-3 tabular-nums">{metrics.n ?? "—"}</td>
                      <td className="pr-3 tabular-nums">
                        {format(metrics["normalized_recall@10"])}
                      </td>
                      <td className="tabular-nums">{format(metrics["entity_coverage@20"])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {suspect.length > 0 && (
        <p className="mt-3 text-xs text-amber-600 dark:text-amber-500">
          {suspect.length} question{suspect.length === 1 ? "" : "s"} flagged by the harness:{" "}
          {suspect.map((q) => `${q.id} (${q.suspect})`).join(", ")}
        </p>
      )}

      <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">{run.file}</p>
    </details>
  );
}

/**
 * Every metric, behind a disclosure.
 *
 * A `<details>` rather than a toggle button on purpose: it needs no client component, no
 * hydration and no JavaScript, and it keeps this page a plain server render — which is what
 * lets `force-dynamic` above pick up a run written seconds ago.
 */
function Traceability({ summary }: { summary: EvalSummary }) {
  return (
    <section>
      <h3 className="text-sm font-semibold">What each point above rests on</h3>
      <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
        The summary is written without metric names in it, so this is where they live. Each point
        carries the keys it was generated from; every figure in the prose is checked against
        those runs before the summary is cached, and any that is not found is named up there
        rather than removed.
      </p>
      <dl className="mt-3 space-y-2 text-xs">
        {summary.findings.map((finding) => (
          <div key={finding.point} className="grid gap-1 md:grid-cols-[1fr_14rem] md:gap-4">
            <dt className="text-muted-foreground">{finding.point}</dt>
            <dd className="font-mono">
              {finding.metrics.length > 0 ? (
                finding.metrics.join(", ")
              ) : (
                <span className="not-italic text-muted-foreground/60">
                  no measurement named
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** The metric caveats. Technical vocabulary, so it lives with the technical numbers. */
function HowToReadThese() {
  return (
    <section className="border-t pt-4 text-xs text-muted-foreground">
      <h3 className="font-medium text-foreground">
        How to read these — written by hand, not generated
      </h3>
      <p className="mt-2 max-w-3xl">
        Three of these metrics are reported but <strong>not</strong> load-bearing, and knowing
        why is the point. <span className="font-mono">recall@k</span> has a per-question ceiling
        that varies 36-fold, so the raw mean is dominated by label cardinality —{" "}
        <span className="font-mono">normalized_recall@k</span> is the honest one.{" "}
        <span className="font-mono">mrr@10</span> and <span className="font-mono">ndcg@10</span>{" "}
        are saturated and measure the entity filter rather than the ranking. And{" "}
        <span className="font-mono">entity_coverage@20</span> is pinned at 1.000 by the
        per-company quota design, so it only informs a quota-on/quota-off comparison.
      </p>
      <p className="mt-2 max-w-3xl">
        These are the constraints the generated summary is written against — they are given to it
        as facts, and they are stated here so they do not have to be taken on a model&apos;s
        word. The full reasoning, with the measurements behind it, is in{" "}
        <code>docs/EVALUATION.md</code>.
      </p>
    </section>
  );
}

/**
 * Every metric, behind a disclosure — and everything with a metric name in it.
 *
 * A `<details>` rather than a toggle button on purpose: it needs no client component, no
 * hydration and no JavaScript, and it keeps this page a plain server render — which is what
 * lets `force-dynamic` above pick up a run written seconds ago.
 */
function TechnicalNumbers({ runs, summary }: { runs: EvalRun[]; summary: EvalSummary | null }) {
  return (
    <details className="group mt-6 rounded-lg border">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
        <span className="text-sm font-medium">
          Technical numbers{" "}
          <span className="font-normal text-muted-foreground">
            — {runs.length} run{runs.length === 1 ? "" : "s"}, every metric, and what the
            summary rests on
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          <span className="group-open:hidden">Show ▾</span>
          <span className="hidden group-open:inline">Hide ▴</span>
        </span>
      </summary>

      <div className="space-y-6 border-t px-4 pb-5 pt-4">
        {summary && <Traceability summary={summary} />}

        <Comparison runs={runs} />

        <section>
          <h3 className="text-sm font-semibold">
            All runs <span className="font-normal text-muted-foreground">({runs.length})</span>
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Newest first. Runs are never overwritten, so configurations can be compared.
          </p>
          <div className="mt-3 space-y-2">
            {runs.map((run) => (
              <RunCard key={run.file} run={run} />
            ))}
          </div>
        </section>

        <HowToReadThese />
      </div>
    </details>
  );
}

export default async function EvalsPage() {
  const runs = await listRuns();
  // Sequential rather than parallel on purpose: staleness is decided against the run files
  // actually on disk, so the summary reader needs the list first.
  const summary = runs.length > 0 ? await readSummary(runs.map((run) => run.file)) : null;
  const newRuns = summary
    ? runs.filter((run) => !summary.runFiles.includes(run.file)).length
    : 0;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-center gap-2">
        <IconChartBar className="size-5" aria-hidden />
        <h1 className="text-lg font-semibold">Retrieval evaluation</h1>
      </div>

      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        How well the system finds the right filings, measured over a hand-labelled set of
        questions. Every <code>make eval</code> run is kept, so configurations can be compared.
      </p>

      {runs.length === 0 ? (
        <div className="mt-6 rounded-lg border bg-muted/20 px-4 py-6 text-sm">
          <p className="font-medium">No eval runs yet.</p>
          <p className="mt-1 text-muted-foreground">
            Run <code className="font-mono">make eval</code> from the repo root. It needs Qdrant
            and an API key, and embeds 22 questions — about two minutes.
          </p>
        </div>
      ) : (
        <>
          {summary ? <Summary summary={summary} newRuns={newRuns} /> : <SummaryMissing />}
          <TechnicalNumbers runs={runs} summary={summary} />
        </>
      )}

      {/*
        One sentence of the caveat stays above the fold in plain words; the version with the
        metric names in it sits inside Technical numbers. A reader who never opens that section
        should still know the scores are not all they appear, and a reader who does open it gets
        the reason.
      */}
      <p className="mt-8 max-w-3xl border-t pt-6 text-xs text-muted-foreground">
        Not every score here can move: some are held near their maximum by how the search is
        designed, and others have almost no room left to improve, so a high number is not by
        itself good news. Which ones, and why, is written out by hand under{" "}
        <strong>Technical numbers</strong> and in <code>docs/EVALUATION.md</code>.
      </p>
    </div>
  );
}
