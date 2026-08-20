# 10-K baseline anchoring for temporal questions

Type: grilling
Status: open
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
