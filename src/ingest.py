"""Parse a filing, split it by SEC item section, then chunk within each section.

SPEC §4: section-aware first, then recursive at ~800 tokens with ~15% overlap, preferring
paragraph then sentence boundaries, with a whole-document fallback when item headers don't
parse.

Every rule below was found by measuring the corpus, not by anticipating it. Each cost a
wrong result first, and the comments say which one:

1. **Metadata lives in a plain-text header block**, terminated by a `====` separator — not in
   `manifest.json` and not in the filing body. `Report Period:` is absent from 54 of the 246
   filings, so fiscal year falls back to the filing-date year.
2. **Item headers are not line-anchored.** They run together mid-line, so an `^Item` regex
   finds only the table of contents on much of the corpus.
3. **Three kinds of impostor look like a section header** and each needs its own rule: TOC
   rows (the line ends in `| <page>`), quoted cross-references (`“Item 1A. Risk Factors”`
   mid-sentence), and the trailing exhibit index that re-lists every item at the end.
4. **Coverage is not optional.** Sections are matched in document order, and everything the
   matcher does not claim is still chunked under `UNLABELLED`. An earlier version kept only
   the text *between* detected headers, and McDonald's FY2025 10-K — whose only matches were
   in its trailing index — lost 99% of its content while reporting six tidy sections.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.chunks import Chunk, count_tokens
from src.config import settings

TARGET_TOKENS = 800
OVERLAP_RATIO = 0.15
# A window this small is a split-off header fragment, not a passage — Apple's FY2025 10-K
# produces exactly one (`Item 8.`, 4 tokens). Indexing it adds a retrievable chunk that can
# never answer anything, so it is dropped rather than embedded.
MIN_TOKENS = 20
# A section label is metadata; losing the text is not acceptable. Text outside any detected
# section keeps this label and stays retrievable.
UNLABELLED = "Unlabelled section"
# If *all* detection lands in the final tenth of the body it is the trailing exhibit index,
# not the body — see `_section_spans`. Set at 0.9 rather than 0.5 after measuring: 10-Qs
# legitimately carry their first item header past the midpoint, and 0.5 discarded detection on
# 153 of 246 filings.
_LATE_DETECTION = 0.9

_SEPARATOR = re.compile(r"={20,}")

# Section maps, per form type, each in document order so the forward scan in
# `_section_spans` can rely on it.
#
# **10-K and 10-Q number their items differently**, and using the 10-K map on a 10-Q finds
# nothing: a 10-Q's Item 1 is Financial Statements (not Business), its MD&A is Item 2 (not 7),
# and its risk factors sit under *Part II* Item 1A. Measured 2026-08-19: with only the 10-K map,
# 91 of the 157 10-Qs detected no sections at all and fell back to unlabelled — and 10-Qs are
# the majority of this corpus, so temporal questions depended on it.
_ITEM = r"Item\s+{}\.?[\s\xa0|]*{}"

_SECTIONS_10K: tuple[tuple[str, str], ...] = (
    (_ITEM.format("1", r"Business"), "Item 1 — Business"),
    (_ITEM.format("1A", r"Risk\s+Factors"), "Item 1A — Risk Factors"),
    (_ITEM.format("3", r"Legal\s+Proceedings"), "Item 3 — Legal Proceedings"),
    (
        _ITEM.format("7", r"Management.s\s+Discussion"),
        "Item 7 — Management's Discussion and Analysis",
    ),
    (
        _ITEM.format("7A", r"Quantitative"),
        "Item 7A — Quantitative and Qualitative Disclosures About Market Risk",
    ),
    (_ITEM.format("8", r"Financial\s+Statements"), "Item 8 — Financial Statements"),
)

_SECTIONS_10Q: tuple[tuple[str, str], ...] = (
    (_ITEM.format("1", r"Financial\s+Statements"), "Item 1 — Financial Statements"),
    (
        _ITEM.format("2", r"Management.s\s+Discussion"),
        "Item 2 — Management's Discussion and Analysis",
    ),
    (
        _ITEM.format("3", r"Quantitative"),
        "Item 3 — Quantitative and Qualitative Disclosures About Market Risk",
    ),
    (_ITEM.format("4", r"Controls\s+and\s+Procedures"), "Item 4 — Controls and Procedures"),
    # Part II repeats low item numbers, which is why the forward scan matters: these can only
    # be found after Part I's items have been passed.
    (_ITEM.format("1", r"Legal\s+Proceedings"), "Part II Item 1 — Legal Proceedings"),
    (_ITEM.format("1A", r"Risk\s+Factors"), "Part II Item 1A — Risk Factors"),
)


def _section_map(form_type: str) -> tuple[tuple[str, str], ...]:
    return _SECTIONS_10Q if "10-Q" in form_type.upper() else _SECTIONS_10K


# Boilerplate that carries no diligence signal. The XBRL dump is the big one: most filings
# open with thousands of characters of concatenated us-gaap tags.
_XBRL = re.compile(r"(us-gaap:|http://fasb\.org|http://xbrl\.|iso4217:|srt:)\S*")
_XBRL_RUN = re.compile(r"^[a-z0-9\-]{4,}(false|true)?\d{4}(FY|Q\d)?\d{6,}.*$", re.MULTILINE)


def parse_header(raw: str) -> tuple[dict[str, str], int]:
    """(header fields, offset where the body starts).

    Public because `query.py` needs the same parse to derive the same fiscal year — two
    copies of this logic is what let `LATEST_FISCAL_YEAR` drift to 2026 while the newest
    period end in the corpus was 2025.
    """
    match = _SEPARATOR.search(raw)
    if not match:
        return {}, 0
    fields = {}
    for line in raw[: match.start()].splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            fields[key.strip().lower()] = value.strip()
    return fields, match.end()


# The canonical SEC document name embeds the period end: `aapl-20250927.htm`. Not always
# flush against `.htm` though — Deere files `de-20251102x10k.htm` — so match the date and
# allow anything but a path separator after it.
_URL_PERIOD_END = re.compile(r"-(\d{8})[^/]*\.html?", re.IGNORECASE)

# A 10-K filed in these months reports on the *previous* calendar year. Only consulted when
# no period end is recoverable at all, which is one filing in this corpus.
_EARLY_FILING_MONTHS = frozenset({"01", "02", "03", "04"})


def fiscal_period(header: dict[str, str]) -> tuple[str, int]:
    """(period end, fiscal year) for one filing, from its header block.

    **This must not fall back to the filing date for the year.** A 10-K is filed one to
    three months after the period it reports on, so the filing-date year is wrong for
    calendar-year issuers — measured, 37 of 246 filings were labelled a year too high, and
    `LATEST_FISCAL_YEAR` read 2026 for a corpus whose newest period ends in 2025. Every
    relative temporal question inherited that error.

    Preference order, each step existing because the previous one is absent:

    1. **`Report Period:`** — present in 192/246 (§2.2). Read, never inferred.
    2. **The date embedded in `URL:`** — recovers 53 of the remaining 54. §2.2 pointed at
       this field for exactly this purpose.
    3. **Filing month** — one filing (`GE_10K_2015-02-27`, URL `gecc10k2014.htm`) has
       neither. `period_end` is returned empty there, which is the signal that the year was
       inferred rather than read.

    The year is the calendar year the period *ends* in. For the 18 of 54 issuers whose
    fiscal year does not end in December that is **not** the issuer's own fiscal-year label
    — NVIDIA calls the quarter ending 2025-10-26 "fiscal year 2026". Deriving the issuer's
    label was considered and rejected: inline-XBRL `DocumentFiscalYearFocus` extracts from
    under half the corpus, and month arithmetic is fragile precisely where it matters
    (52/53-week calendars put JNJ's year end in December *or* early January, Disney's in
    September *or* October). So citations display the **period**, not a bare `FY` label,
    and there is nothing for a reader to catch contradicting itself.
    """
    if reported := header.get("report period", "").strip():
        return reported, int(reported[:4])

    if embedded := _URL_PERIOD_END.search(header.get("url", "")):
        digits = embedded.group(1)
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}", int(digits[:4])

    filed = header.get("filing date", "").strip()
    if not filed:
        return "", 0
    year = int(filed[:4])
    if "10-K" in header.get("filing type", "").upper() and filed[5:7] in _EARLY_FILING_MONTHS:
        year -= 1
    return "", year


def _strip_boilerplate(body: str) -> str:
    body = _XBRL.sub(" ", body)
    body = _XBRL_RUN.sub("", body)
    return body


# A table-of-contents row is a *line* ending in a page number: `Item 1A. | Risk Factors | 6`.
# That trailing `| <digits>` is the discriminator — not the pipe between the item number and
# the title, because filings disagree about that. Apple writes the body header as
# `Item 1A.\xa0\xa0\xa0\xa0Risk Factors`; Amazon writes it as `Item 1A. | Risk Factors`, pipe
# and all, and only the absent page number tells them apart.
#
# It has to be checked to end of line, not within a fixed lookahead. These patterns match a
# *prefix* of the title, so on a long title the page number sits far past the match — Bank of
# America's `Item 7A. | Quantitative and Qualitative Disclosures about Market Risk | 86` put
# it ~50 characters out. Measured 2026-08-19: a 24-character lookahead accepted three TOC rows
# in that filing, which sorted before the real sections and left Item 3 swallowing 157k
# characters — 425 of its 469 chunks labelled "Legal Proceedings".
_TOC_ROW = re.compile(r"^[^\n]*\|[\s\xa0]*\d+[\s\xa0]*$")


# Filings quote their own section names mid-sentence: PepsiCo's FY2026 10-K contains
# `“Item 1A. Risk Factors” and “Item 7. Management’s Discussion and Analysis…`, which has the
# title adjacent to the number and carries no page number, so neither earlier rule rejects it.
# An opening quote before the match is the tell.
_QUOTES = "“‘\"'"


def _first_body_match(body: str, pattern: str, after: int = 0) -> int | None:
    """Offset of the first real section header at or after `after`.

    Three kinds of impostor are rejected here, each found by measurement rather than
    anticipated:

    - **TOC rows** — the line ends in `| <page>`.
    - **Quoted cross-references** — the match is preceded by an opening quote.
    - **Out-of-order matches** — handled by the caller via `after`, because SEC sections
      appear in a fixed order and a match before the previous section cannot be this one.
    """
    for match in re.finditer(pattern, body, re.IGNORECASE):
        if match.start() < after:
            continue
        if match.start() > 0 and body[match.start() - 1] in _QUOTES:
            continue
        line_end = body.find("\n", match.end())
        rest_of_line = body[match.end() : line_end if line_end != -1 else len(body)]
        if not _TOC_ROW.match(rest_of_line):
            return match.start()
    return None


def _section_spans(
    body: str, section_map: tuple[tuple[str, str], ...]
) -> list[tuple[str, int, int]]:
    """(label, start, end) for each section found, in document order.

    A section's start is its first non-TOC match; its end is the next section's start. Only
    the first surviving match of each pattern is taken — later ones are cross-references back
    to a section already captured.
    """
    # The section map is in document order, and SEC filings honour it. Scanning forward — each
    # section sought only *after* the last one found — is what stops an early cross-reference
    # from being mistaken for a header and leaving a later section to swallow the gap. Before
    # this, PepsiCo's Item 3 span ran 282k characters because a quoted mention of Item 1A
    # sorted ahead of Item 1's real header.
    starts: list[tuple[int, str]] = []
    cursor = 0
    for pattern, label in section_map:
        start = _first_body_match(body, pattern, after=cursor)
        if start is not None:
            starts.append((start, label))
            cursor = start + 1

    # Filings carry a trailing exhibit index that lists every item again. If the *first*
    # detected section sits deep in the document, it is that index rather than the body —
    # McDonald's FY2025 10-K matched all six sections in its last 4k characters, and taking
    # them at face value discarded 99% of the filing. Distrust the whole detection instead of
    # labelling an index as six sections.
    if starts and starts[0][0] > len(body) * _LATE_DETECTION:
        starts = []

    if not starts:
        return [(UNLABELLED, 0, len(body))]

    # Cover the **entire** body. Section labels are best-effort metadata; content coverage is
    # not optional, so anything before the first detected header — cover page, index, front
    # matter, or a section whose header this parser does not recognise — is still chunked and
    # still retrievable, just without a section label.
    spans: list[tuple[str, int, int]] = []
    if starts[0][0] > 0:
        spans.append((UNLABELLED, 0, starts[0][0]))
    for index, (start, label) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(body)
        spans.append((label, start, end))
    return spans


def _split_on_boundaries(text: str) -> list[str]:
    """Paragraph first, then sentence — SPEC §4's preference order."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    # Filing text is often one run-together block, so fall through to sentences.
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])", text) if s.strip()]


