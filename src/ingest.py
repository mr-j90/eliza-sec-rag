"""Parse a filing, split it by SEC item section, then chunk within each section.

SPEC §4: section-aware first, then recursive at ~800 tokens with ~15% overlap, preferring
paragraph then sentence boundaries, with a whole-document fallback when item headers don't
parse.

The pipeline: `parse_header` → `fiscal_period` → `_strip_boilerplate` → `_section_spans` →
`_reflow` → `_windows` → `_bind_table_context`.

Every rule here was found by measuring the corpus, not by anticipating it, and each cost a
wrong result first. The evidence is stated once, at the rule it justifies — not summarised
here as well, because two copies of a measurement is how one of them goes stale.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from src.chunks import Chunk, count_tokens, encoding
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
# `[.:\-–—]?` after the number, not just `.`: §2.5 lists a colon/dash form and the pattern
# only ever allowed a period. Measured, that single omission cost **11 filings** their entire
# segmentation — Comcast writes `Item\xa01A: Risk Factors` and Disney's Part II headers use the
# same form, so all 10 Disney 10-Qs plus Comcast's 10-K fell back to unlabelled.
_ITEM = r"Item\s+{}[.:\-–—]?[\s\xa0|]*{}"

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


# Enough to clear the header block and its `=` separator, including the `URL:` line that
# `fiscal_period` falls back to.
_HEADER_BYTES = 4000


@lru_cache(maxsize=1)
def filing_headers() -> tuple[dict[str, str], ...]:
    """Every filing's header block, parsed once per process.

    One scan serves the three things derived from it — the alias table, the corpus fiscal-year
    range and the per-ticker filing census. Three separate scans is what let `query.py` grow
    its own copy of `fiscal_period` and drift a year off.
    """
    headers = []
    for path in sorted(settings().corpus_dir.glob("*.txt")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            fields, _ = parse_header(handle.read(_HEADER_BYTES))
        if fields:
            headers.append(fields)
    return tuple(headers)


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


# How far back to look for an unclosed opening quote. A cross-reference names the item a few
# words into the quotation — `“Part I, Item 1A—Risk Factors”` — so checking only the character
# immediately before the match misses it.
_QUOTE_LOOKBACK = 48
_OPEN_QUOTES = "“‘"
_CLOSE_QUOTES = "”’"


def _inside_a_quotation(body: str, start: int) -> bool:
    """Is this match inside a quoted cross-reference rather than at a real header?

    §2.5 measures **30.7% of all `Item N` mentions as cross-references**, so this guard is
    doing most of the work of keeping segmentation honest.

    Two rules, and the second is why the naive version failed. A quote character immediately
    before the match catches `“Item 1A. Risk Factors”`. But AMD writes
    `see “Part I, Item 1A—Risk Factors” and…`, where the quote opens eight characters earlier
    — and taking that as a header cut Item 1 Business from 19 chunks to 1. So we also walk
    back for an **unclosed** opening quote, stopping at a closing quote or a line break
    because either means the quotation ended before this point.

    Only curly quotes are used for the walk. A straight `'` is an apostrophe far more often
    than a quote in this corpus (`Management's Discussion`), and treating it as one would
    reject real headers.
    """
    if start > 0 and body[start - 1] in _QUOTES:
        return True
    for character in reversed(body[max(0, start - _QUOTE_LOOKBACK) : start]):
        if character in _CLOSE_QUOTES or character == "\n":
            return False
        if character in _OPEN_QUOTES:
            return True
    return False


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
        if _inside_a_quotation(body, match.start()):
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


# --- reflow: putting back the block boundaries the HTML stripper omitted (§2.4) ---------
#
# The converter emitted no separator where a block ended. 216 of 246 filings carry a line
# over 20,000 characters and Tesla's whole Item 1A is one line of 90,033. Measured before
# this landed: 88.8% of chunks contained an invisible block join and 3.6% fused across an
# `ITEM` header — two sections of a filing in one chunk, under one label.
#
# The omission is the signal. Where a boundary was, one of two things is now true.

# A sentence-final character abutting a capital with no space between them.
_GLUE_SENTENCE = re.compile(r'(?<=[.!?"])(?=[A-Z"])')

# A Title Case heading running straight into its body text. Deliberately narrow: the
# unguarded `(?<=[a-z])(?=[A-Z])` this replaces fired 285–335 times per filing and shredded
# `xAI`, `MyPower` and glued table headers. `[a-z]{3}` requires a real word before the join
# and `[A-Z][a-z]+\s` a real word after, which is what excludes those.
_GLUE_HEADING = re.compile(r"(?<=[a-z]{3})(?=[A-Z][a-z]+\s)")

# Abbreviations that end in a period without ending a sentence. Measured on Tesla's 10-K,
# **98 of 416** rule-1 candidates sit after one of these — without the guard, `U.S.` becomes
# `…in U.` / `S. dollar would…`, so this is the difference between reflow working and reflow
# shredding the text.
_ABBREVIATION_WORD = re.compile(
    r"\b(?:Inc|Corp|Ltd|Co|No|Nos|Mr|Mrs|Ms|Dr|Jr|Sr|St|vs|etc|al|Ph|Fig"
    r"|e\.g|i\.e|approx|Dept|Div|Univ|Sec|Art)\.$",
    re.IGNORECASE,
)

# A single capital letter used as an initial, which is how the *interior* periods of `I.R.S.`
# and `U.S.C.` are caught. The preceding character must be a space, an open paren or another
# period — deliberately **not** a word boundary. `\b` would also match the `K` in
# `Form 10-K.`, and a form name genuinely does end a sentence: Tesla writes
# `…on Form 10-K.ITEM 1A. RISK FACTORS…`, which is precisely a boundary we must not miss.
_ABBREVIATION_INITIAL = re.compile(r"(?:^|[\s(. ])[A-Z]\.$")


def _ends_with_abbreviation(before: str) -> bool:
    return bool(_ABBREVIATION_WORD.search(before) or _ABBREVIATION_INITIAL.search(before))

# How far back the heading rule looks for evidence of a Title Case run.
_HEADING_LOOKBACK = 70


def _block_boundaries(text: str) -> list[int]:
    """Offsets where a block boundary was lost, in ascending order."""
    found: set[int] = set()

    for match in _GLUE_SENTENCE.finditer(text):
        # 12 characters is enough for the longest abbreviation above plus its period.
        if _ends_with_abbreviation(text[max(0, match.start() - 12) : match.start()]):
            continue
        found.add(match.start())

    for match in _GLUE_HEADING.finditer(text):
        cut = match.start()
        before = text[max(0, cut - _HEADING_LOOKBACK) : cut]
        # A pipe means a table row, whose glued column headers belong to ticket 06 — cutting
        # them here would separate a figure from the header naming it. A recent newline means
        # the "heading" is just the start of a line, which needs no boundary inserted.
        if "|" in before or "\n" in before[-25:]:
            continue
        words = before.split()[-4:]
        if len(words) < 3 or sum(word[:1].isupper() for word in words) < 3:
            continue
        found.add(cut)

    return sorted(found)


def _reflow(text: str) -> str:
    """Insert `\\n\\n` at every recovered block boundary.

    Inserting separators rather than returning pieces is what lets the paragraph arm of
    `_split_on_boundaries` do the work it was always meant to do — §2.4's point is that the
    preference order was right and the separators were simply missing.

    **This only ever inserts.** It must not alter a single character of filing text; a reflow
    that dropped content would be silent and invisible to every retrieval metric, which is
    why `test_reflow.py` asserts the text is unchanged with newlines removed.
    """
    boundaries = _block_boundaries(text)
    if not boundaries:
        return text
    pieces = []
    previous = 0
    for cut in boundaries:
        pieces.append(text[previous:cut])
        previous = cut
    pieces.append(text[previous:])
    return "\n\n".join(pieces)


def _split_on_boundaries(text: str) -> list[str]:
    """Paragraph first, then sentence — SPEC §4's preference order.

    Reflow runs first, because on this corpus the paragraph separators the preference order
    assumes do not exist: measured across eight representative filings, **0 of 55 sections**
    contained a single `\\n\\n`. Without it the paragraph arm never fires and everything
    falls to the sentence arm, which cannot see a boundary that has no whitespace at all.

    Reflow is applied by `_windows`, which keeps the reflowed text so table-caption binding
    can locate a window inside it. Splitting here without reflowing first would find no
    paragraph boundaries at all.

    Reflow runs per section, after `_section_spans` has run — deliberately.
    Inserting newlines earlier would change the line structure that `_TOC_ROW` and the
    late-detection guard depend on, so section segmentation stays byte-identical and only
    chunking changes. Whether reflowing *before* segmentation would improve detection is a
    real question and belongs to ticket 02, which measures it.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    # Still possible for a short section with no recoverable boundary at all.
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])", text) if s.strip()]


