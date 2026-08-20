"""What the answer is standing on, stated rather than implied.

Ticket 07. The panel's third question is *"What regulatory risks do the major pharmaceutical
companies face?"* — and this corpus holds **JNJ 17 filings, PFE 15, and ABBV, MRK, LLY, TMO
at one filing each** (§2.9). Without a coverage statement the system answers on behalf of an
industry while standing on two companies, and no retrieval metric detects it.

Measured on ticket 01's run of that question, the retrieved context gave **Merck 5 passages
from 1 filing** and **Lilly 3 from 1**. Passage counts create an illusion of depth, which is
why the unit here is **distinct filings**, never passages.

The same asymmetry bites the comparative question: **JPM has 4 filings against Apple's 16**.

Free tier: reads the corpus, needs no Qdrant and no key.
"""

from __future__ import annotations

import pytest

from src.chunks import Chunk
from src.coverage import coverage_of, filings_by_ticker


def chunk(ticker: str, company: str, source_file: str, period_end: str = "2025-12-31") -> Chunk:
    return Chunk(
        chunk_id=f"{ticker}-{source_file}",
        text="Regulatory approval processes are lengthy and uncertain.",
        company=company,
        ticker=ticker,
        cik="0000000000",
        form_type="10-K",
        fiscal_year=int(period_end[:4]),
        period_end=period_end,
        filing_date=period_end,
        item_section="Item 1A — Risk Factors",
        chunk_index=0,
        source_file=source_file,
        token_count=9,
    )


# --- the corpus census ------------------------------------------------------------------


def test_the_corpus_census_matches_the_measured_figures():
    """§2.9's numbers, which are the whole reason this ticket exists."""
    census = filings_by_ticker()
    assert census["JNJ"] == 17
    assert census["PFE"] == 15
    for thin in ("ABBV", "MRK", "LLY", "TMO"):
        assert census[thin] == 1, f"{thin} should hold a single filing"
    assert census["AAPL"] == 16
    assert census["JPM"] == 4, "the thin side of the comparative question"
    assert sum(census.values()) == 246


# --- counting what the answer stood on --------------------------------------------------


def test_passages_are_not_mistaken_for_filings():
    """The exact illusion this ticket removes.

    Five passages from one Merck filing is one filing of evidence. Reporting "5" would
    overstate the evidence base by five times.
    """
    chunks = [chunk("MRK", "Merck & Co Inc", "MRK_10K_2025-02-25_full.txt") for _ in range(5)]
    coverage = coverage_of(chunks)

    assert len(coverage.companies) == 1
    merck = coverage.companies[0]
    assert merck.passages == 5
    assert merck.filings_retrieved == 1, "five passages from one filing is one filing"


def test_distinct_filings_are_counted_separately():
    chunks = [
        chunk("PFE", "Pfizer Inc", "PFE_10K_2025-02-27_full.txt"),
        chunk("PFE", "Pfizer Inc", "PFE_10Q_2025Q2_2025-08-05_full.txt", "2025-06-29"),
        chunk("PFE", "Pfizer Inc", "PFE_10Q_2025Q2_2025-08-05_full.txt", "2025-06-29"),
    ]
    pfizer = coverage_of(chunks).companies[0]
    assert pfizer.passages == 3
    assert pfizer.filings_retrieved == 2


