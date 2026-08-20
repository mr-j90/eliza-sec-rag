# Inline-XBRL strip and text reflow

Type: task
Status: open
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
