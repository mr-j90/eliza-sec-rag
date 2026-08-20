# Inline-XBRL strip and text reflow

Type: task
Status: resolved
Blocked by: 01

## Question

**Are the two highest-leverage preprocessing steps in place, and do they reproduce the
measured numbers on all 246 files?**

The research settles the *what* — nothing to decide. This ticket builds it and confirms the
measurements hold, because both numbers are going into the demo walkthrough and both are
the kind of claim a panel checks.

### Step 1 — strip the inline-XBRL residue (§2.3)

Nearly every file opens, immediately after the `=`×60 header separator, with a colossal run
of concatenated inline-XBRL context strings and almost no whitespace. Measured:

| | |
|---|---|
| Residue block, tokens | min 10 · median 9,930 · p90 34,843 · **max 86,721** (`BAC_10K_2025-02-25`) |
| Corpus body tokens before | 21,071,458 |
| Corpus body tokens after | 17,340,706 |
| **Reduction** | **3,730,752 tokens — 17.7%** |

The residue is glued directly onto the start of the real cover page, so you cannot drop a
line — you **cut at the cover-page anchor**:

```python
m = re.search(r'UNITED\s*STATES\s*SECURITIES AND EXCHANGE COMMISSION', body)
body = body[m.start():] if m else body
```

Found in **244/246** files. The two misses need a fallback — §2.3 suggests cutting at the
first `FORM 10-[KQ]`. **Identify those two files by name and confirm the fallback works on
them.**

Why it matters beyond token cost: at 800 tokens/chunk the BAC residue alone generates
**~108 chunks of pure tag soup**, near-duplicates of each other and of every other BAC
filing. They pollute BM25 term statistics and are exactly what surfaces in a live demo.

Also: **do not parse the header block by line offset.** 192/246 files have a 10-line
header; 54 lack `Report Period` and `Quarter` and have 8 lines. Split on the `=+`
separator. The 54 need fiscal period derived from the filename date or the `URL` field
(which embeds it, e.g. `aapl-20240928.htm`).

### Step 2 — reflow, to recover block boundaries that do not exist (§2.4)

This is the finding that most changes the chunker, and prior art does not implement it
(`grep -ri reflow src/` returns nothing).

The HTML-to-text conversion inserted **no separator at block boundaries**:

- **216/246 files contain at least one line longer than 20,000 characters.**
- Median longest line is **51,464 chars**; max **287,855**.
- Tesla's entire Item 1A is **one line of 79,624 characters**. Apple's 10-K has a
  95,328-char line.

Consequence: a `RecursiveCharacterTextSplitter` on `["\n\n", "\n", " ", ""]` falls straight
through the paragraph and line separators and splits on **spaces, mid-sentence**, for most
of this corpus.

Boundaries are recoverable, because the stripper's omission is itself the signal — where a
block boundary was, a sentence-final character now abuts a capital with no space. Splitting
Tesla's Item 1A on `(?<=[.!?"])(?=[A-Z"])` recovers **81 blocks** (median 747 chars, p90
2,402). Two guards are required:

1. **Abbreviations** — `U.S.` splits into `…in U.` / `S. dollar would…`. Guard with a list:
   `U.S`, `Inc`, `Corp`, `No`, `e.g`, `i.e`, and whatever else the corpus throws.
2. **Heading run-ons** — group headings glue to the first body word with no punctuation:
   `Risks Related to Government Laws and RegulationsDemand for our products…`. Needs a
   second lowercase→Uppercase split rule.

### What must be true to close this

- The 17.7% reduction reproduces. Record the actual before/after token counts.
- The two anchor-miss files are named and their fallback verified.
- Reflow runs over all 246 files without exploding block counts absurdly; spot-check Tesla
  Item 1A against the expected ~81 blocks.
- The abbreviation guard list is recorded here, so ticket 12's write-up can cite it.

Note what §2.3 also says about what *not* to prioritise: exhibit indexes (141 occurrences)
and signature blocks (270) are minor, and page-furniture stamps are only ~8,000 tokens —
strip them for **parse correctness**, since they wedge between a section end and the next
header, not for token savings.

---

## Answer

**Resolved 2026-08-20.** The ticket had two steps. **Step 1 was already done** — the code
already hits the arch doc's headline number by a different route. Step 2 was the whole job,
and it eliminated a correctness defect entirely.

### Step 1 — already achieved, measured three ways

| approach | body tokens | removed |
|---|---|---|
| no strip | 21,071,458 | — |
| **current `_strip_boilerplate`** | **17,342,204** | **17.7%** |
| §2.3's anchor cut | 17,312,306 | 17.8% |
| what §2.3 *claimed* its cut would give | 17,340,706 | 17.7% |

The raw figure reproduces the arch doc **exactly** (21,071,458), and the existing code lands
within **1,498 tokens** of the arch doc's own claimed result. §2.3 calls this "the single
biggest preprocessing win"; it was already banked before this ticket opened.

**Decision: not switching to the anchor cut.** It buys 0.1% more reduction. What it also
buys is 35,330 characters of recovered text — because the current line-anchored regex *does*
delete the cover page in **143 of 246 filings**, as ticket 01 suspected. But that is **0.04%
of the corpus**, at most 913 characters per file, and it is
`"UNITED STATESSECURITIES AND EXCHANGE COMMISSIONWashington, D.C. 20549FORM 10-Q (Mark One)☑
QUARTERLY REPORT PURSUANT TO…"` — checkbox boilerplate whose useful content (company,
ticker, CIK, form, period) we already hold as structured metadata from the header block.
Switching is a one-line change plus a full re-embed; it did not earn one here. **Quantified
and accepted, not overlooked.**