def _windows(text: str) -> list[str]:
    """Accumulate boundary-preferring pieces up to the token target, with overlap."""
    pieces = _split_on_boundaries(text)
    overlap_tokens = int(TARGET_TOKENS * OVERLAP_RATIO)

    out: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for piece in pieces:
        piece_tokens = count_tokens(piece)

        # A single piece bigger than the target has no boundary to split on — cut it by
        # tokens rather than emit something enormous.
        if piece_tokens > TARGET_TOKENS:
            if current:
                out.append(" ".join(current))
                current, current_tokens = [], 0
            out.extend(_hard_split(piece))
            continue

        if current_tokens + piece_tokens > TARGET_TOKENS and current:
            out.append(" ".join(current))
            # Carry the tail of what we just emitted into the next window.
            tail, tail_tokens = [], 0
            for previous in reversed(current):
                previous_tokens = count_tokens(previous)
                if tail_tokens + previous_tokens > overlap_tokens:
                    break
                tail.insert(0, previous)
                tail_tokens += previous_tokens
            current, current_tokens = tail, tail_tokens

        current.append(piece)
        current_tokens += piece_tokens

    if current:
        out.append(" ".join(current))
    stripped = (w.strip() for w in out)
    return [w for w in stripped if w and count_tokens(w) >= MIN_TOKENS]


