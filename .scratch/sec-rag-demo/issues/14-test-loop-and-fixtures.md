# The test loop: one command, layered by what it needs, plus a fixture corpus

Type: task
Status: resolved
Blocked by: 01

## Question

**Can you run the whole suite in one command, in seconds, without Docker or an API key —
and is there a small fixture corpus that exercises the cases the research says are hard?**

This lands early on purpose. Every ticket after it changes text-processing behaviour, and
the point is to catch regressions while building rather than discovering them during the
walkthrough.

Scope was decided when this ticket was added: **local loop only, no GitHub Actions, no
deployment.** See the map's Out-of-scope section for why.

## The layering already exists — it just isn't named

Measured across prior art's 93 Python tests:

| Layer | Files | Tests | Needs | Costs money |
|---|---|---|---|---|
| **Unit** | `test_aliases`, `test_golden_set`, `test_ingest`, `test_metrics`, `test_query`, `test_smoke` | **53** | nothing | no |
| **Integration** | parts of `test_ask`, `test_answer_contract` | **11** | Qdrant | no |
| **Live** | rest of `test_answer_contract`, `test_quotas`, `test_retrieve` | **29** | Qdrant **+ real `OPENAI_API_KEY`** | **11 make real generation calls** |
| **Frontend** | 6 `*.test.ts` / 8 suites under `lib/` | **34** | nothing (SQLite is a file) | no |

**Corrected by [01](01-port-backend.md), which measured this.** An earlier version of this
ticket said no layer needs an API key because `test_ask.py` mocks OpenAI. Only *one* test
there is mocked: **29 tests across three files require a live key**, and 11 of them spend
money on every run. So the loop is three tiers, not two, and the money-spending tier must be
opt-in — never part of the command you run on every save.

So the work is naming the split and putting one door in front of it. Something like:

```
make test        # 53 unit + 34 frontend — no services, no key. Measured: ~18s
make test-int    # + the 11 Qdrant-only tests. Free.
make test-live   # + the 29 that need a key. SPENDS MONEY — opt-in, never the default
make check       # tsc --noEmit + next lint  (scripts exist; nothing currently runs them)
```

Note `typecheck` and `lint` already exist as frontend scripts and are not wired into
anything. They are free to add and they catch a class of error the tests do not.

Whether it is a Makefile, a shell script, or `uv` scripts does not matter much — pick one
and document it in the README (ticket 12).

## The fixture corpus

Tests must not read all 246 files / 81 MB. Carve a small set, chosen so that each file is
there for a *named reason* from the research rather than because it was convenient:

| Fixture | Why it earns its place |
|---|---|
| `BAC_10K_2025-02-25` | Largest XBRL residue in the corpus — **86,721 tokens** on one line (§2.3) |
| `TSLA` 10-K | ALL-CAPS headers, and Item 1A is a single **79,624-char** line (§2.4, §2.5) |
| `AAPL` 10-K | Headers glued behind page furniture; 95,328-char line (§2.5 form B) |
| `GOOG` 10-Q + `META` 10-K | Zero-space headers. **Two corrections found by measuring:** the corpus ticker is `GOOG`, not `GOOGL`; and the zero-space form lives in the **10-Q**, not the 10-K — `GOOG_10K` writes `Item 9A.` with normal spacing, so the 10-K tests nothing. `GOOG`'s 10-Q also combines zero-space *with* ALL CAPS (`ITEM 6.E`), which is harder than either form alone |
| `AMZN` | Pipe headers, and pipe-TOC with the trailing page number as discriminator (§2.5 form A/A′) |
| `JPM` 10-K | Largest file at **396,452 tokens**, most table-dense; also only 4 filings, which is the quota asymmetry against Apple's 16 (§2.9) |
| `NVDA` 10-K + `NVDA_10Q_2025Q4` | The temporal demo question, the 10-Q material-changes trap (§4.4), and the citation `[C11]` fiscal-year contradiction found by ticket 01 |
| `ABBV_10K_2025-02-14` | Second `fiscal_year` off-by-one on a different year boundary from AMZN, so ticket 15's fix cannot be tuned to one filing |
| `NFLX_10K_2026-01-23` + `LLY_10K_2026-02-12` | §2.3's two anchor misses, now identified. **And only one is real:** `LLY` misses solely because the arch doc's regex is case-*sensitive* — `re.IGNORECASE` recovers it free, leaving `NFLX` as the only file needing ticket 03's fallback |
| any `INTC` 10-K | Its sole regex match is an `Item 601(a)` phantom header (§2.5) |

