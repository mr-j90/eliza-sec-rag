# The walkthrough — design decisions, business value, and future state

Type: prototype
Status: resolved
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

---

## Answer

**Resolved 2026-08-20.** The deliverable is **`docs/WALKTHROUGH.md`** — a run-of-show plus the
three arguments the brief asks for, with every number in it fact-checked against the running
system, and rehearsed on all three panel questions.

### Structure

Six beats, ~20 minutes plus questions:

1. **Frame it in their language** — not architecture. Open on the failure a PE analyst fears: a
   confident, well-written, wrong number.
2. **Let them drive.** The panel types; point at three things on screen (verified citation count,
   provenance line, evidence base) and read *Gaps and confidence* aloud.
3. **Break it on purpose** — the Shopify refusal, with what it used to do: refuse correctly and
   then write findings for nine other companies, including Bank of America's China exposure.
4. **Design decisions through measurements** — four numbers that carry the whole argument.
5. **Value creation** — three wrong answers an analyst would have *acted on*, each mapped to the
   mechanism that stops it.
6. **Future state**, split in two because the halves land with different people in the room.

### Future state is split, and the user's own list leads

`docs/future-state.md` was already written and is **product-facing**, which is the half a client
cares about. It leads:

- **inline citations that link back into the filing** — every chunk already carries its source
  file and section, and every filing header carries its SEC URL, so this is the
  highest-value/lowest-risk next item: a citation you have to trust becomes one you can click;
- **a screen to manage CIKs and date ranges** — turning a fixed snapshot into a product;
- **logging queries to build the eval set from real ones** — better test data than anything
  invented, and free once queries are logged;
- **streaming**, with the note that the current single JSON response is deliberate (citations
  arrive with the text), so the citation channel has to be designed alongside it.

The engineering half follows: the XBRL numeric router with its honest caveats, the eval harness
`docs/EVALUATION.md` explains how to make credible, self-hosted embeddings with the one real
privacy angle (*the filings are public; the queries encode the firm's deal interests*), and
multi-tenancy needing `tenant_id` from day one.

### The re-index answer, scripted

A client will ask "so we never rebuild the index?" The walkthrough scripts the honest version,
because saying yes would be wrong: a payload absorbs filters, display fields, grouping and
entitlements for free; it does **not** absorb better chunking, a new embedding model, a changed
prefix or fixed preprocessing. What helps is raw text with offsets plus an alias in front of the
collection — and a full re-embed here is **~$0.40 and fifteen minutes**, which is the real reason
not to over-engineer around avoiding it.

### Rehearsed, and the rehearsal changed the script

All three panel questions run end to end: **5/5 required sections, citations verified, 12–22
seconds.** Two things the rehearsal caught that the draft had wrong:

**Quoting exact coverage numbers would have set up a live contradiction.** The draft coached
"JNJ 3 of 17 filings, PFE 3 of 15" — a rehearsal returned `JNJ 4 of 17, PFE 1 of 15` on the same
question. Which filings win varies between runs. The walkthrough now says **read the numbers off
the screen** and coaches the *shape* instead: two companies with real coverage, `1 of 1` for the
rest. A remembered number the screen contradicts is a small, avoidable credibility hit.

**Twenty seconds of silence needs narrating.** Latency is 12–22s, mostly generation. Better to
say "that's one call producing the whole structured answer" than to let it sit.

### A "things not to say" list

Because several plausible claims are false, and each was measured to be:

- "We never have to re-index."
- "Qdrant is the only OSS store with native hybrid fusion" — Weaviate, Milvus, Elasticsearch,
  Vespa and OpenSearch all do it.
- "`jina-reranker-v1-turbo-en` gives us 8192-token context" — its card says so; measured, it
  truncates at 512 like the rest.
- "The reranker reads the whole passage" — it sees the first 512 tokens; 26.8% of indexed text
  does not influence ranking.
- Any claim that the ablation is statistically significant. n=22, directional, win/loss/tie.

Also prepared: an answer to **"your recall looks low"** (the best question they can ask), and to
**"what would you do differently"** — measure the corpus before writing any pipeline, since
several inherited decisions were defensible in the abstract and wrong here.

### Verification

Every asserted figure was checked against the running system: index at **30,383 chunks**,
`|R|` spanning **1–36**, `recall@10 = 0.513` and normalised **62%** (the draft said 0.52 and
64%, which were the k=2 figures — corrected), `grep -r openai frontend/` returning nothing, and
prompt **v7**. All README and walkthrough links resolve. 201 free python + 34 frontend green.
