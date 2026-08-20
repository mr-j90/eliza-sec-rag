import { IconChartBar } from "@tabler/icons-react";

import { HEADLINE_METRICS, groupByConfig, listRuns } from "@/lib/evals/runs";
import type { EvalRun } from "@/lib/evals/runs";

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
    <section className="mt-8">
      <h2 className="text-sm font-semibold">Configurations compared</h2>
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
          <h3 className="text-xs font-medium">Overall</h3>
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
            <h3 className="text-xs font-medium">By category</h3>
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

export default async function EvalsPage() {
  const runs = await listRuns();

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-center gap-2">
        <IconChartBar className="size-5" aria-hidden />
        <h1 className="text-lg font-semibold">Retrieval evaluation</h1>
      </div>

      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Every <code>make eval</code> run, newest first. Runs are never overwritten, so
        configurations can be compared.
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
          <Comparison runs={runs} />

          <section className="mt-8">
            <h2 className="text-sm font-semibold">
              All runs <span className="font-normal text-muted-foreground">({runs.length})</span>
            </h2>
            <div className="mt-3 space-y-2">
              {runs.map((run) => (
                <RunCard key={run.file} run={run} />
              ))}
            </div>
          </section>
        </>
      )}

      <section className="mt-10 border-t pt-6 text-xs text-muted-foreground">
        <h2 className="font-medium text-foreground">Read these carefully</h2>
        <p className="mt-2 max-w-3xl">
          Three of these metrics are reported but <strong>not</strong> load-bearing, and knowing
          why is the point. <span className="font-mono">recall@k</span> has a per-question
          ceiling that varies 36-fold, so the raw mean is dominated by label cardinality —{" "}
          <span className="font-mono">normalized_recall@k</span> is the honest one.{" "}
          <span className="font-mono">mrr@10</span> and <span className="font-mono">ndcg@10</span>{" "}
          are saturated and measure the entity filter rather than the ranking. And{" "}
          <span className="font-mono">entity_coverage@20</span> is pinned at 1.000 by the
          per-company quota design, so it only informs a quota-on/quota-off comparison.
        </p>
        <p className="mt-2 max-w-3xl">
          The full reasoning, with the measurements behind it, is in{" "}
          <code>docs/EVALUATION.md</code>.
        </p>
      </section>
    </div>
  );
}
