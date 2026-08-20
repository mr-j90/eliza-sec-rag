# SEC EDGAR RAG — Architecture Research Note

**Scope.** Design research for an internal RAG system over 10-K/10-Q filings for private-equity-style diligence. Hard constraint from the assessment brief: **the final answer must come from exactly one LLM API call.** Indexing, retrieval, fusion and reranking all run before that call.

**Date of research:** 2026-08-19. Every claim below either cites a primary source I fetched, or is labelled as a measurement I took against the corpus, or is explicitly marked speculative/unverified.

**Corpus measured:** `/Users/jordan/Developer/eliza/sec-rag/edgar_corpus/` — 246 `.txt` filings + `manifest.json`.

---

## 1. Recommendations

A reader who stops here should still be able to build the right thing.

| # | Decision | Recommendation | One-line justification |
|---|---|---|---|
| 1 | **Preprocessing (do this first)** | Strip the inline-XBRL preamble by anchoring on the literal cover-page string `UNITED STATESSECURITIES AND EXCHANGE COMMISSION` | Removes **3,730,752 of 21,071,458 body tokens (17.7%)** of pure tag residue; works on 244/246 files ([§2.3](#23-inline-xbrl-residue--the-single-biggest-preprocessing-win)) |
| 2 | **Text reflow** | Re-insert block boundaries on the missing-space glue pattern `[.!?"]→[A-Z]` before any chunking | The HTML stripper emitted no block separators — Tesla's entire Item 1A is **one 79,624-char line**; without reflow there are no paragraph boundaries to split on ([§2.4](#24-the-corpus-has-almost-no-line-structure)) |
| 3 | **Section segmentation** | TOC-anchored, monotonic item alignment — not a bare regex | 20 distinct header-format profiles across 246 files; naive regex mis-segments and 30.7% of `Item N` mentions are cross-references, not headers ([§2.5](#25-item-headers-there-is-no-single-pattern)) |
| 4 | **Chunk unit** | **Item-scoped, per-item policy** (table in [§4.2](#42-the-per-item-chunking-policy-table)). Risk factors: one chunk per risk factor. Narrative: ~600–800 tokens. Financial statements: table-row-aligned or skip | Measured median 10-K Item 1A = 11,153 tokens containing ~20 individually sub-captioned risk factors → **~607 tokens per risk factor**, which is what makes ~600–800 the right *narrative* default ([§4.3](#43-risk-factors-the-rule-says-chunk-per-risk-factor)) |
| 5 | **Contextual prefix** | Mandatory. Prepend `company (ticker) — form, period — item` before embedding | **40.5% of 800-token chunks never name their company** and 96.6% never contain the ticker — dense similarity alone cannot attribute them ([§4.5](#45-contextual-enrichment-the-measurement-that-settles-it)) |
| 6 | **Metadata filtering** | Hard **pre-filter** on ticker/period/form, per entity, with per-entity retrieval quotas | Follows directly from #5: attribution must come from metadata, not from embedding space |
| 7 | **Sparse retriever** | BM25 (tune `b` and `k1`; do not accept defaults) | Corpus document length spans 20,626→396,452 tokens; `b` controls length normalisation and Robertson & Zaragoza state the model "provides no guidance" on these ([§5.1](#51-sparse-bm25-and-learned-sparse)) |
| 8 | **Dense embeddings** | `text-embedding-3-small` (1536d, 8192 max tokens, $0.02/1M) as baseline; evaluate `voyage-finance-2` as the domain challenger | Whole corpus embeds for **$0.35**; finance-domain model exists and is a fair test ([§5.3](#53-dense-embedding-models-first-party-specs)) |
| 9 | **Vector store** | Qdrant is a **good** choice, not a unique one. Weaviate, Milvus, Vespa, Elasticsearch and OpenSearch all do server-side hybrid fusion | Corrects the prior-art SPEC's "only mainstream OSS store" claim ([§5.4](#54-vector-store-comparison-native-hybrid--server-side-fusion)) |
| 10 | **Fusion** | RRF — but **fuse in application code if you want to sweep `k`** | Qdrant's default is **k=2**, Milvus's **k=100**, Elasticsearch's **60**; "k=60" is not portable, and `FusionQuery` in qdrant-client 1.19.0 exposes **no k parameter at all** ([§6.2](#62-k-is-not-portable-across-implementations)) |
| 11 | **Reranking** | Yes — cross-encoder, and it does **not** violate the one-call constraint. But pick the model around your chunk size | `bge-reranker-v2-m3` truncates at **512 tokens**, so it silently discards 36% of an 800-token chunk ([§6.4](#64-reranking-and-the-one-call-constraint)) |
| 12 | **Numeric questions** | Route to **XBRL facts**, not chunk retrieval | One HTTP call to `data.sec.gov` returns NVIDIA FY revenue exactly, with an accession number as citation ([§3.4](#34-the-architectural-fork-xbrl-facts-vs-chunk-retrieval)) |
| 13 | **Context ordering** | Put the highest-scoring chunk **first**, second-highest **last**, weakest in the middle | "Lost in the Middle" U-curve ([§8.1](#81-context-assembly-and-ordering)) |
| 14 | **Evaluation** | 40–60 question golden set + the ablation table in [§7.6](#76-the-ablation-table--the-artifact-that-proves-the-architecture). Add **entity coverage**, **item-section precision**, **temporal-scope correctness** — no library ships these | Standard recall@k hides total failure on multi-entity comparative questions ([§7.3](#73-the-three-domain-metrics-no-library-ships)) |
| 15 | **Query understanding** | Deterministic (regex + alias dictionary), no LLM rewriter | Preserves the one-call guarantee; costs recall on vocabulary-mismatch queries — measure that cost rather than assuming it away ([§8.3](#83-deterministic-query-understanding)) |
| 16 | **Payload schema** | **Typed, indexed core + one open `ext: {}` annex** — not one untyped blob | Untyped blobs lose typed filtering: OpenSearch `flat_object` doesn't support "Filtering by subfields" at all, and every store still needs per-path index declarations ([§9.4](#94-recommended-payload-schema)) |
| 17 | **Chunk payload text** | Store the chunk's own text + **`source_file`/`char_start`/`char_end` offsets**; keep full documents in a separate store | Duplicating full filing text into every chunk payload costs **8.81 GB vs 70 MB** — 125×, and 520 MB from the JPM 10-K alone ([§9.3](#93-the-cost-of-index-the-whole-thing-as-well)) |
| 18 | **Declare up front** | `tenant_id` (with `is_tenant`), `schema_version`, `chunker_version`, `embedding_model`, and every anticipated filterable field — even if null | Payload *values* are cheap to add later, but Qdrant states "Payload indexes should be created before ingesting data" and tenant co-location changes storage layout ([§9.3](#93-the-cost-of-index-the-whole-thing-as-well)) |
| 19 | **Reindex safety** | Point the app at a **collection alias** from day one | Alias switches are atomic — "no concurrent requests will be affected during the switch" — so any re-embed is a background build + swap, not an outage ([§9.5](#95-schema-versioning-and-migration)) |

**The one-line version of §9, since it corrects a common expectation:** an extensible payload future-proofs *filtering, display, grouping and entitlements*. It does **not** future-proof the retrieval representation — chunk boundaries, the contextual prefix, and the embedding model all sit behind a full re-embed. Keep raw text + offsets and use aliases so that re-embed is cheap ($0.35 here) rather than avoided.

---

## 2. Corpus profile — measured, not assumed

Everything downstream depends on this section. All numbers below were computed during this session with `tiktoken` 0.14.0, encoding `cl100k_base`, against `/Users/jordan/Developer/eliza/sec-rag/edgar_corpus/`.

> **Note on paths.** The sibling prior-art repo was **moved, not deleted** — it now lives at `/Users/jordan/Developer/rag-old/` (out of `eliza/`), most likely by a concurrent editor session. It is intact: clean `git status`, full history at `3b9579b`, and `src/`, `eval/`, `tests/`, `CLAUDE.md`, `README.md` and `PROMPT_LOG.md` all present. An earlier revision of this note said it had been deleted; that was wrong and is corrected here. Corpus measurements were re-run against `sec-rag/edgar_corpus/` and are byte-identical (246 body files, 21,095,970 tokens).

### 2.1 `manifest.json` schema

Seven top-level keys:

```json
{
  "corpus": "SEC EDGAR 10-K and 10-Q Filings",
  "description": "Annual (10-K) and quarterly (10-Q) reports from 54 major US public
                  companies across technology, financial services, healthcare, consumer,
                  energy, and industrial sectors. 15 companies have full quarterly
                  coverage for 2023-2025.",
  "file_count": 246,
  "filing_types": { "10-K": 89, "10-Q": 157 },
  "files": [ "AAPL_10K_2022Q3_2022-10-28_full.txt", ... ],   // 246 strings
  "license": "Public domain (SEC filings are US government documents)",
  "source": "https://www.sec.gov/edgar/"
}
```

The manifest is **exactly consistent** with the directory: zero files in the manifest missing from disk, zero files on disk missing from the manifest. The "247 files" figure in the task brief is 246 `.txt` + `manifest.json` itself.

**The manifest carries no per-file metadata** — it is a flat filename list. All company/period/form metadata must be parsed from the filename or the per-file header (§2.2). That is a small ingest task, but it means the manifest cannot be the source of truth for the retrieval filter dictionary.

### 2.2 Files are HTML-stripped plain text with a prepended custom header

Not raw HTML, and **not** SGML-wrapped EDGAR submissions — there is no `<SEC-DOCUMENT>` or `<TYPE>` header. Instead each file opens with a fixed key–value block followed by a `=`×60 separator:

```
Company: Apple Inc
Ticker: AAPL
Filing Type: 10-K (Annual Report)
Filing Date: 2024-11-01
Report Period: 2024-09-28
Quarter: 2024Q3
CIK: 0000320193
Source: SEC EDGAR
URL: https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm
============================================================
```

Header field census across all 246 files:

| Field | Present in |
|---|---|
| `Company`, `Ticker`, `Filing Type`, `Filing Date`, `CIK`, `Source`, `URL` | 246 / 246 |
| `Report Period`, `Quarter` | **192 / 246** |

So 54 files have an 8-line header and 192 have a 10-line header. **Do not parse by line offset** — split on the `=+` separator. The 54 files missing `Report Period`/`Quarter` need fiscal period derived from the filename date or from the `URL` field (which embeds the period, e.g. `aapl-20240928.htm`).

This header block is a gift: it gives you `company`, `ticker`, `cik`, `form_type`, `filing_date`, `period_end` and the canonical SEC URL for citation, for free, with no inference.

### 2.3 Inline-XBRL residue — the single biggest preprocessing win

Immediately after the separator, nearly every file contains a colossal run of concatenated inline-XBRL context strings with almost no whitespace:

```
aapl-20240928false2024FY0000320193P1YP1YP1YP1Yhttp://fasb.org/us-gaap/2024#Marketable
SecuritiesCurrent http://fasb.org/us-gaap/2024#MarketableSecuritiesNoncurrenthttp://
fasb.org/us-gaap/2024#LongTermDebtCurrent ...
```

Measured, on the file body (after the header separator):

| Metric | Value |
|---|---|
| Files whose leading body block is XBRL residue | 224 / 246 detected on the first non-blank line; the remaining 22 have it on line 2–3 (behind a bare `10-K` line) — effectively **all 246** |
| Residue block, chars | min 21 · median 29,557 · p90 95,652 · **max 285,080** |
| Residue block, cl100k tokens | min 10 · median 9,930 · p90 34,843 · **max 86,721** (`BAC_10K_2025-02-25`) |
| Corpus body tokens before strip | 21,071,458 |
| Corpus body tokens after strip | 17,340,706 |
| **Reduction** | **3,730,752 tokens — 17.7%** |

The strip is a one-liner: the residue is glued directly onto the start of the real cover page, so you cannot drop a line — you cut at the cover-page anchor.

```python
m = re.search(r'UNITED\s*STATES\s*SECURITIES AND EXCHANGE COMMISSION', body)
body = body[m.start():] if m else body
```

This anchor is found in **244 / 246** files. The two misses need a fallback (e.g. cut at the first `FORM 10-[KQ]` occurrence).

Why this matters beyond token cost: at 800 tokens/chunk, the BAC 10-K residue alone would generate **~108 chunks of pure XBRL tag soup**, all of which are near-duplicates of each other and of the residue in every other BAC filing. They pollute BM25 term statistics, they waste embedding spend, and they are exactly the kind of thing that surfaces in a live demo.

Note the *aggregate* URI-only measurement is small — literal `http://…` URIs are only 209,757 chars (0.26%) of the corpus — because most of the residue is concatenated numeric contexts and tag names, not URIs. Measure the block, not the URIs.

### 2.4 The corpus has almost no line structure

This is the finding that most changes the chunker design.

| Metric | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| chars per file | 71,648 | 178,068 | 271,638 | 422,331 | 1,500,683 |
| non-blank lines per file | 267 | 609 | 884 | 1,260 | 5,136 |
| **longest single line (chars)** | 2,194 | 29,189 | **51,464** | 92,742 | **287,855** |
| median line (chars) | 28 | 63 | 68 | 74 | 93 |

- **216 / 246 files contain at least one line longer than 20,000 characters.**
- **222 / 246 files have fewer than 2,000 non-blank lines** despite a median of 271,638 characters.

The HTML-to-text conversion inserted **no separator at block boundaries**. Concretely, Tesla's entire Item 1A section is a single line of 79,624 characters. Apple's 10-K has a 95,328-char line.

The practical consequence: `RecursiveCharacterTextSplitter`-style splitting on `["\n\n", "\n", " ", ""]` will fall straight through the paragraph and line separators and split on **spaces**, mid-sentence, for most of the corpus.

**Block boundaries are recoverable**, because the stripper's omission is itself a signal: where a block boundary was, a sentence-final character now abuts a capital with no space. Splitting Tesla's Item 1A on `(?<=[.!?"])(?=[A-Z"])` recovers **81 blocks** (median 747 chars, p90 2,402). Two guards are required:

- **Abbreviations**: `U.S.` splits into `…in U.` / `S. dollar would…`. Guard with an abbreviation list (`U.S`, `Inc`, `Corp`, `No`, `e.g`, `i.e`, …).
- **Heading run-ons**: group headings glue to the first body word without punctuation — `Risks Related to Government Laws and RegulationsDemand for our products…`. This needs a second lowercase→Uppercase split rule.

With both guards, this is the reflow step recommended as decision #2.

### 2.5 Item headers: there is no single pattern

Five distinct body-header forms occur in this corpus. Real excerpts:

**A — pipe form** (Amazon, body header; note *no* trailing page number):
```
Item 1A. | Risk Factors
```

**A′ — pipe form, table of contents** (identical except a trailing page number — this is the discriminator):
```
Item 1A. | Risk Factors | 6
```

**B — glued, 2+ spaces** (Apple; page furniture wedged in front of the header):
```
Item 6.    [Reserved]Apple Inc. | 2024 Form 10-K | 20Item 7.    Management's Discussion and Analysis of Financial Condition and Results of Operations
```

**C — ALL CAPS** (Tesla):
```
...is not incorporated by reference into this Annual Report on Form 10-K.ITEM 1A. RISK FACTORS You should carefully consider the risks described below...
```

**D — zero spaces** (Alphabet, Meta):
```
    FINANCIAL INFORMATIONITEM 1.FINANCIAL STATEMENTSAlphabet Inc.CONSOLIDATED BALANCE
enses.27Table of ContentsItem 2.Management's Discussion and Analysis of Financial Cond
```

**E — em-dash / colon** — but see the warning below.

Clustering all 246 files by which forms they contain yields **20 distinct format profiles**. The largest:

| Files | Profile |
|---|---|
| 64 | pipe-TOC + ALLCAPS |
| 31 | pipe-TOC + 1-space + ALLCAPS |
| 30 | pipe-TOC + 1-space |
| 20 | 1-space + dash + ALLCAPS |
| 18 | pipe-TOC only |
| 16 | pipe-TOC + glued-2-space (all Apple) |
| 14 | pipe-TOC + glued-2-space + 1-space |
| … | 13 further profiles |
| **1** | **no pattern at all** (`MS_10K_2026-02-19`) |

Corpus-wide anchor counts: pipe-TOC 2,989 hits in 190 files; ALLCAPS 2,099 in 135; 1-space 1,558 in 135; glued-2-space 431 in 42; dash 278 in 45; zero-space 15 in 15; `PART I`/`PART II` 1,432 in 187.

#### The two false-positive traps

**Trap 1 — cross-references.** Of **10,075** `Item N` mentions corpus-wide, **3,088 (30.7%)** are preceded by a cross-reference cue (`see`, `in`, `under`, `Part II,`, `discussed in`, …). The em-dash form is almost *entirely* cross-references:

```
See Item 1 — Federal Communications Commission Regulation.
As discussed in further detail in Item 1A – Risk Factors, the Company faces...
```

Most cross-referenced: Item 8 (724), Item 1A (589), Item 1 (586), Item 7 (298). A segmenter that treats these as boundaries will shred MD&A.

**Trap 2 — Regulation S-K item numbers.** `INTC_10K_2026-01-23` yields exactly one `Item N` match, and it is not a header:

```
been omitted pursuant to Item 601(a)(5)-(6) and Item 601(b)(10)(iv) of Regulation S-K.
```

85 such `Item 6xx(` citations exist corpus-wide. Filter item numbers > 16.

#### What actually works

Combining (a) all five header forms, (b) TOC discrimination via the trailing-page-number test, (c) cross-reference rejection, (d) Reg S-K number rejection, (e) `PART` tracking, and (f) a **longest monotonically-increasing subsequence** over the canonical item order:

- Segmentation failures drop to **1 / 246** (`MS_10K_2026-02-19`, which genuinely retains no item headers post-stripping — only cross-references like "Part II, Item 7").
- 10-K: median **18 of 23** items recovered (median coverage 78%).
- 10-Q: median **5 of 11** items recovered (median coverage 45%).

**Be honest about this in the build.** Item recovery is good for the big narrative sections and mediocre for the small ones. When a boundary is missed, the preceding section absorbs everything up to the next detected header — which is why an unfiltered measurement showed "Item 4 Mine Safety" at a median of 948 tokens and "Item 16 Form 10-K Summary" at a p90 of 51,200. The numbers in §4.2 are therefore restricted to spans where *both* boundaries were found and are adjacent in canonical order.

### 2.6 The 10-Q Part I / Part II item collision, as it appears here

`AAPL_10Q_2025Q2_2025-08-01_full.txt`, lines 34–46 — the pipe TOC, verbatim:

```
Part I
Item 1. | Financial Statements | 1
Item 2. | Management's Discussion and Analysis of Financial Condition and Results of Operations | 13
Item 3. | Quantitative and Qualitative Disclosures About Market Risk | 19
Item 4. | Controls and Procedures | 19
Part II
Item 1. | Legal Proceedings | 20
Item 1A. | Risk Factors | 21
Item 2. | Unregistered Sales of Equity Securities and Use of Proceeds | 21
Item 3. | Defaults Upon Senior Securities | 21
Item 4. | Mine Safety Disclosures | 21
Item 5. | Other Information | 21
Item 6. | Exhibits | 22
```

Items **1, 2, 3 and 4 each appear twice with entirely different meanings.** In the body:

```
PART I  —  FINANCIAL INFORMATIONItem 1.    Financial StatementsApple Inc.CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)
```

**125 of 157 10-Q files** exhibit the ≥2×`Item 1.` + ≥1×`Item 1A.` signature.

**Implication for the parser:** the item key for a 10-Q must be `(part, item)`, never `item`. A parser keyed on `item` alone will merge Apple's *Financial Statements* with its *Legal Proceedings* and label the result "Item 1". For a diligence system, that is a correctness bug that produces confidently mis-sectioned citations. Track `PART` state while scanning; the `PART I`/`PART II` markers are present in 187/246 files, and for the rest the canonical ordering constraint disambiguates (Part II items follow Part I items).

### 2.7 Tables survive, and they are usable

This was the pleasant surprise. **Tables are preserved as pipe-delimited rows, one row per line, with row labels intact.** `AAPL_10K_2024Q3`, lines 77–83, verbatim:

```
| 2024 |  | Change |  | 2023 |  | Change |  | 2022
Americas | $ | 167,045 |  |  | 3 | % |  | $ | 162,560 |  |  | (4) | % |  | $ | 169,658 |
Europe | 101,328 |  |  | 7 | % |  | 94,294 |  |  | (1) | % |  | 95,118 |
Greater China | 66,952 |  |  | (8) | % |  | 72,559 |  |  | (2) | % |  | 74,200 |
Japan | 25,052 |  |  | 3 | % |  | 24,257 |  |  | (7) | % |  | 25,977 |
Rest of Asia Pacific | 30,658 |  |  | 4 | % |  | 29,615 |  |  | 1 | % |  | 29,375 |
Total net sales | $ | 391,035 |  |  | 2 | % |  | $ | 383,285 |  |  | (3) | % |  | $ | 394,328 |
```

Corpus-wide: **2,138,613 pipe characters**; all 246 files contain them; only 19 files contain a tab.

| Line class | Lines | Chars | Share of corpus chars |
|---|---|---|---|
| pipe-table rows (≥2 pipes) | 214,628 | 18,012,958 | **22.2%** |
| narrative | 60,605 | 63,066,365 | 77.8% |

Empty padding cells (from HTML `colspan`/`rowspan`) account for 2,284,184 chars — 12.7% of table chars, 2.8% of the corpus. Collapsing runs of `|  |` is cheap and improves readability materially.

**Two real defects, both fixable, both important:**

1. **The header row has no row label.** Line 77 is `| 2024 |  | Change |  | 2023 | …`. Split between line 76 and 77 and the numbers lose their years.
2. **The caption and units are glued to the end of the *previous* narrative line.** Line 76 ends `…The following table shows net sales by reportable segment for 2024, 2023 and 2022 (dollars in millions):`. Split there and the table loses both its subject *and* its scale — `391,035` with no "millions" is worse than useless in a diligence memo.

**Recommendation:** table handling is *worth the effort here*, and it is cheap. Do not attempt full table→structured-data extraction. Do this instead:
- Detect a maximal run of consecutive pipe-table lines as one **table block**.
- Attach the trailing sentence of the preceding narrative block (the caption + units) as a prefix.
- Never split inside a table block; if a block exceeds the chunk budget, repeat the caption and the header row on each part.

That is a table-aware chunker in perhaps 40 lines, and it is the difference between a citable number and a naked integer.

### 2.8 Boilerplate census

| Pattern | Occurrences | Files |
|---|---|---|
| `Table of Contents` page furniture | 7,850 | 205 / 246 |
| `Inline XBRL` exhibit boilerplate | 1,125 | 225 / 246 |
| Auditor's report header | 312 | 105 / 246 |
| Signature block (`Pursuant to the requirements…`) | 270 | 242 / 246 |
| Forward-looking safe-harbour (`Private Securities Litigation Reform Act of 1995`) | 160 | 149 / 246 |
| `EXHIBIT INDEX` / `Index to Exhibits` | 141 | 78 / 246 |
| Page header/footer stamps (`Apple Inc. \| 2024 Form 10-K \| 20`) | 569 | — |

The page stamps are only ~8,000 tokens corpus-wide — **strip them for parse correctness, not for token savings.** They wedge themselves between a section's end and the next item header (`[Reserved]Apple Inc. | 2024 Form 10-K | 20Item 7.`), which is precisely what breaks naive header regexes. Same for `Table of Contents`, which glues in front of headers as `enses.27Table of ContentsItem 2.Management's…`.

### 2.9 Corpus composition — and a coverage warning for the demo

54 distinct tickers, but the distribution is severely long-tailed:

```
JNJ:17  DIS:17  XOM:16  TSLA:16  NVDA:16  MSFT:16  AMZN:16  AAPL:16
UNH:15  PFE:15  KO:15  GOOG:14  META:8  JPM:4  BAC:4  PEP:2  MCD:2
…and 37 tickers with exactly 1 filing each
```

Filing-date year histogram: 2015:**1**, 2022:37, 2023:50, 2024:52, 2025:79, 2026:27.

Two things to flag before the demo:

- **`GE_10K_2015-02-27_full.txt` is a 2015 filing** in a corpus described as 2022–2026. It is a genuine outlier — either exclude it or make sure a temporal filter cannot silently pull it into a "last two years" answer.
- **The representative questions are unevenly supported.** "Risk factors facing Apple, Tesla, and JPMorgan, compared" pits AAPL (16 filings) and TSLA (16) against **JPM (4)**. "Regulatory risks facing major pharmaceutical companies" resolves to JNJ (17) and PFE (15) plus ABBV, MRK, LLY, TMO at **one filing each**. "NVIDIA's revenue outlook over the last two years" is well supported (16 filings).

This asymmetry is exactly why per-entity retrieval quotas (decision #6) matter, and it is worth stating out loud in the demo rather than being caught by it: the system should report *which* entities it had thin coverage for.

### 2.10 Token budget summary

| Metric | Value |
|---|---|
| Total corpus tokens (whole files, cl100k) | **21,095,970** |
| Per-file tokens | p25 44,980 · **median 73,057** · p75 100,753 · p90 152,648 · max 396,452 |
| Body tokens after XBRL strip | **17,340,706** |
| chars per token (median) | **3.84** — so `chars/4` under-counts by ~4% |

Largest files are all banks: `JPM_10K_2026` (396,452 tokens), `GS_10K_2025`, `BAC_10K_2025`, `MS_10K_2026`. Smallest are Apple 10-Qs (~20,600 tokens).

---

## 3. EDGAR document structure, from the regulator

> **Fetch note.** `www.sec.gov` and `www.ecfr.gov` both reject the default WebFetch user-agent (HTTP 403 / redirect to an unblock interstitial). I retrieved these with `curl` using a declared User-Agent, and via the eCFR renderer API. Quotes below are from those retrieved documents.
>
> SEC enforces a rate limit: sustained requests return `403 SEC.gov | Request Rate Threshold Exceeded`, and that interstitial directs callers to `www.sec.gov/developer` for "Fair Access guidelines". **I observed this behaviour directly but was rate-limited out of reading the guidelines page itself** — so build your ingest with a declared User-Agent and conservative pacing, and read the current policy there before running anything at volume.

### 3.1 Form 10-K — authoritative item list with Regulation S-K mapping

From [Form 10-K](https://www.sec.gov/files/form10-k.pdf) (the form's own text and its S-K cross-references):

| Part | Item | Title (verbatim) | Reg S-K |
|---|---|---|---|
| I | 1 | Business | [229.101](https://www.ecfr.gov/current/title-17/section-229.101) |
| I | 1A | Risk Factors | [229.105](https://www.ecfr.gov/current/title-17/section-229.105) |
| I | 1B | Unresolved Staff Comments | — |
| I | 1C | Cybersecurity | [229.106](https://www.ecfr.gov/current/title-17/section-229.106) |
| I | 2 | Properties | 229.102 |
| I | 3 | Legal Proceedings | [229.103](https://www.ecfr.gov/current/title-17/section-229.103) |
| I | 4 | Mine Safety Disclosures | 229.104 |
| II | 5 | Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities | 229.201, 229.701, 229.703 |
| II | 6 | [Reserved] | — |
| II | 7 | Management's Discussion and Analysis of Financial Condition and Results of Operations | [229.303](https://www.ecfr.gov/current/title-17/section-229.303) |
| II | 7A | Quantitative and Qualitative Disclosures About Market Risk | 229.305 |
| II | 8 | Financial Statements and Supplementary Data | 229.302 (+ Reg S-X) |
| II | 9 | Changes in and Disagreements With Accountants on Accounting and Financial Disclosure | 229.304(b) |
| II | 9A | Controls and Procedures | 229.307, 229.308 |
| II | 9B | Other Information | 229.408(a) |
| II | 9C | Disclosure Regarding Foreign Jurisdictions that Prevent Inspections | — |
| III | 10 | Directors, Executive Officers and Corporate Governance | 229.401, .405, .406, .407(c)(3),(d)(4),(d)(5), .408(b) |
| III | 11 | Executive Compensation | 229.402, 229.407(e)(4),(e)(5) |
| III | 12 | Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters | 229.201(d), 229.403 |
| III | 13 | Certain Relationships and Related Transactions, and Director Independence | 229.404, 229.407(a) |
| III | 14 | Principal Accountant Fees and Services | — |
| IV | 15 | Exhibits and Financial Statement Schedules | 229.601 |
| IV | 16 | Form 10-K Summary | — |

### 3.2 Form 10-Q — and the Part I/Part II collision, authoritatively

From [Form 10-Q](https://www.sec.gov/files/form10-q.pdf):

| Part | Item | Title (verbatim) | Reg S-K |
|---|---|---|---|
| **I — Financial Information** | 1 | Financial Statements. | — (Reg S-X) |
| I | 2 | Management's Discussion and Analysis of Financial Condition and Results of Operations. | 229.303 |
| I | 3 | Quantitative and Qualitative Disclosures About Market Risk. | 229.305 |
| I | 4 | Controls and Procedures. | 229.307, 229.308(c) |
| **II — Other Information** | 1 | Legal Proceedings. | 229.103 |
| II | 1A | Risk Factors. | (see below) |
| II | 2 | Unregistered Sales of Equity Securities and Use of Proceeds. | 229.701, 229.703 |
| II | 3 | Defaults Upon Senior Securities. | — |
| II | 4 | Mine Safety Disclosures. | 229.104 |
| II | 5 | Other Information. | 229.407(c)(3), 229.408(a) |
| II | 6 | Exhibits. | 229.601 |

**Items 1, 2, 3 and 4 exist in both Parts with unrelated meanings.** Part I Item 1 is *Financial Statements*; Part II Item 1 is *Legal Proceedings*. Part I Item 4 is *Controls and Procedures*; Part II Item 4 is *Mine Safety Disclosures*. This is not a quirk of the corpus — it is the form.

Form 10-Q Item 1A, verbatim:

> "Set forth any **material changes** from risk factors as previously disclosed in the registrant's Form 10-K (§249.310) in response to Item 1A. to Part 1 of Form 10-K. Smaller reporting companies are not required to provide the information required by this item."

This single sentence has a large architectural consequence, discussed in §4.4.

### 3.3 Which items carry diligence signal

Combining the rule text with the measured section sizes from §4.2:

**High signal — index these carefully.**
- **Item 1A Risk Factors** (10-K). The comparative-question workhorse. Median 11,153 tokens.
- **Item 7 MD&A** (10-K) / **Part I Item 2** (10-Q). Median 10,280 / 10,405 tokens. [17 CFR 229.303](https://www.ecfr.gov/current/title-17/section-229.303) structures it as `(a) Objective`, `(b) Full fiscal years` → `(1) Liquidity and capital resources`, `(2) Results of operations`, `(3) Critical accounting estimates`, and `(c) Interim periods` → `(1) Material changes in financial condition`, `(2) Material changes in results of operations`. Those sub-headings are good secondary split points.
- **Item 1 Business**. Segments, competition, regulatory landscape. Median 4,568 tokens but p90 15,030 — highly variable.
- **Item 1C Cybersecurity**. Small (median 1,012 tokens) but dense and directly diligence-relevant; [229.106](https://www.ecfr.gov/current/title-17/section-229.106) structures it as `(a) Definitions`, `(b) Risk management and strategy`, `(c) Governance`, `(d) Structured Data Requirement`.
- **Item 8 Financial Statements**. Largest section by far (median 32,034, p90 72,610 tokens). Mostly tables + notes. See §3.4 — much of what people ask of this is better served by XBRL.

**Near-worthless for retrieval — measured medians confirm the rule.**
- **Item 3 Legal Proceedings**: median **57 tokens**. [17 CFR 229.103](https://www.ecfr.gov/current/title-17/section-229.103) explicitly permits it: *"Information may be provided by hyperlink or cross-reference to legal proceedings disclosure elsewhere in the document, such as in Management's Discussion & Analysis (MD&A), Risk Factors and notes to the financial statements."* So Item 3 is usually a pointer. **Chase the pointer at index time or accept that legal-proceedings questions must hit Item 1A/Item 8 instead.**
- **Item 1B Unresolved Staff Comments**: median **14 tokens** ("None.").
- **Item 4 Mine Safety**: median **21 tokens**. Irrelevant for all 54 issuers here.
- **Item 9 Changes in/Disagreements with Accountants**: median **26 tokens**.
- **Items 10–14**: medians 250 / 60 / 64 / 57 / 64 tokens — almost universally incorporated by reference from the proxy statement, which is **not in this corpus**. Do not index; do answer "not in corpus" when asked about executive compensation.
- **Item 9B Other Information**: median 96 tokens.
- 10-Q **Part II Items 3 and 4**: medians **12 and 13 tokens**.

### 3.4 The architectural fork: XBRL facts vs chunk retrieval

The SEC publishes structured financial data that makes numeric questions a solved problem — and it is a genuinely better answer path than chunk retrieval for a large class of the questions this system will be asked.

Per the [EDGAR APIs page](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):

> "`data.sec.gov` was created to host RESTful data APIs delivering JSON-formatted data… These APIs do not require any authentication or API keys to access."

| Endpoint | URL template | Returns |
|---|---|---|
| Submissions | `https://data.sec.gov/submissions/CIK##########.json` | filing history, former names, tickers, exchanges |
| Company concept | `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/{Tag}.json` | every reported value of one tag for one company, all periods |
| Company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | all concepts for one company |
| Frames | `https://data.sec.gov/api/xbrl/frames/us-gaap/{Tag}/USD/CY####Q#.json` | one fact for **every** reporting entity in a period |

Bulk downloads exist (`companyfacts.zip`, `submissions.zip`), "recompiled nightly", and the JSON structures are "updated throughout the day, in real time, as submissions are disseminated." Also documented: `data.sec.gov` does **not** support CORS — so a browser front-end cannot call it directly; proxy it.

I verified this end-to-end. One call to `companyconcept/CIK0001045810/us-gaap/Revenues.json` returned 276 facts; the annual 10-K series:

| Fiscal period (`start`→`end`) | Revenue | `frame` | `accn` (citation handle) |
|---|---|---|---|
| 2023-01-30 → 2024-01-28 | $60,922,000,000 | CY2023 | 0001045810-26-000021 |
| 2024-01-29 → 2025-01-26 | $130,497,000,000 | CY2024 | 0001045810-26-000021 |
| 2025-01-27 → 2026-01-25 | $215,938,000,000 | CY2025 | 0001045810-26-000021 |

**"How has NVIDIA's revenue changed over the last two years?" is answered exactly, with an accession number for citation, by one HTTP request and zero embeddings.** Compare that to the text path: find the right MD&A chunk, hope the revenue table wasn't split from its caption, hope the model transcribes a 9-digit number from a pipe-delimited row correctly, and have no way to verify it beyond string-matching.

**Recommendation:** treat this as a **router**, not a replacement. Deterministically classify the question; send *quantitative* questions ("revenue", "margin", "how much", "grew by") down an XBRL-facts path that formats exact figures into the single prompt, and send *qualitative* questions ("risk factors", "how are they addressing", "compare their strategy") down the chunk-retrieval path. Both feed the same one LLM call, so the constraint is preserved.

Two traps I hit while verifying:
- The `fy` field is the **filing's** fiscal-year label, not the fact's period. Three different periods above all carry `fy: 2026`. Key on `start`/`end`/`frame`, never `fy`.
- The frames API aligns to calendar quarters (`CY####Q#`, ±30 days) and the docs warn: *"Data users should be mindful different reporting start and end dates for facts contained in a frame."* For cross-company comparison at a point in time that is a real caveat — Apple's FY ends in September.

Also relevant and **unverified**: the [Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets) (quarterly `num.txt`/`sub.txt`/`pre.txt`/`tag.txt` bulk files) and the EDGAR full-text search API (`efts.sec.gov/LATEST/search-index?q=…`). I could not retrieve either page — sec.gov rate-limited me (HTTP 403 "Request Rate Threshold Exceeded") on the retry batch. The XBRL REST APIs above cover the same need for this project, so I did not push further.

---

## 4. Chunking strategy

### 4.1 Principles that follow from §2

1. **Never chunk before reflowing.** With no block separators, a recursive splitter degenerates to splitting on spaces (§2.4).
2. **Never chunk across an item boundary.** A chunk spanning Item 1A→Item 1B is unlabelable, and its `item_section` metadata will be wrong — which corrupts both filtering and citation.
3. **Never split a table from its caption or its header row** (§2.7).
4. **Chunk size is a per-item decision, not a global one.** Item 1A is a list of independent titled risks; Item 7 is flowing argument with embedded tables; Item 8 is tabular; Items 1B/3/4/9/13 are one-liners. One global size is wrong for all of them.

### 4.2 The per-item chunking policy table

Sizes are cl100k tokens, measured over spans where **both** boundaries were detected and adjacent in canonical order (see the caveat in §2.5). `n` is the number of clean spans measured.

#### Form 10-K

| Item | n | p10 | **p50** | p90 | Policy | Target chunk | Overlap | Split preference |
|---|---|---|---|---|---|---|---|---|
| 1 Business | 43 | 46 | **4,568** | 15,030 | **Chunk** | 800 | 10% | reflowed block → sub-heading |
| 1A Risk Factors | 62 | 5,109 | **11,153** | 19,528 | **Chunk per risk factor** | 1 risk factor (~600; split >1,500) | 0 (self-contained) | risk-factor subcaption |
| 1B Unresolved Staff Comments | 51 | 11 | **14** | 48 | **Skip** | — | — | — |
| 1C Cybersecurity | 48 | 34 | **954** | 1,553 | **Chunk whole, don't split** | whole section | — | 229.106 (b)/(c) if >1,200 |
| 2 Properties | 62 | 56 | **312** | 799 | Chunk whole | whole section | — | — |
| 3 Legal Proceedings | 74 | 29 | **57** | 690 | **Index but expect a pointer** | whole section | — | — |
| 4 Mine Safety | 28 | 17 | **21** | 927 | **Skip** | — | — | — |
| 5 Market for Common Equity | 27 | 30 | **697** | 984 | Chunk whole (mostly boilerplate + buyback table) | whole section | — | table-aware |
| 6 [Reserved] | 46 | 9 | **14** | 56 | **Skip** | — | — | — |
| 7 MD&A | 47 | 37 | **10,280** | 25,479 | **Chunk** | 800 | 15% | 229.303 sub-heading → table block → reflowed block |
| 7A Market Risk | 53 | 45 | **493** | 1,920 | Chunk whole if <1,200, else 800 | 800 | 10% | table-aware |
| 8 Financial Statements | 54 | 23 | **32,034** | 72,610 | **Table-aware chunk; consider XBRL instead** | table block, or 1,000 for notes | 0 across tables | note heading → table block |
| 9 Acct. Disagreements | 54 | 20 | **26** | 31 | **Skip** | — | — | — |
| 9A Controls & Procedures | 69 | 203 | **513** | 1,299 | Chunk whole | whole section | — | — |
| 9B Other Information | 64 | 12 | **96** | 523 | Skip unless >200 tokens | — | — | — |
| 9C Foreign Jurisdictions | 31 | 23 | **29** | 37 | **Skip** | — | — | — |
| 10 Directors & Governance | 33 | 20 | **250** | 511 | **Skip** (incorporated by reference) | — | — | — |
| 11 Exec Compensation | 73 | 28 | **60** | 144 | **Skip** (incorporated by reference) | — | — | — |
| 12 Security Ownership | 72 | 44 | **64** | 470 | **Skip** | — | — | — |
| 13 Related Transactions | 80 | 35 | **57** | 101 | **Skip** | — | — | — |
| 14 Accountant Fees | 35 | 20 | **64** | 4,427 | Skip | — | — | — |
| 15 Exhibits | 32 | 57 | **2,622** | 5,676 | **Skip** (exhibit index) | — | — | — |
| 16 Form 10-K Summary | — | — | — | — | Skip | — | — | — |

#### Form 10-Q

| Part-Item | n | p10 | **p50** | p90 | Policy | Target chunk | Overlap |
|---|---|---|---|---|---|---|---|
| I-1 Financial Statements | 46 | 209 | **18,736** | 28,653 | Table-aware; or XBRL | table block / 1,000 for notes | 0 across tables |
| I-2 MD&A | 49 | 24 | **10,405** | 15,255 | **Chunk — primary quarterly signal** | 800 | 15% |
| I-3 Market Risk | 104 | 22 | **91** | 825 | Chunk whole (usually "no material change") | whole | — |
| I-4 Controls & Procedures | 50 | 152 | **334** | 2,754 | Chunk whole | whole | — |
| II-1 Legal Proceedings | 44 | 26 | **34** | 26,842 | Chunk whole if small; chunk at 800 if large | adaptive | 10% |
| II-1A Risk Factors | 74 | 87 | **876** | 12,527 | **Chunk per risk factor; tag as a DELTA** | 1 risk factor | 0 |
| II-2 Unregistered Sales | 26 | 19 | **24** | 475 | Skip | — | — |
| II-3 Defaults | 30 | 12 | **12** | 17 | **Skip** | — | — |
| II-4 Mine Safety | 35 | 13 | **13** | 16 | **Skip** | — | — |
| II-5 Other Information | 50 | 16 | **107** | 523 | Skip unless >200 tokens | — | — |
| II-6 Exhibits | — | — | — | — | **Skip** | — | — |

**Skipping is not laziness — it is precision.** The skipped items are dominated by "None.", "Not applicable." and "incorporated by reference". Indexing 246 near-identical "None." chunks creates a cluster of mutually-near-duplicate vectors that will surface on any vague query and crowd out real content.

### 4.3 Risk factors: the rule says chunk per risk factor

[17 CFR 229.105(a)](https://www.ecfr.gov/current/title-17/section-229.105), verbatim:

> "Where appropriate, provide under the caption 'Risk Factors' a discussion of the material factors that make an investment in the registrant or offering speculative or risky. **This discussion must be organized logically with relevant headings and each risk factor should be set forth under a subcaption that adequately describes the risk.** The presentation of risks that could apply generically to any registrant or any offering is discouraged, but to the extent generic risk factors are presented, disclose them at the end of the risk factor section under the caption 'General Risk Factors.'"

And 229.105(b):

> "Concisely explain how each risk affects the registrant or the securities being offered. **If the discussion is longer than 15 pages, include in the forepart of the prospectus or annual report, as applicable, a series of concise, bulleted or numbered statements that is no more than two pages summarizing the principal factors** that make an investment in the registrant or offering speculative or risky."

Amended `[85 FR 63761, Oct. 8, 2020]` — so the 2020 amendment and the 15-page summary trigger are both confirmed.

**Three things follow.**

1. **The natural chunk unit is the individual risk factor, not a fixed token window.** The regulation mandates that each risk be a self-contained, titled unit. A 229.105-compliant risk factor is *definitionally* a coherent retrieval unit: it has a topic sentence (the subcaption), a mechanism, and a consequence. A fixed 800-token window slices across two or three of them and produces chunks whose embedding is an average of unrelated risks.

2. **Corpus evidence supports it, with a caveat.** Applying the reflow of §2.4 to clean Item 1A spans:

   | | 10-K Item 1A (n=57) | 10-Q Part II Item 1A (n=41) |
   |---|---|---|
   | section tokens (p50) | 11,823 | 10,239 |
   | blocks recovered (p50) | 78 | 36 |
   | **heading-like blocks ≈ risk factors (p50)** | **20** | **6** |
   | **implied tokens per risk factor** | p10 234 · **p50 607** · p90 1,706 | p10 599 · **p50 993** · p90 1,848 |

   The median risk factor is ~607 tokens. That is *why* ~600–800 works as a narrative default: it is not a magic number, it is an approximation of the median risk factor. Where the two diverge — the p90 at 1,706 tokens — the per-risk-factor unit is strictly better, and the fixed window is strictly worse.

   **Caveat, stated plainly:** my heading detector is a heuristic and it under-counts (p10 of only 5 headings for a section with a p10 of 37 blocks). Note also the rule says headings "**must**" be used but each risk "**should**" be under a subcaption — permissive language, which is consistent with imperfect detectability. Recommended design: use per-risk-factor chunking with a **fallback** to a ~800-token window whenever the detected heading count is implausibly low for the section size (e.g. fewer than one heading per 2,000 tokens).

3. **The 15-page summary is rarely present here.** Only **9 of 89 10-Ks** (and 15 of 246 filings) contain a "Summary of Risk Factors"-style heading. So do not build the summary into the critical path — but where it exists it is an excellent, pre-written, high-density chunk. Index it and boost it.

### 4.4 The 10-Q risk-factor trap — a correctness issue for temporal questions

Form 10-Q Item 1A requires only *"any **material changes** from risk factors as previously disclosed in the registrant's Form 10-K"* (§3.2). This is confirmed by the corpus: 10-Q Part II Item 1A has a median of **876 tokens** against the 10-K's **11,153**.

The consequence is sharp and it is the kind of thing that produces a wrong answer that looks right:

> **A question like "how have Apple's risk factors changed over the last two years" cannot be answered from 10-Qs alone.** A 10-Q's Item 1A is a *diff* against a baseline that lives in a different document. Retrieve the diff without the baseline and the model will present an incremental amendment as if it were the company's complete risk profile.

**Recommendation:** tag every chunk with `disclosure_type: baseline | delta`. For any temporal question, the retriever must fetch the governing 10-K baseline alongside any 10-Q deltas, and the prompt must state which is which. Mirror this for MD&A — [229.303(c)](https://www.ecfr.gov/current/title-17/section-229.303) requires only *"Material changes in financial condition"* and *"Material changes in results of operations"* for interim periods.

This is, in my view, the single most under-appreciated correctness risk in the whole design, and it is invisible to recall@k.

### 4.5 Contextual enrichment: the measurement that settles it

I tested whether chunks self-identify. Fixed 800-token chunks over the whole corpus (21,793 chunks):

| Chunk contains… | Count | Share |
|---|---|---|
| the company's leading name token ("Apple", "JPMorgan") | 12,969 | **59.5%** |
| the ticker symbol | 738 | **3.4%** |
| any 4-digit year 2010–2029 | 18,692 | 85.8% |

**40.5% of chunks are anonymous with respect to their company. 96.6% never contain the ticker. 14.2% carry no year at all.**

For a system whose headline question is *"the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare"*, this is decisive. A chunk reading "our supply chain is concentrated among a small number of vendors" is, in embedding space, equally close to a query about Apple and a query about Tesla. Attribution cannot come from the text.

Three techniques, in ascending cost:

**(a) Metadata prefix — do this unconditionally.** Prepend before embedding, store raw text separately for display:

```
Apple Inc. (AAPL) — 10-K, FY2024 (period ending 2024-09-28) — Item 1A Risk Factors:
<chunk text>
```

Nearly free, and it converts 100% of chunks into self-identifying ones. Note it is *not* a substitute for a hard metadata filter — it biases similarity, it does not guarantee attribution.

**(b) LLM-generated per-chunk context.** [Anthropic's Contextual Retrieval writeup](https://www.anthropic.com/news/contextual-retrieval) is first-party for its own numbers. What it measured: *"1 minus recall@20"*, i.e. the share of relevant documents not retrieved in the top 20 chunks, across codebases, fiction, ArXiv papers and science papers.

| Configuration | Top-20 failure rate | Reduction |
|---|---|---|
| baseline | 5.7% | — |
| contextual embeddings | 3.7% | **35%** |
| contextual embeddings + contextual BM25 | 2.9% | **49%** |
| + reranking | 1.9% | **67%** |

Stated cost: *"the one-time cost to generate contextualized chunks is $1.02 per million document tokens"*, using prompt caching so the reference document is not resubmitted per chunk. The cost illustration assumes "800 token chunks, 8k token documents, 50 token context instructions, and 100 tokens of context per chunk".

**Be precise about what this does and does not establish.** It measured *its own* pipeline on *those* corpora — **no SEC filings, no comparative multi-entity queries, and no per-entity attribution metric**. The 49% figure is not transferable evidence for this project; it is a strong reason to put the technique in the ablation table. Also note the writeup's assumption of *8k-token documents* — our filings have a **median of 73,057 tokens**, nearly 10× that, so the caching economics differ and the "whole document as context" prompt will not fit for the large bank filings. Contextualise against the **item section**, not the filing.

At $1.02/M applied to our 17,340,706 post-strip tokens: **≈ $17.69 one-time.** That is affordable, which makes it a real option rather than a roadmap item.

**(c) Late chunking.** [Jina's writeup](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) defines it as applying "the transformer layer of the embedding model to *the entire text*" first, then mean-pooling over chunk spans of the resulting token embeddings — so each chunk embedding is conditioned on the whole document without any generation cost. Reported BEIR gains: SciFact 64.20 → 66.10 nDCG@10; NFCorpus 23.46 → 29.98. It requires a long-context embedding model ("up to 8192 tokens") and, per the writeup, "the longer the document, the more effective the late chunking strategy becomes."

Attractive in principle — zero LLM cost, and our documents are long. But it needs pooling access to token-level embeddings, which a hosted `/embeddings` endpoint does not give you. **This is a self-hosted-only option**; it interacts with open question Q2.

### 4.6 Parent-document / small-to-big retrieval

Embed small for precision, return large for context. First-party implementation: LlamaIndex's [`HierarchicalNodeParser`](https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/), which "chunks input documents into multiple hierarchical levels, where each node references its parent" — the docs illustrate `chunk_sizes=[2048, 512, 128]` — paired with `AutoMergingRetriever`, which per those docs "enables us to automatically replace retrieved nodes with their parents when a majority of children are retrieved."

> LangChain's `ParentDocumentRetriever` implements the same pattern, but the URL `python.langchain.com/docs/how_to/parent_document_retriever/` now 308-redirects to a general overview page that does not document it. **I could not retrieve first-party LangChain documentation for it** — treat my description of the LangChain variant as unverified.

**Recommendation for this corpus: a constrained version, and only for MD&A and Item 8.** Embed ~400-token children, return the enclosing ~1,500-token parent. Do **not** apply it to Item 1A — there the correct parent is the individual risk factor, and it is already the right size; adding a hierarchy re-introduces the topic-averaging problem that per-risk-factor chunking solves. The genuine win is Item 7/Item 8, where a retrieved sentence about a margin change needs the surrounding table and the year labels to be interpretable.

### 4.7 Chunk size vs the models that consume the chunk

Chunk size is constrained from both ends by model limits, and these are easy to overlook:

| Model | Max input | Implication for an 800-token chunk |
|---|---|---|
| [`text-embedding-3-small` / `-large`](https://developers.openai.com/api/docs/guides/embeddings) | **8,192 tokens** | Ample — 800 uses 10%. Chunk size is not embedding-limited here. |
| [`voyage-finance-2`](https://docs.voyageai.com/docs/embeddings) | **16,000 tokens** | Ample. Truncation is on by default: over-length text "will be truncated to fit within the context length, before vectorized". |
| [`bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) | **512 tokens** | **Silently discards ~36% of an 800-token chunk.** |
| [`jina-reranker-v2-base-multilingual`](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) | **1,024 tokens** | Fits, with sliding-window support beyond. Licence **CC-BY-NC-4.0** — non-commercial. |
| [Cohere `rerank-v3.5`](https://docs.cohere.com/docs/rerank) | 4,096 total context | Fits comfortably. |
| [Cohere `rerank-v4.0-*`](https://docs.cohere.com/docs/rerank) | 32,768 total context | Fits trivially. |

**The reranker, not the embedder, is what caps chunk size.** If you plan to rerank with `bge-reranker-v2-m3`, chunks above ~450 tokens are partially invisible to the reranker — which means your reranker is scoring a truncation of the thing you retrieved. Either keep chunks ≤ 450 tokens, or use a longer-context reranker.

Cost interacts too. Per [Cohere's pricing](https://cohere.com/pricing): *"A single search unit is defined as one query with up to 100 documents to be ranked"*, and documents over 500 tokens are split into further chunks, **each counting as a separate document**. So:

| Chunk size | Rerank depth | Billable documents | Search units / query |
|---|---|---|---|
| 800 tokens | top-50 | 100 | 1 |
| 800 tokens | top-100 | 200 | 2 |
| 400 tokens | top-100 | 100 | 1 |

Halving chunk size halves reranking cost at equal depth.

### 4.8 Index size and cost at candidate chunk sizes

Against the 17,340,706 post-strip tokens, ignoring the skip policy (so these are upper bounds):

| Chunk | Overlap | Chunks | Embedding cost (`3-small` @ $0.02/1M) | Contextual-retrieval add-on (@ $1.02/1M) |
|---|---|---|---|---|
| 400 | 0% | 43,351 | $0.35 | $17.69 |
| 400 | 15% | 51,002 | $0.41 | $17.69 |
| 600 | 15% | 34,001 | $0.41 | $17.69 |
| **800** | **15%** | **25,501** | **$0.41** | **$17.69** |
| 1,000 | 15% | 20,400 | $0.41 | $17.69 |
| 1,200 | 15% | 17,000 | $0.41 | $17.69 |

`text-embedding-3-small` at **$0.02 per 1M tokens** ([model page](https://developers.openai.com/api/docs/models/text-embedding-3-small)); `-large` at $0.13/1M per the same source family. **The entire index costs well under a dollar at any of these settings.** Chunk size should therefore be chosen purely on retrieval quality — sweep it in the ablation (§7.6) and let the measurement decide. Anyone arguing chunk size on cost grounds for a corpus this small is optimising the wrong variable.

---

## 5. Hybrid retrieval

### 5.1 Sparse: BM25 and learned sparse

**BM25.** The canonical formulation is [Robertson & Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) (Foundations and Trends in IR, 3(4), 2009). Equation 3.15:

$$w_i^{BM25}(tf) = \frac{tf}{k_1\left((1-b) + b\frac{dl}{avdl}\right) + tf}\cdot w_i^{RSJ}$$

with the length-normalisation component (3.12) $B := (1-b) + b\frac{dl}{avdl},\; 0 \le b \le 1$, where $tf$ is within-document term frequency, $dl$ document length, $avdl$ average document length, and $w_i^{RSJ}$ the Robertson–Spärck-Jones weight (which reduces to a form of IDF absent relevance information). The document score sums these over query terms. "Setting $b = 1$ will perform full document-length normalisation, while $b = 0$ will switch normalisation off."

On parameters, the paper is explicit and it matters here:

> "Concerning the internal parameters, **the model provides no guidance on how these should be set.**… experiments… suggest that in general values such as **0.5 < b < 0.8 and 1.2 < k₁ < 2** are reasonably good in many circumstances. However, there is also evidence that **optimal values do depend on other factors (such as the type of documents or queries).**"

**This is a live tuning decision for this corpus, not a default to accept.** Our documents span 20,626 → 396,452 tokens — a 19× range, and systematically: bank 10-Ks are 4–5× the length of Apple 10-Qs. `b` governs exactly that. Left at a library default, BM25 will systematically over- or under-favour the bank filings. Sweep `b` and `k1` in the ablation.

**Learned sparse (SPLADE).** [SPLADE v2 (Formal et al., arXiv:2107.05720)](https://arxiv.org/abs/2107.05720) learns sparse vectors over the vocabulary via MLM logits with "explicit sparsity regularization and log-saturation effects on term weights", preserving "the exact matching of terms and the efficiency of inverted indexes" while adding term expansion. The abstract claims "competitive results with respect to state-of-the-art dense and sparse methods."

Term expansion is genuinely attractive for filings: a query saying "chip export restrictions" could match a document saying "export controls on advanced semiconductors" through learned expansion rather than exact overlap. But SPLADE also gives up some of BM25's exact-match crispness, which is the main reason to have a sparse leg at all. **Recommendation: start with BM25, add SPLADE as an ablation row only if the eval shows a lexical-recall gap.**

**In Qdrant specifically.** FastEmbed provides a `Bm25` sparse encoder that is statistical, not neural — it counts tokens — and it deliberately **omits the IDF component**, which Qdrant computes server-side. It is therefore expected to be used with `modifier="idf"` on the sparse vector index. Getting this wrong yields a silently miscalibrated sparse leg. FastEmbed also ships SPLADE (`prithivida/Splade_PP_en_v1`, vocab 30,522) and miniCOIL. *Sources: [FastEmbed SPLADE docs](https://qdrant.tech/documentation/fastembed/fastembed-splade/) (verified) and the [`fastembed/sparse/bm25.py` source](https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py) plus [Qdrant BM25 docs](https://qdrant.tech/documentation/edge/edge-bm25/) (**I read these via search-result summaries, not a direct fetch — treat the IDF-split detail as high-confidence but not first-party-verified**).*

### 5.2 Why hybrid, specifically for filings

The honest version of this argument, with the evidence stated at its actual strength.

**What is well supported.** [BEIR (Thakur et al., arXiv:2104.08663)](https://arxiv.org/abs/2104.08663), 18 datasets, zero-shot:

> "Our results show **BM25 is a robust baseline** and re-ranking and late-interaction-based models on average achieve the best zero-shot performances, however, at high computational costs. In contrast, dense and sparse-retrieval models are computationally more efficient but often underperform other approaches."

Note carefully what this does and does not say. It says BM25 is *robust* and that *reranking and late-interaction* win on average. It does **not** say dense retrievers lose to BM25 across the board. Citing BEIR as "BM25 beats dense out-of-domain" overstates it. The defensible reading: **out-of-domain, BM25 is hard to beat and expensive to beat, so a lexical leg is cheap insurance** — and the strongest configurations involve reranking.

> BEIR's canonical reported metric is nDCG@10; the [BEIR repo](https://github.com/beir-cellar/beir) states it evaluates "with NDCG@k, MAP@K, Recall@K and Precision@K where k = [1,3,5,10,100,1000]" without naming a headline metric on the page I fetched. nDCG@10 as *the* BEIR number is corroborated by third-party model cards reporting "BEIR nDCG@10" (e.g. the Jina reranker card, 53.17) — **treat "nDCG@10 is BEIR's headline metric" as strongly indicated but not first-party-confirmed here.**

**The corpus-specific argument, which is the stronger one.** Filings are saturated with exact identifiers that carry enormous semantic weight and near-zero distributional signal: `Section 174`, `CECL`, `Basel III`, `CHIPS Act`, `Item 1A`, ticker symbols, dollar amounts, `us-gaap:` tags, CIK numbers. A dense embedding smears `Section 174` into a neighbourhood of tax-ish text; BM25 matches it exactly. Meanwhile the actual questions are paraphrases — *"what could go wrong for them?"* must retrieve text that never contains the token "risk factor."

Real diligence questions contain both modes in one sentence: *"What regulatory risks do the major pharmaceutical companies face under the Inflation Reduction Act?"* — `Inflation Reduction Act` is a lexical needle, "regulatory risks… face" is a paraphrase. That is the argument for fusion, and it is grounded in this corpus rather than borrowed from a benchmark.

### 5.3 Dense embedding models, first-party specs

| Model | Dims | Max tokens | Price | Source |
|---|---|---|---|---|
| `text-embedding-3-small` | 1536 (reducible via `dimensions`) | 8,192 | **$0.02 / 1M** | [OpenAI](https://developers.openai.com/api/docs/guides/embeddings), [model page](https://developers.openai.com/api/docs/models/text-embedding-3-small) |
| `text-embedding-3-large` | 3072 (reducible) | 8,192 | $0.13 / 1M | same |
| `voyage-finance-2` | 1024 | **16,000** | not stated on the page I fetched | [Voyage](https://docs.voyageai.com/docs/embeddings) |
| `voyage-4` / `-4-large` / `-4-lite` | 1024 (also 256/512/2048) | 32,000 | not stated | same |
| `voyage-code-4`, `voyage-law-2` | 1024 | 32,000 / 16,000 | not stated | same |
| Cohere Embed | — | — | — | **not verified** — [cohere.com/pricing](https://cohere.com/pricing) showed only instance-based Model Vault rates ($4–5/hr for Embed 4), not per-token pricing, on the page I fetched |
| `BAAI/bge-*`, E5, Nomic (self-hostable) | varies | varies | self-hosted | I fetched the [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) card but **not** the bge/E5/Nomic *embedding* cards — specs for those are **unverified** here |

**`voyage-finance-2` exists and is finance-domain** — 16,000 tokens, 1024 dimensions. Its truncation behaviour is documented: with `truncation` enabled (the default) over-length input "will be truncated to fit within the context length, before vectorized by the embedding model"; disabled, it errors. **Silent truncation is a footgun** — if a per-risk-factor chunk or a table block runs long, you get an embedding of a prefix with no error. Assert chunk length at index time regardless of model.

**On MTEB.** [MTEB (Muennighoff et al., arXiv:2210.07316)](https://arxiv.org/abs/2210.07316) covers 8 task types, 58 datasets, 112 languages, 33 models. Its own headline finding is the reason to use it only directionally:

> "We find that **no particular text embedding method dominates across all tasks.**"

Use the leaderboard to shortlist two or three candidates. Do not use it to pick one — it contains no SEC filings and no multi-entity comparative retrieval task. The ablation on your own golden set is the decision procedure. (I was unable to fetch descriptive content from the [MTEB leaderboard Space](https://huggingface.co/spaces/mteb/leaderboard) — it renders client-side — so the retrieval-subset metric there is **unverified**.)

**Recommendation.** Start with `text-embedding-3-small`: 8,192-token ceiling is ample, the whole index costs $0.35, and 1536d keeps the vector store small. Put `voyage-finance-2` in the ablation as the domain challenger — a finance-tuned model on a finance corpus is a fair and cheap test, and if it wins it is a good story for the demo. Note `text-embedding-3-large` at 3072d **will not fit a pgvector `vector` column** (2,000-dimension limit, §5.4) without dimension reduction.

### 5.4 Vector store comparison: native hybrid + server-side fusion

The prior-art SPEC claims Qdrant is the "only mainstream OSS store with first-class named dense + sparse vectors in one collection and server-side RRF." **That is not correct.** Verified, each from the product's own documentation:

| Store | Dense + sparse in one collection | Server-side fusion | Fusion methods | Source |
|---|---|---|---|---|
| **Qdrant** | Yes (named vectors) | Yes — `prefetch` + `FusionQuery`, "Whenever a query has at least one prefetch, Qdrant will: 1. Perform the prefetch query (or queries), 2. Apply the main query over the results" | **RRF** (k default **2**; configurable from v1.16.0; weighted RRF v1.17.0), **DBSF** (v1.11.0+) | [Hybrid Queries](https://qdrant.tech/documentation/concepts/hybrid-queries/) |
| **Weaviate** | Yes | Yes — single server-side query | `rankedFusion`, `relativeScoreFusion` (**default since v1.24**), `alpha` (0 = pure keyword, 1 = pure vector) | [Hybrid search](https://docs.weaviate.io/weaviate/search/hybrid) |
| **Milvus** | **Yes** — docs show `text_dense` (768d), `text_sparse`, `image_dense` (512d) in one collection | Yes | `RRFRanker` (**k default 100**), `WeightedRanker` | [Multi-vector search](https://milvus.io/docs/multi-vector-search.md) |
| **Elasticsearch** | Yes (via retrievers) | Yes — "RRF runs entirely on the server within a single `_search` request" | **RRF**, `rank_constant` **default 60**, `rank_window_size` | [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) |
| **Vespa** | Yes | Yes — first-phase / second-phase / **global-phase** ranking | RRF expressible via `reciprocal_rank()` in a global-phase ranking expression; also `OR`/`RANK` operators to combine `bm25` and `nearestNeighbor` in one YQL query | [Hybrid search tutorial](https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html) |
| **OpenSearch** | Yes | Yes — search pipelines with `normalization-processor` and `score-ranker-processor` | normalization + combination; RRF via score-ranker-processor | [Hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/) — **partially verified: the pages I fetched named both processors but I could not retrieve the processor reference page, so the RRF default and version are unverified** |
| **pgvector + Postgres FTS** | No — separate mechanisms | **No** | None. "pgvector itself does not natively provide hybrid search — users must combine it with Postgres's built-in text search and implement fusion methods like Reciprocal Rank Fusion… separately" | [pgvector README](https://github.com/pgvector/pgvector) |

pgvector limits worth knowing: `vector` up to **2,000 dimensions**, `halfvec` 4,000, `bit` 64,000; `sparsevec` up to 16,000 non-zero elements but **1,000 non-zero per indexed vector** — restrictive for BM25/SPLADE sparse vectors over a 30k vocabulary. Index types HNSW and IVFFlat; operators `<->` L2, `<#>` negative inner product, `<=>` cosine, `<+>` L1, `<~>` Hamming, `<%>` Jaccard.

**Note:** this table compares *retrieval* capability only. These same stores differ just as sharply in **metadata/payload mutability** — whether you can add and index a field after the fact — and two of them (Weaviate, Elasticsearch/OpenSearch) are materially worse there. See [§9.2](#92-per-store-payload-mutability-from-first-party-docs) before treating this table as the whole store decision.

**Corrected recommendation.** Qdrant remains a sound choice for this project — local Docker, clean Python client, both fusion methods including DBSF, and `Formula` queries (v1.14.0+) for recency weighting, which is genuinely useful for filings. But the justification must be "good fit, simple ops, DBSF available" rather than "only option". **Note the DBSF asymmetry: Qdrant ships DBSF and, of the stores above, appears to be the only one that does** — that is a real and defensible differentiator, and it is a better argument than the incorrect uniqueness claim.

**Metadata filtering semantics — pre-filter vs post-filter.** This matters more than the fusion choice for our use case, because every question is entity-scoped and 40.5% of chunks are company-anonymous (§4.5). A post-filter retrieves top-k globally and *then* drops non-matching rows, which for a three-company question can return zero chunks for the least verbose company. A pre-filter constrains the ANN search itself.

I did not verify each store's filter semantics from first-party docs in this pass — **this is unverified and it is the highest-value remaining verification task.** Qdrant is designed around filterable HNSW with payload indexes (pre-filtering), which is the behaviour you want; confirm before committing. Regardless of store, the per-entity quota design in §8.2 makes the system robust to filter semantics by issuing one filtered query per entity.

---

## 6. Fusion — RRF and alternatives

### 6.1 The RRF formula and what the paper actually says about k=60

From [Cormack, Clarke & Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods", SIGIR 2009](http://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf) — I fetched and read the full 2-page paper.

Given a document set $D$ and rankings $R$, each a permutation on $1..|D|$:

$$\text{RRFscore}(d \in D) = \sum_{r \in R} \frac{1}{k + r(d)}$$

> "where **k = 60 was fixed during a pilot investigation and not altered during subsequent validation.** Our intuition in choosing this formula derived from fact that while highly-ranked documents are more important, the importance of [lower-ranked documents declines slowly]"

**So k=60 was tuned — and the paper says the tuning barely mattered.** Verbatim on the pilot:

> "We conducted four pilot experiments, each combining the results of **30 configurations of Wumpus Search** applied to four different TREC collections. The results of the first, shown in table 1, indicated that **k = 60 was near-optimal, but that the choice was not critical.**"

Table 1 (MAP vs k, RRF over 30 model system results, TREC topics 351–400):

| k | 0 | 10 | 20 | 30 | 40 | 50 | **60** | 70 | 80 | 90 | 100 | 500 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MAP | .2072 | .2123 | .2134 | .2139 | .2138 | .2144 | **.2145** | .2146 | **.2147** | .2145 | .2142 | .2098 |

Three corrections to the folklore:

1. **k=60 is not optimal even in the paper.** k=80 scores .2147 against k=60's .2145. Everything from k=30 to k=100 lies within .0009 MAP. The paper's own words are "not critical."
2. **The provenance is not a dense+sparse hybrid.** It is the fusion of **30 configurations of one lexical search engine**, in 2009, evaluated by MAP on TREC ad-hoc topics. Fusing 30 homogeneous runs is a statistically different problem from fusing 2 heterogeneous ones. Carrying k=60 across that gap is a convention, not a derivation.
3. **Ranks are 1-based** in the paper ($r$ is a permutation on $1..|D|$). Implementations differ on this, which shifts the effective k by one.

The paper's other reported results, for completeness: RRF "outperforms Condorcet, CombMNZ and the best system by 4% to 5% on average", with significance by sign test — RRF beat Condorcet 7/7 times (p ≈ 0.008) and CombMNZ 6/7 (p ≈ .04).

### 6.2 k is not portable across implementations

This is the practically important finding, and it directly contradicts a "keep the default" strategy:

| Implementation | Default RRF k | Source |
|---|---|---|
| Cormack et al. 2009 | 60 (pilot-tuned; "not critical") | [paper](http://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf) |
| **Qdrant** | **2** | [`DEFAULT_RANKING_CONSTANT_K = 2`](https://github.com/qdrant/qdrant-client/blob/master/qdrant_client/hybrid/fusion.py); [hybrid queries docs](https://qdrant.tech/documentation/concepts/hybrid-queries/) confirm "k defaults to 2… As of v1.16.0, the k constant is configurable" — **but not via `FusionQuery` in client 1.19.0, which forbids extra fields; see below** |
| Elasticsearch | 60 | [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) |
| Milvus `RRFRanker` | 100 | [multi-vector search](https://milvus.io/docs/multi-vector-search.md) |

Qdrant's client computes `1 / ((pos + 1.0) / score_weight + ranking_constant - 1.0)`, with an inline comment that the ranking constant "mitigate[s] the impact of high rankings by outlier systems".

**Consequence for the prior art:** a SPEC that says "keep k=60 (the Cormack et al. default)" while calling `FusionQuery(fusion=Fusion.RRF)` on Qdrant is **actually running k=2** on any version before 1.16.0, and on later versions only if k is passed explicitly. k=2 is aggressive: it weights rank 1 far more heavily relative to rank 10 than k=60 does, i.e. it trusts whichever retriever won the top slot. That may even be the better choice here — but it should be a measured decision, not an accident.

**[confirmed in code, 2026-08-19]** Verified directly against the prior art at its current location
(`/Users/jordan/Developer/rag-old/`), which pins `qdrant/qdrant:v1.19.0` and `qdrant-client>=1.19.0`:

- `src/retrieve.py:60` calls `models.FusionQuery(fusion=models.Fusion.RRF)` with **no ranking constant** — so
  the SPEC's "k=60" is prose only; the server default is what runs.
- In the installed `qdrant-client` 1.19.0, `FusionQuery` is declared
  `class FusionQuery(BaseModel, extra="forbid")` with **exactly one field, `fusion`**. There is no parameter
  to pass.
- The client's own schema description for the fusion enum reads: *"`rrf` - Reciprocal Rank Fusion **(with
  default parameters)**"* (`qdrant_client/embed/_inspection_cache.py:3236`).

**This narrows the recommendation.** "Set k explicitly" is *not* a two-line change on this stack — the
REST/gRPC `FusionQuery` model as shipped in 1.19.0 exposes no knob, so k is not tunable server-side through
the documented Query API path. Sweeping k therefore requires one of:

1. **Fuse in application code** — issue the two `prefetch` legs as separate `query_points` calls and apply
   RRF yourself. Costs the single-round-trip property the SPEC valued, but makes k a free parameter and is
   ~20 lines. This is the honest way to get the ablation row.
2. **Qdrant `Formula` queries** — express the fusion arithmetic as a server-side formula over prefetch
   scores. Keeps one round trip; more complex to write and to explain. *Unverified — I did not confirm that
   `Formula` can reference prefetch ranks (as opposed to scores), which is what RRF needs.*
3. **Accept the default and say so** — measure hybrid-vs-single-leg without claiming a tuned k.

*Corrected recommendation:* stop claiming k=60. Either fuse in application code so k is genuinely swept
({2, 10, 60, 100}), or state plainly that fusion runs at the store's default and that k was not tuned. The
SPEC's error is not the value — it is asserting a parameter the code never set.

### 6.3 Score-based alternatives, and when RRF is wrong

**DBSF (Distribution-Based Score Fusion).** Qdrant normalises each retriever's score distribution by its mean and 3σ before combining: $\hat{s} = \frac{s - (\mu - 3\sigma)}{6\sigma}$ ([Qdrant docs](https://qdrant.tech/documentation/concepts/hybrid-queries/), available since v1.11.0). I did not locate an originating paper for DBSF — **treat the method as vendor-documented rather than peer-reviewed; the formula above is from Qdrant's own docs.**

**Weighted score fusion / convex combination.** Normalise each leg (min-max or z-score) then take a weighted sum. Weaviate's `relativeScoreFusion` with `alpha` is this, and it is Weaviate's **default since v1.24** — a notable vote of confidence from a vendor that also ships rank fusion.

**When RRF is the wrong choice.** RRF discards score magnitude entirely — it sees only positions. That is exactly what makes it robust when the two legs' scores are incomparable (cosine in [-1,1] versus unbounded corpus-dependent BM25), and it is why the prior-art SPEC's reasoning on this point is sound. But it has a specific failure mode that matters here:

> When one retriever is confidently right and the other returns noise, RRF still credits the noise. A query for `CECL` gets a near-exact BM25 hit at rank 1 with a huge score, while the dense leg returns ten plausible-but-wrong paragraphs about credit risk generally. RRF treats "BM25 rank 1" and "dense rank 1" as equal evidence, so dense's rank-1 noise lands above BM25's rank-2 genuine hit.

For a corpus this saturated with exact identifiers, that is not a hypothetical. **Recommendation: default to RRF for robustness, but include DBSF and a weighted convex combination as ablation rows.** Score-based fusion should win on lexical-needle queries; if it does, that is a result worth reporting and possibly a query-dependent fusion strategy (deterministically detectable: does the query contain a quoted phrase, a statute name, a number?).

### 6.4 Reranking and the one-call constraint

**Pipeline order.** Filter → retrieve (per leg, per entity) → fuse → rerank → assemble → **one LLM call**.

Filtering must come first and must be a pre-filter (§5.4): fusing then filtering wastes candidate budget on documents that will be discarded, and for the least-verbose company in a three-way comparison it can leave nothing.

**Does a cross-encoder reranker violate "one LLM API call"? No.** A cross-encoder is a discriminative scoring model — it takes a (query, passage) pair and emits a relevance scalar. Per the [bge-reranker-v2-m3 card](https://huggingface.co/BAAI/bge-reranker-v2-m3), it "directly output[s] similarity" rather than an embedding, and it generates no text. It is a ranking function, in the same category as BM25. The brief's constraint is about *the answer* being produced by a single generative call, and reranking happens in the retrieval pipeline that the brief explicitly permits to "run beforehand."

**An LLM-based reranker is a different matter and I would call it a violation** — or at minimum a bad-faith reading. If you prompt a generative model per candidate ("rate this passage's relevance 1–10"), you are making N generative calls in the answer path. Even a single batched "rank these 50 passages" call is a second generative call whose output determines the answer. Do not do it; the honest version of this system does not need it.

**Options.**

| Reranker | Max input | Notes |
|---|---|---|
| [Cohere `rerank-v4.0-pro` / `-fast`](https://docs.cohere.com/docs/rerank) | 32,768 context | Multilingual; long docs auto-chunked across inferences |
| [Cohere `rerank-v3.5`](https://docs.cohere.com/docs/rerank) | 4,096 context (docs chunked at 4,093) | Query capped at 2,048 tokens |
| [`bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) | **512 tokens** | 0.6B params, base `bge-m3`, **Apache 2.0** — self-hostable and commercially usable |
| [`jina-reranker-v2-base-multilingual`](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) | 1,024 (sliding window beyond) | 278M params, flash attention "3x-6x speedup", **CC-BY-NC-4.0 — non-commercial** |

Per [Cohere best practices](https://docs.cohere.com/docs/reranking-best-practices): max **10,000 documents** per request (`documents × max_chunks_per_doc` must be ≤ 10,000).

**Two decision-relevant points.** First, licensing: `jina-reranker-v2` is CC-BY-NC-4.0, which **rules it out for an internal commercial deployment at a PE firm** unless accessed through Jina's paid APIs. `bge-reranker-v2-m3` is Apache 2.0. For an on-premise, commercially-used system, that is close to decisive. Second, cost and latency: reranking is per-query, unlike embedding which is one-time. At top-50 with 800-token chunks that is 1 Cohere search unit per query (§4.7); self-hosted `bge-reranker-v2-m3` at 0.6B params is CPU-feasible but GPU-preferable. **I did not find first-party latency benchmarks for either at realistic k — that number is unverified and should be measured locally.**

**Recommendation:** rerank, and treat it as the highest-expected-value single addition after hybrid retrieval — it is the component Anthropic's numbers credit with the largest marginal gain (49% → 67% failure reduction) and BEIR credits with the best zero-shot performance. But make it an ablation row, because it is also the component with real per-query cost, and on a 40–60 question golden set you need to show it earns that.

---

## 7. Evaluation

> **Companion note.** [`eval-harness-findings.md`](./eval-harness-findings.md) audits the prior art's *as-built* eval harness against its own committed results, and finds three defects that would make the §7.6 ablation report noise: `recall@k` ceilings varying 0.139–1.000 across questions, `MRR@10`/`nDCG@10` saturated at 0.977/0.963, and near-duplicate suppression being anti-correlated with the file-level recall label. Read it before building the harness below.

### 7.1 Retrieval metrics — definitions and the nDCG variant question

**Recall@k and Precision.** From the [TREC common evaluation measures appendix](https://trec.nist.gov/pubs/trec16/appendices/measures.pdf):

> Recall = number of relevant items retrieved / number of relevant items in collection
> Precision = number of relevant items retrieved / total number of items retrieved

Both are set-based; at a cutoff k they are computed over the top-k.

**MRR.** Mean over queries of the reciprocal of the rank of the first relevant document. Implemented in `trec_eval` as `recip_rank` ([`m_recip_rank.c`](https://github.com/usnistgov/trec_eval)).

**nDCG — and be precise about the variant, because libraries disagree.** I read the reference implementation, [`m_ndcg.c` in `usnistgov/trec_eval`](https://github.com/usnistgov/trec_eval). Its own header:

> "Normalized Discounted Cumulative Gain. Compute a traditional nDCG measure according to **Jarvelin and Kekalainen (ACM ToIS v. 20, pp. 422-446, 2002)**. **Gain values are set to the appropriate relevance level by default.** The default gain can be overridden on the command line by having comma separated parameters 'rel_level=gain'."

And the computation, verbatim from the source:

```c
/* Note: i+2 since doc i has rank i+1 */
results_dcg += results_gain / log2((double) (i + 2));
...
ideal_dcg   += ideal_gain   / log2((double) (i + 2));
```

So `trec_eval`'s `ndcg` is: **linear gain** (gain = the relevance level itself — confirmed in `m_ndcg_cut.c` by `gain = res_rels.results_rel_list[i]`), **discount $\log_2(r+1)$** for 1-based rank $r$, normalised by the ideal DCG of the gain-sorted ranking.

**This differs from the other common convention**, exponential gain $2^{rel}-1$, which many libraries (and learning-to-rank literature) use by default. On binary relevance the two coincide; on graded relevance they do not, and the difference is large enough to change conclusions. **Recommendation: use binary relevance labels for this project** (a chunk is relevant or it is not). That sidesteps the variant question entirely, is far cheaper to label, and is adequate for the architectural comparisons in §7.6. State in the eval README which variant and which relevance scale you used.

> I could not retrieve the original [Järvelin & Kekäläinen paper](https://dl.acm.org/doi/10.1145/582415.582418) — ACM returned HTTP 403. The definitions above are from the NIST reference implementation, which cites it explicitly; I consider that authoritative for *what trec_eval computes*, which is what matters operationally.

### 7.2 Why the standard metrics are not sufficient here

Consider *"What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"* with 30 gold-relevant chunks — 10 per company — and k=20.

A retriever returning **20 Apple chunks and nothing else** scores **recall@20 = 10/30 = 0.33** and a respectable nDCG@10, because all 10 Apple chunks it found are genuinely relevant and highly ranked. The same 0.33 recall is achieved by a retriever returning 7 chunks from each company — which produces a correct comparative answer, while the first produces an answer that silently omits two of the three companies the user asked about.

**Standard recall@k cannot distinguish these.** It is an aggregate over a flat relevant-set and has no notion of the query's internal structure. For a comparative-question system, that makes it the wrong headline metric. This is also why the entity asymmetry in §2.9 is dangerous: JPM has 4 filings against Apple's 16, so a global top-k is structurally biased toward Apple, and the bias is invisible in recall.

### 7.3 The three domain metrics no library ships

**1. Entity coverage@k.** Fraction of entities named in the question that appear at least once in the top-k retrieved set.

$$\text{EntityCov@}k = \frac{|\{e \in E_q : \exists c \in \text{top-}k,\ \text{ticker}(c) = e\}|}{|E_q|}$$

Report the mean, but **also report the share of queries at 1.0** — a mean of 0.83 could be "every query missed one company" or "five of six queries were perfect and one returned nothing." Only the second is acceptable. This is the metric that proves per-entity quotas were necessary, and it is the one that communicates to a business audience.

**2. Item-section precision@k.** Fraction of top-k chunks whose `item_section` is in the expected set for the question type. Risk questions should retrieve Item 1A; outlook questions Item 7 / Part I Item 2; numeric questions Item 8. This catches a specific and common failure: a "risk factors" question pulling Item 7 chunks that *discuss* risks narratively. It also directly validates the §2.5 segmenter — if section labels are wrong, this metric degrades even when the text is right.

**3. Temporal-scope correctness@k.** Fraction of top-k chunks whose fiscal period falls within the question's requested window, plus — separately — whether the required **baseline** was retrieved. Per §4.4, a "last two years" risk question needs the governing 10-K, not only the 10-Q deltas. Score this as two numbers: in-window precision, and baseline-present (boolean per query). The second is the one that catches the delta-without-baseline correctness bug, and nothing else will.

Add a fourth, cheap and worth it: **near-duplicate rate@k** — filings repeat language verbatim across quarters, so a top-20 can be five distinct facts and fifteen restatements. Measure it; it justifies the dedup step.

### 7.4 Generation metrics

**Deterministic checks — free, run on every eval and in CI.** These catch most hallucination without a judge, and they are the ones to build first:
- every `[C#]` handle in the answer resolves to a chunk that was actually in the assembled context;
- every ticker mentioned in the answer appears in the retrieved set (catches parametric-knowledge leakage);
- every numeric string in the answer appears verbatim in the context (catches transcription and fabrication);
- for a question naming an out-of-corpus company, the answer contains an explicit refusal.

That last one deserves emphasis for this audience: **graceful refusal is the single most valuable demo behaviour.** A confidently fabricated risk factor in an IC memo is a serious problem, and being able to show the system declining to invent is worth more than any retrieval metric.

**LLM-judged metrics.** [Ragas](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) — and note that on the page I fetched, **all four of the core metrics are LLM-based**:

| Metric | Definition | LLM required |
|---|---|---|
| Faithfulness | whether the response is grounded in the retrieved context without unsupported claims | **Yes** |
| Response relevancy | how well the response addresses the question | **Yes** |
| Context precision | proportion of retrieved contexts that are relevant | **Yes** |
| Context recall | fraction of the needed relevant information present in the retrieved context | **Yes** |

So every headline Ragas metric costs money and introduces nondeterminism — run them with a fixed judge model and seed where possible, report variance across repeats, and never gate CI on them alone.

The originating paper is [*Ragas: Automated Evaluation of Retrieval Augmented Generation*, Es, James, Espinosa-Anke & Schockaert (arXiv:2309.15217)](https://arxiv.org/abs/2309.15217). Its central design claim is that evaluation is **reference-free**: "We put forward a suite of metrics which can be used to evaluate these different dimensions without having to rely on ground truth human annotations." That is a real advantage for this project — it means Ragas can score answers on questions you have *not* labelled, complementing the labelled golden set rather than duplicating it. Note the abstract does not itself enumerate faithfulness / answer relevance / context relevance by name; those names come from the Ragas **docs** cited above, so treat the docs as authoritative for current metric definitions and the paper as authoritative for the reference-free framing.

Alternatives, first-party links, **all unverified in this pass** (listed for completeness, not endorsed): [DeepEval](https://github.com/confident-ai/deepeval), [promptfoo](https://www.promptfoo.dev/), [TruLens](https://www.trulens.org/).

**Critically:** judge calls are *eval-time*, entirely separate from the answer path. Say this explicitly in the writeup so nobody thinks the one-call constraint is being finessed.

### 7.5 Building the golden set on a realistic budget

**Size: 40–60 questions.** Below ~30 nothing is measurable (§7.7); above ~60 labelling dominates the schedule.

Suggested composition, weighted toward the failure modes this corpus actually has:

| Category | n | Why |
|---|---|---|
| Multi-entity comparative | 14 | the headline use case; the only category that exercises entity coverage |
| Temporal / trend | 10 | exercises the 10-Q delta-vs-baseline trap (§4.4) |
| Sector-wide | 8 | exercises recall breadth and the thin-coverage tickers (§2.9) |
| Single-company factual | 10 | the control group; isolates retrieval from aggregation |
| Numeric / quantitative | 6 | tests the XBRL router (§3.4) against the text path |
| Out-of-corpus / unanswerable | 6 | tests refusal — includes absent companies *and* absent items (e.g. executive compensation, §3.3) |

**Sourcing questions cheaply.** Do not invent them from nothing. Three cheap sources, in order of value:
1. **Mine the corpus for its own vocabulary.** Grep for high-IDF identifiers (statute names, `Section 174`, `CECL`, programme names) and build questions around them — this guarantees a lexical-needle test set with known-present answers.
2. **Use the item structure as a template.** For each of the 5–6 high-signal items × a handful of companies, generate "what does {company} disclose about {item topic}" — mechanical, and the gold section is known by construction.
3. The three examples in the brief, plus paraphrases of them, since those are what will actually be typed in the demo.

**Labelling relevance without reading everything.** The trick is to label at **section granularity, not chunk granularity**:

> Gold label = the set of `(ticker, form, period, item_section)` tuples that *should* be retrieved. A retrieved chunk counts as relevant if its metadata matches a gold tuple.

This is dramatically cheaper — you are asserting "Apple's FY2024 10-K Item 1A is relevant to this question", which takes seconds and requires no reading — and it is adequate for recall@k, entity coverage, item-section precision and temporal correctness, which are the metrics that decide the architecture. It is *not* adequate for nDCG at chunk granularity; accept that, or add chunk-level labels for a 10-question subset only.

Then bootstrap: run the current best pipeline, pool the top-20 from every ablation configuration, and label only the pooled union. This is standard TREC pooling and it is the only way to make this affordable. Document the pooling depth, because pooled judgments are biased against systems that did not contribute to the pool — a new configuration later may be under-credited.

**Regression safety.** Commit `golden_set.json` and the results tables to the repo. Pin the judge model and the embedding model versions in the results file — an embedding model silently updating server-side will move every number and you will spend a day looking for a code bug. Make the deterministic checks (§7.4) a CI gate; leave the LLM-judged metrics as a reported-not-gating artifact.

### 7.6 The ablation table — the artifact that proves the architecture

This is what turns "we chose hybrid" into a measured claim. Design it so that **each row isolates exactly one decision**, and each column is the metric that decision is supposed to move.

| # | Configuration | Recall@20 | nDCG@10 | **EntityCov@20** | ItemPrec@20 | TemporalCorr@20 | Faithfulness | Proves |
|---|---|---|---|---|---|---|---|---|
| 0 | Dense only, fixed 800t, no prefix | | | | | | | baseline |
| 1 | Sparse (BM25) only | | | | | | | lexical-needle coverage |
| 2 | Hybrid + RRF (k explicit) | | | | | | | **hybrid > either leg** |
| 3 | 2 + DBSF instead of RRF | | | | | | | fusion-method choice (§6.3) |
| 4 | 2 + RRF k sweep {2,10,60,100} | | | | | | | **k is not a default** (§6.2) |
| 5 | 2 + contextual metadata prefix | | | | | | | prefix earns its 20 lines (§4.5) |
| 6 | 5 + section-aware chunking | | | | | | | segmentation earns its complexity (§2.5) |
| 7 | 6 + per-risk-factor chunking for Item 1A | | | | | | | **the 229.105 argument** (§4.3) |
| 8 | 7 + chunk-size sweep {400,600,800,1200} | | | | | | | size is measured, not folklore |
| 9 | 7 + per-entity quotas | | | | | | | **the comparative-question fix** — expect this to move only EntityCov |
| 10 | 9 + cross-encoder rerank | | | | | | | rerank earns its per-query cost (§6.4) |
| 11 | 9 + LLM-generated chunk context ($17.69) | | | | | | | contextual retrieval on *this* corpus |
| 12 | 10 + XBRL router for numeric questions | | | | | | | the §3.4 fork, on the numeric subset only |

Read the table by column, not by row. **Row 9 is the important one to get right**: per-entity quotas should move `EntityCov@20` sharply and barely move `Recall@20`. If you only report recall, row 9 looks like a no-op, and the single most important retrieval behaviour for the headline question type appears worthless. That asymmetry *is* the argument for the custom metrics.

Run rows 0–2 first, on day one. If hybrid does not beat dense-only on this corpus, you want to know while there is time to investigate — and an honest null result with a hypothesis is a better artifact than a table that does not reproduce.

### 7.7 Statistical honesty at n = 40–60

With 40–60 questions, small differences are noise, and presenting them as findings is the fastest way to lose a technical panel.

Per [Urbano, Lima & Hanjalic, "Statistical Significance Testing in Information Retrieval: An Empirical Analysis of Type I, Type II and Type III Errors" (SIGIR 2019, arXiv:1905.11096)](https://arxiv.org/abs/1905.11096) — a simulation study spanning "over 500 million p-values" across systems, effectiveness measures, topic set sizes and effect sizes — "the t-test is the most popular choice among IR researchers", and the study was designed to "make sound recommendations for practitioners." The abstract does not itself state the final recommendation; **the specific recommended test is unverified here — I read the abstract, not the full paper.**

Practical guidance for this project, stated as engineering judgment rather than as a citation:
- Use the **paired** test — the same questions run through both configurations. Pairing is what buys you power at small n.
- Report **per-question deltas**, not just means. A win of +0.04 mean recall that comes from one question improving by +0.8 and thirty-nine unchanged is a different fact from a uniform +0.04, and only the second generalises.
- Report a **confidence interval or the win/loss/tie count**, not a bare mean. "Hybrid beat dense on 31 of 50 questions, tied on 14, lost on 5" is more honest and more persuasive than "recall improved 4%".
- Treat differences below roughly 0.05 in recall@20 at n=50 as **not demonstrated**. Say so in the table's caption rather than letting a reader over-read the third decimal.
- Do not run twelve ablation rows and report the one significant result as though it were a single planned comparison. With 12 comparisons at α=0.05 you expect a false positive. Pre-register which rows are the primary claims (I would nominate rows 2, 7 and 9) and treat the rest as exploratory.

---

## 8. Answer synthesis under the one-call constraint

### 8.1 Context assembly and ordering

Position within the prompt has a measurable effect on whether the model uses the information. From [Liu et al., "Lost in the Middle: How Language Models Use Long Contexts" (arXiv:2307.03172)](https://arxiv.org/abs/2307.03172):

> "performance is often highest when relevant information occurs at the beginning or end of the input context, and **significantly degrades when models must access relevant information in the middle of long contexts**"

The curve is U-shaped, it was measured on multi-document QA and key-value retrieval, and the paper reports it holding "even for models specifically designed for extended contexts." (The abstract does not quantify the drop; I did not read the full paper, so the magnitude is unverified here.)

**Recommendation for assembly order:**
1. Rank the assembled chunks by rerank score.
2. Place rank 1 **first** and rank 2 **last**, then fill inward — strongest evidence at both edges, weakest buried in the middle.
3. For comparative questions this competes with grouping by company, which aids the model's own organisation. Resolve it by grouping by company but ordering *companies* by their best chunk score, and within each company putting its strongest chunk first. That preserves the structure the answer needs while keeping weak evidence away from the edges.
4. Dedup near-identical chunks before assembly (§7.3) — filings repeat language verbatim across quarters, and a duplicate occupying a high-salience edge position is a wasted slot.

Suggested budget: ~40k tokens of context. Note this is well within modern context windows, so the binding constraint is attention quality (the above), not the window.

### 8.2 Per-entity quotas

Given $n$ detected entities, issue $n$ filtered hybrid queries with budget $\lceil k/n \rceil$ each (floor ~6 so a single-company query still gets useful depth), then merge. With zero entities detected, one unfiltered query at full $k$.

The justification is now empirical rather than intuitive: §2.9 shows JPM has 4 filings against Apple's 16, and §4.5 shows 40.5% of chunks cannot be attributed from their text. A global top-k on a three-company question will structurally over-represent whichever company filed more and writes more vividly. Quotas make coverage a guarantee rather than a hope — and §7.3's `EntityCov@k` is what demonstrates it.

### 8.3 Deterministic query understanding

To preserve the one-call guarantee, extract everything without an LLM:

- **Entities** — alias dictionary matched against the corpus. Build it from the per-file `Company` and `Ticker` headers (§2.2), not from the manifest (which has no metadata, §2.1). Include legal-suffix variants ("JPMorgan Chase & Co", "JPMorgan", "JPM", "Chase") and, for sector questions, a hand-built sector→ticker map. 54 companies is small enough that this is a 30-minute job and it will be more accurate than an LLM.
- **Temporal scope** — regex for explicit years, quarters, and relative phrases ("last two years", "most recent quarter", "since FY2023") resolved against `filing_date`/`period_end`. Watch the fiscal-year trap: Apple's FY2024 ended 2024-09-28, so "in 2024" is ambiguous. Prefer `period_end` over any `fy` label (§3.4).
- **Form hints** — "quarterly"/"10-Q" vs "annual"/"10-K".
- **Question type** — quantitative vs qualitative, to drive the XBRL router (§3.4). Keyword-based: "revenue", "margin", "how much", "grew by", "%".
- **Lexical-needle detection** — quoted phrases, capitalised multi-word terms, `Section \d+`, dollar amounts. Useful for query-dependent fusion weighting (§6.3).

**Where this costs recall, honestly.** A rule-based extractor fails on: pronouns and anaphora ("what about the other two?"); implicit entities ("the largest US bank"); vocabulary mismatch where the user's framing shares no terms with the filing's ("is their moat eroding?"); and multi-hop questions requiring decomposition ("which of these companies has the most exposure to the risk that Tesla flagged first?"). An LLM rewriter would help with all four.

The trade is deliberate and worth stating in the README: **the constraint is a guarantee, and guarantees have costs.** The right move is to *measure* the cost rather than assume it away — add a golden-set subset of vocabulary-mismatch and anaphoric questions, report recall on it separately, and put the LLM rewriter on the roadmap with that number attached. "We measured that rule-based query understanding costs us 11 points of recall on paraphrase-heavy questions, and here is what fixing it would cost" is a far stronger position than either ignoring the gap or quietly breaking the constraint.

### 8.4 Citation enforcement — verifiable, not model-asserted

The difference between a demo and a diligence tool is whether a citation can be checked mechanically.

Give each assembled chunk an opaque handle and require the model to reuse it:

```
[C7] Apple Inc. (AAPL) | 10-K FY2024 (period ending 2024-09-28) | Item 1A Risk Factors
     source: AAPL_10K_2024Q3_2024-11-01_full.txt
     https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm
<chunk text>
```

Then enforce **post-hoc, in code, outside the model** (this is the part that makes it verifiable):
1. Parse all `[C#]` handles from the answer; assert each resolves to a chunk actually in the assembled context. Any unresolvable handle is a hard failure, not a warning.
2. Assert every ticker in the answer appears in the retrieved set.
3. Assert every numeric string in the answer appears verbatim in some cited chunk. This is the highest-value check for a financial system, and it is where the §2.7 table work pays off — a number split from its "(dollars in millions)" caption will fail this check for the right reason.
4. Return the citation→chunk mapping in the API response and render it in the UI, so a user can click a claim and read the source span.

Because the SEC URL is in every file's header (§2.2), each citation can link to the actual filing on sec.gov. That is a small touch that materially changes how the output is received: the reader can verify against the primary document without leaving the tool.

**What the prompt must forbid:** answering from parametric knowledge about these companies; presenting an uncited factual claim; substituting general knowledge when a named company has no retrieved context (it must say so explicitly); and presenting a hedge as a finding.

---

## 9. Payload schema design & future-proofing

**The ask:** store a flexible/extensible JSON object alongside each chunk, so that future use cases needing additional properties don't force a re-read and re-index of the whole corpus. Plus "index the whole thing."

This is a good instinct and it is worth doing. But it buys less than it sounds like it buys, and the gap matters enough to state first.

### 9.1 The crux: what is cheap and what is expensive to change after indexing

The dividing line is **whether the thing you want to change feeds the embedded text.**

| Change | Re-embed required? | Cost on this corpus |
|---|---|---|
| Add a new payload field | **No** | Minutes. A `set_payload` sweep. |
| Mutate an existing payload field's value | **No** | Same. |
| Add a filter dimension over data you already stored | **No** | One `create_payload_index` call — but see the HNSW caveat in §9.3 |
| Add a display/grouping/dedup key | **No** | Same. |
| Add entitlements / tenant tags | **No** | Same. |
| Change the **contextual prefix** (§4.5) | **Yes — all chunks** | Re-embed 21,675 chunks ≈ $0.35 |
| Change **chunk size or boundaries** | **Yes — all affected chunks** | Re-chunk + re-embed; needs the source text again |
| Switch to **per-risk-factor chunking** | **Yes** | Same |
| Switch **embedding model** | **Yes — all chunks** | Re-embed; new collection (§9.6) |
| Add a **sparse representation** you didn't index originally | **Yes — sparse side** | Re-encode all chunks |
| Fix the **XBRL preamble strip** (§2.3) or table-caption binding (§2.7) | **Yes** | These change chunk text, so they change vectors |

Qdrant's own API makes the first group explicit: `set_payload` "Set only the given payload values on a point", `overwrite_payload` "Fully replace any existing payload with the given one", and `clear_payload` "removes all payload keys from specified points" — **none of these touch vectors**, and all of them accept a filter instead of an explicit point-id list, so you can rewrite a field across the whole collection without enumerating IDs ([Qdrant payload docs](https://qdrant.tech/documentation/manage-data/payload/)).

So, stated bluntly:

> **An extensible payload future-proofs filtering, faceting, display, grouping and entitlements. It does not future-proof the retrieval representation.** Everything that determines *which* chunk comes back for a given query — chunk boundaries, the prefix, the embedding model, the sparse encoding — lives on the far side of a full re-embed. No payload design can move it across.

That is not an argument against the extensible payload. It is an argument for pairing it with the *other* two mitigations, which are what actually make re-embedding cheap when it comes (§9.6): **keep raw text + offsets so you can re-chunk without re-downloading**, and **use collection aliases so you can rebuild beside the live collection**.

### 9.2 Per-store payload mutability, from first-party docs

The answer to "can I just add JSON fields later?" is store-dependent, and two of the six commonly-recommended stores say no.

| Store | Arbitrary JSON per record? | Add a field later without re-import? | Index a *new* field later? |
|---|---|---|---|
| **Qdrant** | Yes — "any information that can be represented using JSON" | **Yes**, `set_payload` by filter, vectors untouched | Yes, but rebuilding the HNSW index is recommended (§9.3) |
| **Milvus** | Yes — dynamic field / `JSON` type | **Yes** (dynamic field) | Yes — JSON path index, 2.5.x+ |
| **pgvector / Postgres** | Yes — `jsonb` | **Yes**, plain `UPDATE` | **Yes**, and this is the strongest story (§9.2.3) |
| **Weaviate** | No — explicit schema | Property addable, **but pre-existing objects are not re-indexed** | Effectively requires re-import |
| **Elasticsearch** | Partly — `flattened` | New fields yes; **changing an existing field's mapping requires reindex** | Yes for new fields |
| **OpenSearch** | Partly — `flat_object` | Same as ES; **`flat_object` subfields are not filterable at all** | No, for `flat_object` subfields |

#### 9.2.1 Qdrant — the good case

Payloads accept arbitrary nested JSON. Filterable types are integer (i64), float (f64), bool, keyword, geo, `datetime` (v1.8.0+) and `uuid` (v1.11.0+), plus arrays of these, with array semantics that matter for our `item_code` style fields: "When we apply a filter to an array, it will succeed if at least one of the values inside the array meets the condition" ([payload docs](https://qdrant.tech/documentation/manage-data/payload/)).

Payload indexes are created with `create_payload_index` over field schema types `keyword`, `integer`, `float`, `bool`, `datetime`, `text`, `uuid` and `geo` ([indexing docs](https://qdrant.tech/documentation/concepts/indexing/)). Nested JSON is addressed with dot notation — "You can use dot notation to specify a nested field for indexing. Similar to specifying nested filters."

One design warning straight from Qdrant, and it is the single most important sentence for this section: for open-ended key spaces, Qdrant **recommends reshaping dynamic keys into fixed fields rather than indexing each key separately.** That is the docs telling you not to do the naive version of what was asked. §9.4 turns it into a concrete rule.

#### 9.2.2 Milvus — dynamic field, with real JSON path indexing

Setting `enable_dynamic_field=True` at collection creation means "any non-schema-defined fields and their values inserted later on will be saved as key-value pairs in the reserved dynamic field", which is "a reserved JSON field named `$meta`" ([dynamic field docs](https://milvus.io/docs/enable-dynamic-field.md)). Keys with special characters need bracket notation: `$meta["$key"]`.

Milvus also supports indexing a **specific JSON path**, which is more than most stores offer: you supply a `json_path` (e.g. `metadata["supplier"]["country"]`) and a `json_cast_type` (varchar, double, bool, or array variants), with index type `AUTOINDEX` or `INVERTED`. Introduced in **2.5.x** ([JSON field docs](https://milvus.io/docs/use-json-fields.md)). Limitations worth knowing: "Each JSON path supports only one index. You must choose a single `json_cast_type`"; "Each JSON field is limited to 65,536 bytes"; mixed-type values across entities index only the numeric ones and silently skip string-form entries; and values above 2^53 can lose precision. The 65,536-byte cap alone rules out stuffing raw filing text into a Milvus JSON field.

#### 9.2.3 Postgres `jsonb` — the strongest story for genuinely open-ended metadata

If the requirement is literally "arbitrary evolving properties, indexed", Postgres has the best answer of the six, and the docs support saying so.

`jsonb` supports GIN indexing under two operator classes ([Postgres JSON types docs](https://www.postgresql.org/docs/current/datatype-json.html)):
- **`jsonb_ops`** (default) — supports `?`, `?|`, `?&` (key existence), `@>` (containment), and `@?` / `@@` (jsonpath).
- **`jsonb_path_ops`** — supports `@>`, `@?`, `@@` but **not** the key-existence operators.

The docs are explicit about the trade: "A `jsonb_path_ops` index is usually much smaller than a `jsonb_ops` index over the same data, and the specificity of searches is better, particularly when queries contain keys that appear frequently in the data. Therefore search operations typically perform better than with the default operator class." The mechanism: "the former creates independent index items for each key and value in the data, while the latter creates index items only for each value." Its disadvantage: "it produces no index entries for JSON structures not containing any values, such as `{"a": {}}`."

And crucially for our use case, **targeted expression indexes on specific JSON paths** are supported — `CREATE INDEX idxgintags ON api USING GIN ((jdoc -> 'tags'));` — with the docs noting "targeted expression indexes are likely to be smaller and faster to search than a simple index."

So on Postgres you can: add a key to `jsonb` with a plain `UPDATE` (no vector touched), then add a B-tree or GIN expression index on exactly that path, at any time, with no reindex of anything else. That is the closest thing to the future-proofing the user actually wants. **The trade-off is on the retrieval side, not the metadata side:** pgvector has no native hybrid fusion (§5.4), caps `vector` at 2,000 dimensions, and caps `sparsevec` at 1,000 non-zero elements per *indexed* vector — restrictive for BM25/SPLADE vectors over a 30k vocabulary. You would be trading server-side hybrid retrieval for best-in-class metadata flexibility.

#### 9.2.4 Weaviate — a real counterexample

Weaviate's schema is explicit, and adding a property after import does not do what you would hope. From [collection-operations docs](https://docs.weaviate.io/weaviate/manage-collections/collection-operations): "If you add a new property after you import data, there is an impact on indexing" — specifically, "Property indexes are built at import time. If you add a new property after importing some data, pre-existing objects index aren't automatically updated to add the new property."

The documented remedies are to add all properties before importing, or to "Export the existing data from the collection. Re-create it with the new property. Import the data into the updated collection." In other words, on Weaviate the user's stated goal — add a property later without re-indexing — is **not achievable for anything you intend to filter on**.

#### 9.2.5 Elasticsearch / OpenSearch — the sharpest counterexample

Elasticsearch: "In most cases, you can't change mappings for fields that are already mapped. These changes require reindexing" ([mapping docs](https://www.elastic.co/docs/manage-data/data-store/mapping)). OpenSearch states it even more flatly: "**You cannot change the mapping of an existing field; you can only modify the field's mapping parameters.**" ([OpenSearch mappings](https://docs.opensearch.org/latest/mappings/)).

Adding *new* fields is fine via dynamic mapping. The danger is the opposite one: with dynamic mapping, every novel key in every document creates a new field mapping, which is the classic **mapping explosion** — Elasticsearch's docs describe it as accumulating "too many fields in an index, potentially causing out-of-memory errors", mitigated by mapping-limit settings.

The escape hatch is the `flattened` type (ES) / `flat_object` type (OpenSearch, introduced 2.7), which maps a whole JSON object as one field to "help prevent a mappings explosion." But read what it costs. Elasticsearch: "all queries, including range, treat the values as string keywords", highlighting unsupported, and "The flattened mapping type should **not** be used for indexing all document content." OpenSearch is blunter still — `flat_object` "treat[s] the entire JSON object as a string", subfields "are not indexed for fast lookup", and the documented list of things it does not support includes:

> "Type-specific parsing. Numerical operations, such as numerical comparison or numerical sorting. Text analysis. Highlighting. Aggregations of subfields using dot notation. **Filtering by subfields.**"

**"Filtering by subfields" is exactly what a chunk payload exists to do.** A `fiscal_year` range filter inside a `flat_object` is not a range filter — it is a string comparison, or a full index scan. This is the concrete reason "just put everything in an open JSON blob" is the wrong default, and it generalises beyond OpenSearch: untyped blobs lose typed filtering everywhere, to varying degrees.

### 9.3 The cost of "index the whole thing as well"

Read as: index every payload field, and also keep the full raw document text stored. Both halves have real costs.

**Indexing every field.** Qdrant's own guidance: "Payload indexes occupy additional memory and disk space, so it is recommended to only apply payload indexes for those fields that are used in filtering conditions" ([indexing docs](https://qdrant.tech/documentation/concepts/indexing/)). Unindexed fields still *work* for filtering — they are just resolved by scan rather than by index, so the cost is latency, not capability. Since v1.11.0 payload indexes can also be pushed to `cached` or `cold` memory tiers to reduce heap at some latency cost.

There is also a sequencing cost that undercuts naive "add the index later" optimism. Verbatim:

> "**Payload indexes should be created before ingesting data.** [Qdrant's filterable HNSW index] only benefits from additional filter-aware edges when it is generated after the payload indexes have been created."

and

> "If you create a payload index after data has already been ingested, you need to rebuild the HNSW index to take advantage of the new payload indexes."

So adding a filter dimension later is **cheap but not free**: no re-embedding, but a HNSW rebuild if you want filter-aware graph edges. For 21,675 chunks that is minutes, not hours — but it is a real step, and it is exactly the kind of detail that turns "we future-proofed it" into a surprise later. Declare the filterable fields you can anticipate *up front* even if you leave them null.

**Storing full raw filing text in every chunk's payload.** This is the expensive half, and the numbers on this corpus are decisive. At 800 tokens with no overlap the corpus yields **21,793 chunks across 246 filings — a mean of 88.6 chunks per filing, max 407**:

| Strategy | Payload text volume | Ratio |
|---|---|---|
| **A** — full filing text in every chunk's payload | **8,813,402,814 chars ≈ 8.81 GB** | 125× |
| **B** — chunk text only (≈ the corpus once) | 70,266,346 chars ≈ 70 MB | 1× |
| **C** — offsets only (`source_file` + `char_start`/`char_end`, ~64 chars/chunk) | ≈ 1,394,752 chars ≈ **1.4 MB** | 0.02× |

The worst single filing makes it vivid: `JPM_10K_2026-02-13_full.txt` is 1,276,935 chars and produces 407 chunks, so duplicating its text into every chunk payload costs **520 MB from one filing**.

**Recommendation:** store the chunk's own text (Option B) plus **offsets** into the source file, and keep the full document in a separate document store — the filesystem is fine at this scale, since the whole corpus is 81 MB. Hydrate parent context on read. This is the same mechanism that powers parent-document retrieval (§4.6), so you get small-to-big for free from a schema decision you were making anyway. If payloads do grow large, Qdrant's cold (on-disk) payload tier is the right setting — the docs note cached storage "may require a lot of space to keep all the data warm in RAM, especially if the payload has large values attached", while indexed fields stay in RAM regardless: "Qdrant will preserve all values of the indexed field in RAM regardless of the payload storage type" ([storage docs](https://qdrant.tech/documentation/concepts/storage/)).

**Tenancy, since "internal solution" implies entitlements later.** Qdrant explicitly discourages a collection per tenant: "Creating a separate collection for each tenant is rarely the most efficient approach. Each collection carries its own resource overhead, so creating many collections can quickly become expensive", and Qdrant Cloud "limits each cluster to a maximum of 1000 collections by default." The recommended pattern is payload-based partitioning with an `is_tenant=true` keyword payload index, which "organizes the storage structure to co-locate vectors of the same tenant together", enabling a sequential rather than scattered disk read ([multitenancy docs](https://qdrant.tech/documentation/guides/multiple-partitions/)).

**Put a `tenant_id` (or `entitlement_group`) field in the schema now, even if it is a constant.** Adding the field later is cheap; discovering later that you need it *and* that the storage layout should have been tenant-co-located is the expensive version. This is the one genuinely load-bearing piece of future-proofing in the whole section, because it is the one where the layout — not just the value — depends on having declared it.

### 9.4 Recommended payload schema

```python
{
  # ---- stable identity -------------------------------------------------
  "chunk_id":        "AAPL-10K-2024-P2I7-0007",   # deterministic, reproducible
  "doc_id":          "AAPL_10K_2024Q3_2024-11-01",
  "source_file":     "AAPL_10K_2024Q3_2024-11-01_full.txt",
  "char_start":      412_887,        # offsets into the POST-STRIP body (§2.3)
  "char_end":        416_204,        # -> re-chunk & hydrate parents without re-download
  "chunk_index":     7,
  "token_count":     786,

  # ---- retrieval-critical filterables (typed + indexed) ---------------
  "ticker":          "AAPL",                      # keyword
  "cik":             "0000320193",                # keyword (string: leading zeros)
  "company":         "Apple Inc",                 # keyword
  "form_type":       "10-K",                      # keyword
  "fiscal_year":     2024,                        # integer  -> range filters
  "period_end":      "2024-09-28T00:00:00Z",      # datetime (v1.8.0+)
  "filing_date":     "2024-11-01T00:00:00Z",      # datetime
  "part":            "II",                        # keyword  -> 10-Q collision (§2.6)
  "item_code":       "7",                         # keyword  -> "1A", "7", "7A"
  "item_title":      "Management's Discussion and Analysis...",
  "section_key":     "II-7",                      # keyword  -> the real join key
  "disclosure_type": "baseline",                  # keyword  -> baseline|delta (§4.4)
  "content_type":    "narrative",                 # keyword  -> narrative|table|heading
  "tenant_id":       "default",                   # keyword, is_tenant=true (§9.3)

  # ---- provenance: what made this point, and with what ----------------
  "schema_version":   3,            # integer — this payload contract
  "chunker_version":  "sec-chunk-2.1.0",
  "ingest_version":   "ingest-2026.08.19",
  "embedding_model":  "text-embedding-3-small",
  "prefix_template":  "v2",         # the contextual prefix that was embedded (§4.5)
  "text_sha256":      "9f2c…",      # dedup + change detection

  # ---- deliberately open: unanticipated future properties ------------
  "ext": {}                          # nested; index specific paths on demand
}
```

**The rule for what goes where.** Promote a field to the typed top level when *any* of these is true:
1. it is, or plausibly will be, a **filter or range** predicate (`fiscal_year`, `period_end`);
2. it is a **join or grouping key** (`doc_id`, `section_key`, `tenant_id`);
3. it needs **type semantics** — numeric ordering, date ranges, boolean logic;
4. it affects **storage layout** (`tenant_id`).

Everything else — a downstream scoring annotation, a UI badge, an experiment tag, a third-party enrichment — starts in `ext` and gets promoted if and when it becomes a predicate. Promotion is a `set_payload` sweep plus a `create_payload_index`, which is cheap (modulo the HNSW rebuild in §9.3).

**Why "just put everything in an untyped blob" is a mistake**, concretely:
- **You lose typed filtering.** OpenSearch `flat_object` does not support "Numerical operations, such as numerical comparison or numerical sorting" or "Filtering by subfields" at all; Elasticsearch `flattened` treats "all queries, including range… as string keywords." A `fiscal_year >= 2024` filter over a blob is a string comparison or a scan. Since *every* question in this project is entity- and period-scoped, that is the hot path, not an edge case.
- **You still need path-level indexing anyway.** Qdrant needs dot-notation index declarations; Milvus needs an explicit `json_path` + `json_cast_type` per path; Postgres needs an expression index per path. The blob does not save you the declaration — it just delays it and hides it.
- **No schema validation.** With 246 filings and five header-format families (§2.5), silent metadata drift is the realistic failure. A typed schema plus `schema_version` catches "this generation of points has `item_code` as an int and that one as a string" at write time. A blob catches it never, and it surfaces as a filter that quietly returns nothing.
- **Qdrant's own docs advise against it** for open-ended keys, recommending you reshape dynamic keys into fixed fields rather than index each key separately.

So: **typed core, open annex.** Not one or the other.

### 9.5 Schema versioning and migration

`schema_version`, `chunker_version`, `embedding_model` and `prefix_template` on every point are what make future change *safe* rather than merely *possible*. They give you four things you otherwise cannot have:

1. **Detect mixed-generation points.** A single filter — `schema_version < 3` — tells you exactly what is stale, and how much. Without it you cannot distinguish "not backfilled yet" from "backfilled with a null value", which is the difference between a bug and a fact.
2. **Migrate incrementally.** Backfill in batches with `set_payload` by filter, monitoring the count of remaining old-version points. No downtime, no full rewrite, resumable if it fails halfway.
3. **A/B two chunking generations.** `chunker_version` lets both generations coexist in one collection and be compared on the same golden set (§7.6) by filtering each retrieval to one generation. This is how you'd actually settle the open question in §4.3 (per-risk-factor vs fixed window) with evidence instead of argument — and it only works if the field is there from the start.
4. **Explain a regression.** When retrieval quality moves, the first question is "what changed" — and provenance on the point answers it directly.

**Zero-downtime rebuilds via aliases.** For anything requiring a re-embed, build the new collection beside the live one and swap atomically. Qdrant aliases are designed for exactly this: "Aliases are additional names for existing collections. All queries to the collection can also be done identically, using an alias instead of the collection name", and critically "since all changes of aliases happen atomically, no concurrent requests will be affected during the switch." The docs name the motivating use case directly: "In a production environment, it is sometimes necessary to switch different versions of vectors seamlessly. For example, when upgrading to a new version of the neural network" ([collections docs](https://qdrant.tech/documentation/concepts/collections/#collection-aliases)).

**Point the application at an alias from day one** (`filings` → `filings_v1`). It costs nothing now and it is the difference between a blue-green swap and a maintenance window later.

**Do not mix embedding models in one collection.** Vectors from two different models are not comparable — distances between them are meaningless, so a single ANN index over both returns results ranked by an incoherent metric, and any fusion or threshold tuned on one is invalid for the other. Dimensionality often differs too (1536 vs 1024 vs 3072), which makes it a hard error rather than a silent one, but *equal* dimensionality is the dangerous case: it will "work" and be wrong. A model change means a new collection plus an alias swap — which is precisely why `embedding_model` belongs on the point, so a mistake is detectable rather than invisible. (Qdrant does support multiple *named* vectors per point, which is a legitimate way to hold two representations side by side — but that is a deliberate schema decision made up front, not a migration path.)

### 9.6 Honest verdict

**Does this future-proofing deliver what the user hopes?** Partly — and the part it delivers is worth having. But the framing needs correcting, because the most expensive future changes are exactly the ones it does not cover.

**Absorbed for free** (payload update, no re-embed, minutes of work):
- a new filter dimension over data you already stored — sector, SIC code, auditor, exchange, market cap band;
- a new display or UI field — badges, snippet overrides, confidence annotations;
- a new grouping key — group by filing, by section, by fiscal period;
- entitlements and tenancy — *provided* `tenant_id` exists from the start (§9.3);
- dedup keys and near-duplicate cluster IDs;
- downstream enrichment — sentiment scores, extracted entities, human review flags;
- anything that is a *label on* a chunk rather than a *change to* a chunk.

**Not absorbed** — these all require re-embedding, and no payload design changes that:
- better chunking (per-risk-factor, table-aware, different size);
- a new embedding model, including a "free" upgrade to the same vendor's next version;
- adding or changing the contextual prefix (§4.5);
- adding a sparse representation you did not index originally;
- fixing the preprocessing (XBRL strip, reflow, table-caption binding) — these change chunk *text*, therefore vectors;
- late chunking, which changes how embeddings are produced entirely.

Note the asymmetry: the "not absorbed" list is where the retrieval-quality wins live. The extensible payload protects the cheap stuff and leaves the expensive stuff exactly as expensive as it was.

**The two mitigations that actually reduce the cost of the expensive changes**, and which matter more than the payload design:

1. **Keep raw text + offsets** (`source_file`, `char_start`, `char_end`) — the `char_start`/`char_end` fields in §9.4 are not bookkeeping, they are the re-chunking insurance policy. With them, changing chunk strategy is a local recompute over an 81 MB corpus you already have on disk: no re-download, no re-parse from scratch, no dependency on SEC rate limits (§3, fetch note). Without them, "re-chunk" means re-running the whole ingest and hoping it is deterministic.
2. **Alias-fronted collections** — so any re-embed is a background build plus an atomic swap rather than an outage.

**Bottom line to give the user:** yes, build the extensible payload — it is cheap and it genuinely absorbs a whole class of future requests. But the sentence "so we never have to re-index the corpus" is not one the design supports. The accurate version is: *"we never have to re-index for a new metadata, filtering, or display requirement; and when we do need to re-index for a better retrieval representation, offsets plus aliases make it a background job measured in dollars and minutes rather than a project."* On this corpus that is a **$0.35 embedding cost over 21,675 chunks** — which is the real reason not to over-engineer around avoiding it.

## 10. Prior art: what survives scrutiny, what needs revisiting

> **Caveat on scope.** The prior-art repo was **moved to `/Users/jordan/Developer/rag-old/`, not deleted** (see §2 note) — an earlier revision of this note reported it deleted, which was incorrect. I read `SPEC.md` in full. I did **not** read `src/`, `eval/`, `CLAUDE.md` or `README.md`, so the verdicts below are against the SPEC as written. Two implementation facts were independently confirmed from the repo by the main session and are marked **[confirmed in code]** where they appear.

### Survives scrutiny

| SPEC decision | Verdict | Note |
|---|---|---|
| Hybrid dense + sparse rather than choosing | **Correct, and the reasoning is good.** | The "filings are saturated with exact identifiers *and* users ask in paraphrase" argument is the right argument, and it is better grounded in this corpus than in BEIR (§5.2). |
| RRF is rank-based, avoiding cosine-vs-BM25 score reconciliation | **Correct.** | "Score normalization across those two scales is fragile" is a fair statement of why RRF is the robust default. The gap is that it does not acknowledge RRF's own failure mode (§6.3). |
| Contextual metadata prefix as "the highest-leverage 20 lines" | **Correct, and understated.** | Measurement backs it hard: 40.5% of chunks are company-anonymous, 96.6% lack the ticker (§4.5). The SPEC's intuition about "company-anonymous in embedding space" is exactly right. |
| Per-entity quota retrieval | **Correct, and the most important call in the SPEC.** | Now empirically justified by the JPM-4-vs-AAPL-16 asymmetry (§2.9) plus chunk anonymity (§4.5). |
| Deterministic query understanding to preserve the one-call constraint | **Correct.** | Including the SPEC's honesty that "an LLM query-rewriter would probably improve recall". §8.3 adds: measure that cost rather than assuming it. |
| Metadata as "the retrieval mechanism, not bookkeeping" | **Correct.** | The single best line in the SPEC, and §4.5 proves it. |
| Eval harness as the bridge between technical and business audiences; ablation table as the money artifact | **Correct.** | §7.6 extends the row set and, importantly, adds the metric columns that make row 9 legible. |
| Out-of-corpus refusal as a must-demo behaviour | **Correct.** | Also the cheapest thing to verify deterministically (§7.4). |
| "Do not write the chunker before you have looked at three actual filings" | **Correct — and it should have said ten.** | The five header variants and the Amazon/Alphabet/Meta/Morgan-Stanley edge cases (§2.5) are not visible in three files. |

### Needs revisiting

**1. `k=60` — the rationale is folklore and the code likely contradicts it.** *(§6.1, §6.2)*

The SPEC says: "Keep `k=60` (the Cormack et al. default) and note weighted RRF as a tuning knob you deliberately left at default rather than overfit."

Three problems.
- k=60 is not "the default" in the sense implied — it is a value the paper **tuned on a pilot** and then reported as "near-optimal, but… not critical". In the paper's own Table 1, **k=80 scores higher than k=60**, and k=30–100 are within .0009 MAP.
- The provenance is fusion of **30 configurations of one lexical engine** on 2009 TREC ad-hoc topics — not a 2-leg dense+sparse hybrid.
- **Most importantly:** the SPEC's own code snippet calls `FusionQuery(fusion=Fusion.RRF)` on Qdrant, whose ranking constant **defaults to 2** (`DEFAULT_RANKING_CONSTANT_K = 2`), configurable only from v1.16.0. So the system as specified is **not running k=60** — it is running k=2. The prose and the code disagree, and the prose is what would be defended in the demo.

**Corrected version:** set the constant explicitly, sweep it in the ablation ({2, 10, 60, 100}), and report the chosen value with the paper's "not critical" finding as context. The restraint the SPEC was reaching for is better expressed as "we measured k and it didn't matter much, consistent with Cormack et al." — which is both true and stronger.

**2. "Only mainstream OSS store with first-class named dense + sparse vectors in one collection and server-side RRF" — not correct.** *(§5.4)*

Verified from each vendor's own docs: **Weaviate** (hybrid with `alpha`, `relativeScoreFusion` default since v1.24), **Milvus** (dense + sparse vector fields in one collection, `RRFRanker`/`WeightedRanker` server-side), **Elasticsearch** (RRF "entirely on the server within a single `_search` request", `rank_constant` default 60), **Vespa** (`reciprocal_rank()` in a global-phase ranking expression), and **OpenSearch** (normalization-processor + score-ranker-processor) all do this. Only pgvector genuinely does not — its README says users "must combine it with Postgres's built-in text search and implement fusion methods like Reciprocal Rank Fusion… separately".

**Corrected version:** Qdrant is still a good choice — local Docker, clean client, `Formula` queries for recency, and it does appear to be the only one of these shipping **DBSF**, which is a real differentiator. Justify it on fit and on DBSF, not on uniqueness. An interviewer who has used Weaviate or Milvus will catch the original claim, and it is the kind of overreach that costs credibility on everything else.

**3. The 800-token justification is reasoning-shaped but unsourced — and the real reason is better.** *(§4.3, §4.7)*

The SPEC argues: "Below ~500 tokens a risk factor gets severed from its 'we may be unable to...' consequence clause… Above ~1200 the embedding averages over too many topics and precision drops. 800 is the defensible middle."

The conclusion is roughly right; the argument is not evidence. There is no citation, and both the 500 and 1200 bounds are asserted. What is actually true, and better:
- **The measured median risk factor in this corpus is ~607 tokens** (p90 1,706). So ~600–800 is not a "defensible middle" — it is an approximation of the natural semantic unit, which is why it works.
- Once you know that, the stronger move is to chunk *at* the unit rather than approximate it (§4.3), with [17 CFR 229.105(a)](https://www.ecfr.gov/current/title-17/section-229.105) — "each risk factor **should be set forth under a subcaption** that adequately describes the risk" — as the justification.
- The embedding models impose no relevant ceiling (8,192 tokens for OpenAI, 16,000 for `voyage-finance-2`), so the "above 1200 precision drops" claim is not about model limits. **The real ceiling is the reranker**: `bge-reranker-v2-m3` — which the SPEC itself names in its future-state roadmap — truncates at **512 tokens**, silently discarding ~36% of an 800-token chunk.

**Corrected version:** per-item policy (§4.2), per-risk-factor chunks for Item 1A, ~800 for flowing narrative, table-block-aligned for Item 8 — with the size swept in the ablation and the reranker's context limit as the binding constraint.

**4. The chunking preprocessing list is missing the two biggest items.** *(§2.3, §2.4)*

The SPEC's step 3 is "Drop boilerplate: exhibit indexes, signature blocks, XBRL tag dumps, TOC." Directionally right, but the priorities are inverted relative to what is actually in the files:
- It treats "XBRL tag dumps" as one item in a list of four. It is **17.7% of all body tokens** (3,730,752 of 21,071,458) and it is concentrated in a single line per file, up to 86,721 tokens in one line. It is the first thing to do and it is a one-line fix (§2.3).
- **It does not mention reflow at all** — and without reflow there are no paragraph boundaries to chunk on, because the HTML stripper emitted none (§2.4). The SPEC's step 2 says "recursive character/token split… preferring paragraph then sentence boundaries", but on this corpus those boundaries **do not exist**: 216/246 files have a line over 20,000 characters and Tesla's whole Item 1A is one 79,624-char line. As specified, the splitter would silently fall through to splitting on spaces.

Conversely, exhibit indexes and signature blocks are minor (141 and 270 occurrences), and the page-furniture stamps are only ~8,000 tokens — worth stripping for **parse correctness**, since they wedge between a section end and the next header, not for token savings.

**5. Section-splitting is under-specified for what the corpus actually contains.** *(§2.5, §2.6)*

The SPEC says: "Split on SEC item headers (`Item 1A.`, `Item 7.`, `Item 8.`, `Part II Item 1A.`, etc.) via regex with a fallback to whole-document if headers don't parse."

The instinct to have a fallback is right. But the regex as sketched matches only one of the **five** header forms present, and would fail outright on Alphabet/Meta (`Item 1.Financial Statements`, zero spaces), Tesla (`ITEM 1A. RISK FACTORS`, all caps), and Apple (headers glued behind page furniture). It also has no defence against the two false-positive classes: **30.7% of all `Item N` mentions are cross-references**, and `Item 601(a)` Reg S-K citations produce phantom headers (the sole match in Intel's 10-K is one of these).

Whole-document fallback is also too coarse a fallback: a 396,452-token JPMorgan 10-K with no section labels is close to useless for item-filtered retrieval, and item-section metadata is what §7.3's `ItemPrec@k` measures.

**Corrected version:** the multi-form, TOC-anchored, monotonic aligner of §2.5 — which gets failures to 1/246 and median 10-K coverage to 78% — with a *graded* fallback (item-level → part-level → whole-document) rather than a binary one.

**6. The 10-Q Part I/II collision is named but its consequence is not.** *(§2.6, §4.4)*

The SPEC's metadata model has a single `item_section` string ("Item 1A — Risk Factors") and its splitting list mentions "Part II Item 1A.". So the collision was noticed. But two consequences are missing:
- The item key **must** be `(part, item)`. 125 of 157 10-Qs exhibit the collision; a key on `item` alone merges Apple's *Financial Statements* with its *Legal Proceedings*.
- **More seriously, and not mentioned anywhere in the SPEC:** Form 10-Q Item 1A contains only *"any **material changes** from risk factors as previously disclosed in the registrant's Form 10-K"*. Measured, 10-Q Item 1A has a median of **876 tokens** vs the 10-K's **11,153**. A temporal question answered from 10-Q risk factors alone presents an incremental amendment as a complete risk profile. This is a correctness bug that produces plausible wrong answers and is **invisible to recall@k** — which is exactly why §7.3's temporal-scope metric needs a separate "baseline present" boolean.

**7. Golden set of ~25 questions is too small to support the 5-row ablation.** *(§7.6, §7.7)*

25 questions across 5 categories is 3–8 per category. Differences of a few points will not be distinguishable from noise, and the SPEC's own table has 5 configurations to compare. §7.5 recommends 40–60 questions with heavier weighting on comparative and temporal questions, and §7.7 recommends reporting win/loss/tie counts and per-question deltas rather than means alone.

The SPEC's instinct to label at "`source_file` + section" granularity rather than chunk granularity is **exactly right** and is the reason 40–60 is affordable — worth keeping and stating as a deliberate methodological choice rather than a time-pressure compromise.

**8. Missing entirely: the XBRL numeric path.** *(§3.4)*

The SPEC lists "XBRL structured financials joined to narrative text" under **future state**. Given that one of the three stated demo questions is *"How has NVIDIA's revenue and growth outlook changed over the last two years?"*, this is arguably present-state. A single unauthenticated GET to `data.sec.gov/api/xbrl/companyconcept/CIK0001045810/us-gaap/Revenues.json` returns NVIDIA's exact annual revenues with accession numbers for citation. Compared with extracting those figures from pipe-delimited table rows that may have been split from their "(dollars in millions)" caption, it is both more accurate and less work.

It does not break the one-call constraint — it is retrieval, formatted into the same single prompt. **Recommendation: build the deterministic quantitative/qualitative router (§3.4) in-scope, and demo it.** "We route numeric questions to the SEC's own structured data and narrative questions to the text index" is a genuinely strong architectural answer to a question the panel is likely to probe.

**9. Missing: table-caption binding.** *(§2.7)*

The SPEC's chunking section does not mention tables. Since 22.2% of corpus characters are pipe-table rows, and since captions and units sit on the *preceding* narrative line while column-year headers sit on their own label-less row, a naive splitter will routinely emit numbers stripped of their scale and period. For a financial diligence tool that is the highest-consequence silent failure available. The fix is ~40 lines (§2.7).

---

## 11. Open questions / needs a decision

These are genuine forks. I have stated the trade-off rather than resolving it.

**Q1 — XBRL-numeric path vs pure text retrieval.**
*For the router:* exact figures, accession-level citations, no extraction risk, one HTTP call, and it directly serves one of the three demo questions. *Against:* a second data path to build, test and explain; XBRL tag selection is genuinely fiddly (`Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax` vs company extensions — NVIDIA's own filings use several); the frames API aligns to calendar quarters while issuers have arbitrary fiscal years (§3.4); and `data.sec.gov` has no CORS so it needs proxying. *My lean:* build it for a narrow, well-tested set of tags (revenue, net income, total assets, operating margin components) and route conservatively — when the router is unsure, use text. But this is a scope call, not a technical one.

**Q2 — Managed vs self-hosted embeddings.**
*Managed (`text-embedding-3-small`):* $0.35 for the whole index, no GPU, no ops, 8,192-token ceiling. *Self-hosted (BGE/E5/Nomic):* no per-token cost, no data leaving the network — which for filings is a non-issue since they are public, but the *queries* may encode a firm's deal interests, which is genuinely sensitive. Self-hosting also unlocks **late chunking** (§4.5c), which needs token-level pooling that a hosted endpoint does not expose. *Unresolved:* whether query confidentiality justifies the ops burden. Note this is the one place where a public corpus still has a real privacy dimension, and a PE firm may care a lot.

**Q3 — Rerank at all?**
*For:* the largest single marginal gain in Anthropic's numbers (49%→67% failure reduction), and BEIR credits reranking with the best zero-shot performance. *Against:* the only component with recurring per-query cost and latency; `bge-reranker-v2-m3`'s 512-token limit couples it to chunk size (§4.7); `jina-reranker-v2` is CC-BY-NC and therefore unusable commercially. *Unresolved:* whether the gain on *this* corpus and *these* question types justifies it. That is what ablation row 10 is for — decide from the table, not from priors.

**Q4 — Chunk unit for Item 1A: per-risk-factor or fixed window?**
*For per-risk-factor:* mandated by [229.105(a)](https://www.ecfr.gov/current/title-17/section-229.105), matches the measured median (607 tokens), and self-contained chunks need no overlap. *Against:* heading detection is heuristic and under-counts (§4.3), so a fraction of chunks will be mis-bounded — and a mis-bounded chunk may be worse than a cleanly-cut arbitrary window. *Unresolved:* the detector's actual precision/recall, which I did not measure against hand-labelled ground truth. That measurement is a half-day and would settle it.

**Q5 — Fusion method: RRF, DBSF, or query-dependent.**
RRF is robust and ignores magnitude; DBSF and weighted fusion use magnitude and can be better when one leg is confidently right (§6.3) — which, given how identifier-dense filings are, may be common here. A query-dependent policy (score fusion when a lexical needle is detected, RRF otherwise) is deterministically implementable but adds a branch to explain and test. *Unresolved:* whether the added complexity earns its keep. Rows 3 and 4 of the ablation should tell you.

**Q6 — Does the corpus support sector questions at all?**
"Regulatory risks facing major pharmaceutical companies" resolves to JNJ (17 filings), PFE (15), and then ABBV, MRK, LLY, TMO at **one filing each** (§2.9). *Unresolved:* whether to answer such questions with an explicit coverage caveat, restrict them to well-covered sectors, or decline. I lean toward answering *with* a machine-generated coverage statement ("based on 2 companies with multi-year coverage and 4 with single filings"), because it is honest and it demonstrates the system knows its own limits — but it is a product decision.

**Q7 — Item 3 Legal Proceedings: chase the cross-reference at index time?**
[229.103](https://www.ecfr.gov/current/title-17/section-229.103) permits Item 3 to point at MD&A, Risk Factors, or the notes, and measured median Item 3 is **57 tokens**. *For chasing:* legal-exposure questions are core diligence, and the content does exist elsewhere in the document. *Against:* resolving "see Note 12" to the right span is a real parsing task on text with no reliable structure. *Unresolved.* A cheap middle path: index Item 3 as-is but tag it `is_pointer: true` so the retriever can expand to the same filing's Item 8 notes when a legal question fires.

**Q8 — Pre-filter vs post-filter semantics per store.**
§5.4 flags this as unverified and it is the highest-value remaining verification task, because post-filtering can return **zero** chunks for the thinnest-covered company in a comparative question. The per-entity quota design (§8.2) largely insulates the system either way, which is a good reason to keep quotas even if pre-filtering is confirmed.

**Q9 — Metadata flexibility vs native hybrid retrieval.**
This is the fork §9.2.3 surfaces and it is a genuine one. **Postgres `jsonb`** gives the best story for arbitrary evolving metadata — add a key with an `UPDATE`, add a GIN or expression index on exactly that path, any time, no reindex of anything else. But pgvector has **no native hybrid fusion** (§5.4), caps `vector` at 2,000 dimensions, and caps `sparsevec` at 1,000 non-zero elements per indexed vector. **Qdrant** gives server-side hybrid + DBSF and arbitrary JSON payloads, but wants filterable fields declared before ingest for filter-aware HNSW edges. *Unresolved:* whether the metadata flexibility is worth hand-rolling fusion in application code. *My lean:* no — fusion is the harder thing to get right, and the §9.4 typed-core schema makes Qdrant's declare-up-front constraint cheap to satisfy. But if the future roadmap is genuinely metadata-heavy (entitlements, many enrichment passes, per-user annotations) rather than retrieval-heavy, the calculus flips.


---

## Appendix A — Sources

Every link below was fetched during this session unless marked otherwise.

**Regulator / primary law**
- [Form 10-K](https://www.sec.gov/files/form10-k.pdf) — retrieved via `curl` with declared User-Agent; WebFetch returns 403
- [Form 10-Q](https://www.sec.gov/files/form10-q.pdf) — same
- [17 CFR 229.105 — Risk factors](https://www.ecfr.gov/current/title-17/section-229.105) — retrieved via eCFR renderer API
- [17 CFR 229.303 — MD&A](https://www.ecfr.gov/current/title-17/section-229.303) — same
- [17 CFR 229.103 — Legal proceedings](https://www.ecfr.gov/current/title-17/section-229.103) — same
- [17 CFR 229.106 — Cybersecurity](https://www.ecfr.gov/current/title-17/section-229.106) — same
- [EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — retrieved via `curl`
- `data.sec.gov/api/xbrl/companyconcept/CIK0001045810/us-gaap/Revenues.json` — retrieved and parsed directly

**Papers**
- [Cormack, Clarke & Buettcher — Reciprocal Rank Fusion, SIGIR 2009](http://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf) — full text read
- [Robertson & Zaragoza — The Probabilistic Relevance Framework: BM25 and Beyond](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) — formula section read
- [Thakur et al. — BEIR (arXiv:2104.08663)](https://arxiv.org/abs/2104.08663) — abstract
- [Formal et al. — SPLADE v2 (arXiv:2107.05720)](https://arxiv.org/abs/2107.05720) — abstract
- [Liu et al. — Lost in the Middle (arXiv:2307.03172)](https://arxiv.org/abs/2307.03172) — abstract
- [Muennighoff et al. — MTEB (arXiv:2210.07316)](https://arxiv.org/abs/2210.07316) — abstract
- [Urbano et al. — Statistical Significance Testing in IR (arXiv:1905.11096)](https://arxiv.org/abs/1905.11096) — abstract only
- [Es, James, Espinosa-Anke & Schockaert — Ragas (arXiv:2309.15217)](https://arxiv.org/abs/2309.15217) — abstract

**Vendor / implementation documentation**
- [Qdrant — Hybrid Queries](https://qdrant.tech/documentation/concepts/hybrid-queries/)
- [Qdrant client — `hybrid/fusion.py`](https://github.com/qdrant/qdrant-client/blob/master/qdrant_client/hybrid/fusion.py)
- [Qdrant — FastEmbed SPLADE](https://qdrant.tech/documentation/fastembed/fastembed-splade/)
- [Qdrant — Payload](https://qdrant.tech/documentation/manage-data/payload/)
- [Qdrant — Indexing / payload index](https://qdrant.tech/documentation/concepts/indexing/)
- [Qdrant — Storage (payload memory tiers)](https://qdrant.tech/documentation/concepts/storage/)
- [Qdrant — Collection aliases](https://qdrant.tech/documentation/concepts/collections/#collection-aliases)
- [Qdrant — Multitenancy / multiple partitions](https://qdrant.tech/documentation/guides/multiple-partitions/)
- [Weaviate — Hybrid search](https://docs.weaviate.io/weaviate/search/hybrid)
- [Weaviate — Collection operations](https://docs.weaviate.io/weaviate/manage-collections/collection-operations)
- [Milvus — Multi-vector search](https://milvus.io/docs/multi-vector-search.md)
- [Milvus — Enable dynamic field](https://milvus.io/docs/enable-dynamic-field.md)
- [Milvus — Use JSON fields (JSON path indexing)](https://milvus.io/docs/use-json-fields.md)
- [PostgreSQL — JSON types & `jsonb` indexing](https://www.postgresql.org/docs/current/datatype-json.html)
- [Elasticsearch — Mapping](https://www.elastic.co/docs/manage-data/data-store/mapping), [`flattened` field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/flattened)
- [OpenSearch — Mappings](https://docs.opensearch.org/latest/mappings/), [`flat_object` field type](https://docs.opensearch.org/latest/mappings/supported-field-types/flat-object/)
- [Elasticsearch — Reciprocal Rank Fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
- [Vespa — Hybrid search tutorial](https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html)
- [Vespa — nativeRank](https://docs.vespa.ai/en/nativerank.html)
- [pgvector](https://github.com/pgvector/pgvector)
- [OpenSearch — Hybrid search](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/) — partial
- [OpenAI — Embeddings guide](https://developers.openai.com/api/docs/guides/embeddings), [`text-embedding-3-small` model page](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- [Voyage AI — Embeddings](https://docs.voyageai.com/docs/embeddings)
- [Cohere — Rerank](https://docs.cohere.com/docs/rerank), [Reranking best practices](https://docs.cohere.com/docs/reranking-best-practices), [Pricing](https://cohere.com/pricing)
- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [jinaai/jina-reranker-v2-base-multilingual](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual)
- [Anthropic — Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [Jina — Late Chunking](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
- [LlamaIndex — Node Parser Modules](https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/)
- [Ragas — Available metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
- [NIST `trec_eval`](https://github.com/usnistgov/trec_eval); `m_ndcg.c` and `m_ndcg_cut.c` source read directly
- [TREC common evaluation measures](https://trec.nist.gov/pubs/trec16/appendices/measures.pdf)
- [BEIR repository](https://github.com/beir-cellar/beir)

**Fetches that failed (stated for honesty)**
- `sec.gov` and `ecfr.gov` reject the WebFetch user-agent (403 / interstitial redirect); worked around with `curl` + declared UA and the eCFR API.
- SEC rate-limited my retry batch (403 "Request Rate Threshold Exceeded"), so the **Financial Statement Data Sets** page, the **EDGAR full-text search API**, and SEC's own **Fair Access guidelines** page are **unverified**.
- `dl.acm.org` returned 403 — the original **Järvelin & Kekäläinen (2002)** paper could not be retrieved; nDCG definitions come from the NIST reference implementation, which cites it.
- `platform.openai.com/pricing` and `openai.com/api/pricing` returned 403/404; embedding prices come from the `developers.openai.com` model pages.
- LangChain's `ParentDocumentRetriever` page now redirects to a general overview; the LangChain variant of that pattern is **unverified** (LlamaIndex's equivalent is verified).
- The **MTEB leaderboard** Space renders client-side; its retrieval-subset metric is **unverified**.
- The **OpenSearch score-ranker-processor** reference page could not be retrieved; its RRF default and introducing version are **unverified**.
- **Cohere Embed** per-token pricing is not on the pricing page I fetched (only instance-based Model Vault rates); **unverified**.
- **BGE / E5 / Nomic embedding** model cards were not fetched; their specs are **unverified** here.
- No originating paper found for **DBSF**; treated as vendor-documented.

## Appendix B — Reproducing the corpus measurements

All numbers in §2 and §4 were produced with `tiktoken` 0.14.0 / `cl100k_base` against `/Users/jordan/Developer/eliza/sec-rag/edgar_corpus/`. The measurement scripts were written to a session scratchpad and are not committed; the load-bearing logic is small enough to reproduce from the note:

- **XBRL strip** — split body at `\n=+\n`, then cut at `re.search(r'UNITED\s*STATES\s*SECURITIES AND EXCHANGE COMMISSION', body)`. Found in 244/246 files; removes 3,730,752 tokens (17.7%).
- **Block reflow** — split on `(?<=[.!?"'])(?=[A-Z"])`, re-joining any piece whose predecessor ends in a known abbreviation, then additionally split on `(?<=[a-z)\]])(?=[A-Z][a-z]{2,})` to separate glued headings.
- **Header detection** — `(?<![A-Za-z0-9])(ITEM|Item)\s{0,6}(\d{1,2})([A-C])?\s*[.:—–]?\s*(?:\|\s*)?(?=[A-Z\[])`, then reject: item number > 16; a preceding cross-reference cue; and any match whose remainder-of-line matches `\|\s*[^|\n]{0,140}\|\s*\d{1,4}\s*$` (a TOC entry).
- **Segmentation** — track `PART\s+(I{1,3}|IV)` state, key 10-Q items as `(part, item)`, then take the longest strictly-increasing subsequence over the canonical item order. Yields 1/246 failures.
- **Trustworthy section sizes** — only measure spans whose next detected header is the immediately-following canonical item; spans with a boundary gap are contaminated by missed headers and must be discarded (this is why §4.2's numbers differ from an unfiltered run).
- **Payload duplication cost (§9.3)** — chunk each post-strip body at 800 tokens with no overlap (`ceil(tokens/800)`, min 1) giving 21,793 chunks over 246 filings; then compare `Σ(chunks_per_file × file_chars)` = 8,813,402,814 chars against the corpus once (70,266,346 chars) and against ~64 chars of offset metadata per chunk (1,394,752 chars).
