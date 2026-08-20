# Prompt log

Every change to the system prompt in `src/prompt.py`, why it changed, and what it did.
Written as the changes happen — a log reconstructed at the end shows, and the brief asks for
this history as a deliverable in its own right rather than as a byproduct.

Expect the interesting entries to be failures. "v2 over-cited and became unreadable" says
more about the work than a list of clean wins.

The version here is the one `retrieval_meta.prompt_version` reports on every answer, so any
answer can be traced to the prompt that produced it. `tests/test_prompt_template.py` asserts
the live version has an entry and that the numbering has no gaps — a gap would mean an
iteration happened and was not written down, which is the one thing this file exists to
prevent.

The rendered prompt itself is [`docs/PROMPT_TEMPLATE.md`](docs/PROMPT_TEMPLATE.md), generated
from `src/prompt.py` rather than transcribed, with a test that fails if the two disagree.

## What an entry contains

Not a template to fill in — the useful ones vary — but each answers these, and an entry that
cannot answer the second and fourth is not worth writing:

- **What changed.** The actual text, before and after, or close enough to quote.
- **Why.** The failure it addresses, with the measurement or the transcript that revealed it.
  "Improved the prompt" is not a reason.
- **Observed effect.** What the change did, including when the answer is "nothing measurable".
- **What it made worse.** Prompt changes trade off; the entry that hides this is the one that
  misleads the next person. Several entries below exist mostly to record a regression the
  change forced.

Entries headed **"observed again … (no prompt change)"** record a change in the *context* the
prompt receives — a new reranker, reflowed passages, bound table captions — rather than an edit
to the prompt. They are logged because the prompt's behaviour changed even though its text did
not, and the log would otherwise imply it had been working against the same input all along.

---

## v1 — 2026-08-19 — the two rules everything else depends on

**Version:** v1 · the first end-to-end answer — frontend → FastAPI → one LLM call

**What it says.** Four rules in precedence order: answer only from the provided context;
every factual claim carries a `[C#]` handle; a company named in the question but absent from
the context is called out explicitly rather than substituted; never dress a hedge as a
finding. Closes with a Sources list mapping handles to company, form, period and section.

**Why this and not the full contract.** The answer contract is five parts — bottom line,
per-entity findings, comparison table, gaps and confidence, sources. v1 deliberately does
not ask for that structure. v1's scope was the *wire*: one real answer travelling from the
corpus through one LLM call to the browser. Prompting for a comparison table while the
context is a fixed slice of a single filing would produce a table with one column and teach
us nothing about whether the prompt works. The structure arrives with the retrieval that
makes it meaningful.

**Rule ordering is deliberate.** "Answer only from the provided context" sits above the
citation rule because a model that invents a claim and then attaches a plausible handle to it
has defeated the citation contract while appearing to honour it. Grounding first, attribution
second.

**Observed effect — first live runs, `gpt-4.1`, 2026-08-19.** Two questions against the fixed
Apple context.

*"What are the primary risk factors facing Apple?"* — grounded, three handles used, all three
resolve to real citations. Structure emerged as numbered themes (macroeconomic, political and
trade, natural disasters and public health) with a Sources list, without being asked for that
shape. Generation 5,990 ms; retrieval 1.1 ms.

*"...facing Apple, Tesla, and JPMorgan, and how do they compare?"* — **rule 3 held.** It opened
with "The context provided contains detailed risk factors for Apple Inc. only. There is no
information about Tesla or JPMorgan in the excerpts you provided," answered for Apple, and
closed by repeating that no comparison could be made. No fabricated Tesla or JPMorgan risk
factors, no invented tickers, every handle resolved. Generation 4,944 ms.

That second result — a graceful refusal — is the single most valuable behaviour to demo, and
it worked at v1 without refusal-specific tuning. Worth not over-reading: with a single-company
context, "the others are absent" is the *easy* case. The hard case is a company absent from the
whole 246-filing corpus while nine plausible neighbours are retrieved — still ahead of us here.

**Two things to watch, not yet problems.**

- **Rule 3 fires twice in one answer.** The refusal appears in the opening paragraph and again
  in the closing line. Correct but redundant, and at v1 it is not worth trading away emphasis
  for concision — a refusal that repeats itself is a better failure than one a reader skims
  past. Revisit if answers get long.
- **Generation dominates latency by three orders of magnitude** — ~5-6 s against ~1 ms of
  context assembly. The 15 s end-to-end target has real headroom now, but that is with three
  chunks. At the full 40k-token context budget this is the number that will move, and that
  budget is the named lever.


