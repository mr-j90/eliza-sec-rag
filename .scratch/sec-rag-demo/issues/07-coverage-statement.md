# Machine-generated coverage statement

Type: grilling
Status: open
Blocked by: 01

## Question

**What exactly does the answer say about the evidence it rests on, and how is that
computed?**

The decision to include a coverage statement was made at charting. What is open is its
shape, its trigger, and its wording.

### The failure it prevents

*"What regulatory risks do the major pharmaceutical companies face, and how are they
addressing them?"* is one of the three questions the panel will type. Measured corpus
coverage for that sector (§2.9):

| Company | Filings |
|---|---|
| JNJ | 17 |
| PFE | 15 |
| ABBV, MRK, LLY, TMO | **1 each** |

So "major pharmaceutical companies" resolves to two companies with real multi-year coverage
and four with a single snapshot. Without a coverage statement the system answers
confidently on behalf of an industry while standing on two companies — and no retrieval
metric detects it.

The same asymmetry bites the comparative question: **JPMorgan has 4 filings, Apple 16**
(§2.9). A comparison presented as symmetric is not.

`coverage` already appears in `src/ingest.py` and `src/eval/metrics.py` but **not in
`src/prompt.py`** — so it is computed today and never told to the reader or the model.

### The forks to resolve

1. **Answer with a caveat, restrict to well-covered sectors, or decline?** (Q6) The arch
   doc leans toward answering *with* a machine-generated coverage statement, on the grounds
   that it is honest and demonstrates the system knows its own limits — while noting this is
   a product decision, not a technical one. It is also the best of the three in front of a
   panel: declining looks like a broken demo, and restricting silently is the same dishonesty
   with extra steps.
2. **Where does it live?** Three candidates, not mutually exclusive: a line in the answer
   text; a structured field in `retrieval_meta` for the UI to render; or part of the prompt
   so the model weaves it into its prose. The first two are deterministic and verifiable;
   the third is not, and the answer contract's first rule is to answer only from context.
   **Lean deterministic** — a coverage claim the model generated is a coverage claim that can
   be wrong.
3. **When does it fire?** Always, or only when coverage is materially uneven? Always is
   simpler and never surprises; only-when-uneven needs a threshold you then have to justify.
4. **What counts as a unit of coverage** — filings, distinct fiscal periods, or companies?
   "17 filings" and "3 fiscal years" tell a reader different things. §2.9 counts filings.

### Note the interaction with ticket 09

If the coverage statement is deterministic and appended outside the model's output, it must
not be mistaken for cited text — verifiable citation enforcement scans for `[Cn]` handles
and the coverage line has none. Make sure one does not flag the other.

### What must be true to close this

A worked example for each of the three demo questions, showing the exact string the reader
sees. The pharma one is the test that matters — if it does not make a reader hesitate about
ABBV, MRK, LLY and TMO, it is not doing its job.
