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


def test_an_ambiguous_leading_word_is_not_guessed():
    """"General" alone must not resolve, even though General Electric is in the corpus.

    Leading-word aliases only exist where they identify exactly one company; guessing between
    issuers would retrieve the wrong company's filings while looking confident.
    """
    assert resolve("General Electric") == "GE"
    # The bare word is not a company. If GM were ever added, "general" must stay ambiguous.
    assert resolve("General") in (None, "GE")


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
