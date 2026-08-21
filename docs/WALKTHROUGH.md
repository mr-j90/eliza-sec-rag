# Demo walkthrough

A run-of-show for the panel session, plus the three arguments the brief asks for: design
decisions, value creation, and future state.

Treat the timings as a budget, not a script. **The panel types the question, not you** — the
demo has to survive whichever of the three they pick, and all three are covered below.

---

## Before they arrive

```bash
make up                        # sec-rag-qdrant on :6533
curl -s localhost:8000/health  # expect chunks: 30383 — if 0, the index is empty
make answers                   # backend on :8000
cd frontend && bun run dev     # UI on :3000, sign in as demoadmin
```

Have a second terminal on `./example-request.sh` — if the UI misbehaves, the same answer comes
back through one `curl` and the demo continues.

Two failure modes to know cold. If the backend is down the UI **says so and names the start
command** — it will not show a fabricated answer, which is deliberate and worth saying out loud
if it happens. And `onnxruntime` sometimes prints `recursive_mutex lock failed` at interpreter
teardown; it is cosmetic, exit codes are 0.

---

## Run of show (~20 min + questions)

### 1. Frame it in their language (2 min)

> "This answers diligence questions from SEC filings, with every claim traceable to a filing
> and a period. One LLM call per question. What I want to show you is not that it retrieves —
> it's the four places where it *refuses to guess*, because that's what separates a research
> tool from a plausible-sounding one."

Do not open with architecture. Open with the failure mode a PE analyst fears: a confident,
well-written, wrong number.

### 2. Let them drive (6 min)

**Narrate the wait.** Rehearsed end-to-end: **12–22 seconds**, of which retrieval is ~1–2s and
the rest is generation. Say what is happening — "that's one call producing the whole structured
answer" — rather than letting a silent twenty seconds sit there. If it matters, `top_k` is a
request parameter and a smaller context answers faster.

They type. Whichever they pick, point at three things **on screen**:

- the **`[C1]`** handles, and that the `N of M passages cited (verified)` count is a server-side
  check against what was retrieved, not the model's own arithmetic;
- the **provenance line** — company, form, *period ending*, section, source file;
- the **evidence-base line** — what the answer stands on, in distinct filings.

Then read the **Gaps and confidence** section aloud. It is the part a diligence reader trusts
most, and it is a required section, not an afterthought.

### 3. Break it on purpose (3 min) — the strongest two minutes of the demo

Type: **"What is Shopify's China exposure?"**

It names Shopify, says the corpus holds nothing for it, and writes **no findings for anyone
else**. Say what it used to do:

> "Before this rule existed, that question refused correctly and then wrote findings for Amazon,
> Bank of America, Goldman Sachs and six others — including Bank of America's dollar exposure to
> China. Fluent, cited, and about a company nobody asked about."

Then the pharmaceutical question, and point at the amber line:

> "Read that line — two of those companies have one filing in the whole corpus. It's telling you
> it's speaking for an industry while standing on a fraction of it. That's computed, not written
> by the model — the model gets the same sentence so its prose hedges in proportion."

**Read the numbers off the screen, do not quote them from here.** Which filings win varies
between runs — rehearsals returned `JNJ 3 of 17, PFE 3 of 15` and `JNJ 4 of 17, PFE 1 of 15` on
the same question. The **shape** is stable and is what matters: two companies with real coverage,
`1 of 1` for the rest. Quoting a remembered number that the screen contradicts is a small,
avoidable credibility hit.

### 4. Design decisions, through measurements (6 min)

Lead with the number, not the technique. Four that carry the whole argument:

**"Dense similarity alone cannot attribute these passages."**
**40.5%** of chunks never name their company; **96.6%** never contain the ticker. So a
company/period/section prefix is embedded with every chunk. This turns "we add metadata" into a
measured necessity.

**"The corpus has no paragraphs."**
The HTML converter emitted no block separators — Tesla's entire Item 1A arrives as **one
90,033-character line**. A standard recursive splitter falls through to splitting on spaces,
mid-sentence. Reconstructing block boundaries took chunks that fused two blocks from **88.8% to
36.3%**, and chunks spanning two different *sections* — under one section label — **to zero**.

**"A number without its units is worse than no number."**
**28%** of table-bearing chunks carried figures with no stated scale, because the
`(in millions)` caption sits on the *preceding narrative line*, outside the table. Now **4%**.
On the NVIDIA question, **5 of 5** table citations show `($ in millions)` beside the figure.

**"We measured the constant everyone cites."**
Qdrant's RRF default is **2**; the prior version's prose claimed 60. Swept 2/10/60/100 plus
DBSF: **total spread 0.008–0.023.** So: *we set it explicitly, measured it, and it didn't matter
much — consistent with the paper, which says exactly that.* Offer this one if they probe on
tuning; it demonstrates the method more than the result.

**Volunteer the scope discipline.** ~4 hours of build. Say what was cut and why — it reads as
judgement, not as a gap, and it is much stronger volunteered than extracted.

### 5. Value creation (4 min)

Three wrong answers an analyst would have **acted on**, each prevented by a specific mechanism.
This is the section to slow down in.