## v1 — observed again under entity quotas, 2026-08-19 (no prompt change)

Recorded because the prompt did **not** change and the behaviour did. Rule 3 — name the absent
company rather than substitute — was previously only exercisable on companies missing from the
*index*. With all 246 filings loaded and entity extraction running, it can finally be tested
against a company genuinely absent from the corpus.

*"What is Shopify's China exposure?"* → `entities_detected: []`,
`unresolved_mentions: ["Shopify"]`, and the answer: *"Shopify does not appear in any of the
provided context passages. Therefore, I cannot provide any information about Shopify's China
exposure. Sources: None (Shopify not present in context)."*

Note what the retrieval did underneath: with no company resolved, the unfiltered search still
returned 20 passages from ten unrelated companies. The prompt refused anyway and cited nothing —
which is the rule holding under adversarial conditions rather than in the easy case. It is also
the argument for the refusal hardening still to come: a reader should not have to trust that the
model ignored twenty irrelevant passages.

*"...facing Apple, Tesla, and JPMorgan"* → 6/6/6 passages, 13 handles, all resolving, and the
answer grouped itself by company without being asked to. v1 still does not request the
five-part structure; it is now clear that it should, because the model is inventing a structure
per answer and consistency is part of what makes a comparison readable. That is a v2 change and
belongs with the refusal work.


## v2 — 2026-08-19 — the five-part contract, and it did not take

**Version:** v2 · the five-part answer contract

**What changed.** Added the five-part answer contract — bottom line, findings, comparison,
gaps and confidence, sources — as required markdown headings in the **system prompt**, after the
grounding rules. Also started passing the absent-company list from `unresolved_mentions` into the
user message, so rule 3 acts on a fact rather than on the model noticing a gap.

**Observed effect: it barely worked, and a single-sample test hid that.** The section check passed
on its first run, so I nearly shipped it. Reading an actual answer showed no headings at all —
it opened `**Apple Inc. — Primary Risk Factors:**`. Four generations of the same question:

| run | sections present |
|---|---|
| 1 | **0 of 5** |
| 2 | **0 of 5** |
| 3 | **0 of 5** |
| 4 | 2 of 5 |

So the first pass was luck. The absent-company note *did* work — the refusal named Shopify
reliably — which made the failure easier to miss, because the answer was correct in substance and
shapeless in form.

**Why.** The format sat in the system prompt behind five grounding rules, and the user message
carried ~14k tokens of retrieved passages between it and the question. Instruction adherence
degrades with distance from the end of the prompt, and the context block is what creates that
distance. Nothing was wrong with the wording.

---

## v3 — 2026-08-19 — move the format to the end of the user message

**Version:** v3 · same change, relocated

**What changed.** The grounding rules stay in the system prompt, which ends with a single line
pointing at the format. The required skeleton now goes **last in the user message**, after the
context and after the question. Not a rewording — a relocation.

**Observed effect.**

| question | v2 | v3 |
|---|---|---|
| comparative (Apple/Tesla/JPMorgan) | 0-2 of 5 | **5 of 5** |
| temporal (NVIDIA, last two years) | — | **5 of 5** |
| sector (major pharma) | — | **5 of 5** |
| out-of-corpus (Shopify) | — | **5 of 5** |

Stable across repeated generations, which is now asserted by a test that pays for two extra calls
rather than trusting one sample — the specific failure v2 taught.

**What this cost.** Two extra generations per test run, and a prompt that is now split across two
messages, which is marginally harder to read than one block. Worth it: structure that appears 40%
of the time is worse than no structure, because a reader learns to distrust the shape.

**Known weakness, carried deliberately.** The "Comparison" section is required even for
single-company questions, where the prompt tells it to write one line saying a comparison does not
apply. That is a heading earning its place by convention rather than by content, and if answers
start reading as padded, this is the first thing to reconsider.


## v4 — 2026-08-19 — a refusal answers nothing else

**Version:** v4 · the clean refusal

**What changed.** When the question names companies and **none** of them are in the corpus, the
five-part skeleton is replaced by a two-section refusal instruction: bottom line, gaps, and an
explicit prohibition on Findings, Comparison and citations. Everything else is untouched.