def _hard_split(text: str) -> list[str]:
    encoding = __import__("tiktoken").get_encoding("cl100k_base")
    tokens = encoding.encode(text, disallowed_special=())
    step = TARGET_TOKENS - int(TARGET_TOKENS * OVERLAP_RATIO)
    return [
        encoding.decode(tokens[i : i + TARGET_TOKENS]) for i in range(0, len(tokens), step)
    ]


def chunk_filing(source_file: str) -> list[Chunk]:
    """Every chunk of one filing, section-labelled and sized."""
    path: Path = settings().corpus_dir / source_file
    raw = path.read_text(encoding="utf-8", errors="replace")

    header, offset = parse_header(raw)
    body = _strip_boilerplate(raw[offset:])

    ticker = header.get("ticker", "")
    form_type = (header.get("filing type", "").split("(")[0] or "").strip()
    filing_date = header.get("filing date", "")
    # Never from the `Quarter:` tag, which is the calendar quarter of the period end, and
    # never from the filing date alone — see `fiscal_period` for why that was wrong for 37
    # filings.
    period_end, fiscal_year = fiscal_period(header)

    spans = _section_spans(body, _section_map(form_type))
    if not spans:
        # Documented fallback: `Item 1A` is line-anchored in only 180 of 246 files, and one
        # filing lacks it entirely. Chunk the whole document rather than return nothing.
        spans = [("Whole document", 0, len(body))]

    chunks: list[Chunk] = []
    for label, start, end in spans:
        for window in _windows(body[start:end]):
            index = len(chunks)
            slug = re.sub(r"[^a-z0-9]+", "", label.split("—")[0].strip().lower())
            chunks.append(
                Chunk(
                    # The filing date is what makes this unique. Without it, every 10-Q a company
                    # filed in one fiscal year produced identical ids: Apple's three FY2022
                    # 10-Qs all yielded `AAPL-10Q-2022-item1-0002`, and because the Qdrant
                    # point id is derived from the chunk id, two of the three quarters were
                    # silently overwritten. 8,046 of 29,499 chunks (27%) vanished that way,
                    # which would have broken precisely the temporal questions this corpus
                    # is for. SPEC §3's example id has the same flaw.
                    chunk_id=(
                        f"{ticker}-{form_type.replace('-', '')}-FY{fiscal_year}"
                        f"-{filing_date}-{slug}-{index:04d}"
                    ),
                    text=window,
                    company=header.get("company", ""),
                    ticker=ticker,
                    cik=header.get("cik", ""),
                    form_type=form_type,
                    fiscal_year=fiscal_year,
                    period_end=period_end,
                    filing_date=filing_date,
                    item_section=label,
                    chunk_index=index,
                    source_file=source_file,
                    token_count=count_tokens(window),
                )
            )
    return chunks
