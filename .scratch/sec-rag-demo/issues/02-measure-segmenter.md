# Measure what the existing item segmenter actually achieves

Type: task
Status: open
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