| The wrong answer | Why it happened | What stops it |
|---|---|---|
| A figure quoted at the wrong **order of magnitude** | the scale caption sits outside the table and was severed from it | caption + period header bound to every table chunk |
| A **risk profile that is one quarter's amendment** | a 10-Q's Item 1A carries only *material changes* — Pfizer's is 562 tokens against 10,000+ annually | the annual baseline is retrieved, and quarterly passages are labelled as amendments |
| An **industry conclusion resting on two companies** | four of six pharma companies have one filing each | every answer states its evidence base in distinct filings |

Then the honest framing of what this is worth:

> "None of this makes an analyst faster at reading one filing. It makes 246 filings searchable
> with an audit trail — and more importantly, it makes the system's *limits* visible. A tool
> that tells you when it doesn't know is one you can put in front of an investment committee.
> One that doesn't, you can't."

### 6. Future state (4 min)

Split it, because the two halves land with different people in the room.

**What a user would ask for next** — from `docs/future-state.md`:

- **Inline citations that link back to the filing.** Every chunk already carries its source file
  and section, and every filing header carries its SEC URL — so a `[C4]` can become a link into
  the actual document. Highest-value, lowest-risk next item: it turns a citation you have to
  trust into one you can click.
- **Let users manage the corpus.** A screen to add CIKs and date ranges and pull those filings
  in. Today the corpus is a fixed snapshot; this makes it a product.
- **Log queries and build the eval set from real ones.** The 22-question golden set was written
  by hand. Real user questions are better test data than anything invented, and they are free
  once queries are logged.
- **Stream the answer.** Currently one JSON response — deliberately, so citations arrive with
  the text. Streaming is a UX win and needs the citation channel designed alongside it, not
  bolted on.

**What an engineer would ask about:**

- **Route numeric questions to XBRL facts.** One unauthenticated GET to `data.sec.gov` returns
  NVIDIA's exact annual revenue with an accession number to cite. Exact figures, no extraction
  risk, and it does not break the one-call constraint because it is retrieval. Honest caveats:
  tag selection is fiddly (NVIDIA's own filings use several revenue tags), the frames API aligns
  to calendar quarters while issuers have arbitrary fiscal years, and there is no CORS so it
  needs proxying.
- **The eval harness this deserves** — 40–60 questions, section-level labels, item-section
  precision, temporal-scope correctness with a baseline-present flag, and a paired significance
  test. `docs/EVALUATION.md` explains precisely why the naive version of that table would have
  been noise, which is what makes this credible rather than aspirational.
- **Self-hosted embeddings**, and the one real privacy angle: the filings are public, but *the
  queries encode the firm's deal interests*.
- **Multi-tenancy** — `tenant_id` has to exist from day one; tenant co-location changes storage
  layout, so it is not a free retrofit.

### The re-index question, if asked — get this right

A client will ask "so we never have to rebuild the index?" Do **not** say yes.

> "An extensible payload absorbs new filters, display fields, grouping, entitlements, enrichment
> — free. It does *not* absorb better chunking, a new embedding model, a changed prefix, or
> fixed preprocessing; those are a full re-embed. The two things that actually help are keeping
> raw text with character offsets, and putting an alias in front of the collection so a rebuild
> is a background job and an atomic swap. On this corpus a full re-embed is about **$0.40 and
> fifteen minutes** — which is the real reason not to over-engineer around avoiding it."

---

## Questions they are likely to ask

**"Is this really one LLM call?"**
Yes, and it is checkable rather than asserted. The frontend imports no provider SDK at all —
`grep -r openai frontend/` returns nothing — so it cannot make a model call even by accident.
The backend has one `complete()` call site. Embedding and reranking are retrieval work before
that call, the same as a vector search. There is a test that counts the calls on the
three-company question, where per-company quotas issue several vector searches.

**"Why Qdrant?"**
Fit: local Docker, one clean Python client, named dense+sparse vectors in one collection, and
fusion server-side in a single query. **Do not say it is the only store with server-side hybrid
fusion** — Weaviate, Milvus, Elasticsearch, Vespa and OpenSearch all do it, and anyone who has
used one will catch that. It also ships distribution-based score fusion, which the others do
not; measured here it was not better than RRF, so the code runs RRF only.

**"Your recall looks low."**
The best question to get. `recall@10 = 0.513` against label ceilings that vary from **0.139 to
1.000**, because relevant-file counts per question run from 1 to 36. Normalised against what was
attainable it is **62%**. And near-duplicate suppression is *anti-correlated* with the label —
every correctly-suppressed duplicate lowers recall while improving the answer. `docs/EVALUATION.md`
§3.

**"How do you know it isn't making things up?"**
Three answers: every claim carries a handle, handles are verified server-side against what was
retrieved, and the out-of-corpus refusal is a tested behaviour rather than a hope.

**"What would you do differently?"**
Have one ready. Honest answer: measure the corpus before writing any pipeline. Several decisions
inherited from the earlier attempt were defensible in the abstract and wrong here — the fiscal
year taken from the filing date, the fusion constant left at a server default, a chunker
assuming paragraphs the corpus does not contain.

---

## Things not to say

- "We never have to re-index." (See above.)
- "Qdrant is the only OSS store with native hybrid search." (False.)
- "`jina-reranker-v1-turbo-en` gives us 8192-token context." Its card says so; **measured, it
  truncates at 512** like every other reranker available here.
- "The reranker reads the whole passage." It sees the first 512 tokens; 26.8% of indexed text
  does not influence ranking. Say that plainly — the full passage still reaches the model.
- Any claim about the ablation being statistically significant. n=22, reported as directional,
  win/loss/tie.
