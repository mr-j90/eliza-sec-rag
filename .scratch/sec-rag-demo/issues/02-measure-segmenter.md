# Measure what the existing item segmenter actually achieves

Type: task
Status: resolved
Blocked by: 01

## Question

**How good is the ported segmenter, measured against all 246 files — and is that good
enough to chunk against?**

This is a measurement, not a decision. It exists because the chunking policy, the 10-K
baseline anchoring (ticket 08) and the `item_section` field every citation displays all
rest on item boundaries being real. Rewriting the segmenter is expensive; the research
says a naive regex fails badly, but prior art may already be past naive. Nobody has
looked.

### What §2.5 and §2.6 establish, so the measurement has something to compare against

- **Five distinct body-header forms** occur: pipe (`Item 1A. | Risk Factors`), pipe-TOC
  (same plus a trailing page number — the page number is the discriminator), glued behind
  page furniture (Apple), ALL CAPS (Tesla), and zero-space (`Item 1.Financial Statements`
  — Alphabet, Meta).
- Clustering the 246 files by which forms they contain yields **20 distinct format
  profiles**. The largest is only 64 files.
- **30.7% of all `Item N` mentions are cross-references, not headers.** Plus `Item 601(a)`
  Reg S-K citations produce phantom headers — the sole regex match in Intel's 10-K is one
  of these.
- The 10-Q Part I / Part II collision appears in **125 of 157 10-Qs**. A key on `item`
  alone merges Apple's *Financial Statements* with its *Legal Proceedings*.
- §2.5's TOC-anchored monotonic aligner reportedly gets failures to **1/246** and median
  10-K coverage to **78%**.

### Numbers to produce

1. Per-file: how many items were segmented, and what fraction of the body ended up inside
   a named item versus unassigned. Report the distribution, not just a mean.
2. Count of files where segmentation **failed outright** (zero or one item found).
3. Whether the key is `(part, item)` or `item` alone — and if the latter, how many 10-Qs
   are silently merging two different sections.
4. False positives: does it treat cross-references or `Item 601(a)` citations as headers?
   Spot-check Intel's 10-K specifically.
5. Named spot-checks across the five header forms, because a mean hides them: **Amazon**
   (pipe), **Apple** (glued behind page furniture), **Tesla** (ALL CAPS), **Alphabet** and
   **Meta** (zero-space).

### What the Answer must state plainly

A verdict on one of three: (a) good enough, chunk against it; (b) needs the §2.5
TOC-anchored monotonic aligner with a **graded** fallback — item → part → whole-document,
not the binary fallback the SPEC sketched; (c) good enough for narrative items but not for
Item 8 financial statements.

Whichever it is, the coverage number goes into the demo walkthrough — "78% of the median
10-K lands inside a correctly-identified item" is exactly the kind of measured claim the
panel will probe for.

---

## Answer

**Resolved 2026-08-20. Verdict: (a) — good enough, chunk against it.** Not (b). The existing
segmenter already beats by a wide margin the target §2.5 sets for the aligner it recommends
building, and rewriting it would have been a regression risk for no measured gain.

Measured across **all 246 filings**, not sampled.

### Coverage — the number the verdict rests on

| form | filings | min | p25 | **median** | p75 | max |
|---|---|---|---|---|---|---|
| 10-K | 89 | 0% | 96% | **98%** | 99% | 99% |
| 10-Q | 157 | 0% | 94% | **96%** | 98% | 99% |

§2.5 reports its TOC-anchored monotonic aligner reaching "median 10-K coverage 78%". **The
ported code reaches 98%.** It already *is* a TOC-anchored monotonic aligner — forward scan with
a cursor, TOC-row rejection checked to end-of-line, quoted-cross-reference rejection, a
late-detection guard, and a coverage guarantee. §10's critique was written against the SPEC,
and the code went well past it.

Items detected: **83 of 89 10-Ks and 122 of 157 10-Qs find all 6** in their form's map.

### The 27 outright failures, and their two causes

**27 filings (11%) detected zero items**, concentrated in seven tickers: **DIS 10, JNJ 12**,
plus CMCSA, COST, INTC, MCD, MS one each. The TOC guard was **not** the culprit — it was
correctly rejecting table-of-contents rows. In these filings the TOC rows were the *only*
matches, because the real body headers were in a form the patterns never handled.