# --- table-caption binding (§2.7) --------------------------------------------------------
#
# 22.2% of corpus characters are pipe-table rows, and two of the three things a figure needs
# sit outside the table: the **scale caption** on the preceding narrative line, and the
# **period header** on its own label-less row. Cut a long table below those and every figure
# under the cut is meaningless — measured, 113 of 405 (28%) financial-table chunks carried
# figures with no stated scale.
#
# Demo-critical because the XBRL numeric router is future state: with no structured path,
# NVIDIA's revenue figures come from exactly these rows.

_SCALE_CAPTION = re.compile(
    r"(?:\(|\b)(?:\$\s*)?(?:in|dollars\s+in|amounts\s+in)\s+(?:millions|thousands|billions)\b",
    re.IGNORECASE,
)

# A figure with a thousands separator, currency mark or decimal — the kind of number whose
# scale changes its meaning. A bare `13` is a page number, not a financial figure.
_SCALED_FIGURE = re.compile(r"\|\s*\$?\s*\(?(?:\d{1,3}(?:,\d{3})+|\$\s*[\d.]+|\d+\.\d\d)\b")

# Period labels a column header is built from.
_PERIOD_LABEL = re.compile(
    r"\b(?:19|20)\d\d\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\b"
    r"|\b(?:Three|Six|Nine|Twelve)\s+Months\b|\bQ[1-4]\b|\bYear(?:s)?\s+Ended\b",
    re.IGNORECASE,
)


