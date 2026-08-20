"""Rule-based query understanding — no LLM, by construction (SPEC §5.2).

The expected values here come from the assessment's own questions and from the corpus, not
from what the implementation happens to produce.
"""

from src.query import LATEST_FISCAL_YEAR, plan

PANEL_COMPARATIVE = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, "
    "and how do they compare?"
)
PANEL_TEMPORAL = "How has NVIDIA's revenue and growth outlook changed over the last two years?"
PANEL_SECTOR = (
    "What regulatory risks do the major pharmaceutical companies face, "
    "and how are they addressing them?"
)


# --- companies ---


def test_the_panel_comparative_question_resolves_all_three_companies():
    assert plan(PANEL_COMPARATIVE).companies == ["AAPL", "TSLA", "JPM"]


def test_a_possessive_company_name_is_found():
    """"NVIDIA's" — the apostrophe must not hide the company."""
    assert plan(PANEL_TEMPORAL).companies == ["NVDA"]


def test_a_sector_question_names_no_company():
    """Sector breadth comes from retrieval, not from expanding a sector into tickers."""
    assert plan(PANEL_SECTOR).companies == []


def test_companies_are_reported_in_the_order_the_question_names_them():
    p = plan("Compare JPMorgan and Apple on regulatory risk.")
    assert p.companies == ["JPM", "AAPL"]


def test_a_company_absent_from_the_corpus_is_detected_as_absent_not_ignored():
    """SPEC §7.1's out-of-corpus case. Entry 6's refusal is built on this distinction.

    "Detected but absent" and "not mentioned" must not look the same, or the answer has no
    way to say *which* company it cannot speak about.
    """
    p = plan("What is Shopify's China exposure?")
    assert p.companies == []
    assert "Shopify" in p.unresolved_mentions


def test_a_misspelt_company_is_answered_rather_than_refused():
    """The question as a user actually typed it, 2026-08-21. It came back "There are no filings
    for Morgen in this corpus": the run "JP Morgen" matched no alias, "JP" was then dropped by
    the short-token rule, and the leftover "Morgen" was reported as an absent company. A typo
    presented as a corpus gap is the refusal contract firing on the wrong thing.
    """
    p = plan(
        "What regulatory risks does JP Morgen have and that did that look like "
        "over the last 2 years"
    )
    assert p.companies == ["JPM"]
    assert p.unresolved_mentions == []
    assert p.fiscal_years == (LATEST_FISCAL_YEAR - 1, LATEST_FISCAL_YEAR)


def test_a_misspelling_never_outranks_a_name_the_corpus_spells_exactly():
    """Near-misses are only tried after every exact span has failed. Inline, the longer span
    "Compare Micorsoft" could fuzzy-match before "Amazon" was ever tested exactly.
    """
    p = plan("Compare Micorsoft and Amazon on cloud competition.")
    assert p.companies == ["MSFT", "AMZN"]
    assert p.unresolved_mentions == []


def test_ordinary_capitalised_words_are_not_mistaken_for_companies():
    """The heuristic that finds Shopify must not find "Risk" or "Item"."""
    p = plan("What are the primary Risk Factors disclosed in Item 1A of recent filings?")
    assert p.companies == []
    assert p.unresolved_mentions == []


def test_short_tickers_do_not_match_ordinary_prose():
    """`V` is Visa and `T` is AT&T. A question about T-bills is not a question about AT&T."""
    p = plan("How do rising rates on a T-bill affect the value of long-dated debt?")
    assert "T" not in p.companies
    p2 = plan("What does V disclose about payment volumes?")
    assert "V" in p2.companies, "an explicit standalone ticker should still resolve"


# --- time scope ---


def test_relative_time_anchors_to_the_corpus_not_the_clock():
    """The newest fiscal year here is 2026. Anchoring to the system clock would silently
    return nothing once this snapshot stops being current — SPEC §9 already calls the corpus
    a fixed snapshot, so the code should behave like one."""
    years = plan(PANEL_TEMPORAL).fiscal_years
    assert years == (LATEST_FISCAL_YEAR - 1, LATEST_FISCAL_YEAR)


def test_an_explicit_year_is_taken_literally():
    assert plan("What did Apple disclose about supply chains in 2023?").fiscal_years == (2023, 2023)


def test_since_a_year_is_a_range_to_the_newest():
    assert plan("How has Tesla's outlook shifted since 2023?").fiscal_years == (
        2023,
        LATEST_FISCAL_YEAR,
    )


def test_no_time_language_means_no_time_filter():
    assert plan(PANEL_COMPARATIVE).fiscal_years is None
    assert plan(PANEL_SECTOR).fiscal_years is None


def test_a_year_outside_the_corpus_is_still_honoured():
    """Better an empty result the user can understand than a silent widening to a year they
    did not ask about."""
    assert plan("What did Apple say in 2019?").fiscal_years == (2019, 2019)


# --- form hints ---


def test_quarterly_language_selects_10_q():
    assert plan("What did Apple report in its most recent quarter?").form_type == "10-Q"
    assert plan("Summarise Tesla's quarterly filings.").form_type == "10-Q"


def test_annual_language_selects_10_k():
    assert plan("What does Apple's annual report say about competition?").form_type == "10-K"
    assert plan("In its 10-K, what does Apple disclose?").form_type == "10-K"


def test_no_form_language_means_no_form_filter():
    assert plan(PANEL_COMPARATIVE).form_type is None


def test_the_plan_is_pure_and_needs_no_services():
    """Query understanding must not require Qdrant or a provider — it is rules over text.

    If this ever needs a network call, the one-call constraint has been broken somewhere
    upstream of the answer.
    """
    p = plan(PANEL_COMPARATIVE)
    assert p.companies and p.fiscal_years is None and p.form_type is None


def test_a_name_containing_a_lowercase_connective_is_read_as_one_company():
    """"Bank of America" is one company, not the words "Bank" and "America".

    Capitalised runs used to stop at the lowercase "of", so this span was never tested against
    the dictionary at all — it resolved only because bare "bank" mapped to BAC, which resolved
    "bank regulations" the same way. Fixing that alias without fixing the run would have taken
    a company with 4 filings here down to ticker-only.
    """
    assert plan("What does Bank of America disclose about credit losses?").companies == ["BAC"]
    assert plan("What does Procter and Gamble say about commodity costs?").companies == ["PG"]


def test_absent_companies_joined_by_and_are_named_separately():
    """The golden set's unanswerable comparison. One mention reading "Spotify and Rivian" would
    still refuse correctly, but the refusal names what it cannot speak about, and it should
    name two companies because two were asked about.
    """
    assert plan("Compare the risks disclosed by Spotify and Rivian.").unresolved_mentions == [
        "Spotify",
        "Rivian",
    ]


def test_a_descriptor_alone_is_not_reported_as_an_absent_company():
    """`unresolved_mentions` drives the "no filings for X" line in an answer. A bare descriptor
    is not a company, so reporting one puts a sentence in the answer saying this corpus holds
    no filings for "Technologies". Two words still count — "General Motors" is a real company
    with no filings here, and naming it is the point of the list.
    """
    assert plan("Which Technologies are named in these filings?").unresolved_mentions == []
    assert plan("How do Bank regulations affect lenders?").unresolved_mentions == []
    assert plan("Compare Tesla and General Motors on demand.").unresolved_mentions == [
        "General Motors"
    ]
