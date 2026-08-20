# `fiscal_year` is wrong for 37 of 246 filings

Type: task
Status: resolved
Blocked by: —

## Question

**How is a filing's fiscal year determined, so that the year on a citation matches the year
the filing is actually about?**

Surfaced by [01](01-port-backend.md), measured, not suspected. Unblocked because it is a
defect in already-ported code and nothing else has to land first.

## Two distinct causes

### Cause 1 — the filing-date fallback is off by one (37 filings)

`ingest.py` computes:

```python
fiscal_year = int((period_end or filing_date or "0")[:4])
```

**54 filings have no `Report Period` header** (§2.2 measured this: 192/246 have a 10-line
header, 54 have 8). Those fall back to the **filing date** — and a 10-K is filed one to three
months *after* the fiscal year it reports on. Measured against the true period end:

| | count |
|---|---|
| `fiscal_year` **wrong** (off by one) | **37** |
| correct | 15 |
| no parseable URL | 2 |

| Filing | Labelled | Actually covers |
|---|---|---|
| `AMZN_10K_2026-02-06` | 2026 | **2025** |
| `ABBV_10K_2025-02-14` | 2025 | **2024** |
| `ADBE_10K_2026-01-15` | 2026 | **2025** |
| `AMD_10K_2026-02-04` | 2026 | **2025** |
| `AXP_10K_2026-02-06` | 2026 | **2025** |