# A caption sits on the line immediately before its table (§2.7), so a couple of prose lines
# between a window and a candidate caption is normal — a run of them means we have left the
# table entirely.
_MAX_NARRATIVE_LINES_ABOVE_TABLE = 2


def _scale_caption(line: str) -> bool:
    """Does this line state the scale its neighbouring figures are reported in?"""
    return bool(_SCALE_CAPTION.search(line))


def _is_period_header(line: str) -> bool:
    """A table's column header: period labels and **no figures of its own**.

    The absence of figures is the discriminator. `Total | 130,497 | 60,922` names no period
    and carries data; `| Jan 26, 2025 | Jan 28, 2024 |` names periods and carries none.
    """
    if line.count("|") < 2:
        return False
    if _SCALED_FIGURE.search(line):
        return False
    return bool(_PERIOD_LABEL.search(line))


def _bind_table_context(window: str, section: str) -> str:
    """Carry a table's scale caption and period header into a window that lost them.

    Only ever prepends **the filing's own lines**, taken from earlier in the same section.
    `index.py` stores this text as what citations display, so an excerpt must be the filing's
    words — this is a composition of two real spans, never a synthesized header.

    The *nearest preceding* caption is used, not the first or last in the section: a section
    holding one table in thousands and another in millions would otherwise have them swapped,
    which is worse than no caption at all.
    """
    lines = window.split("\n")
    if not any(_SCALED_FIGURE.search(line) for line in lines):
        return window
    if any(_scale_caption(line) for line in lines):
        return window

    start = section.find(window)
    if start <= 0:
        return window

    caption = header = None
    narrative_run = 0
    for line in reversed(section[:start].split("\n")):
        if header is None and _is_period_header(line):
            header = line
        if _scale_caption(line):
            caption = line
            break
        # Stop at prose. A caption belongs to the table it introduces, and crossing a run of
        # narrative means we have walked out of that table and into whatever came before it —
        # where a caption in *thousands* could get bolted onto figures in *millions*. A wrong
        # scale is worse than a missing one, because it reads as authoritative.
        if line.strip() and "|" not in line:
            narrative_run += 1
            if narrative_run > _MAX_NARRATIVE_LINES_ABOVE_TABLE:
                return window
        elif line.strip():
            narrative_run = 0
    if caption is None:
        return window

    carried = [caption] + ([header] if header else [])
    return "\n".join(carried + lines)


def _windows(text: str) -> list[str]:
    """Accumulate boundary-preferring pieces up to the token target, with overlap."""
    # Reflowed once and held, because `_bind_table_context` locates a window by searching
    # this text — a window from the pre-reflow string would not be found in it.
    reflowed = _reflow(text)
    pieces = _split_on_boundaries(reflowed)
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
    kept = [w for w in stripped if w and count_tokens(w) >= MIN_TOKENS]
    # §2.7: a window cut below a table's caption gets it back, from the filing's own lines.
    return [_bind_table_context(window, reflowed) for window in kept]


def _hard_split(text: str) -> list[str]:
    encoder = encoding()
    tokens = encoder.encode(text, disallowed_special=())
    step = TARGET_TOKENS - int(TARGET_TOKENS * OVERLAP_RATIO)
    return [
        encoder.decode(tokens[i : i + TARGET_TOKENS]) for i in range(0, len(tokens), step)
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