**Why.** v3 refused correctly and then kept going. Asked *"What is Shopify's China exposure?"* it
said there were no Shopify filings — and then wrote findings for Amazon, Bank of America, Cisco,
Goldman Sachs, JPMorgan, McDonald's, Merck, NVIDIA, Pfizer and Procter & Gamble, quoting Bank of
America's China exposure to the dollar. Twenty citations. Nothing fabricated; the wrong question
answered at length.

The cause was a rule I wrote for a different case. v2 added *"answer for the companies that are
present"* so a mixed question — Apple present, Shopify absent — would not lose the Apple half. With
**no** named company present, "present" degrades to "whatever retrieval happened to return", and
the model obligingly answered about ten companies nobody had mentioned.

**The distinction is three-way, and getting it wrong breaks the best-behaving question type.**

| The question | v4 behaviour |
|---|---|
| names companies, none present | refusal only — 2 sections, 0 findings, 0 citations |
| names companies, some present | findings for those present, absent ones named |
| names no company at all | unchanged: normal answer over what was retrieved |

That last row is why the rule is phrased around *absent named companies* rather than "only answer
about what was named". A sector question — "What regulatory risks do major pharmaceutical companies
face?" — names no company either, and a careless version of this fix would refuse it.

**Observed effect.**

| question | sections | company subsections | citations |
|---|---|---|---|
| Shopify (refusal) | Bottom line, Gaps | **0** | **0** |
| Apple + Shopify (mixed) | all five | 1 (Apple) | 34 |
| major pharma (sector) | all five | 4 | 30 |
| Apple/Tesla/JPMorgan | all five | 3 | 28 |

**What it made worse, and what that forced.** A refusal has no Sources section, because it cites
nothing — which broke a v2-era test that required Sources on every answer unconditionally. The test
was amended rather than the behaviour: the honest rule is "cite your sources when you have used
sources", and demanding the heading on a refusal would mean either an empty section or an
invitation to fill it. Worth noting as a general shape — a prompt rule written as "always include
X" acquires an exception the moment a legitimate answer has no X.

