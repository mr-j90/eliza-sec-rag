# Prompt log

Every change to the system prompt in `src/prompt.py`, why it changed, and what it did.
Written as the changes happen — a log reconstructed at the end shows, and SPEC §6 treats
this as a graded deliverable rather than a byproduct.

Expect the interesting entries to be failures. "v2 over-cited and became unreadable" says
more about the work than a list of clean wins.

---

## v1 — 2026-08-19 — the two rules everything else depends on

**Version:** v1 · introduced under [I001](.eng/intents/I001-frontend-answers-from-fastapi.md)

**What it says.** Four rules in precedence order: answer only from the provided context;
every factual claim carries a `[C#]` handle; a company named in the question but absent from
the context is called out explicitly rather than substituted; never dress a hedge as a
finding. Closes with a Sources list mapping handles to company, form, period and section.

**Why this and not the full contract.** SPEC §6 specifies a five-part answer — bottom line,
per-entity findings, comparison table, gaps and confidence, sources. v1 deliberately does
not ask for that structure. I001's scope is the *wire*: one real answer travelling from the
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

That second result is the behaviour SPEC §6 calls the single most valuable thing to demo, and
it worked at v1 without refusal-specific tuning. Worth not over-reading: with a single-company
context, "the others are absent" is the *easy* case. The hard case is a company absent from
the whole 246-filing corpus while nine plausible neighbours are retrieved — route entry 6.

**Two things to watch, not yet problems.**

- **Rule 3 fires twice in one answer.** The refusal appears in the opening paragraph and again
  in the closing line. Correct but redundant, and at v1 it is not worth trading away emphasis
  for concision — a refusal that repeats itself is a better failure than one a reader skims
  past. Revisit if answers get long.
- **Generation dominates latency by three orders of magnitude** — ~5-6 s against ~1 ms of
  context assembly. G01's signal 4b (end-to-end under 15 s) has real headroom now, but that is
  with three chunks. At SPEC §5.5's 40k-token budget this is the number that will move, and
  the context budget is the named lever.


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
answer grouped itself by company without being asked to. v1 still does not request SPEC §6's
five-part structure; it is now clear that it should, because the model is inventing a structure
per answer and consistency is part of what makes a comparison readable. That is a v2 change and
belongs with the refusal work.


## v2 — 2026-08-19 — the five-part contract, and it did not take

**Version:** v2 · introduced under [I006](.eng/intents/I006-refusal-and-answer-contract.md)

**What changed.** Added SPEC §6's five-part answer contract — bottom line, findings, comparison,
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

**Version:** v3 · same intent

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

**Version:** v4 · introduced under [I007](.eng/intents/I007-clean-refusal.md)

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
nothing — which broke an I006 test that required Sources on every answer unconditionally. The test
was amended rather than the behaviour: the honest rule is "cite your sources when you have used
sources", and demanding the heading on a refusal would mean either an empty section or an
invitation to fill it. Worth noting as a general shape — a prompt rule written as "always include
X" acquires an exception the moment a legitimate answer has no X.

**Placement, again.** The refusal instruction goes after the context for the same reason the format
block does (v3's finding). Put before it, it would have read as fixed and behaved as before.

## v5 — 2026-08-20 — the passage label states a period, not a fiscal year

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
*or* October. It would also have to run **before** the XBRL strip that ticket 03 is about, which
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
