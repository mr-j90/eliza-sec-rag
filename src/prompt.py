"""The prompt and context assembly.

Every version is logged in `PROMPT_LOG.md` — SPEC §6 treats it as a graded deliverable, and
`tests/test_prompt_template.py` fails if `PROMPT_VERSION` has no entry there or if the numbering
has a gap. The history lives there and nowhere else: this docstring once narrated v2 while the
code ran v4, which is the drift that made the log a test rather than a habit.

`docs/PROMPT_TEMPLATE.md` is generated from this module by `render_template()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.chunks import Chunk

PROMPT_VERSION = "v8"

# The headings the answer must use. Tests assert on these rather than on phrasing, so a
# reworded prompt that still behaves correctly keeps passing.
SECTIONS = {
    "bottom_line": "## Bottom line",
    "findings": "## Findings",
    "comparison": "## Comparison",
    "gaps": "## Gaps and confidence",
    "sources": "## Sources",
}

SYSTEM = """You are a diligence analyst answering questions about SEC filings for a private equity firm.

Grounding rules, in order of precedence:

1. Answer only from the provided context passages. Never use what you know about these
   companies from anywhere else. If the context does not support a claim, do not make it.
2. Every factual claim carries a citation handle in square brackets, like [C1], naming the
   passage it came from. A claim with no handle is not allowed, and a handle must not be
   attached to a passage that does not support the claim.
3. If the question names a company with no passages in the context, say so explicitly, by
   name, and answer for the companies that *are* present. One absent company must not cost
   the reader the rest of the answer.
4. Never present a hedge as a finding or a finding as a hedge. If the evidence is thin, say
   it is thin.
5. Do not name a company, ticker or figure that does not appear in the context.
6. A row of values separated by `|` is a row of a financial table, and a scale caption in the
   same passage — `(in millions)`, `($ in thousands)` — states the scale of the figures in it.
   Give a figure with the scale its own passage states. Where a passage states no scale, give
   the figure as it appears and say the scale is not stated. Never assume one.

Follow the output format given at the end of the user message exactly."""


# The required skeleton, emitted at the **end** of the user message rather than in the system
# prompt. Measured 2026-08-19: with the format in the system prompt behind the grounding
# rules, and ~14k tokens of passages in between, four generations of the same question
# produced 0, 0, 0 and 2 of the five sections. Instruction adherence degrades with distance
# from the end of the prompt, and the context block is what creates that distance.
def _format_block() -> str:
    return f"""Reply using exactly these markdown headings, in this order, omitting none:

{SECTIONS["bottom_line"]}
Two or three sentences answering the question directly.

