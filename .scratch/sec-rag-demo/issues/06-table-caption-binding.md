# Table-caption binding

Type: task
Status: open
Blocked by: 03

## Question

**Do retrieved table rows carry their scale and period, or are numbers arriving stripped of
what they mean?**

### Why this is demo-critical rather than nice-to-have

It was promoted when the XBRL numeric router was cut to future state. With no numeric path,
*"How has NVIDIA's revenue and growth outlook changed over the last two years?"* — one of
the three questions the panel will type — is answered from **pipe-delimited table rows**.

**22.2% of corpus characters are pipe-table rows** (§2.7). And the layout works against a
naive splitter in two specific ways:

- The caption and units — `(dollars in millions)` — sit on the **preceding narrative
  line**, not in the table.
- Column-year headers sit on their **own label-less row**.

So a chunk boundary in the wrong place yields `Revenue | 26,974 | 6,051` with no scale, no
currency, and no idea which column is which year. For a financial diligence tool that is
the **highest-consequence silent failure available** — it produces a confident, specific,
wrong number, and no retrieval metric detects it.

Prior art's chunking does not mention tables at all (§10 item 9).

### The fix

§2.7 puts it at roughly **40 lines**: when emitting a chunk containing table rows, bind the
preceding caption line and the column-header row to it, and never split a table away from
either.

### What must be true to close this

1. A chunk containing table rows always carries its caption line and its column-header row.
2. Spot-check the NVIDIA revenue tables specifically, across two years of filings — that is
   the actual demo question. Confirm a retrieved chunk is self-sufficient: a reader can tell
   what the number measures, in what units, for what period.
3. Spot-check JPMorgan too. It is the largest filing in the corpus (396,452 tokens) and the
   most table-dense.
4. Decide and record what happens to tables too large to keep whole — §4.2's Item 8 policy
   is "table-row-aligned or skip," and which one you chose is a defensible answer either way
   but must be a choice rather than an accident.

### Worth saying in the walkthrough

This is a good concrete example of the value argument the brief asks you to defend: the
failure it prevents is not "slightly worse retrieval," it is *quoting a number to a client
with the wrong order of magnitude*.
