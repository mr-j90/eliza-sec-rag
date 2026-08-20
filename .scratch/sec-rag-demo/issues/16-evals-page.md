# An evals page in the front-end, and where runs are stored

Type: task
Status: resolved
Blocked by: 10, 12

## Question

**Where do eval runs live, and how does a reader see them without a terminal?**

Added after the map was complete, at the user's request. It extends the destination slightly —
the eval work existed only as JSON on disk and prose in `docs/EVALUATION.md`, so a panel could
read *about* the numbers but not see them.

## The storage decision: JSON files, not SQLite

Asked as an open question; recommended and taken as JSON files, one per run.

**Against SQLite.** The harness that produces runs is Python; the front-end is TypeScript.
`frontend/lib/db/` is deliberately the only SQL in the app, and putting a second runtime's
writer into that schema means coordinating migrations across two languages — for data with no
relational shape.

**For JSON.** Eval runs are append-only artefacts: no update, no delete, no joins. The
operation that actually matters is **comparing two runs**, and files diff natively where rows
need a query layer. `metrics.py` already emitted JSON, so the Python side barely changed. And a
run can be committed as a baseline if wanted; a SQLite blob cannot be reviewed in a diff.

## The change that made the page possible

`metrics.py` **overwrote a single file** — `retrieval_metrics.json` — so history did not exist.
Every before/after table in `docs/EVALUATION.md` was produced by copying results out by hand
between runs, which is exactly the workflow a page like this should remove.

Now one file per run, `<timestamp>--<config>.json`, never overwritten, plus `latest.json` as a
stable path for anything scripted. Timestamp first so a directory listing sorts chronologically;
config second so two runs are distinguishable without opening them.

`eval/results/` stays gitignored — runs are artefacts of a specific index, not source.

## What the page shows

`/evals`, gated by the existing middleware like every other route.

- **A comparison table** — configurations across the columns, metrics down the rows. That
  orientation because the question is "did this configuration change help", so the things being
  compared belong side by side. Only the newest run per configuration; two runs of the *same*
  config differ by retrieval nondeterminism, which is noise rather than a result.
- **Every run, expandable** — overall metrics, per-category breakdown, and any question the
  harness itself flagged as suspect.
- **A "read these carefully" footer** carrying `docs/EVALUATION.md`'s central point onto the
  screen: three of the metrics shown are reported but **not** load-bearing —
  `recall@k`'s ceiling varies 36-fold, `mrr@10`/`ndcg@10` are saturated and measure the entity
  filter rather than the ranking, and `entity_coverage@20` is pinned at 1.000 by the quota
  design. A metrics page that showed the numbers without that would be worse than no page.
- **An empty state** that names the command to run, because before anyone runs `make eval` this
  page is legitimately blank and that is not an error.

Nav: an **Evals** button in the sidebar, active-state aware.

## The render caught two bugs the types could not

Both about the delta column, and both only visible with real data in it.

1. **The comparison was subtracting backwards.** `groupByConfig` preserves newest-first order,
   so the most recent experiment landed in the baseline column. Fixed by ordering columns by
   when each configuration was *first* run.
2. **Then the framing was still misleading.** With columns in run order, the label
   "newest − oldest" implies a progression — but fusion-only was run *last* here purely to
   produce a comparison row, not because it is a newer design. The delta header now names both
   configurations explicitly (`hybrid+quotas+prefix − hybrid+quotas+prefix+rerank`) so no
   direction is implied at all.

Worth recording because `tsc` was clean throughout. Neither was a type error; both were wrong
*meaning*, and only rendering the page with two real configurations in it surfaced them.

## Verification

- `/evals` returns 200 authenticated, renders the comparison table, all runs, and the caveat
  footer. Verified against two real configurations (`+rerank` and fusion-only).
- `make check` clean; **201 free python + 34 frontend green**.
- `docs/EVALUATION.md`'s reproduction appendix updated — it still described a single
  overwritten file.

## Not done

No test covers `lib/evals/runs.ts` or the page. The frontend suite is `node --test` over
`lib/**/*.test.ts` and this reads the filesystem outside the app directory, so a test needs a
fixtures directory and an `EVAL_RESULTS_DIR` override — which the module already supports for
exactly that reason. Worth adding; not done here, and stated rather than left to be noticed.
