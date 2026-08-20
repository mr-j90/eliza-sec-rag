# Prompt-iteration log — format, and start it now

Type: task
Status: open
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
