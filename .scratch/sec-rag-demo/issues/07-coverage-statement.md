# Machine-generated coverage statement

Type: grilling
Status: resolved
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

---

## Answer

**Resolved 2026-08-20.** The answer now states what it stands on, computed once and used
twice. `PROMPT_VERSION` → **v6**.

### Correction to this ticket

It claimed "coverage is already computed in `ingest.py`; this wires it into `prompt.py`."
**Wrong** — I wrote that. `coverage` in `ingest.py` is a comment about *content* coverage
(chunking everything, labelled or not). The only real computation was `entity_coverage_at_k`
in `eval/metrics.py`, an **eval metric unavailable at answer time**. This was built, not wired.

### The four forks, resolved

**1. Answer with a caveat** — settled at charting.

**2. Where it lives: both, computed once.** `src/coverage.py` produces the sentence; it is
passed into the prompt *and* returned in `retrieval_meta`. The model gets it as a stated fact
so its prose can hedge proportionately; the UI renders the computed copy verbatim. **The
rendered copy is authoritative** — asking the model to derive its own coverage would make the
most trust-bearing claim in the answer the least verifiable thing in it.

**3. It fires always.** A threshold would need justifying and would surprise a reader by
appearing only sometimes.

**4. The unit is distinct filings, never passages.** On ticket 01's run the context held
**seven Merck passages from one filing**. Reporting "7" would have overstated that evidence
sevenfold in exactly the case where honesty matters. The display is ordered by filings too,
with passages only as a tie-break — sorting by passages would reproduce the same illusion in
the UI, and there is a test for it.

### One distinction the ticket did not ask for, and it earns its place

`filings_retrieved of filings_in_corpus`, not just a retrieved count:

- **`MRK 1 of 1`** — the corpus held nothing better. A limit of the data.
- **`JNJ 3 of 17`** — retrieval chose three. A limit of the budget.

Those are different claims, and only the first justifies a hedge. `rests_on_one_filing` keys
off `filings_in_corpus`, so a deliberate budget choice is never reported as thin data. Live on
the comparative question: **`JPM 2 of 4` is shown but not flagged**, because four filings
exist.

### What the reader and the model now see

Pharmaceutical question:

> Evidence base — 4 companies, filings used: JNJ 3 of 17, PFE 3 of 15, MRK 1 of 1, LLY 1 of 1.
> This corpus holds only a single filing for MRK and LLY, so conclusions about them rest on one
> period.

Comparative question:

> Evidence base — 3 companies, filings used: TSLA 5 of 16, AAPL 3 of 16, JPM 2 of 4.

Rendered by `CoverageNote` in `sources.tsx`, amber when anything is thin, alongside the
existing `unresolved_mentions` line. The sentence is written to be **read aloud**, because it
will be.

And the model hedges in its own words:

> "Only a single (most recent) filing is available for Merck & Co Inc and Eli Lilly and
> Company, so conclusions about their regulatory risks are based on limited evidence and may
> not fully reflect ongoing or prior strategies."

### The change made something worse first, and fixing it is the interesting part

Given the counts alone, the model wrote **"No filings are available for companies except [the
four listed]"** — which is **false**. This corpus holds filings for ABBV and TMO; retrieval
simply did not reach them. A partial census invited the model to treat the partial set as
complete, turning a retrieval limit into a confident claim about the data. That is worse than
no statement at all, because it sounds like knowledge of the corpus.

The prompt note now ends: *"This describes the passages you were given, not the whole corpus…
say a company is absent from the corpus only if you were told so explicitly above."* Genuine
absences still arrive through v4's `absent` mechanism. Re-run:

> "Other major pharmaceutical companies not listed in the context (e.g., Novartis, Sanofi,
> GSK) are not addressed."

True, and scoped to the context rather than the corpus. **The general lesson, recorded in
`PROMPT_LOG.md`: any count handed to a model must say what it is a count *of*, or the model
picks the more useful-sounding interpretation.**

### Accepted limitation

For a **sector** question the system cannot name who is missing. It has no sector taxonomy, so
it cannot know that ABBV and TMO are pharmaceutical companies that should have been consulted.
It reports what it stood on and says the list is not the corpus. Naming the gap would need
sector metadata — a payload field, cheap to add later (§9.6's "absorbed for free" class), and
not built here. Worth saying out loud in the walkthrough rather than hoping nobody asks.

### Verification

- `tests/test_coverage.py` — 12 tests, free tier. Includes the corpus census against §2.9's
  figures (JNJ 17, PFE 15, the four singletons, JPM 4, and 246 filings total), that passages
  are never mistaken for filings, that ordering is by filings, and that a named-but-unretrieved
  company is distinguished from an out-of-corpus one.
- **163 tests green**: 135 free python + 28 live, plus 34 frontend. `make check` clean.