Every one of those is a case some ticket on this map has to handle. A fixture set assembled
this way means ticket 03's reflow, ticket 02's segmenter and ticket 06's table binding all
have something to assert against on day one.

**Keep them small if you can** — a truncated slice that preserves the pathology is better
than a 1.5 MB file, and JPM at 396,452 tokens should probably be excerpted rather than
copied whole. Say in the answer whether you truncated and how, because a fixture that has
been quietly trimmed past its pathology is worse than no fixture.

## Standing discipline once this closes

Every subsequent build ticket lands with tests, per `/tdd`. The map's Notes carry this. It
is cheap here specifically because almost everything this map builds is a pure function
over text — XBRL strip, reflow, segmentation, table-caption binding, RRF arithmetic,
citation enforcement, coverage computation. None of it needs a service to test.

## What must be true to close this

1. One command, no Docker, no key, finishes fast enough that you actually run it.
2. The Qdrant-backed layer is separately runnable and clearly labelled — not silently
   skipped, because a suite that quietly skips 40 tests reports green while testing
   nothing.
3. The fixture set exists, and each file's reason is recorded.
4. The command is in the README (ticket 12) so the panel can run it too.

---

## Answer

**Resolved 2026-08-20.** One door, two tiers, and a self-verifying fixture manifest. All
**156 tests pass** — and 29 of them had never run in this repo before.

### The loop

```
make test        93 python + 34 frontend   14.4s   no Docker, no key, no cost
make test-live   29 python                120.2s   needs a key; 11 real generation calls
make test-all    everything
make check       tsc --noEmit + next lint          clean
make up/down/index/answers                         services and data
```

`make help` prints the lot, including the warning that `test-live` spends money.

### The tiers are *selected*, not skipped — which was the point

`make test` reports **"93 passed, 29 deselected"** with **0 skipped**. That distinction is
the whole ticket: "29 skipped" is indistinguishable from a suite that quietly tested nothing,
while "29 deselected" is a claim you can read.

`tests/conftest.py` marks tests by the **fixture they request** rather than by hand, so a new
test inherits the right tier automatically:

- `indexed` — the module-scoped fixture in `test_retrieve.py` and `test_quotas.py`
- `live` — autouse in `test_answer_contract.py`, so all 11 of its tests are caught without
  naming any of them

One test gates itself inline and cannot be caught that way
(`test_three_company_question_still_makes_exactly_one_llm_call`), so it is listed by name —
and the conftest **raises a `UsageError` if that name ever stops being collected**, because a
rename would otherwise slide a paying test into the free tier, where it would skip itself and
still report green.

### Two guards against green-but-untested

Both exist because the default behaviour reports something misleading. Both verified by
running them.

**`RAG_REQUIRE_LIVE=1`** — `make test-live` sets it. Without a key the run would skip all 29
and exit 0. Now it exits **1** with the reason:

```
RAG_REQUIRE_LIVE=1 but the live tier cannot run:
  - no provider key — set OPENAI_API_KEY (or OPENAI_BASE_URL for a local ...)
  - Qdrant not reachable at http://127.0.0.1:59999 — `docker compose up -d`

These tests would otherwise skip and the run would report green.
```

**Missing corpus** — not in the original ticket, found while measuring. The corpus is a
prerequisite of the **free** tier, not just the live one: hiding `edgar_corpus/` made **21
tests fail** with assorted assertion errors, leaving a newcomer to deduce that one missing
directory caused all of them. Now it exits 1 with a single message naming the directory and
the download.

