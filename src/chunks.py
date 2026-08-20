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


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    # cl100k_base is what text-embedding-3-small uses, so "800 tokens" means the same
    # thing here as it does at the embedder.
    return tiktoken.get_encoding("cl100k_base")


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
