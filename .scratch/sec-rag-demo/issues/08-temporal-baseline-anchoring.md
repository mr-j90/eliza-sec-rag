# 10-K baseline anchoring for temporal questions

Type: grilling
Status: resolved
Blocked by: 01, 02

## Question

**How does the system guarantee that a temporal question sees the 10-K baseline and not
just a quarter's amendments — and how does it detect that a question is temporal?**

### The correctness bug

Form 10-Q Item 1A contains only *"any **material changes** from risk factors as previously
disclosed in the registrant's Form 10-K."* That is the regulation, not a convention. And
the corpus shows it plainly (§4.4):

| | median tokens |
|---|---|
| 10-K Item 1A | **11,153** |
| 10-Q Item 1A | **876** |

A 13× gap, because the 10-Q is a **delta document**.

So *"How has NVIDIA's revenue and growth outlook changed over the last two years?"* —
a question the panel will type — retrieves 10-Q risk factors, and presents an incremental
amendment as a complete risk profile. §10 item 6 calls this out as a correctness bug that
produces **plausible wrong answers and is invisible to `recall@k`**. `grep -ri "material
change\|baseline" src/` in the prior art returns **nothing** — it is entirely unhandled.

This is the worst failure shape available in front of a panel: fluent, specific, cited, and
wrong about the thing it was asked.

### The forks to resolve

1. **How is a temporal question detected?** It has to be deterministic — an LLM classifier
   would break the one-call constraint (§8.3). `retrieval_meta` already declares a
   `fiscal_years` field, so date-range extraction exists or was planned; establish what
   ticket 01 found. Phrases like "over the last two years", "how has X changed", "trend"
   are the obvious surface, and the walkthrough should be honest that a deterministic
   detector has misses.
2. **What is the guarantee?** Reserve context budget for the covering 10-K's Item 1A
   whenever 10-Q Item 1A chunks are retrieved for a risk question? Or a hard retrieval quota
   by form type? Prior art already has per-entity quotas in `retrieve.py`, so a per-form
   quota is the same mechanism pointed at a different axis — likely the cheapest route.
3. **How is the distinction surfaced?** §4.4's suggestion is to tag 10-Q Item 1A chunks
   `is_incremental: true` so the prompt can tell the model these are amendments to a
   baseline, not the baseline. This costs a payload field and a prompt clause. Note §9.6:
   a payload field like this is in the "absorbed for free" class — a label on a chunk, not
   a change to a chunk — so it needs no re-embed.
4. **Does the answer say so to the reader?** "NVIDIA's Q2 FY2025 10-Q reports material
   changes from the FY2024 10-K baseline" is a *stronger* answer than one that silently
   merges them. Related to ticket 07 — both are the system stating what it stands on.

### Interaction with ticket 02

If item segmentation cannot reliably distinguish 10-Q Part I Item 1A from Part II Item 1A,
this whole mechanism is built on sand. §2.6 measures the collision in **125 of 157 10-Qs**.
Read ticket 02's answer before designing the guarantee.

### What must be true to close this

Run the NVIDIA question end to end and confirm the context contains 10-K Item 1A material,
that 10-Q content is identifiable as incremental, and that the answer does not present a
quarterly delta as a full risk profile.

---

## Answer

**Resolved 2026-08-20.** Both mechanisms, per the decision on this ticket. `PROMPT_VERSION` →
**v7**.

### The premise held, but was wrong in two ways worth recording

**The gap is smaller than §4.4 states.** Measured on the current index, median annual
risk-factor section is **12,876 tokens** against a quarterly **2,617** — a **4.9×** ratio, not
the 12.7× the arch doc's 11,153-vs-876 implies. Still large enough to matter.

**And the regulation is a floor, not a description of practice.** 42 of 136 10-Qs carry an
Item 1A over 8,000 tokens, and per-issuer against their *own* annual section:

