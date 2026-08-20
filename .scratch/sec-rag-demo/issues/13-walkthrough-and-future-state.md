# The walkthrough — design decisions, business value, and future state

Type: prototype
Status: open
Blocked by: 12

## Question

**What do you actually say to the panel — and what does the future-state section contain?**

### Why this is a first-class deliverable, not a wrap-up

Re-read the brief's own framing: *"You will build a presentation that displays technical
capabilities while defending business value for a fictitious company Private Equity firm."*
The presentation **is** the deliverable; the working demo is how it displays capability. And
the demo format section is explicit: *"Be prepared to walk through your design decisions as
well as defend the value creation. Additionally, assume the client would want to understand
future state and capabilities if they are sold on this RAG solution."*

So there are three distinct things to prepare, and the second and third are where the
technical work either lands or doesn't.

### 1. Design decisions — the measured ones

The strongest asset here is that nearly every decision has a number behind it. Draft the
walkthrough around the measurements, not the architecture diagram:

- **17.7% of body tokens were XBRL tag residue** — 3,730,752 of 21,071,458 — concentrated in
  a single line per file, up to 86,721 tokens in one line.
- **216 of 246 files have a line over 20,000 characters.** Tesla's entire Item 1A is one
  79,624-character line. The HTML stripper emitted no block separators at all — so a
  standard recursive splitter silently splits on spaces, mid-sentence, across most of this
  corpus.
- **40.5% of 800-token chunks never name their company; 96.6% never contain the ticker.**
  This is the number that justifies the contextual prefix, and it is the one to lead with —
  it turns "we add metadata" into "dense similarity alone cannot attribute these passages."
- **The median risk factor is ~607 tokens**, and 17 CFR 229.105(a) requires each to sit
  under its own subcaption. So the chunk size is derived from the regulation and the
  measurement, not chosen.
- **20 distinct item-header format profiles** across 246 files, and 30.7% of `Item N`
  mentions are cross-references rather than headers.
- Whatever ticket 05 concluded about **RRF k** — including that the naive path silently runs
  k=2 while the folklore says 60.

Say what was cut, and why, in budget terms. Scope discipline against a ~4h timebox is itself
a defensible engineering answer, and volunteering it is stronger than being caught by it.

### 2. Business value — for a PE diligence audience

The failures prevented are more concrete than any capability claim. Three worth having ready:

- A number quoted with the wrong order of magnitude, because a table row was severed from
  its `(dollars in millions)` caption (ticket 06).
- A risk profile that is actually one quarter's amendment presented as complete (ticket 08)
  — a 13× understatement: 876 median tokens versus 11,153.
- An industry-level conclusion resting on two companies (ticket 07) — JNJ 17 filings, PFE
  15, then four companies at one filing each.

Each is a wrong answer a diligence analyst would act on, and each is prevented by a specific
mechanism you built. That is the value argument.

### 3. Future state — the brief explicitly asks for it

Everything ruled out of scope has a home here. From the map's Out-of-scope section, plus the
arch doc's own future items:

- **The XBRL numeric router** (Q1) — the strongest item. *"Numeric questions currently answer
  from retrieved table rows. Next: route them to the SEC's own structured data — one
  unauthenticated GET to `data.sec.gov` returns NVIDIA's exact annual revenues with accession
  numbers for citation. Exact figures, no extraction risk, and it does not break the one-call
  constraint because it is retrieval."* Be ready for the honest caveats: tag selection is
  genuinely fiddly (NVIDIA's own filings use several revenue tags), the frames API aligns to
  calendar quarters while issuers have arbitrary fiscal years, and `data.sec.gov` has no CORS
  so it needs proxying.
- **The full eval harness** — 40–60 questions, section-level labels, `ItemPrec@k`,
  temporal-scope correctness with a baseline-present boolean, and an ablation with a paired
  significance test. Ticket 10's critique is what makes this credible: you can say precisely
  why the naive version of this table would have been noise.
- **Reindex economics** — the honest version of the future-proofing story, and worth getting
  right because it is a question a client *will* ask. An extensible payload absorbs new
  filter dimensions, display fields, grouping keys, entitlements and enrichment for free. It
  does **not** absorb better chunking, a new embedding model, a changed contextual prefix, or
  fixed preprocessing — all of those sit behind a full re-embed. The two mitigations that
  actually matter are keeping raw text plus `char_start`/`char_end` offsets, and fronting
  collections with an alias so a re-embed is a background build and an atomic swap. On this
  corpus a full re-embed is **$0.35** — which is the real reason not to over-engineer around
  avoiding it. Do not say "so we never have to re-index."
- **Self-hosted embeddings** (Q2) — and note the one genuinely interesting privacy angle for
  a PE audience: the filings are public, but *the queries encode the firm's deal interests*.
- **Multi-tenancy** — `tenant_id` with `is_tenant` must exist from day one; tenant
  co-location changes storage layout, so it is not a free retrofit.
- Store alternatives, if asked: Weaviate, Milvus, Elasticsearch, Vespa and OpenSearch all do
  server-side hybrid fusion. **Do not claim Qdrant is the only one** — it is not, and anyone
  who has used Weaviate or Milvus will catch it. Justify Qdrant on fit and on DBSF.

### Format

This is a `prototype` ticket: draft something concrete and cheap — an outline or a rough
run-of-show — and react to it rather than trying to get the narrative right in the abstract.
Rehearse the actual demo at least once, typing all three questions, because the panel types
them and latency, layout and refusal behaviour all show live.
