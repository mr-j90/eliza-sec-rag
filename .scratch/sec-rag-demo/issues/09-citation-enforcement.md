# Verifiable citation enforcement

Type: task
Status: open
Blocked by: 01

## Question

**Does every `[Cn]` handle in the answer resolve to a passage that was actually retrieved —
checked, not trusted?**

The decision to enforce was made at charting. What remains is the mechanism and one real
sub-decision: flag or strip.

### Why

§8.4's framing is that citations should be **verifiable, not model-asserted**. A model that
emits `[C7]` when only six passages were retrieved has fabricated provenance, and that is
strictly worse than no citation — it is a false claim of groundedness in a tool whose entire
value proposition is groundedness.

Half the machinery already exists. `frontend/components/chat/sources.tsx` parses handles
client-side:

```ts
for (const match of answer.matchAll(/\[(C\d+)\]/g)) seen.add(match[1]);
```

and renders *"9 of 20 passages cited."* But that count is currently derived from whatever
the model wrote. This ticket makes it a **verified** count rather than a reported one.

### The sub-decisions

1. **Flag or strip?** Stripping produces clean prose but silently edits the model's answer.
   Flagging preserves it and shows the reader something went wrong. For a diligence tool,
   surfacing the failure is probably right — and it is certainly the better demo, because it
   proves the check exists. A stripped answer looks identical whether or not the check ran.
2. **Where does the check run?** Server-side in `src/api.py` or `src/prompt.py`, so the
   guarantee holds regardless of client. The frontend's parse is presentation, not
   enforcement.
3. **What is reported?** `retrieval_meta` already declares `n_chunks`; a verified-citation
   count belongs alongside it so `sources.tsx` can show a trustworthy "N of M."
4. **What happens when the answer cites nothing at all?** For a refusal that is correct and
   expected — prior art's `_REFUSE_ONLY` path deliberately emits a two-section answer with
   no citations. **The enforcement must not treat a correct refusal as a failure.** Read
   `src/prompt.py` around the `_REFUSE_ONLY` template before implementing.

### Watch for

Ticket 07's coverage statement is deterministic text appended outside the model's output and
carries no `[Cn]` handles by design. Confirm the two mechanisms do not flag each other.

### What must be true to close this

- A test that feeds a fabricated `[C99]` through the enforcement path and asserts it is
  caught. This is cheap and it is the kind of test that makes the claim credible in the
  walkthrough.
- The out-of-corpus refusal still passes end to end, uncited and unflagged.
