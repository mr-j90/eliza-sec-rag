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