def test_a_company_resting_on_a_single_filing_is_flagged():
    """The distinction that matters: whether the limit is the corpus or the retrieval budget.

    `MRK 1 of 1` means the corpus holds one filing — nothing better was available. `JNJ 4 of
    17` means retrieval chose four. Those are different claims and a reader deserves both.
    """
    chunks = [
        chunk("JNJ", "Johnson & Johnson", f"JNJ_10Q_2025Q{q}_2025-0{q}-01_full.txt", f"2025-0{q}-01")
        for q in (1, 2, 3, 4)
    ] + [chunk("MRK", "Merck & Co Inc", "MRK_10K_2025-02-25_full.txt")]

    coverage = coverage_of(chunks)
    by_ticker = {c.ticker: c for c in coverage.companies}

    assert by_ticker["JNJ"].filings_retrieved == 4
    assert by_ticker["JNJ"].filings_in_corpus == 17
    assert by_ticker["MRK"].filings_retrieved == 1
    assert by_ticker["MRK"].filings_in_corpus == 1

    assert "MRK" in coverage.thin, "one filing available means the evidence is thin"
    assert "JNJ" not in coverage.thin, "four of seventeen is a budget choice, not a thin corpus"


def test_companies_are_ordered_by_evidence_not_by_passage_count():
    """A company with many passages from one filing must not outrank one with several
    filings — that ordering would reproduce the illusion in the display."""
    chunks = [chunk("MRK", "Merck & Co Inc", "MRK_10K_2025-02-25_full.txt") for _ in range(9)] + [
        chunk("PFE", "Pfizer Inc", f"PFE_10Q_2025Q{q}_2025-0{q}-01_full.txt", f"2025-0{q}-01")
        for q in (1, 2, 3)
    ]
    order = [c.ticker for c in coverage_of(chunks).companies]
    assert order == ["PFE", "MRK"], f"ordered by passages rather than filings: {order}"


def test_a_named_company_that_retrieval_missed_is_reported():
    """Different from an out-of-corpus refusal: these filings exist and were not reached.

    `unresolved_mentions` already covers "named, and this corpus has nothing". This covers
    "named, we hold filings, and none of them came back" — which is a retrieval gap, not a
    corpus gap, and the reader cannot tell the two apart without being told.
    """
    chunks = [chunk("AAPL", "Apple Inc", "AAPL_10K_2025-10-31_full.txt", "2025-09-27")]
    coverage = coverage_of(chunks, named=["AAPL", "TSLA", "JPM"])
    assert set(coverage.named_but_absent) == {"TSLA", "JPM"}


def test_nothing_retrieved_yields_no_claim():
    coverage = coverage_of([])
    assert coverage.companies == ()
    assert coverage.sentence() == ""


# --- the sentence -----------------------------------------------------------------------


def test_the_sentence_names_the_thin_evidence_explicitly():
    """A reader must not have to do the arithmetic to notice the problem."""
    chunks = (
        [chunk("JNJ", "Johnson & Johnson", f"JNJ_10Q_{q}.txt", f"2025-0{q}-01") for q in (1, 2, 3, 4)]
        + [chunk("PFE", "Pfizer Inc", f"PFE_10Q_{q}.txt", f"2025-0{q}-01") for q in (1, 2)]
        + [chunk("MRK", "Merck & Co Inc", "MRK_10K.txt")]
        + [chunk("LLY", "Eli Lilly and Company", "LLY_10K.txt")]
    )
    sentence = coverage_of(chunks).sentence()

    assert "4 of 17" in sentence, "JNJ's retrieved-of-available must be visible"
    assert "1 of 1" in sentence
    assert "MRK" in sentence and "LLY" in sentence
    assert "single filing" in sentence.lower(), (
        f"the thin companies must be called out in words, not left to arithmetic: {sentence}"
    )


def test_the_sentence_is_a_single_line():
    """It is rendered in a UI facts row and read aloud in a demo."""
    chunks = [chunk("JNJ", "Johnson & Johnson", "JNJ_10K.txt")]
    assert "\n" not in coverage_of(chunks).sentence()


@pytest.mark.parametrize("named", [None, [], ["JNJ"]])
def test_the_sentence_never_claims_more_than_it_has(named):
    chunks = [chunk("JNJ", "Johnson & Johnson", "JNJ_10K.txt")]
    sentence = coverage_of(chunks, named=named).sentence()
    assert "17" in sentence, "the corpus total belongs in the claim"
    assert "1 of 17" in sentence
