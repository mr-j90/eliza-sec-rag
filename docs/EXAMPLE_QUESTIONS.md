# Example questions

Questions this system is meant to be asked, grouped by the retrieval behaviour each one
exercises. Every prompt here was checked against the shipped code: the entity, period and
form-type resolution for all of them, and live retrieval for the ones marked **✓**.

Ask them through the UI, or one at a time:

```bash
./example-request.sh "What does Johnson & Johnson disclose about talc litigation?"
```

Nothing here is cherry-picked to flatter the system — the last two sections are the ones where
it is supposed to refuse, and the corpus limits are stated rather than avoided.

---

## What the corpus can actually support

Filings are distributed very unevenly, and it decides which questions are answerable:

| depth | companies |
|---|---|
| 14–17 filings | JNJ, DIS, XOM, TSLA, NVDA, MSFT, AMZN, AAPL, UNH, PFE, KO, GOOG |
| 4–8 filings | META, JPM, BAC |
| 1–2 filings | the other 39, most of them a single 10-K |

So a **trend** question only has evidence behind it for the first group. Ask one about a
single-10-K company and the honest answer is one period, which is what the evidence-base line
under the answer will say.

Fiscal years run **2014–2025**. The brief says 2023–2025; the corpus disagrees, and a question
scoped to a year outside the range is refused by period rather than answered from the nearest
one.

---

## Single company, deep history

- `What does NVIDIA disclose about export controls on its products?`
- `What does Johnson & Johnson disclose about talc litigation?` **✓**
- `How does UnitedHealth describe medical cost trends and its medical loss ratio?` **✓**
- `What does Exxon Mobil say about energy transition and climate-related risk?` **✓**
- `How does Apple describe its dependence on outsourcing partners for manufacturing?`
- `What risks does Tesla disclose about Autopilot and self-driving features?`

## Cross-company comparison — the entity-quota path

*n* companies means *n* filtered searches with a budget each, not one global top-k. Without
quotas a comparative question returns whichever company writes the most vivid risk factors.

- `What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?`
- `Compare how Microsoft and Amazon describe competition in cloud services.`
- `Compare Apple, Microsoft, Alphabet and Amazon on AI-related capital expenditure.`
- `Compare the climate-related risks disclosed by Exxon Mobil and Chevron.` — asymmetric on
  purpose: XOM has 16 filings here, CVX has 1
- `How do Visa and Mastercard describe interchange fee regulation?` — both single-filing
  issuers, so the answer should read thinner than the one above
- `How do Pfizer and Merck describe patent expiration risk?`

## Temporal — relative periods anchor to the corpus, not to today

"The last two years" means the last two years of *available filings* (FY2024–2025), not two
years back from the clock. Anchored to the clock, these questions would quietly return nothing
once the snapshot stopped being current.

- `How has NVIDIA's revenue and growth outlook changed over the last two years?` → FY2024–2025
- `How has Tesla's vehicle delivery guidance changed since 2023?` → FY2023–2025
- `What guidance did Meta give on capital expenditure in its quarterly filings since 2024?` **✓**
  → FY2024–2025 **and** 10-Q only, both from rules
- `How has Coca-Cola described currency headwinds in its most recent quarterly filings?` **✓**
  → 10-Q only. A good place to see quarterly risk factors labelled as *amendments* to the 10-K
  baseline rather than a full risk profile
- `What did Amazon report about AWS growth in its 2022 and 2025 filings?` → explicit range
- `Summarise Tesla's Item 1A risk factors in its most recent annual report.` → 10-K only

## Sector-wide — no company named, so coverage does the work

No entities detected means one unfiltered search, and an answer for "an industry" that may
stand on two companies. The evidence-base line says which, and the model is given the same
sentence so its prose hedges in proportion.

- `What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?`
- `What do large US banks disclose about expected credit loss provisioning?`
- `What do technology companies disclose about data-centre power consumption?`

## Where it should refuse

The highest-value behaviour to watch, and the reason the first four sections are worth
trusting.

- `What is Shopify's China exposure?` — Shopify is named as absent, and **no findings are
  written for anyone else**. Before that rule existed this question refused correctly and then
  produced cited findings for nine other companies, including one about a bank's China exposure
- `Compare the regulatory risks disclosed by Spotify and Rivian.` — both absent, both named
  individually
- `Compare Apple and Shopify on supply chain concentration risk.` **✓** — the harder mixed
  case: it answers fully for Apple and says plainly that it cannot speak for Shopify
- `What did Apple disclose about the iPhone in 2010?` **✓** — Apple is in the corpus, 2010 is
  not. Refused by *period*, naming the scope that emptied the result and the range the corpus
  covers. No model call is made: with no passages there is nothing to ground an answer in
- `Compare Tesla and General Motors on vehicle demand.` — GM has no filings here; Tesla is
  answered, GM is named as absent rather than resolved to a near-neighbour

## Naming companies

Legal names, common short names, contractions and tickers all resolve — `Disney`,
`Walt Disney`, `DIS`; `J&J`, `Johnson & Johnson`, `JNJ`; `P&G`, `Amex`, `Coke`, `Google`,
`Raytheon`. A ticker of one or two letters only resolves written exactly as the ticker, so `V`
is Visa but a question about T-bills is not a question about AT&T.

Words that describe a company rather than identify one — `Bank`, `General`, `International`,
`Technologies` — resolve to nothing on purpose. Guessing an issuer from one of those retrieves
the wrong company's filings while looking completely confident.