**Placement, again.** The refusal instruction goes after the context for the same reason the format
block does (v3's finding). Put before it, it would have read as fixed and behaved as before.

## v5 — 2026-08-20 — the passage label states a period, not a fiscal year

**Version:** v5 · the period end replaces the fiscal-year label

**What changed.** `_label` — the header on each context passage the model reads — went from
`Apple Inc (AAPL) | 10-K FY2025 | Item 1A — Risk Factors` to
`Apple Inc (AAPL) | 10-K, period ending 2025-09-27 | Item 1A — Risk Factors`. Nothing else in
the prompt moved.

**Why.** `FY{fiscal_year}` was derived from the calendar year the reporting period ends in.
For the **18 of 54 issuers** in this corpus whose fiscal year does not end in December, that is
not the year the filing calls itself. NVIDIA's quarter ending 2025-10-26 is "fiscal year 2026"
throughout its own text — and **26 of the 67 chunks** from that filing say so explicitly, under a
label reading FY2025.

That is a bad thing to hand a model whose first rule is to answer only from the passages given.
The label and the passage disagreed, and the model had no way to know which to trust. A wrong
period in a diligence answer is not a cosmetic error: "revenue grew to $130.5B in FY2025" is a
different claim from the same sentence about FY2026.

A date cannot disagree with the passage it labels, which is the whole reason for preferring it.

**Considered and rejected: deriving the issuer's own fiscal-year label.** It is the most faithful
option and it was measured rather than dismissed. Inline XBRL carries
`DocumentFiscalYearFocus` — `nvda-20251026...2026Q3` — and where it extracts it is
authoritative. But two regex attempts over the residue reached only 93/246 and 74/246 files;
AAPL, AMZN, GOOG, MSFT, TSLA, META, XOM, UNH, KO and DIS all missed. The arithmetic fallback
(period-end month versus fiscal-year-end month) is fragile exactly where it matters, because
52/53-week calendars put JNJ's year end in December *or* early January and Disney's in September
*or* October. It would also have to run **before** the pending inline-XBRL strip rework, which
couples two unrelated changes.

**Observed effect.** Not a prompt-quality change so much as a correctness one — the 29 live tests
pass unchanged under v5, including all 11 answer-contract tests. The visible difference is on the
panel's own temporal question:

| | v4 | v5 |
|---|---|---|
| `fiscal_years` filter for "the last two years" | `[2025, 2026]` | `[2024, 2025]` |
| distinct years in the retrieved citations | `[2025]` — one year | `[2024, 2025]` — two |

That second row is the one that matters, and it is not a display fix. `LATEST_FISCAL_YEAR`
anchors relative time expressions to the corpus, and it was computed from the same broken
derivation, so it read 2026 for a snapshot whose newest period ends in 2025. A question asking
for two years received one, and the answer looked confident about it.

**Note for whoever writes the next entry.** The label is what the model sees; `sources.tsx` is
what the reader sees. They were changed together on purpose. If one moves without the other, the
answer will cite a period the UI does not show.

## v6 — 2026-08-20 — the model is told what it is standing on

**What changed.** A computed coverage sentence is inserted after the context, before the
format block:

> Evidence available to you: Evidence base — 4 companies, filings used: JNJ 3 of 17, PFE 3 of
> 15, MRK 1 of 1, LLY 1 of 1. This corpus holds only a single filing for MRK and LLY, so
> conclusions about them rest on one period.

plus an instruction to reflect it in *Gaps and confidence* and let it temper how broadly
conclusions are stated.

**Why.** The panel's third question is *"What regulatory risks do the major pharmaceutical
companies face?"* and this corpus holds **JNJ 17 filings, PFE 15, and ABBV, MRK, LLY, TMO at
one filing each**. Every passage retrieved for that question is genuinely relevant, so no
retrieval metric flags anything — the system simply answers on behalf of an industry while
standing on two companies. The failure is invisible to `recall@k` and obvious to a reader.

The sentence is **computed, not requested**. Asking the model to derive its own coverage would
make the single most trust-bearing claim in the answer the least verifiable thing in it. The
same string is rendered beside the answer, so what the reader sees is the computed copy and
the model's prose only has to be *proportionate*, not accurate about counts.

Counting is in **distinct filings, never passages** — the context held seven Merck passages
from one filing, and "7" would have overstated that evidence sevenfold in precisely the case
where it matters.

**Observed effect.** The model now writes its own hedge, unprompted as to wording:

> "Only a single (most recent) filing is available for Merck & Co Inc and Eli Lilly and
> Company, so conclusions about their regulatory risks are based on limited evidence and may
> not fully reflect ongoing or prior strategies."

**What it made worse, and what that forced — a second edit in the same version.** Given the
counts alone, the model wrote:

> "No filings are available for companies except Eli Lilly and Company, Johnson & Johnson,
> Merck & Co Inc, and Pfizer Inc"

which is **false**. This corpus holds filings for ABBV and TMO; retrieval did not reach them.
The model had turned a retrieval limit into a claim about the data — worse than saying nothing,
because it sounds like knowledge of the corpus.

So the note now ends: *"This describes the passages you were given, not the whole corpus.
Companies not listed may still have filings here that this search did not return — say a
company is absent from the corpus only if you were told so explicitly above."* Genuine
absences already arrive through the `absent` mechanism from v4, and only those may be
described that way. After the edit:

> "Other major pharmaceutical companies not listed in the context (e.g., Novartis, Sanofi,
> GSK) are not addressed."

True, and carefully scoped to the context rather than the corpus.

**The general shape, worth carrying forward.** Handing the model a *partial* census invites it
to treat the partial set as complete. Any count given to a model needs to say what it is a
count *of*, or the model will pick the more useful-sounding interpretation.

## v6 — observed again after table-caption binding, 2026-08-20 (no prompt change)

No prompt edit. Recorded because the *context* the v6 prompt receives changed materially, and
the log would otherwise imply the prompt was working against the same input it started with.

Table-caption binding (§2.7) carries a table's scale caption — `(In millions)` — and its
period-header row into any chunk that was cut below them. Measured across five filings,
financial-table chunks carrying figures with **no stated scale** fell from **113 of 405 (28%)
to 15 of 405 (4%)**; the residual are share-count tables that need no caption.

**Why this belongs in a prompt log.** The passages are the prompt. Before this, a passage
reaching the model could read:

    Shares repurchased | (211) |  | (27) |  | (9,719) |  | (9,746) |
    Net income         | —     |  | —    |  | 72,880  |  | 72,880  |

`72,880` is millions of dollars and `(211)` is millions of shares, and nothing in the passage
said so. No prompt instruction can recover a unit that is not in the context — the model either
guesses or omits, and for a diligence answer an order-of-magnitude guess is the worst available
outcome. This is the clearest case on the map of a retrieval fix doing what no prompt wording
could.

**Nothing synthesized.** Only the filing's own caption and header lines are carried, from
earlier in the same section, and the walk stops at prose so a caption in *thousands* can never
be bolted onto figures in *millions*. A wrong scale reads as authoritative and would be worse
than the missing one.