**Cause A — a form §2.5 lists and the pattern never allowed.** `_ITEM` was
`Item\s+{}\.?[\s\xa0|]*{}` — optional **period**, no colon or dash. Comcast writes
`Item 1A: Risk Factors`; Costco uses a dash; Disney's Part II headers use the colon form. That
single character cost **11 filings their entire segmentation**. Widened to `[.:\-–—]?`:
**27 → 15**.

**Cause B — filings that genuinely have no body item headers.** The remaining 15 (JNJ 12,
INTC, MCD, MS) are not a regex gap. JNJ's 10-Qs structure by `NOTE 11 — LEGAL PROCEEDINGS`,
and `Risk Factors` appears exactly once in the whole document — as a cross-reference. There is
nothing to match. §2.5's **graded fallback** (item → **part** → whole-document) would help
here, since these filings do carry `PART I` / `PART II`; that is real new work and not in this
ticket. **Their content is still fully chunked and retrievable under `UNLABELLED`** — only the
section label is missing, and there is a test asserting JNJ still produces >10,000 tokens.

### The widening introduced a regression, which is why the check mattered

Comparing every chunk's label against the live index — rather than assuming only the
zero-item filings changed — caught **AMD, 23 of 149 chunks relabelled**. Item 1 Business had
collapsed from **19 chunks to 1**, with Item 1A absorbing the rest.

Cause: AMD writes `see “Part I, Item 1A—Risk Factors” and…`. The dash made it match, and the
quote guard only checked the character **immediately** before the match — but the opening quote
sits eight characters earlier, before `Part I,`. Item 1A's boundary jumped from 16.3% of the
body to 2.3%.

Fixed properly rather than by dropping the dash: `_inside_a_quotation` now walks back up to 48
characters for an **unclosed** opening quote, stopping at a closing quote or a line break
because either means the quotation already ended. Only curly quotes are used for the walk — a
straight `'` is an apostrophe far more often than a quote here (`Management's Discussion`), and
treating it as one would reject real headers.

Both wins kept: zero-item **15**, coverage medians unchanged at **98% / 96%**, AMD restored to
19 Business chunks. §2.5's figure that 30.7% of `Item N` mentions are cross-references is why
this guard carries most of the weight in keeping segmentation honest.

### The other things this ticket asked for

- **`(part, item)` keying** — correct, and verified. `Part II Item 1 — Legal Proceedings` is a
  distinct label from `Item 1 — Financial Statements`, with a test asserting Apple's 10-Q
  produces both and no duplicate labels. §2.6's collision affects 125 of 157 10-Qs.
- **False positives** — Intel's `Item 601(a)` Reg S-K citation is not treated as a header;
  asserted directly.
- **Named spot-checks across the five header forms** — Amazon (pipe), Apple (glued behind page
  furniture), Tesla (ALL CAPS), Meta (zero-space), GOOG 10-Q (zero-space *and* caps). All
  segment, each parametrised separately so a mean cannot hide one failing.

### Ticket 03's open question, answered

*Would reflowing before segmentation improve detection?* **No, and it is not needed.** The
premise was that item headers buried mid-line are hard to find — but detection already reaches
98% coverage without reflow, and the 15 remaining failures have no headers to line-anchor. Reflow
would change the line structure that `_TOC_ROW` and the late-detection guard depend on, risking
the 231 filings that work to help none of the 15. Removed from the map's fog as answered rather
than left open.

### Migration

15 filings relabelled → **1,599 chunks re-embedded**. `item_section` sits in the contextual
prefix, so a label change is a vector change. Verified no orphans by comparing stored count to
fresh chunk count per filing — collection **30,348 → 30,383**, green.

### Verification

- `tests/test_segmentation.py` — 14 tests, free tier: the three colon/dash filings, the
  corpus-wide coverage floor (a regression guard on the medians the walkthrough quotes), the
  content-never-dropped guarantee on JNJ, the Reg S-K false positive, one test per header form,
  `(part, item)` keying, and the AMD quoted-cross-reference regression with a unit test on the
  quote walk itself.
- **187 tests green**: 159 free python + 28 live, plus 34 frontend.