**The anchor-miss files, and only one is real.** §2.3's "found in 244/246" reproduces exactly
— **with its case-sensitive regex**. The two misses are `LLY_10K_2026-02-12` and
`NFLX_10K_2026-01-23`. Adding `re.IGNORECASE` gives **245/246**, recovering LLY for free.
With §2.3's suggested `FORM 10-[KQ]` fallback, **0 files miss**. Both are pinned as fixtures.

### Step 2 — reflow, and it corrects ticket 01

**Ticket 01 claimed the sentence splitter "cannot fire on this corpus." That was wrong.**
§2.4 says no separator at **block** boundaries; sentences *within* a block are normally
spaced. Measured: the sentence arm produces 12,052 pieces from 55 sections and only **1.5%**
need a raw-token cut. The splitter works fine.

What is actually broken is narrower and worse:

- **0 of 55 sections contain a single blank line.** The paragraph arm — the *preferred* one —
  never fires at all.
- **88.8% of chunks contained an invisible block join**, where two blocks are fused with no
  separator.
- **3.6% fused across an `ITEM` header** — two different sections of a filing inside one
  chunk, under one section label. That is the correctness defect: every citation from such a
  chunk displays a section it is only half from.

`_reflow` inserts `\n\n` at recovered boundaries, so the paragraph arm does the work the
preference order always intended.

| | before | after |
|---|---|---|
| chunks with an invisible block join | 637 (88.8%) | **273 (36.3%)** |
| chunks fusing across an `ITEM` header | 26 (3.6%) | **0** |
| chunk tokens | — | median 701, p10 281, p90 800, max 871 |

**All 367 residual joins are guarded abbreviations** — `I.R.S.`, `U.S.C.`, `U.S.` — with zero
unsplit cases. The 36.3% is the guard working, not misses.

Tesla's Item 1A: 90,679 chars arriving as a **90,033-character line** → **97 blocks, median
711 chars**. §2.4 reported 81 and 747 on a different filing year. The finding reproduces.

### The guards are the entire difficulty

**Rule 1** (`(?<=[.!?"])(?=[A-Z"])`) — 416 candidates in Tesla's 10-K, of which **98 (24%)
sit after an abbreviation** and must not split. Without the guard `U.S.` becomes `…in U.` /
`S. dollar would…`.

The guard needed splitting in two, and finding out why was worth the test that caught it: a
single `\b[A-Z]\.$` pattern also matches the `K` in **`Form 10-K.`** — and a form name
genuinely does end a sentence. Tesla writes `…on Form 10-K.ITEM 1A. RISK FACTORS…`, which is
exactly a boundary we must not miss. So the initial arm requires the preceding character to
be a space, paren or period, never a word boundary.

**Rule 2** (heading run-on) — §2.4 requires it. The naive `(?<=[a-z])(?=[A-Z])` fires 285–335
times per filing at roughly **50% precision**: it shatters `xAI` → `x|AI`, `MyPower` →
`My|Power`, and glued table headers like `| Operating|Leases` — the last of which would
separate a figure from the header naming it, which is ticket 06's whole concern.

Four guards fix it, each killing one measured failure class: `[a-z]{3}` before (kills `xAI`),
`[A-Z][a-z]+\s` after (kills `AI Proposal`), no pipe in the preceding 70 chars (kills table
rows), and ≥3 of the last 4 words capitalised (requires a Title Case run). Guarded, it adds
**75 boundaries on Tesla and 38 on Apple at ~100% precision on inspection** — including
§2.4's own example, `Risks Related to Government Laws and Regulations|Demand for our
products`.

### Where reflow runs, and why it matters

**Inside `_split_on_boundaries`, per section, after `_section_spans` has run.** Inserting
newlines earlier would change the line structure that `_TOC_ROW` and the late-detection guard
depend on, so section segmentation stays **byte-identical** and only chunking changes.

Whether reflowing *before* segmentation would improve detection is a real question — item
headers would become line-anchored, which is §2.5's whole difficulty — but it would change the
20-profile detection that **ticket 02 exists to measure**. Left to that ticket deliberately.

### Migration

Chunk text changed everywhere, so every vector changed. Run with **`--recreate`**, not a
plain upsert: chunk counts shift per filing, and since point ids are
`uuid5(source_file#chunk_index)`, any filing producing *fewer* chunks would leave **orphaned
points** holding stale text. Recreating cannot orphan.

**29,499 → 30,348 points** (+849, +2.9%), status green, reconciliation clean — 30,348 sent,
30,348 held. ~20M tokens re-embedded, ~$0.40.

### Verification

- **185 tests pass**: 123 free python + 34 frontend + 28 live.
- `test_reflow.py` — 20 tests, including a parametrised abbreviation suite and the invariant
  that matters most: **reflow never loses a character**. It asserts the text is unchanged with
  newlines stripped, across three filings. A reflow that dropped content would be silent and
  invisible to every retrieval metric.
- The comparative demo question end to end: 18 citations, quotas intact at 6/6/6, retrieval
  1.0s, and **0 chunks fusing two sections**.

### Incidental

Two foreign tracker ids remained in ported code (`D001` in `config.py` and `api.py`),
pointing at a decision log that is not in this repo. Replaced with the reasoning they stood
for. `grep` for `I0nn|G0n|D00n` across `src/` and `tests/` now returns nothing.
