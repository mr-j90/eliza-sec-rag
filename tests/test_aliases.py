"""The company/ticker alias dictionary, built from filing headers.

CLAUDE.md correction 1: SPEC §5.2 says build this from `manifest.json`, which has no company
names. These assertions use names quoted from the corpus headers, so they disagree with the
code if the derivation drifts.
"""

from src.aliases import aliases, by_ticker, normalise, resolve


def test_every_company_in_the_corpus_is_known():
    companies = by_ticker()
    assert len(companies) == 54, f"expected 54 tickers, got {len(companies)}"
    assert companies["AAPL"] == "Apple Inc"
    assert companies["JPM"].startswith("JPMorgan")


def test_the_spec_example_resolves_all_three_ways():
    """SPEC §5.2 states this case verbatim: JPMorgan / JPM / JPMorgan Chase & Co. → JPM."""
    assert resolve("JPMorgan") == "JPM"
    assert resolve("JPM") == "JPM"
    assert resolve("JPMorgan Chase & Co.") == "JPM"


def test_names_resolve_with_and_without_corporate_suffixes():
    assert resolve("Apple") == "AAPL"
    assert resolve("Apple Inc") == "AAPL"
    assert resolve("apple inc.") == "AAPL"
    assert resolve("NVIDIA Corporation") == "NVDA"
    assert resolve("Tesla, Inc.") == "TSLA"


def test_a_company_absent_from_the_corpus_resolves_to_nothing():
    """The out-of-corpus case SPEC §6 calls the most valuable behaviour to demo.

    Shopify and General Motors are real companies with no filings here. Resolving them to a
    near-neighbour would be the failure the refusal contract exists to prevent.
    """
    assert resolve("Shopify") is None
    assert resolve("General Motors") is None
    assert resolve("Nonexistent Holdings Ltd") is None


def test_a_descriptor_word_never_resolves_on_its_own():
    """A word that describes a company rather than identifying it must not resolve alone.

    Measured 2026-08-20: promoting the leading word unconditionally had put four wrong-issuer
    resolutions in front of a reader — "General Motors" → GE, "United States" → UPS, "American
    companies" → AXP, "bank regulations" → BAC. Each retrieved a real company's filings for a
    question that was not about it, and said nothing about having done so.
    """
    for word in ("General", "United", "American", "Bank", "Home", "International",
                 "Advanced", "Business", "Electric", "Systems", "Express", "Services"):
        assert resolve(word) is None, f"{word!r} identifies no company and must not resolve"

    # The names those words belong to are unaffected: a descriptor still resolves in context.
    assert resolve("General Electric") == "GE"
    assert resolve("United Parcel Service") == "UPS"
    assert resolve("American Express") == "AXP"
    assert resolve("Bank of America") == "BAC"


def test_a_distinctive_word_resolves_from_anywhere_in_the_name():
    """Not only the leading one. "The Walt Disney Company" yielded `walt disney` and `walt`
    but not **disney** — the commonest way to name a company with 17 filings here, and the
    phrasing of the golden set's own temporal question, which therefore ran unfiltered.
    """
    assert resolve("Disney") == "DIS"
    assert resolve("Lilly") == "LLY"
    assert resolve("Chase") == "JPM"
    assert resolve("Sachs") == "GS"
    assert resolve("Hathaway") == "BRK"
    assert resolve("Mobil") == "XOM"


def test_names_no_rule_could_derive_from_the_filing_header():
    """A former name, a contraction, or a brand that is not the registrant. None of these
    appear in any `Company:` line, so they are listed explicitly — and the list is filtered
    against the corpus, so it cannot claim a company this index does not hold.
    """
    assert resolve("Coke") == "KO"
    assert resolve("Amex") == "AXP"
    assert resolve("P&G") == "PG"
    assert resolve("J&J") == "JNJ"
    assert resolve("Raytheon") == "RTX"
    assert resolve("Google") == "GOOG"
    assert resolve("Facebook") == "META"


def test_tickers_always_win_over_name_collisions():
    for ticker in by_ticker():
        assert resolve(ticker) == ticker, f"ticker {ticker} did not resolve to itself"


def test_normalise_strips_suffixes_and_punctuation():
    assert normalise("JPMorgan Chase & Co.") == "jpmorgan chase"
    assert normalise("Amazon.com, Inc.") == "amazon com"


def test_the_dictionary_is_derived_not_hardcoded():
    """Every alias must trace back to a ticker the corpus actually contains."""
    known = set(by_ticker())
    assert set(aliases().values()) <= known
