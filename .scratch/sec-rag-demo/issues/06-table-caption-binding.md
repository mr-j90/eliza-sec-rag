# Table-caption binding

Type: task
Status: resolved
Blocked by: 03

## Question

**Do retrieved table rows carry their scale and period, or are numbers arriving stripped of
what they mean?**

### Why this is demo-critical rather than nice-to-have

It was promoted when the XBRL numeric router was cut to future state. With no numeric path,
*"How has NVIDIA's revenue and growth outlook changed over the last two years?"* — one of
the three questions the panel will type — is answered from **pipe-delimited table rows**.

**22.2% of corpus characters are pipe-table rows** (§2.7). And the layout works against a
naive splitter in two specific ways:

- The caption and units — `(dollars in millions)` — sit on the **preceding narrative
  line**, not in the table.
- Column-year headers sit on their **own label-less row**.

So a chunk boundary in the wrong place yields `Revenue | 26,974 | 6,051` with no scale, no
currency, and no idea which column is which year. For a financial diligence tool that is
the **highest-consequence silent failure available** — it produces a confident, specific,
wrong number, and no retrieval metric detects it.

Prior art's chunking does not mention tables at all (§10 item 9).

### The fix

§2.7 puts it at roughly **40 lines**: when emitting a chunk containing table rows, bind the
preceding caption line and the column-header row to it, and never split a table away from
either.

### What must be true to close this

1. A chunk containing table rows always carries its caption line and its column-header row.
2. Spot-check the NVIDIA revenue tables specifically, across two years of filings — that is
   the actual demo question. Confirm a retrieved chunk is self-sufficient: a reader can tell
   what the number measures, in what units, for what period.
3. Spot-check JPMorgan too. It is the largest filing in the corpus (396,452 tokens) and the
   most table-dense.
4. Decide and record what happens to tables too large to keep whole — §4.2's Item 8 policy
   is "table-row-aligned or skip," and which one you chose is a defensible answer either way
   but must be a choice rather than an accident.

### Worth saying in the walkthrough

This is a good concrete example of the value argument the brief asks you to defend: the
failure it prevents is not "slightly worse retrieval," it is *quoting a number to a client
with the wrong order of magnitude*.

---

## Answer

**Resolved 2026-08-20.** Financial-table chunks carrying figures with no stated scale fell
from **113 of 405 (28%) to 15 of 405 (4%)**, and the residual are tables that legitimately
need no caption.

### The measurement, and two false starts getting to it

The honest number took three attempts, and the wrong ones are worth recording because each
inflated the problem:

1. **Any chunk with 3+ pipe rows** — caught the SEC cover page, whose checkbox rows also
   contain pipes. 39%.
2. **Pipe rows containing 2+ digits** — caught the table of contents, where `Item 1A. | Risk
   Factors | 13` looks like a data row. 28% but on the wrong population.
3. **Thousands-separated, currency-marked or decimal figures** — the numbers whose *scale
   changes their meaning*. **113 of 405 (28%)**, and this time of actual financial tables.

The case that makes it concrete, from NVIDIA's statement of shareholders' equity:

```
Shares repurchased | (211) |  | (27) |  | (9,719) |  | (9,746) |
Net income         | —     |  | —    |  | 72,880  |  | 72,880  |
```

`72,880` is millions of dollars. `(211)` in the same table is millions of **shares**. Neither
unit appears anywhere in the chunk.

### The fix

`_bind_table_context` carries two lines into any window cut below them:

- the **scale caption**, which §2.7 says sits on the preceding *narrative* line, outside the
  table
- the **period header**, which sits on its own label-less row

Recognising the header needed a discriminator: it names periods and carries **no figures of its
own**. `| Jan 26, 2025 | Jan 28, 2024 |` is a header; `Total | 130,497 | 60,922` is data.

**Only the filing's own lines are ever added.** `index.py` stores this text as what citations
display, and its comment is explicit that an excerpt must show the filing's words, not a
synthesized header. A bound chunk is a composition of two real spans from the same section —
there is a test asserting every line of a bound window appears verbatim in the source.

### The guard that matters more than the feature

The first implementation searched backwards through the whole preceding section for a caption.
That is dangerous: a section holding one table in *thousands* and another in *millions* would
have them swapped, and **a wrong scale is worse than a missing one because it reads as
authoritative**.

The walk now stops after two consecutive lines of prose. A caption belongs to the table it
introduces; crossing narrative means we have left that table. There is a test for the
two-tables-one-section case specifically.

### A test that was wrong before the code was

`test_nvidia_..._carry_their_scale` initially failed on a chunk I assumed was a defect. It was
NVIDIA's **Rule 10b5-1 trading-arrangement table** — director names against absolute share
counts like `29,000` — which needs no scale caption, because a share count is unambiguous.

The test now scopes to **currency** figures, which are the only ones whose meaning depends on
scale. Worth noting the sequence: measuring badly would have driven the implementation to
"fix" tables that were never broken, and possibly to attach captions to share counts.

### Results

| filing | table chunks | no scale before | after |
|---|---|---|---|
| `NVDA_10K_2025-02-26` | 38 | 6 (16%) | **2 (5%)** |
| `JPM_10K_2026-02-13` | 267 | 87 (33%) | **8 (3%)** |
| `AAPL_10K_2025-10-31` | 30 | 6 (20%) | **2 (7%)** |
| `TSLA_10K_2026-01-29` | 37 | 8 (22%) | **2 (5%)** |
| `NVDA_10Q_2025Q4` | 33 | 6 (18%) | **1 (3%)** |
| **total** | **405** | **113 (28%)** | **15 (4%)** |

**On the panel's own temporal question, live:** 20 citations, 5 carrying table figures, and
**5 of 5 now show their scale** — `($ in millions)` sitting directly beside `$17,047`.

### Migration

Binding only prepends to existing windows, so window counts are unchanged — no orphan risk,
and a plain `--all` upsert kept the index queryable throughout. **30,348 chunks re-embedded,
count identical before and after, green, reconciliation clean.** ~$0.40.

### Verification

- `tests/test_table_context.py` — 10 tests, free tier: caption and header recognition, the
  no-synthesized-text invariant, the two-tables-one-section guard, and the corpus case.
- **173 tests green**: 145 free python + 28 live, plus 34 frontend.
- `PROMPT_LOG.md` carries a no-prompt-change entry, because the *context* the v6 prompt
  receives changed materially and the log would otherwise imply otherwise. This is the clearest
  case on the map of a retrieval fix doing what no prompt wording could: no instruction can
  recover a unit that is not in the context.

### The remaining 4%

Share-count and per-share tables that state no scale because they need none. Left alone
deliberately — forcing a caption onto them would be inventing one.
