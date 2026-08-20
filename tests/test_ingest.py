"""Section-aware chunking over a real filing.

These tests read an actual filing rather than a fixture, because the whole lesson of
I001 was that filing text defeats assumptions that look reasonable on synthetic input.
Expected values are quoted from the document — an independent source of truth, not a
value recomputed the way the code computes it.
"""

import re
from functools import lru_cache

from src.chunks import contextual_prefix
from src.config import settings
from src.ingest import _strip_boilerplate, chunk_filing

FILING = "AAPL_10K_2025-10-31_full.txt"


def chunks():
    return chunk_filing(FILING)


def test_metadata_comes_from_the_header_block():
    first = chunks()[0]

    assert first.company == "Apple Inc"
    assert first.ticker == "AAPL"
    assert first.cik == "0000320193"
    assert first.form_type == "10-K"
    # No `Report Period:` in this filing — one of the 54 that omit it — so fiscal year
    # falls back to the filing-date year, per CLAUDE.md.
    assert first.fiscal_year == 2025
    assert first.source_file == FILING


def test_risk_factors_starts_at_the_header_not_the_toc_or_a_cross_reference():
    """The lesson from I001, now against the real chunker.

    `Item 1A` appears many times in this filing. The TOC row is pipe-delimited
    (`Item 1A. | Risk Factors | 5`). A cross-reference in the forward-looking-statements
    paragraph reads "...discussed in Part I, Item 1A of this Form 10-K under the heading
    'Risk Factors.'" — no pipe, and it sits *earlier* in the file than the real header.
    Only one occurrence opens the section, and this sentence is quoted from it.
    """
    risk = [c for c in chunks() if "1A" in c.item_section]
    assert risk, "no Item 1A chunks were produced"

    opening = risk[0].text
    assert "The following summarizes factors" in opening, (
        f"Item 1A did not start at the section body; got: {opening[:200]!r}"
    )
    # The cross-reference sentence must not be what we captured.
    assert "under the heading" not in opening[:400]


def test_the_xbrl_dump_is_dropped():
    """Filings open with thousands of characters of concatenated us-gaap tags."""
    body = "\n".join(c.text for c in chunks())
    assert "us-gaap:" not in body
    assert "http://fasb.org" not in body


def test_chunks_are_near_the_target_size_and_overlap():
    sized = [c for c in chunks() if c.chunk_index > 0]
    assert sized, "expected more than one chunk"
    # SPEC §4: ~800 tokens. Allow slack for boundary-preferring splits, but a chunker
    # that ignored the target entirely would fail this.
    oversized = [c.token_count for c in sized if c.token_count > 1100]
    assert not oversized, f"chunks exceed the 800-token target by too much: {oversized[:5]}"


def test_sections_are_labelled_and_more_than_one_is_found():
    sections = {c.item_section for c in chunks()}
    assert len(sections) > 1, f"only found sections: {sections}"
    assert any("1A" in s for s in sections), f"Item 1A missing from {sections}"


def test_the_contextual_prefix_names_the_company_form_and_section():
    """SPEC §4's prefix is what makes a company-anonymous chunk findable by company."""
    first = chunks()[0]
    prefix = contextual_prefix(first)

    assert first.company in prefix
    assert first.ticker in prefix
    assert first.form_type in prefix
    assert str(first.fiscal_year) in prefix
    assert first.item_section in prefix
    # It is a prefix, not a wrapper: the raw text must not be inside it.
    assert first.text not in prefix


def test_chunk_ids_are_unique_and_traceable():
    ids = [c.chunk_id for c in chunks()]
    assert len(ids) == len(set(ids)), "chunk_ids collide"
    assert all(re.match(r"^AAPL-10K-FY2025-2025-10-31-", i) for i in ids[:5]), ids[:5]


# --- corpus-wide invariants (I004) ---


def all_filings():
    return sorted(p.name for p in settings().corpus_dir.glob("*.txt"))


# The corpus-wide tests each chunk all 246 filings; without this they re-do ~10s of work apiece.
@lru_cache(maxsize=None)
def cached_chunks(name: str):
    return tuple(chunk_filing(name))


def test_every_filing_chunks_without_error():
    failures = []
    for name in all_filings():
        try:
            if not cached_chunks(name):
                failures.append((name, "zero chunks"))
        except Exception as exc:  # noqa: BLE001 - the point is to report, not to raise
            failures.append((name, repr(exc)))
    assert not failures, f"{len(failures)} filings failed to chunk: {failures[:5]}"


def test_no_filing_loses_its_body_text():
    """The invariant that would have caught the worst bug in this intent.

    An earlier chunker kept only the text *between* detected section headers. For filings
    whose only matches were in the trailing exhibit index, that silently discarded almost the
    whole document while reporting a tidy set of sections — a filing that looked indexed and
    could answer nothing. Coverage exceeds 100% because windows overlap by ~15%.
    """
    worst = []
    for name in all_filings():
        raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
        separator = raw.find("=" * 20)
        # Measured against the *stripped* body: dropping the XBRL tag dump is deliberate, so
        # counting it as lost content would make this test fail for doing the right thing.
        body = _strip_boilerplate(raw[separator:]).strip()
        covered = sum(len(c.text) for c in cached_chunks(name))
        ratio = covered / max(len(body), 1)
        if ratio < 0.85:
            worst.append((name, round(ratio, 3)))
    assert not worst, f"filings losing body text: {worst[:5]}"


def test_section_detection_does_not_collapse_to_fallback():
    """Fallback is legitimate and must stay bounded — a silent rise means detection rotted."""
    total = all_filings()
    unlabelled_only = [
        name
        for name in total
        if {c.item_section for c in cached_chunks(name)} == {"Unlabelled section"}
    ]
    share = len(unlabelled_only) / len(total)
    # Measured 2026-08-19 at 11% (27 of 246), almost all 10-Qs with unusual layouts. The
    # bound catches detection rotting — a jump here means a pattern stopped matching.
    assert share < 0.20, (
        f"{len(unlabelled_only)}/{len(total)} filings ({share:.0%}) detected no sections at all"
    )


def test_chunk_ids_are_unique_across_the_whole_corpus():
    """The invariant that would have caught 27% silent data loss.

    Qdrant point ids are derived deterministically, so two chunks sharing an id means the
    second overwrites the first. `{ticker}-{form}-{fiscal_year}-{section}-{index}` collides for
    every company that filed more than one 10-Q in a fiscal year: Apple's three FY2022 10-Qs all
    produced `AAPL-10Q-2022-item1-0002`. 8,046 of 29,499 chunks disappeared without an error,
    and the ones lost were exactly what temporal questions need.
    """
    seen: dict[str, str] = {}
    collisions = []
    for name in all_filings():
        for chunk in cached_chunks(name):
            if chunk.chunk_id in seen and seen[chunk.chunk_id] != name:
                collisions.append((chunk.chunk_id, seen[chunk.chunk_id], name))
            seen[chunk.chunk_id] = name
    assert not collisions, f"{len(collisions)} colliding chunk_ids, e.g. {collisions[:3]}"
