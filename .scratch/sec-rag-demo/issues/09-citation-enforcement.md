# Verifiable citation enforcement

Type: task
Status: resolved
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

---

## Answer

**Resolved 2026-08-20.** Handles are verified server-side, reported in `retrieval_meta`, and
surfaced in the UI. **Flagged, never stripped.**

### It guards a failure that has not occurred, and that is worth saying

Checked across **thirteen saved runs** from this session before building anything: **zero
fabricated handles.** The model is behaving.

So this is not fixing a live defect. It is worth having because "every claim traces to a filing"
is the claim the whole system rests on, and a claim that is *checked* is worth more than one
that has merely held so far. It also converts the count on screen from a reported number into a
verified one. Both of those are things a panel can be shown; "it hasn't happened yet" is not.

### The sub-decisions

**Flag, not strip.** Stripping a bad handle produces clean prose and silently edits the model's
answer — and a stripped answer looks *identical* whether or not the check ran, which makes the
guarantee unobservable. There is a test asserting `verify.py` contains no `replace` or `sub`: it
may inspect the answer, never rewrite it.

**Where it runs:** `src/verify.py`, called from `api.py` before the response is assembled, so
the guarantee holds regardless of client. `sources.tsx`'s existing `[Cn]` parse is presentation;
this is enforcement.

**What is reported:** `retrieval_meta.citation_check` — `cited`, `fabricated`, `n_cited`,
`n_available`, `verified`. The UI's Facts line now prefers the server's count and labels it
`(verified)`, because two independent counts of the same thing is how they drift. A red warning
naming the offending handles renders only when `fabricated` is non-empty.

**The refusal case, which was the trap.** A correct refusal emits two sections and **no handles**
over twenty retrieved passages about companies nobody asked about. Live check: the Shopify
question returns `n_cited: 0, n_available: 20, verified: true` — not flagged. `is_uncited` is
deliberately separate from `ok`, and deliberately does *not* judge whether an uncited answer is a
refusal or a contract violation: that cannot be told from handles alone, and the answer-contract
tests judge it on the prose where the evidence actually is.

### Verified live

| question | result |
|---|---|
| Apple / Tesla / JPMorgan comparative | `n_cited: 18, n_available: 18, verified: true` |
| Shopify (out of corpus) | `n_cited: 0, n_available: 20, verified: true` |

### Verification

- `tests/test_verify.py` — 12 tests, free tier. The fabricated-handle catch, repeats collapsing
  in first-appearance order, the refusal not being flagged, handle-format parsing pinned against
  what `prompt.handle` emits, and the no-rewrite assertion.
- One test guards an interaction: ticket 07's **coverage sentence** is deterministic text
  appended outside the model's output and carries no handles by design — the two mechanisms must
  not flag each other.
- **201 free python + 34 frontend green**; `make check` clean.
