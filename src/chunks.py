"""The unit of context, and the contextual prefix that makes it findable.

`Chunk` moved here from the placeholder module it was born in: the shape is reusable and
outlived the fixed-window loader that produced the first ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Chunk:
    """One passage plus the provenance a citation needs. SPEC §3's metadata model."""

    chunk_id: str
    text: str
    company: str
    ticker: str
    cik: str
    form_type: str
    fiscal_year: int
    period_end: str
    filing_date: str
    item_section: str
    chunk_index: int
    source_file: str
    token_count: int

    @property
    def is_incremental_risk_factors(self) -> bool:
        """A 10-Q's Item 1A carries only *material changes* from the 10-K, by regulation.

        Measured on this corpus: median 10-K Item 1A is **12,876 tokens** against a 10-Q's
        **2,617** — and at the thin end, Pfizer's quarterly risk section is 562 tokens where
        its annual one runs past 10,000. An answer built from the quarterly text alone
        presents an amendment as a complete risk profile, which is fluent, cited, and wrong
        about the thing it was asked.

        Derived rather than stored: it follows entirely from `form_type` and `item_section`, so
        a payload field would be a second copy that could disagree with them. Note the
        regulation is a floor, not a description — 3 of 15 issuers here (Meta, Amazon,
        Microsoft) restate their full risk factors quarterly, so this flags what *may* be
        incremental and the prompt is worded accordingly.
        """
        return "10-Q" in self.form_type.upper() and self.item_section in RISK_FACTOR_SECTIONS


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    # cl100k_base is what text-embedding-3-small uses, so "800 tokens" means the same
    # thing here as it does at the embedder.
    return tiktoken.get_encoding("cl100k_base")


# The two labels a risk-factor section can carry. A 10-Q files its risk factors under
# *Part II* Item 1A; a 10-K under Item 1A.
RISK_FACTOR_SECTIONS = frozenset(
    {"Item 1A — Risk Factors", "Part II Item 1A — Risk Factors"}
)


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text, disallowed_special=()))


def contextual_prefix(chunk: Chunk) -> str:
    """The synthesized header prepended *before embedding only*.

    SPEC §4 calls this the highest-leverage piece of the ingest path, and the reason is
    retrieval rather than tidiness: a chunk reading "our supply chain is concentrated in a
    small number of vendors" is company-anonymous in embedding space. With the prefix, the
    company, form, period and section are inside the embedded text, so a question naming a
    company can reach a passage that never names it.

    The raw text is stored separately and is what citations display — so an excerpt never
    shows a header the filing did not write.
    """
    period = f" (period ending {chunk.period_end})" if chunk.period_end else ""
    return (
        f"{chunk.company} ({chunk.ticker}) — {chunk.form_type}, "
        f"FY{chunk.fiscal_year}{period} — {chunk.item_section}:"
    )


def embedding_text(chunk: Chunk) -> str:
    """What actually goes to the embedder: prefix, then the passage."""
    return f"{contextual_prefix(chunk)}\n{chunk.text}"