**The fix is free and already sitting in the header.** The `URL` field embeds the true period
end — `.../amzn-20251231.htm`. §2.2 said exactly this: *"The 54 files missing `Report
Period`/`Quarter` need fiscal period derived from the filename date or from the `URL` field
(which embeds the period)."* `ingest.py` uses the filing date instead. Prefer
`period_end` → `URL`-embedded date → filing date, in that order.

Two filings have no parseable URL date and need their own fallback. Name them.

### Cause 2 — off-calendar filers mislabel even *with* a `Report Period`

A 10-Q's period end falls mid-fiscal-year, so for an issuer whose fiscal year does not end in
December, the calendar year of `period_end` is not the fiscal year the document is about.

NVDA's Q3 FY2026 (`period_end 2025-10-26`) is labelled `fiscal_year: 2025`, while the filing
text says "fiscal 2026". In the NVIDIA demo run, citation `[C11]` renders as **FY2025 against
an excerpt discussing fiscal 2026** — from `NVDA_10Q_2025Q4_2025-11-19_full.txt`.

Off-calendar filers in this corpus: **NVDA** (Jan), **AAPL** (Sep), **MSFT** (Jun), **DIS**
(Sep/Oct). Note the 10-K sample that produced that list only covered filings that *have* a
`Report Period`, so re-derive it once cause 1 is fixed.

## Why it matters — two consequences, both demo-visible

1. **Year filters silently miss.** `retrieval_meta.fiscal_years` is a real filter. A question
   scoped to FY2025 will exclude an Amazon 10-K labelled 2026 that *is* FY2025, and include
   nothing that should be there. The failure is a quiet absence, not an error.
2. **Citations contradict themselves on screen.** `sources.tsx` renders
   `{form_type} FY{fiscal_year} · {section}` directly above the excerpt. A panel member
   reading "FY2025" above text discussing fiscal 2026 will ask about it — and that question
   lands on the credibility of every other number in the demo.

## The decision inside this ticket

`fiscal_year` is a single integer, and the two causes pull in different directions. An
off-calendar filer has a *filing-labelled* fiscal year (NVIDIA's "fiscal 2026") and a
*period-end calendar* year (2025). Options:

- Store the issuer's own fiscal-year label, and accept that FY2026 means different date ranges
  for different companies.
- Store the period-end calendar year, and accept that it contradicts the document text.
- Store both — `fiscal_year` plus `period_end` (already present) — and be explicit in the UI
  about which one is displayed.

Whichever way it goes, the **10-K off-by-one (cause 1) is an unambiguous bug** and should be
fixed regardless.

## Cost note

`fiscal_year` is payload, not vector — §9.6 puts it in the "absorbed for free" class, a label
*on* a chunk rather than a change *to* one. So fixing it is a payload update over 29,499
points, **not a re-embed**. Confirm that before choosing a heavier route.

## What must be true to close this

1. All 246 filings' `fiscal_year` verified against the period end derived from `Report
   Period` or the `URL` field. Report the count corrected.
2. The 2 filings with no parseable URL date named, with their fallback stated.
3. The NVIDIA `[C11]` case re-run and no longer self-contradictory.
4. A test over the fixture corpus (ticket 14) asserting the derivation, including at least one
   off-calendar filer and one `Report Period`-absent 10-K.

---

## Answer

**Resolved 2026-08-20.** Both causes fixed, 54 filings re-indexed, **131 tests green** (103
free + 28 live). The fix turned out to matter more than the ticket claimed, and the ticket's
own cost note was wrong.

### The consequence the ticket missed — and it was the important one

`query.py::_latest_fiscal_year` had **its own copy of the same derivation**
(`Report Period or Filing Date`), so the off-by-one filings inflated it. Measured:
**`LATEST_FISCAL_YEAR` read 2026 for a corpus whose newest period ends in 2025.**

Every relative time expression anchors to that constant, so "the last two years" resolved to
`[2025, 2026]` — and nothing in the corpus is 2026. On the panel's own NVIDIA question:

| | before | after |
|---|---|---|
| `fiscal_years` filter | `[2025, 2026]` | **`[2024, 2025]`** |
| distinct years retrieved | `[2025]` — **one year** | **`[2024, 2025]` — two** |

**A question asking for two years was receiving one, and answering confidently.** That is a
retrieval fix, not a display fix, and it is the strongest thing to come out of this ticket.

Two derivations of one number is what let it go unnoticed, so there is now one:
`ingest.fiscal_period`, imported by `query.py` rather than reimplemented.

### Cause 1 — the derivation

`fiscal_period(header)` returns `(period_end, fiscal_year)`, preferring:

1. **`Report Period:`** — 192/246, read never inferred.
2. **The date embedded in `URL:`** — recovers **53 of the remaining 54**. §2.2 pointed at this
   field for exactly this purpose and the code was ignoring it.
3. **Filing month** — one filing only.

Result: **37 filings corrected, all by exactly −1, all 10-Ks.** `LATEST_FISCAL_YEAR` 2026 → 2025.

**The 2 unresolvable filings, as the ticket required — and only 1 survived.**
`DE_10K_2025-12-18` was a regex artefact: its URL is `de-20251102x10k.htm`, and the date is not
flush against `.htm`, which my first pattern required. Loosening to `-(\d{8})[^/]*\.html?`
resolves it. That leaves **`GE_10K_2015-02-27`** — URL `gecc10k2014.htm`, no 8-digit date, and a
genuine outlier: a 2015 filing in a corpus the brief describes as 2023–2025. Its fallback is the
filing month (a 10-K filed Jan–Apr reports on the previous year → 2014, which the URL's own
`10k2014` confirms), and its `period_end` stays empty — that emptiness is the signal the year was
inferred rather than read.

### Cause 2 — fixed in the display, not the data

Per the decision taken on this ticket: **citations show the period, not a bare `FY` label.**

The `[C11]` filing needed no data change at all — `NVDA_10Q_2025Q4` already had
`period_end 2025-10-26` and `fiscal_year 2025`, both correct under a period-end reading. The
defect was entirely in what was rendered. And it was wider than one citation: **26 of that
filing's 67 chunks contain the string "fiscal year 2026"**, every one of which would have
appeared under a label reading FY2025.

```
old:  10-Q FY2025 · Item 2 — MD&A          <- reader spots the clash
new:  10-Q · period ending 2025-10-26 · Item 2 — MD&A
```

Changed on both sides deliberately, because they must not drift:

- `prompt.py::_label` — what the **model** reads. Handing a model a year its passage
  contradicts, when its first rule is to use only what it was given, invites it to state the
  wrong period. **`PROMPT_VERSION` → v5**, logged in `PROMPT_LOG.md`.
- `sources.tsx::periodLabel` — what the **reader** sees.
- `Citation` gained `period_end` on all three declarations (`prompt.py`, `lib/chat/types.ts`,
  `lib/ai/provider.ts`). A deliberate contract extension, not drift.

**Rejected: deriving the issuer's own fiscal-year label.** Measured rather than dismissed.
Inline XBRL carries `DocumentFiscalYearFocus` (`nvda-20251026...2026Q3`) and is authoritative
where it extracts — but two regex attempts over the residue reached only **93/246 and 74/246**;
AAPL, AMZN, GOOG, MSFT, TSLA, META, XOM, UNH, KO and DIS all missed. The arithmetic fallback is
fragile exactly where it matters: **52/53-week calendars** put JNJ's year end in December *or*
early January and Disney's in September *or* October. It would also have to run **before** ticket
03's XBRL strip, coupling two unrelated changes.

Also worth recording: **18 of 54 issuers are off-calendar**, not the 3–4 the ticket named. That
earlier figure came from a sample restricted to filings that already had a `Report Period`.

### The ticket's cost note was wrong

It said this was payload-only, "absorbed for free" under §9.6. It is not.
`chunks.py::contextual_prefix` puts `FY{fiscal_year}` **inside the embedded text**, so correcting
it changes vectors. Scope: the **54 filings** whose derived period changed — not just the 37,
because the 53 that gained a `period_end` also gained `(period ending …)` in the prefix.

The migration was clean for a reason worth knowing: point ids are
`uuid5(source_file#chunk_index)`, **not** derived from `chunk_id`, so a subset re-index overwrites
in place. **9,926 chunks re-embedded, collection steady at 29,499 points, ~$0.13.** Re-indexing
all 246 would have cost four times that for no change.

### Two incidental fixes

**The indexer now takes named files.** It only did `--all` or one seed filing, which made a
targeted re-index impossible. `uv run python -m src.index FILE...` now works, validating that
each name exists first.

**And that exposed a false-positive warning I had just introduced.** The post-run reconciliation
compared chunks-sent against the *whole* collection count — meaningful only for `--all`. On the
54-file run it printed `WARNING: -19573 chunks did not land`, which is alarming and meaningless.
`count()` now takes an optional `source_files` filter so a subset reconciles against its own
scope.

### A test that looked like coverage and proved nothing

`test_fixtures.py::test_fiscal_year_off_by_one_cases_are_still_wrong` was written to fail the
moment this ticket landed. **It didn't.** It reimplemented the old derivation inline
(`report period or filing date`) instead of calling `fiscal_period`, so it pinned the header
*data* — which never changed — rather than the *behaviour*, which did.

Rewritten as `..._are_now_right`, and verified the hard way: reverting the fix makes it fail,
restoring it makes it pass. A test that cannot observe the fix cannot observe the regression
either.

### One inherited test asserted the defect

`test_retrieve.py::test_report_period_is_used_when_the_filing_carries_it` asserted that filings
without a `Report Period` have **no** period end and take the **filing-date year** — the defect,
written down as a requirement. Amended, with the reasoning in the docstring, and extended to
cover `AMZN_10K_2026-02-06`.

It also **needed no Qdrant and no key** — it only calls `chunk_filing` — but requested the
`indexed` fixture, which put it in the paying tier. Dropping that moved it to the free tier:
free 102 → 103, live 29 → 28.

### Closing conditions

| | |
|---|---|
| 1. All 246 verified against period end | **Done** — 37 corrected, none now labelled beyond 2025 |
| 2. Unresolvable filings named with fallback | **Done** — 1, not 2: `GE_10K_2015-02-27`, filing-month fallback |
| 3. `[C11]` re-run, no longer self-contradictory | **Done** — display shows `period ending 2025-10-26` |
| 4. Test over the fixture corpus | **Done** — `test_fiscal_period.py`, 9 tests, incl. off-calendar (`AAPL`, `ADBE`) and `Report Period`-absent 10-Ks |
