# Prompt-iteration log — format, and start it now

Type: task
Status: resolved
Blocked by: —

## Question

**What form does the prompt-iteration log take, and is it being written as we go rather than
reconstructed at the end?**

### Why this is unblocked and starts immediately

*"A log of your prompt iterations (what changed, why)"* is one of the brief's seven named
deliverables. It is the only one that **cannot be produced retroactively with integrity** —
a log written at the end from memory is a summary pretending to be a record, and it reads
that way.

Every other ticket on this map changes the prompt or the context assembled into it. If the
log is not open while they are worked, the deliverable is lost.

### What already exists

- `/Users/jordan/Developer/rag-old/PROMPT_LOG.md` — port it as the starting history rather
  than starting from zero.
- `src/prompt.py` already documents a **v2** that *"adds SPEC §6's five-part answer contract
  and makes the refusal explicit rather than implicit."* That is a real iteration with a real
  reason and it belongs in the log.
- `retrieval_meta` declares a `prompt_version` field, so versions are already meant to be
  stamped on every answer. Confirm ticket 01 found it populated — a version in the log that
  cannot be tied to an answer is half a record.

### The forks to resolve

1. **Where does it live?** `PROMPT_LOG.md` at the repo root is the obvious choice and matches
   prior art. It is a deliverable the panel reads, so it should not be buried.
2. **What is an entry?** Minimum: version, what changed, why, and what it fixed or broke.
   The "why" is the part the brief asks for and the part that is worthless if vague — *"made
   the refusal explicit"* is a reason; *"improved the prompt"* is not.
3. **Does each entry cite the evidence that prompted it?** Several changes coming down this
   map have a measurement behind them (the 10-Q material-changes trap, the coverage
   asymmetry, fabricated citation handles). Entries that name the failure they fix are much
   stronger than entries that describe an edit.
4. **Is the final prompt template a separate deliverable or the log's last entry?** The
   brief lists *"your final prompt template"* separately from the log, so it likely wants
   both — the template legible on its own, plus the history.

### Standing instruction once this ticket closes

Every subsequent ticket that touches the prompt appends an entry before closing. Tickets
07, 08 and 09 all will. Note that in each ticket's answer.

---

## Answer

**Resolved 2026-08-20.** The log did its job by being written as the work happened —
**363 lines, v1 through v6 with no gaps**, plus three no-prompt-change observation entries.
What this ticket added is the *second* deliverable the brief lists separately, and the
machinery that stops either one drifting.

### Why there was little to reconstruct

This ticket was deliberately left unblocked at charting on the grounds that a prompt log
"cannot be produced retroactively with integrity". That held. Every version was written at the
moment of the change, by the ticket that made it:

| version | what changed | from |
|---|---|---|
| v1 | the two grounding rules everything rests on | ported |
| v2 | the five-part answer contract — *and it did not take* | ported |
| v3 | format block moved to the **end** of the user message | ported |
| v4 | a refusal answers nothing else | ported |
| v5 | passage label states a **period**, not a fiscal year | ticket 15 |
| v6 | the model is told what evidence it is standing on | ticket 07 |
| v6 (again) | context changed by table-caption binding | ticket 06 |
| v6 (again) | context changed by cross-encoder reranking | ticket 04 |

The two most useful entries are the ones recording harm. v2's own heading says the contract
"did not take"; v6's records that the model, given a partial census, wrote *"No filings are
available for companies except…"* — false — and what that forced.

### Fork 4 was the real work: the final prompt template

The brief lists **"your final prompt template"** separately from the log, and it did not exist
as anything a reader could read — the prompt lives in `src/prompt.py`, so a panel would have to
assemble `SYSTEM` plus `user_prompt` in their head.

Now `docs/PROMPT_TEMPLATE.md`: system message verbatim, the user message in both its
**answering** and **refusing** forms, with two-line illustrative passages so the structure is
visible without dumping filing text.

**It is generated, never transcribed.** `render_template()` builds it from the live prompt code,
`uv run python -m src.prompt` emits it, and `tests/test_prompt_template.py` regenerates it and
fails on any difference.

That discipline is not decoration — this repo has already been bitten twice by a second copy
drifting: `frontend/README.md` described a pre-RAG chat app that no longer existed, and
`prompt.py`'s own module docstring claimed v2 while the code ran v4. A hand-maintained prompt
document would have been stale within a day, and a stale one is worse than none because it
describes a system that no longer exists while looking authoritative.

### Forks 1–3

**Where it lives:** `PROMPT_LOG.md` at the repo root, matching prior art. It is a deliverable a
panel reads, so not buried under `docs/`.

**What an entry contains:** now stated in the log's own header rather than left implicit — what
changed, **why** (with the measurement or transcript that revealed it), observed effect
including "nothing measurable", and **what it made worse**. Explicitly not a template to fill
in, because the useful entries vary; but an entry that cannot answer *why* and *what it made
worse* is not worth writing.

**Evidence in every entry:** yes, and that is the convention now written down. Every entry from
v5 on cites the measurement that prompted it — 18 of 54 issuers off-calendar, 26 of 67 NVIDIA
chunks saying "fiscal year 2026", 113 of 405 table chunks with no stated scale, the 512-token
truncation deltas.

The header also documents the **"observed again … (no prompt change)"** convention: entries
recording a change in the *context* the prompt receives rather than an edit to it. The log would
otherwise imply the prompt had been working against unchanged input all along.

### Verification

- `tests/test_prompt_template.py` — 6 tests, free tier. The committed template matches the live
  prompt; both answering and refusing forms are shown; the live `PROMPT_VERSION` has a log
  entry; **logged versions are exactly 1..N with no gaps** (a gap means an iteration was made
  and not written down); and observation entries are labelled as such.
- The version-has-an-entry test is the one that would have caught the docstring/code
  discrepancy ticket 01 found by reading rather than by testing.
- **213 tests green**: 179 free python + 34 frontend.
- **The paying tier was not re-run, deliberately.** `src/prompt.py` is +138 insertions and 0
  deletions, and `SYSTEM`, `_format_block` and `user_prompt` hash identically to what the last
  live run exercised — the answer path is untouched, so 11 real generation calls would have
  bought nothing. This is the opt-in tier working as designed.

### Handed to ticket 12

An audit of the brief's seven deliverables now stands at **5 of 7**: indexing/retrieval code,
prompt log, final prompt template, front-end, quality notes. Missing are the **README with
setup and run instructions** and the **example request ready to execute** — both squarely
ticket 12's, not started here.