| issuer | quarterly ÷ annual Item 1A |
|---|---|
| META | **1.00×** — restates in full every quarter |
| AMZN | **0.95×** — restates in full |
| MSFT | outlier (its annual section under-segments) |
| NVDA | 0.50× |
| TSLA | 0.07× |
| XOM | 0.05× |
| PFE | **0.03×** |

**3 of 15 issuers restate everything quarterly.** A blanket "quarterly risk factors are
incomplete" would have been false for a fifth of the corpus, which is why the prompt wording
says these passages *state only material changes per the regulation* and instructs the model to
treat them as amendments — rather than asserting they are short or telling it to discount them.

### The bug is latent, and the trigger is narrow

This is the finding that shaped the fix. On three probe questions the annual section
**dominated** risk-factor retrieval — 10 of 13, 13 of 16, 0 of 0. The reason is the asymmetry
itself: a 5× larger section yields ~5× more chunks, so it wins on volume. **The size gap that
creates the bug also masks it.**

The failure appears only when the question's own wording restricts the form, which
`_form_type_in` honours on "quarterly" or "10-Q". Measured then:

| question | risk-factor context before |
|---|---|
| *"What are Tesla's quarterly risk factors?"* | 7 chunks, 5,372 tokens, **no baseline** |
| *"What new risks did Tesla disclose in its most recent 10-Q?"* | 3 chunks, 2,287 tokens, **no baseline** |
| *"How did Pfizer's risk factors change in its latest quarterly report?"* | **1 chunk, 562 tokens** |

Pfizer's annual section runs past 10,000 tokens. So the answer rested on roughly **5%** of the
disclosure while reading as complete. That is a narrow trigger, so the fix is narrow too — the
quota design was left alone rather than reworked.

### Mechanism 1 — the form filter admits the baseline

`_form_scope` replaces a bare `form_type` equality when the scope is 10-Q: match 10-Q, **or**
match a 10-K whose `item_section` is a risk-factor section. One query, no extra round trip.

| question | after |
|---|---|
| Tesla quarterly risk factors | 4 annual + 7 quarterly Item 1A chunks |
| Pfizer quarterly risk change | 14 annual Item 1A chunks (was 1 quarterly) |
| **"What were Apple's quarterly results?"** | **20 quarterly, 0 annual — no leak** |

That last row matters: widening a scope the reader asked for needs to be surgical. A quarterly
question about *results* still gets quarterly filings only, because the annual arm requires a
risk-factor section.

### Mechanism 2 — the amendments are labelled, and it is not optional

Mechanism 1 **creates a new error**: with baseline and amendment side by side and nothing
distinguishing them, "newly disclosed this quarter" can be asserted about a risk that has sat in
the 10-K for years. Supplying more context without saying what it is trades one wrong answer for
another. The two halves only work together, and the prompt note says so explicitly — naming the
handles, stating the material-changes rule, and forbidding "new or newly disclosed" on the
strength of a quarterly passage alone.

**Implemented as a derived property, not a payload field.** `Chunk.is_incremental_risk_factors`
follows entirely from `form_type` and `item_section`, so:

- no payload migration and **no re-embed** — the 30,383 points are untouched;
- it cannot drift from the two fields it is computed from, which matters because this repo has
  already been bitten twice by a stored value disagreeing with its source.

Ticket 02's `(part, item)` keying is what makes it work at all — a 10-Q files under `Part II
Item 1A`, a 10-K under `Item 1A`, and a key on `item` alone would have merged them.

### Verification

- `tests/test_temporal_baseline.py` — 11 tests, 8 free and 3 live. The free ones cover the
  derived flag (including that a 10-Q's *MD&A* is **not** flagged — quarterly MD&A is a complete
  discussion of its quarter), that it is a property rather than a field, both section labels, and
  the prompt's three required clauses. The live ones assert the baseline arrives, that it does
  not leak into non-risk questions, and that the Pfizer case is no longer a single amendment.
- The two `PROMPT_LOG.md` guards from ticket 11 **fired correctly** — the free tier went red on
  v7 having no log entry, which is precisely what they were written for.
- **189 free python + 34 frontend green**; live tier re-run because both retrieval and the
  prompt changed.