### The layering, measured — and it corrects ticket 01 twice

| Layer | Tests | Needs | Cost |
|---|---|---|---|
| Python free | **93** | nothing | none |
| Python live | **29** | Qdrant **+ real key** | 17 embed queries; **11 real generation calls** |
| Frontend | **34** (8 suites) | nothing | none |

**There is no Qdrant-only tier.** Ticket 01 reported 11 tests needing "Qdrant only" — wrong.
Proved by two runs: with `QDRANT_URL` at a dead port, 64 passed / 29 skipped; with Qdrant
**up** and the key emptied, still 64 passed / 29 skipped, and every skip reason was
key-related. The binding constraint on all 29 is the key, not the service. (Free tier is now
93 rather than 64 because this ticket added 29 fixture tests.)

### The fixture corpus is a manifest, not copies

`tests/fixtures/pathologies.json` — 13 filings, each with why it earns its place, which
tickets depend on it, and a **verifiable claim**. `tests/test_fixtures.py` asserts every
claim (29 tests).

**Why a manifest rather than copied files** — the ticket asked for truncation, and truncation
turned out to be unsafe:

1. **`ingest.py`'s `_LATE_DETECTION` guard is a *fraction* of body length (0.9).** Shortening
   a file changes whether header detection counts as "late", so a truncated fixture can
   segment differently from the real filing — quietly misleading ticket 02, the very ticket it
   would exist to serve.
2. Whole copies would be ~6.4 MB of duplicated public-domain text already on disk, in a repo
   where `edgar_corpus/` is gitignored *because* the brief links it for redownload.
3. The suite already requires the corpus, by design, with a test asserting it. A manifest
   matches how the suite works instead of inventing a second source of truth.

The verification is not ceremony: every ticket on this map reasons from these measurements.
If BAC's 285,080-char line or Amazon's off-by-one fiscal year stops holding, the premise moved
and a silent drift would be invisible everywhere else.

### Four measurement corrections found by writing the assertions

Writing the claims down falsified four of them, which is the argument for writing them down.

1. **The zero-space header fixture was the wrong file.** `GOOG_10K` writes `Item 9A.` with
   normal spacing — it tests nothing. The zero-space form (§2.5 form D) is in the **10-Q**.
   Swapped to `GOOG_10Q_2025Q3`, which is **better than the arch doc's framing**: it combines
   zero-space *with* ALL CAPS (`ITEM 6.E`), forms C and D at once, harder than either alone.
   `META_10K` does use it mixed-case (`Item 9A.C`), so the two fixtures now cover both
   casings.
2. **The ticker is `GOOG`, not `GOOGL`.** No `GOOGL` file exists.
3. **NVDA writes `fiscal year 2026`** (53 occurrences), not `fiscal 2026`. My first claim was
   too narrow and failed.
4. **Only one of §2.3's two anchor misses is real.** The misses are
   `LLY_10K_2026-02-12` and `NFLX_10K_2026-01-23` — and §2.3's "244/246" only reproduces with
   its **case-sensitive** regex. Adding `re.IGNORECASE` gives 245/246, recovering LLY for
   free. **Ticket 03 needs a fallback for one file, not two.** Both are kept as fixtures with
   claims that pin this distinction.

### One test asserts a defect is still present

`test_fiscal_year_off_by_one_cases_are_still_wrong` pins ticket 15's bug for `AMZN` and
`ABBV`. It **fails the moment ticket 15 fixes it**, at which point invert it. Deliberate: a
known defect should not be able to disappear quietly either.

### Noted for ticket 12

`next lint` prints *"`next lint` is deprecated and will be removed in Next.js 16"* and
suggests `npx @next/codemod@canary next-lint-to-eslint-cli .`. Works today; will not forever.

### Not done

`make test-fe` still relies on `bun run test`, which works. But `bun run dev` remains broken
on Node 25.8.0 (ticket 01, → ticket 12) — that is the frontend *dev server*, not the tests, so
it does not block this loop.
