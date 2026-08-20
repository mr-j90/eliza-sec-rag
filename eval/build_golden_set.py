"""Regenerate `eval/golden_set.json` by deriving labels from the corpus.

    uv run python eval/build_golden_set.py

**This script must never call retrieval.** Labels come from reading the filings: for each
question, the relevant filings are those containing its probe term, restricted to the tickers
the question names. That keeps the ground truth independent of the system being measured — a
golden set labelled from retrieval output would make every metric a measure of how closely a
configuration reproduces today's behaviour.

Questions are hand-written. The *labels* are computed, which is the part that has to be
auditable: the probe is recorded with each question so a reader can re-run the same grep.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REPO_ROOT, settings  # noqa: E402

# (id, category, question, tickers, probe, sections, absent, note)
# Probes are chosen to be *narrow*: "CHIPS Act" appears in one filing, "Basel III" in seven.
# A broad probe like "pandemic" (186 files) labels half the corpus as relevant and measures
# nothing.
QUESTIONS: list[dict] = [
    # --- single-company factual (6) ---
    dict(
        id="sc-01",
        category="single_company",
        question="What does NVIDIA disclose about export controls on its products?",
        tickers=["NVDA"],
        probe="export control",
        sections=["Item 1A — Risk Factors"],
        note="US export restrictions on advanced GPUs are a core NVIDIA risk disclosure.",
    ),
    dict(
        id="sc-02",
        category="single_company",
        question="What does Intel say about the CHIPS Act?",
        tickers=["INTC"],
        probe="CHIPS Act",
        sections=[],
        note="The probe appears in exactly one filing in the whole corpus, so the label is unusually precise.",
    ),
    dict(
        id="sc-03",
        category="single_company",
        question="What risks does Tesla disclose about Autopilot and self-driving features?",
        tickers=["TSLA"],
        probe="Autopilot",
        sections=["Item 1A — Risk Factors"],
        note="Autopilot is named in Tesla's product-liability and regulatory risk factors.",
    ),
    dict(
        id="sc-04",
        category="single_company",
        question="How does Apple describe its dependence on outsourcing partners for manufacturing?",
        tickers=["AAPL"],
        probe="outsourcing partners",
        sections=["Item 1A — Risk Factors"],
        note="Apple's supply-chain concentration language uses this exact phrase.",
    ),
    dict(
        id="sc-05",
        category="single_company",
        question="What does Boeing disclose about the 737 MAX?",
        tickers=["BA"],
        probe="737 MAX",
        sections=[],
        note="A named product with a specific identifier — the kind of term BM25 should win on.",
    ),
    dict(
        id="sc-06",
        category="single_company",
        question="What does Berkshire Hathaway say about its insurance float?",
        tickers=["BRK"],
        probe="float",
        sections=[],
        note="Deliberately harder: 'float' is a common word, so the label is broad and precision will suffer.",
    ),
    # --- cross-company comparative (8) ---
    dict(
        id="cc-01",
        category="cross_company",
        question=(
            "What are the primary risk factors facing Apple, Tesla, and JPMorgan, "
            "and how do they compare?"
        ),
        tickers=["AAPL", "TSLA", "JPM"],
        probe="risk factors",
        sections=["Item 1A — Risk Factors", "Part II Item 1A — Risk Factors"],
        note="Stated verbatim in the assessment brief. The canonical entity-quota case.",
    ),
    dict(
        id="cc-02",
        category="cross_company",
        question="How do Goldman Sachs and JPMorgan describe their Basel III capital requirements?",
        tickers=["GS", "JPM"],
        probe="Basel III",
        sections=[],
        note="A regulatory term specific to large banks; narrow probe, two named issuers.",
    ),
    dict(
        id="cc-03",
        category="cross_company",
        question="Compare how Microsoft and Amazon describe competition in cloud services.",
        tickers=["MSFT", "AMZN"],
        probe="cloud",
        sections=[],
        note="Both are cloud incumbents; a broad probe, so recall matters more than precision here.",
    ),
    dict(
        id="cc-04",
        category="cross_company",
        question="How do Pfizer and Merck describe patent expiration risk?",
        tickers=["PFE", "MRK"],
        probe="patent",
        sections=["Item 1A — Risk Factors"],
        note="Loss of exclusivity is the central pharma risk; both issuers disclose it.",
    ),
    dict(
        id="cc-05",
        category="cross_company",
        question="Compare what Walmart and Costco disclose about supply chain disruption.",
        tickers=["WMT", "COST"],
        probe="supply chain",
        sections=[],
        note="Two retailers, same topic — tests whether quotas keep both represented.",
    ),
    dict(
        id="cc-06",
        category="cross_company",
        question="How do Visa and Mastercard describe interchange fee regulation?",
        tickers=["V", "MA"],
        probe="interchange",
        sections=[],
        note="Also exercises short-ticker extraction: V must resolve to Visa.",
    ),
    dict(
        id="cc-07",
        category="cross_company",
        question="Compare the climate-related risks disclosed by Exxon Mobil and Chevron.",
        tickers=["XOM", "CVX"],
        probe="climate",
        sections=["Item 1A — Risk Factors"],
        note="Both majors disclose transition and physical climate risk.",
    ),
    dict(
        id="cc-08",
        category="cross_company",
        question="How do Lockheed Martin and RTX describe dependence on US government contracts?",
        tickers=["LMT", "RTX"],
        probe="U.S. Government",
        sections=["Item 1A — Risk Factors"],
        note="Defence primes; concentration of a single customer is the shared risk.",
    ),
    # --- temporal / trend (5) ---
    dict(
        id="tm-01",
        expect_fiscal_years=[2025, 2026],
        category="temporal",
        question="How has NVIDIA's revenue and growth outlook changed over the last two years?",
        tickers=["NVDA"],
        probe="revenue",
        sections=["Item 7 — Management's Discussion and Analysis"],
        note=(
            "Stated verbatim in the assessment brief. Relevance legitimately spans several "
            "filings and periods, which a single-file label describes badly."
        ),
    ),
    dict(
        id="tm-02",
        expect_fiscal_years=[2023, 2026],
        category="temporal",
        question="How has Tesla's vehicle delivery guidance changed since 2023?",
        tickers=["TSLA"],
        probe="deliveries",
        sections=["Item 7 — Management's Discussion and Analysis", "Item 2 — Management's Discussion and Analysis"],
        note="Requires the time filter to select the right fiscal years.",
    ),
    dict(
        id="tm-03",
        expect_fiscal_years=[2024, 2026],
        category="temporal",
        question="How has Intel's capital expenditure plan evolved over the last three years?",
        tickers=["INTC"],
        probe="capital expenditure",
        sections=[],
        note="Foundry build-out spans several filings; a trend question over MD&A.",
    ),
    dict(
        id="tm-04",
        expect_fiscal_years=[2025, 2025],
        category="temporal",
        question="What did Disney report about streaming subscriber trends in its recent quarterly filings?",
        tickers=["DIS"],
        probe="subscriber",
        sections=["Item 2 — Management's Discussion and Analysis"],
        note=(
            "Tests the form hint: 'quarterly' must select 10-Q. Window is FY2025 because that is "
            "Disney's newest fiscal year — its FY2025 Q4 10-Q was *filed* 2026-02-02, so the "
            "corpus-wide newest year (2026) is the wrong window for this issuer. Originally "
            "phrased 'most recent quarter', reworded because a single newest filing is not "
            "expressible as a year window and the label must stay derivable. The underlying "
            "gap — recency is company-specific, and src/query.py resolves it corpus-wide — is "
            "recorded as a finding rather than papered over here."
        ),
    ),
    dict(
        id="tm-05",
        expect_fiscal_years=[2022, 2026],
        category="temporal",
        question="How has Boeing's commercial aircraft delivery outlook shifted since 2022?",
        tickers=["BA"],
        probe="deliveries",
        sections=[],
        note="Multi-year trend for an issuer with a disrupted delivery history.",
    ),
    # --- sector-wide (3) ---
    dict(
        id="sw-01",
        category="sector",
        question=(
            "What regulatory risks do the major pharmaceutical companies face, "
            "and how are they addressing them?"
        ),
        tickers=[],
        probe="drug pricing",
        sections=["Item 1A — Risk Factors"],
        note=(
            "Stated verbatim in the assessment brief. Names no company, so retrieval must find "
            "the sector unaided — measured to already work without filters."
        ),
    ),
    dict(
        id="sw-02",
        category="sector",
        question="What do large US banks disclose about expected credit loss provisioning?",
        tickers=[],
        probe="CECL",
        sections=[],
        note=(
            "Narrowed from 'allowance for credit losses' (111 files) to the CECL acronym (12, "
            "all financials). A probe matching 45% of the corpus makes recall structurally tiny "
            "and measures nothing. SPEC §5.1 names CECL as exactly the kind of identifier BM25 "
            "should win on, which makes it a useful ablation discriminator too."
        ),
    ),
    dict(
        id="sw-03",
        category="sector",
        question="What do semiconductor and technology companies disclose about power consumption in their operations?",
        tickers=[],
        probe="power consumption",
        sections=[],
        note=(
            "Narrowed from 'data center' (89 files) to 'power consumption' (6, all "
            "semiconductor issuers). Sector breadth is still tested — retrieval must find them "
            "with no company named — without labelling a third of the corpus relevant."
        ),
    ),
    # --- unanswerable / out-of-corpus (3) ---
    dict(
        id="un-01",
        category="unanswerable",
        question="What is Shopify's China exposure?",
        tickers=[],
        probe=None,
        sections=[],
        absent=["Shopify"],
        note="SPEC §7.1's example. Shopify has no filings in this corpus.",
    ),
    dict(
        id="un-02",
        category="unanswerable",
        question="What does Ferrari disclose about supply chain risk?",
        tickers=[],
        probe=None,
        sections=[],
        absent=["Ferrari"],
        note="A real issuer, absent here — the answer must refuse rather than substitute a peer.",
    ),
    dict(
        id="un-03",
        category="unanswerable",
        question="Compare the regulatory risks disclosed by Spotify and Rivian.",
        tickers=[],
        probe=None,
        sections=[],
        absent=["Spotify", "Rivian"],
        note="Two absent companies, so the refusal must name both rather than one.",
    ),
]


def _fiscal_year(path: Path) -> int:
    """From the header block, exactly as the chunker derives it — Report Period, else filing date."""
    head = path.read_text(encoding="utf-8", errors="replace")[:400]
    period = re.search(r"^Report Period:\s*(\d{4})", head, re.MULTILINE)
    filed = re.search(r"^Filing Date:\s*(\d{4})", head, re.MULTILINE)
    source = period or filed
    return int(source.group(1)) if source else 0


def matching_files(
    probe: str, tickers: list[str], years: list[int] | None = None
) -> list[str]:
    """Filings containing the probe, restricted to the named tickers and fiscal-year window.

    This is the whole labelling method: read the corpus, not the index.

    The year window matters for the temporal questions. Without it, "how has NVIDIA's outlook
    changed over the last two years" labels all 16 NVIDIA filings — and a *correct* answer,
    which applies the time filter and retrieves two years of them, scores badly. The window is
    hand-written per question rather than parsed, so a parser bug cannot launder itself into the
    ground truth.
    """
    pattern = re.compile(re.escape(probe), re.IGNORECASE)
    out = []
    for path in sorted(settings().corpus_dir.glob("*.txt")):
        ticker = path.name.split("_")[0]
        if tickers and ticker not in tickers:
            continue
        if years and not (years[0] <= _fiscal_year(path) <= years[1]):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            out.append(path.name)
    return out


def main() -> int:
    questions = []
    for spec in QUESTIONS:
        entry = dict(spec)
        probe = entry.get("probe")
        entry.setdefault("absent", [])
        if probe:
            files = matching_files(probe, entry["tickers"], entry.get("expect_fiscal_years"))
            if not files:
                print(f"  !! {entry['id']}: probe {probe!r} matched nothing — label would be empty")
                return 1
            entry["source_files"] = files
        else:
            entry["source_files"] = []
        questions.append(entry)
        print(f"  {entry['id']:6s} {entry['category']:15s} {len(entry['source_files']):3d} files")

    out = REPO_ROOT / "eval" / "golden_set.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "note": (
                    "Labels are derived from the corpus by eval/build_golden_set.py, never from "
                    "retrieval output. Each answerable question records the probe term its "
                    "source_files were matched on, so any label can be re-derived."
                ),
                "questions": questions,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out} — {len(questions)} questions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