## v6 — observed again with cross-encoder reranking, 2026-08-20 (no prompt change)

No prompt edit. Recorded because the **selection** of passages reaching the v6 prompt changed,
and because reranking is the step most likely to be mistaken for an extra LLM call.

A cross-encoder now scores the overfetched candidate set before the top-k cut —
`Xenova/ms-marco-MiniLM-L-6-v2`, run locally through FastEmbed's ONNX runtime like the BM25
leg. **No API call, no key, no per-query cost.** It is retrieval work done before the single
generation call, exactly as embedding is, so the one-call constraint is untouched: there is
still one `complete()` call site, and `src/rerank.py` imports no provider SDK.

**What the model now sees.** The same 20 passages' worth of budget, chosen by a model that read
the question and each passage *together* rather than by fusing two rank lists that never
compared them. Retrieval latency 1.0s → 1.7s; generation is ~15s, so it is not perceptible.

**The limit worth stating out loud in the walkthrough.** Every reranker FastEmbed exposes
truncates at **512 tokens**, measured rather than assumed — a marker sentence at token 300
moves the score, the same sentence at token 600 moves it by exactly 0.0000, for all four
candidates. Chunks are median 715 tokens, so **26.8% of indexed text does not influence
ranking**. Two things make that tolerable, and both are consequences of earlier entries:
reflow means a chunk's first 512 tokens are a real block opening rather than an arbitrary
window, and the full chunk still reaches the prompt untouched. The reranker orders candidates;
it does not read them on the model's behalf.

**A trap for whoever revisits this.** `jina-reranker-v1-turbo-en` advertises 8192 context and
truncates at 512 through this export — do not repeat the 8192 figure. And
`jina-reranker-v2-base-multilingual` is **CC-BY-NC-4.0**: the strongest option on offer and
unusable commercially. Both are pinned by tests.

## v7 — 2026-08-20 — quarterly risk factors are labelled as amendments

**What changed.** When any retrieved passage is a 10-Q risk-factor section, its handles are
named and characterised:

> Note on C5, C6, C7, C8, C9, C10, C11: these are quarterly (Form 10-Q) risk-factor passages,
> which by regulation state only *material changes* since the company's most recent annual
> report — not its full risk profile. Treat them as amendments. Do not describe a risk as new
> or newly disclosed on the strength of one, and do not present them as a complete set of
> risks. Where an annual (10-K) risk-factor passage is also provided, that is the baseline they
> amend.

**Why.** Form 10-Q's Item 1A carries only material changes from the 10-K. Measured on this
corpus, the median annual risk-factor section is **12,876 tokens** against a quarterly
**2,617** — and at the thin end, *"How did Pfizer's risk factors change in its latest quarterly
report?"* retrieved **one chunk, 562 tokens**, with no baseline at all. Answered from that, the
system describes a company's entire risk posture from an amendment: fluent, cited, and wrong
about the thing it was asked. No retrieval metric detects it, because the passage retrieved is
genuinely relevant.

The trigger is narrow, which is worth knowing. With no form filter the annual section is ~5x
larger, yields ~5x more chunks, and dominates retrieval on its own — three probe questions all
came back 10-K-majority. The failure appears only when the *question's own wording* restricts
the form ("quarterly", "10-Q"), which `_form_type_in` honours.

**Why the label is needed and not just the baseline.** The retrieval half of this fix
(relaxing a 10-Q form filter to let the annual risk-factor baseline through) makes the context
complete — and thereby makes a *new* error available: with baseline and amendment side by side
and nothing distinguishing them, "newly disclosed this quarter" can be asserted about a risk
that has sat in the 10-K for years. Supplying more context without saying what it is trades one
wrong answer for another. The two halves only work together.

**A limit stated in the wording.** The regulation is a floor, not a description of practice.
Measured, **3 of 15 issuers** here — Meta, Amazon, Microsoft — restate their **full** risk
factors every quarter; Meta's quarterly Item 1A runs ~36,000 tokens, *larger* than the median
annual one. So the note says these passages *state only material changes* per the regulation
rather than asserting they are short, and it tells the model to treat them as amendments rather
than to discount them. A blanket "quarterly risk factors are incomplete" would have been false
for a fifth of the corpus.

**Observed effect.** The handles are named correctly (7 of 20 passages on the Tesla quarterly
question). Not a measurable retrieval change — the retrieval half is what moved those numbers,
and it is recorded in the ticket rather than here.
