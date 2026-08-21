"""What the answer is standing on, computed rather than asserted.

The panel's third question is *"What regulatory risks do the major pharmaceutical companies
face?"* This corpus holds **JNJ 17 filings, PFE 15, and ABBV, MRK, LLY, TMO at one filing
each** (§2.9). Answered without qualification, the system speaks for an industry while
standing on two companies — and no retrieval metric detects it, because every passage it used
was genuinely relevant.

Two design commitments, both from measurement.

**The unit is distinct filings, never passages.** On ticket 01's run of that question the
context held five Merck passages from *one* filing and three Lilly passages from *one*.
Passage counts would overstate the evidence base five-fold in exactly the case where honesty
matters most.

**Retrieved-of-available, not just retrieved.** `MRK 1 of 1` is a limit of the data; `JNJ 4 of
17` is a limit of the budget. Conflating them tells the reader the wrong thing about what a
follow-up question could fix.

Computed once and used twice: passed into the prompt so its prose can hedge honestly, and
returned in `retrieval_meta` so the UI renders a copy the model cannot garble. The rendered copy
is the one to trust.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from src.chunks import Chunk


def _join(names: tuple[str, ...] | list[str]) -> str:
    """`A`, `A and B`, `A, B and C` — this string is read aloud, so it reads as English."""
    items = list(names)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


@dataclass(frozen=True)
class CompanyCoverage:
    """One company's contribution to the context."""

    ticker: str
    company: str
    passages: int
    filings_retrieved: int
    filings_in_corpus: int
    periods: tuple[str, ...] = field(default=())

    @property
    def rests_on_one_filing(self) -> bool:
        """True only when the corpus itself offers nothing more.

        Deliberately not "we retrieved one" — that would flag a deliberate budget choice as a
        data limitation.
        """
        return self.filings_in_corpus <= 1


@dataclass(frozen=True)
class Coverage:
    companies: tuple[CompanyCoverage, ...] = ()
    thin: tuple[str, ...] = ()
    named_but_absent: tuple[str, ...] = ()

    def sentence(self) -> str:
        """One line, for the prompt and for the UI. Empty when there is nothing to claim.

        Written to be read aloud, because it will be — in a demo, with the answer on screen.
        `filings` appears once rather than after every count, and the thin companies are named
        in words so nobody has to spot `1 of 1` and work out what it implies.
        """
        if not self.companies:
            return ""

        counts = ", ".join(
            f"{c.ticker} {c.filings_retrieved} of {c.filings_in_corpus}" for c in self.companies
        )
        company_word = "company" if len(self.companies) == 1 else "companies"
        sentence = f"Evidence base — {len(self.companies)} {company_word}, filings used: {counts}."

        if self.thin:
            plural = len(self.thin) > 1
            sentence += (
                f" This corpus holds only a single filing for {_join(self.thin)},"
                f" so conclusions about {'them' if plural else 'it'} rest on one period."
            )

        if self.named_but_absent:
            sentence += (
                f" No passages were retrieved for {_join(self.named_but_absent)},"
                " though this corpus holds filings for"
                f" {'them' if len(self.named_but_absent) > 1 else 'it'}."
            )

        return sentence

    def as_dict(self) -> dict[str, object]:
        """The structured form for `retrieval_meta`, so the UI need not parse prose."""
        return {
            "companies": [asdict(c) for c in self.companies],
            "thin": list(self.thin),
            "named_but_absent": list(self.named_but_absent),
            "sentence": self.sentence(),
        }


@lru_cache(maxsize=1)
def filings_by_ticker() -> dict[str, int]:
    """How many filings this corpus holds per ticker.

    Read from the filing headers rather than the index, so a coverage claim does not depend on
    Qdrant being reachable — and so it stays correct if the index is mid-rebuild.
    """
    from src.ingest import filing_headers

    counts: dict[str, int] = defaultdict(int)
    for header in filing_headers():
        if ticker := header.get("ticker", "").strip():
            counts[ticker] += 1
    return dict(counts)


def coverage_of(chunks: list[Chunk], *, named: list[str] | None = None) -> Coverage:
    """What the retrieved context actually covers.

    `named` is the tickers the question asked about, so a company the question named and
    retrieval never reached can be reported. That is distinct from `unresolved_mentions`,
    which is "named, and this corpus holds nothing" — a corpus gap rather than a retrieval
    one. The reader cannot tell those apart unless told.
    """
    if not chunks:
        return Coverage()

    census = filings_by_ticker()
    passages: dict[str, int] = defaultdict(int)
    filings: dict[str, set[str]] = defaultdict(set)
    periods: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}

    for chunk in chunks:
        ticker = chunk.ticker or "?"
        passages[ticker] += 1
        filings[ticker].add(chunk.source_file)
        if chunk.period_end:
            periods[ticker].add(chunk.period_end)
        names.setdefault(ticker, chunk.company)

    companies = [
        CompanyCoverage(
            ticker=ticker,
            company=names.get(ticker, ticker),
            passages=passages[ticker],
            filings_retrieved=len(filings[ticker]),
            filings_in_corpus=census.get(ticker, len(filings[ticker])),
            periods=tuple(sorted(periods[ticker])),
        )
        for ticker in filings
    ]

    # Ordered by filings first and passages only as a tie-break. Sorting by passages would
    # put a company with nine passages from one filing above one with three filings, which is
    # the same illusion this module exists to remove — in the display this time.
    companies.sort(key=lambda c: (-c.filings_retrieved, -c.passages, c.ticker))

    retrieved = set(filings)
    absent = tuple(
        ticker
        for ticker in (named or [])
        if ticker not in retrieved and census.get(ticker, 0) > 0
    )

    return Coverage(
        companies=tuple(companies),
        thin=tuple(c.ticker for c in companies if c.rests_on_one_filing),
        named_but_absent=absent,
    )