{SECTIONS["findings"]}
One `### Company Name` subsection per company. Every claim carries a [C#] handle.

{SECTIONS["comparison"]}
A markdown table comparing the companies on the dimensions asked about. If only one company
is present, write one line saying a comparison does not apply — do not invent one.

{SECTIONS["gaps"]}
What the context does not support: companies named but absent, periods not covered, questions
the filings do not answer. Never leave this empty.

{SECTIONS["sources"]}
Each handle used, mapped to company, form, fiscal year and section."""


@dataclass(frozen=True)
class Citation:
    """What the caller is told about one context passage. SPEC §8's shape."""

    id: str
    company: str
    form_type: str
    fiscal_year: int
    # The period the filing reports on, e.g. "2025-10-26". Added in v5 alongside `fiscal_year`
    # rather than replacing it: the year drives filtering, the period is what gets displayed.
    # See `_label`. Empty for the one filing whose period end is not recoverable.
    period_end: str
    section: str
    source_file: str
    excerpt: str


EXCERPT_CHARS = 300


def handle(index: int) -> str:
    """`0` → `C1`. Handles are positional in the assembled context."""
    return f"C{index + 1}"


def _label(chunk: Chunk) -> str:
    """`Apple Inc (AAPL) | 10-K, period ending 2025-09-27 | Item 1A — Risk Factors`.

    SPEC §5.5, revised in v5. This used to read `10-K FY2025`, and for the 18 of 54 issuers
    whose fiscal year does not end in December that label disagrees with the filing's own
    text — NVIDIA calls the quarter ending 2025-10-26 "fiscal year 2026". Handing the model
    a year the passage contradicts invites it to state the wrong period in an answer whose
    first rule is to use only what it was given.

    Stating the period end instead is a fact rather than a label, so there is nothing to
    disagree with. Falls back to the year when no period end is recoverable (one filing).
    """
    when = (
        f"period ending {chunk.period_end}"
        if chunk.period_end
        else f"FY{chunk.fiscal_year}"
    )
    return (
        f"{chunk.company} ({chunk.ticker}) | {chunk.form_type}, {when}"
        f" | {chunk.item_section}"
    )


def citations(chunks: list[Chunk]) -> list[Citation]:
    return [
        Citation(
            id=handle(index),
            company=chunk.company,
            form_type=chunk.form_type,
            fiscal_year=chunk.fiscal_year,
            period_end=chunk.period_end,
            section=chunk.item_section,
            source_file=chunk.source_file,
            excerpt=chunk.text[:EXCERPT_CHARS],
        )
        for index, chunk in enumerate(chunks)
    ]


# When the question named companies and **none** are in the corpus, the honest answer is a
# refusal and nothing else — retrieval still returns twenty passages about companies nobody
# asked about. Measured before this existed: "What is Shopify's China exposure?" refused
# correctly and then wrote findings for Amazon, Bank of America, Cisco, Goldman Sachs and six
# others, quoting BofA's exposure to the dollar.
#
# The distinction is three-way: a question naming *no* company is a sector question, not a
# refusal, and answering it over whatever was retrieved is the behaviour most at risk from
# getting this rule wrong.
_REFUSE_ONLY = """The question asks about {absent}, and this corpus contains no filings for {pronoun}. The passages above are about other companies and are **not** what was asked about.

Reply with only two sections:

{bottom_line}
State plainly that there are no filings for {absent} in this corpus, so the question cannot be answered from it.

{gaps}
Name what is missing, and say that the corpus does hold filings for other issuers if the reader wants to ask about one of those instead.

Do not write a Findings section. Do not write a Comparison section. Do not cite any passage — none of them are about {absent}. Do not summarise what other companies disclose."""


def no_matches_answer(
    *,
    companies: list[str],
    fiscal_years: tuple[int, int] | None,
    form_type: str | None,
    corpus_years: tuple[int, int],
) -> str:
    """The answer when retrieval returned nothing but the index is populated.

    Written **in code, with no model call**: zero passages is the one case where a generated
    answer could only come from the model's own knowledge of these companies, which rule 1 of
    `SYSTEM` forbids. The one-call constraint is a ceiling, not a quota.

    A question scoped to a period this corpus does not cover — "what did Apple disclose about the
    iPhone in 2010?" — used to reach the reader as `503 Nothing was retrieved. The index may be
    empty`, which was both alarming and wrong: the index held 30,383 chunks and the year filter
    excluded all of them.
    """
    scope = _scope_phrase(companies, fiscal_years, form_type)
    asked = (
        f"the scope of this question — {scope} — so this question"
        if scope
        else "this question, so it"
    )
    covered = (
        f"fiscal years {corpus_years[0]}–{corpus_years[1]}"
        if corpus_years[0] != corpus_years[1]
        else f"fiscal year {corpus_years[0]}"
    )
    # One line per paragraph, assembled from fragments rather than hard-wrapped: markdown
    # renders either identically, but the terminal client prints the raw text, where a wrapped
    # sentence arrives with the break in it.
    bottom_line = (
        f"No filings in this corpus match {asked} cannot be answered from it. "
        "Nothing was retrieved, so no answer was generated."
    )
    gaps = (
        f"The corpus covers {covered}. A question scoped outside what it holds returns nothing "
        "rather than the nearest available filing — answering from a different period than the "
        "one asked about would be the more misleading result. Widen or drop the period, or ask "
        "about a company and period the corpus covers."
    )
    return (
        f"{SECTIONS['bottom_line']}\n{bottom_line}\n\n"
        f"{SECTIONS['gaps']}\n{gaps}\n\n"
        f"{SECTIONS['sources']}\n"
        "None. No passages were retrieved, so there is nothing to cite."
    )


def _scope_phrase(
    companies: list[str],
    fiscal_years: tuple[int, int] | None,
    form_type: str | None,
) -> str:
    """`AAPL, fiscal year 2010` — what the question narrowed to, in the reader's terms.

    Naming the scope is the whole value of this path: the reader needs to know *which* part of
    the question emptied the result, because a company that is present and a year that is not
    look identical from the outside. Empty when the question narrowed to nothing at all, which
    with a populated index should not happen — and if it does, an honest "no match" beats a
    sentence naming a scope that was never applied.
    """
    parts: list[str] = []
    if companies:
        parts.append(", ".join(companies))
    if fiscal_years:
        first, last = fiscal_years
        parts.append(f"fiscal year {first}" if first == last else f"fiscal years {first}–{last}")
    if form_type:
        parts.append(f"{form_type} filings only")
    return ", ".join(parts)


def user_prompt(
    question: str,
    chunks: list[Chunk],
    *,
    absent: list[str] | None = None,
    named_present: list[str] | None = None,
    coverage: str = "",
) -> str:
    """The context block plus the question, as one user message.

    Every passage is introduced by the handle the answer must reuse, so a `[C#]` in the answer
    is resolvable back to a filing.

    `absent` names companies the question mentioned that this corpus does not hold. Telling
    the model rather than leaving it to infer is what makes the refusal reliable: rule 3 then
    has a fact to act on instead of an absence to notice.

    `coverage` is the same deterministic sentence the UI renders (v6). The model is given it
    as a **fact about the context**, not asked to derive one: a coverage claim the model
    computed could be wrong, and this is precisely the claim a reader would trust. It exists
    so the prose can hedge in proportion to the evidence — an industry-level answer resting on
    two companies should not read like one resting on twenty.
    """
    passages = "\n\n".join(
        f"[{handle(index)}] {_label(chunk)}\n{chunk.text}"
        for index, chunk in enumerate(chunks)
    )

    companies = sorted({chunk.company for chunk in chunks})
    present = "\n\nCompanies present in the context: " + ", ".join(companies) if companies else ""

    # A refusal-only answer replaces the format block rather than adding to it — the five-part
    # skeleton asks for Findings and Comparison, which is exactly what must not appear. Placed
    # last for the same reason the format block is: v3 measured that anything which must be
    # obeyed has to come *after* the context, not before it.
    if absent and not named_present:
        named = ", ".join(absent)
        instruction = _REFUSE_ONLY.format(
            absent=named,
            pronoun="it" if len(absent) == 1 else "them",
            bottom_line=SECTIONS["bottom_line"],
            gaps=SECTIONS["gaps"],
        )
        return (
            f"Context passages:\n\n{passages}{present}"
            f"\n\n---\n\nQuestion: {question}"
            f"\n\n---\n\n{instruction}"
        )

    notes = ""
    if absent:
        named = ", ".join(absent)
        notes = (
            f"\n\nNote: the question mentions {named}, which this corpus contains no filings "
            f"for. Say so explicitly in your answer, and still answer fully for the companies "
            f"that are present.\n"
        )

    # v6. Stated as a computed fact, with an explicit instruction to use it rather than
    # restate it — the deterministic sentence is already rendered beside the answer, so a
    # paraphrase here would be a second, unverifiable copy of the same claim. What the model
    # is asked for is proportionality: an industry-level conclusion drawn from one filing per
    # company must not read like one drawn from twenty.
    if coverage:
        notes += (
            f"\n\nEvidence available to you: {coverage}\n"
            "Reflect this in Gaps and confidence, and let it temper how broadly you state "
            "conclusions. Do not describe evidence you were not given.\n"
            # Measured on the pharmaceutical question: given the counts alone, the model wrote
            # "No filings are available for companies except [the four listed]" — but this
            # corpus holds filings for ABBV and TMO too; retrieval simply did not reach them.
            # That turns a retrieval limit into a false claim about the data, which is worse
            # than saying nothing. Companies genuinely absent from the corpus arrive through
            # `absent` above, and only those may be described that way.
            "This describes the passages you were given, not the whole corpus. Companies not "
            "listed may still have filings here that this search did not return — say a "
            "company is absent from the corpus only if you were told so explicitly above.\n"
        )

    # v7. A 10-Q's Item 1A carries only *material changes* from the 10-K, by regulation, so a
    # passage from one is an amendment to a baseline rather than a risk profile. Naming the
    # handles is what lets the model tell the two apart — without it, a long-standing risk that
    # a quarter merely restated can be reported as newly disclosed, and the retrieval fix that
    # supplies the baseline would make that *more* likely by putting both in front of it.
    if incremental := [
        handle(index) for index, chunk in enumerate(chunks)
        if chunk.is_incremental_risk_factors
    ]:
        notes += (
            f"\n\nNote on {', '.join(incremental)}: these are quarterly (Form 10-Q) risk-factor "
            "passages, which by regulation state only *material changes* since the company's "
            "most recent annual report — not its full risk profile. Treat them as amendments. "
            "Do not describe a risk as new or newly disclosed on the strength of one, and do "
            "not present them as a complete set of risks. Where an annual (10-K) risk-factor "
            "passage is also provided, that is the baseline they amend.\n"
        )

    return (
        f"Context passages:\n\n{passages}{present}{notes}"
        f"\n\n---\n\nQuestion: {question}"
        f"\n\n---\n\n{_format_block()}"
    )


# --- the rendered template, as a deliverable ---------------------------------------------
#
# The brief asks for "your final prompt template" as its own deliverable. It is **generated**,
# never transcribed: `docs/PROMPT_TEMPLATE.md` is the committed output of `render_template()`,
# and `tests/test_prompt_template.py` regenerates it and fails on any difference.

_ILLUSTRATIVE = (
    (
        "Apple Inc",
        "AAPL",
        "10-K",
        "2025-09-27",
        "Item 1A — Risk Factors",
        "The Company's business can be impacted by political events, trade and international "
        "disputes, war, terrorism, natural disasters, and public health issues.",
    ),
    (
        "Tesla Inc",
        "TSLA",
        "10-Q",
        "2025-09-28",
        "Part II Item 1A — Risk Factors",
        "We are dependent on our suppliers, the majority of which are single-source "
        "suppliers, and the inability of these suppliers to deliver components could "
        "disrupt production.",
    ),
)


def _illustrative_chunks() -> list[Chunk]:
    """Two short passages, so the rendered template shows structure rather than filing text."""
    return [
        Chunk(
            chunk_id=f"{ticker}-illustrative-{index:04d}",
            text=text,
            company=company,
            ticker=ticker,
            cik="0000000000",
            form_type=form,
            fiscal_year=int(period[:4]),
            period_end=period,
            filing_date=period,
            item_section=section,
            chunk_index=index,
            source_file=f"{ticker}_{form.replace('-', '')}_{period}_full.txt",
            token_count=len(text.split()),
        )
        for index, (company, ticker, form, period, section, text) in enumerate(_ILLUSTRATIVE)
    ]


def render_template() -> str:
    """`docs/PROMPT_TEMPLATE.md`, generated from the live prompt code."""
    chunks = _illustrative_chunks()
    coverage = (
        "Evidence base — 2 companies, filings used: AAPL 1 of 16, TSLA 1 of 16."
    )
    answering = user_prompt(
        "What are the primary risk factors facing Apple and Tesla, and how do they compare?",
        chunks,
        coverage=coverage,
    )
    refusing = user_prompt(
        "What is Shopify's China exposure?",
        chunks,
        absent=["Shopify"],
        named_present=[],
        coverage=coverage,
    )
    return f"""# Final prompt template — `{PROMPT_VERSION}`

**Generated from `src/prompt.py`. Do not edit by hand** — `tests/test_prompt_template.py`
regenerates this file and fails on any difference, so it cannot drift from the prompt the
system actually sends. Regenerate with:

```bash
uv run python -m src.prompt > docs/PROMPT_TEMPLATE.md
```

Every change to this template has an entry in [`PROMPT_LOG.md`](../PROMPT_LOG.md) saying what
changed and why. The passages below are **illustrative two-line stand-ins**; a real request
carries up to 20 retrieved passages of ~800 tokens each.

Exactly **one** LLM call is made per question, with the system message and one user message
below. Everything that builds them — entity resolution, retrieval, fusion, reranking, coverage
— is deterministic and happens first.

---

## System message

The grounding rules. Stable since v1 in substance; v1's log entry explains why rules 1 and 2
are ordered as they are.

```text
{SYSTEM}
```

---

## User message — answering

One message: the context block, then any notes, then the question, then the required output
format. **The format block is last on purpose** — v3 measured that with it in the system
message behind ~14k tokens of passages, four generations produced 0, 0, 0 and 2 of the five
required sections.

```text
{answering}
```

---

## User message — refusing

When every company the question names is absent from the corpus, the five-part skeleton is
**replaced** rather than extended: it asks for Findings and a Comparison, which is exactly what
must not appear. See v4.

Note the passages are still supplied. Retrieval has no way to return nothing, and the model is
told plainly which company is absent rather than being left to infer it from an absence — which
is what makes the refusal reliable instead of lucky.

```text
{refusing}
```
"""


if __name__ == "__main__":
    print(render_template())
