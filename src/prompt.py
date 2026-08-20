"""The prompt and context assembly.

Iterations are logged in `PROMPT_LOG.md`, which SPEC §6 treats as a graded deliverable rather
than a byproduct — every change to `SYSTEM` gets an entry there, written when the change is
made.

**v2** adds SPEC §6's five-part answer contract and makes the refusal explicit rather than
incidental. v1's rules were right and are unchanged in substance; what changed is that the
answer now has a shape a reader can scan, and that the prompt is *told* which named companies
are absent instead of being left to notice.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.chunks import Chunk

PROMPT_VERSION = "v5"

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
    # The period the filing reports on, e.g. "2025-10-26". Added in v5 alongside
    # `fiscal_year` rather than replacing it: the year still drives filtering, but the
    # *period* is what gets displayed, because a bare "FY2025" contradicts the excerpt for
    # any issuer whose fiscal year does not end in December (18 of 54 here). Empty for the
    # one filing whose period end is not recoverable.
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


# When the question named companies and **none** of them are in the corpus, the honest answer
# is a refusal and nothing else. Retrieval still returns twenty passages — it has no way not to
# — and they will be about companies nobody asked about. Measured before this existed: "What is
# Shopify's China exposure?" refused correctly and then wrote findings for Amazon, Bank of
# America, Cisco, Goldman Sachs and six others, quoting BofA's China exposure to the dollar.
#
# The distinction is three-way. A question naming *no* company (a sector question) is not a
# refusal case at all — it should answer over whatever was retrieved, and that is the
# behaviour most at risk from getting this rule wrong.
_REFUSE_ONLY = """The question asks about {absent}, and this corpus contains no filings for {pronoun}. The passages above are about other companies and are **not** what was asked about.

Reply with only two sections:

{bottom_line}
State plainly that there are no filings for {absent} in this corpus, so the question cannot be answered from it.

{gaps}
Name what is missing, and say that the corpus does hold filings for other issuers if the reader wants to ask about one of those instead.

Do not write a Findings section. Do not write a Comparison section. Do not cite any passage — none of them are about {absent}. Do not summarise what other companies disclose."""


def user_prompt(
    question: str,
    chunks: list[Chunk],
    *,
    absent: list[str] | None = None,
    named_present: list[str] | None = None,
) -> str:
    """The context block plus the question, as one user message.

    Every passage is introduced by the handle the answer must reuse, so a `[C#]` in the answer
    is resolvable back to a filing.

    `absent` names companies the question mentioned that this corpus does not hold. Telling
    the model rather than leaving it to infer is what makes the refusal reliable: rule 3 then
    has a fact to act on instead of an absence to notice.
    """
    passages = "\n\n".join(
        f"[{handle(index)}] {_label(chunk)}\n{chunk.text}"
        for index, chunk in enumerate(chunks)
    )

    companies = sorted({chunk.company for chunk in chunks})
    present = "\n\nCompanies present in the context: " + ", ".join(companies) if companies else ""

    # A refusal-only answer replaces the format block rather than adding to it — the five-part
    # skeleton asks for Findings and Comparison, which is exactly what must not appear. Placed
    # last for the same reason the format block is: I006 measured that anything which must be
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

    return (
        f"Context passages:\n\n{passages}{present}{notes}"
        f"\n\n---\n\nQuestion: {question}"
        f"\n\n---\n\n{_format_block()}"
    )
