# Future State


- Being able to have inline citations and backlinks to the document section and such.
	- Should be able to anchor back on the HTML since are txt documents do have a source URL.
- Being able to have a entry point for users to manage CIKs and start-end dates of documents that would be desired to be pulled into our RAG solution.
- Evolve table ingestion beyond the current pipe-delimited text chunks and caption/period-header binding: preserve each table's identity, headers, units/scales, periods, rows, columns, and cells as structured data alongside the existing text chunks. This should enable reliable cell-level numeric comparison while retaining the current chunks for retrieval and citations.
- More robust evaluation suite; log user prompts to run evaluations based on real search behavior.
	- Capture anonymized production-style prompts (with metadata like date filters, entity filters, and refusal outcomes) to build a rolling evaluation set.
	- Bucket prompts by intent (fact lookup, comparison, trend, temporal query, etc.) so we can track pass/fail and regression rates by query type.
	- Re-run a representative sampled prompt set on every retrieval/parser/reranker change and fail CI on statistically meaningful drops.
	- Add dashboards for citation coverage, refusal quality, and answerability so we can see drift before users report it.
- Score refusals instead of just testing one. Today the three unanswerable questions are excluded from every metric, so there is no false-refusal number next to the correct-refusal one — nothing catches the system declining a question the corpus can actually answer.
	- A year filter that parses wrong looks exactly like a year the corpus lacks: both come back with zero passages and the same refusal. `parser_window_agrees` already disagrees on all five temporal questions ("last two years" resolves to 2024-2025 and drops every 2026 filing), and that flag currently fails nothing.
	- Cheap version needs no judge: `expect_refusal` on each golden question, report refusal rate over answerable and unanswerable separately off `no_matches` / `n_cited`, add a few year-scoped questions at the 2022 and 2026 edges that must *not* refuse, and make the parser-window disagreement fail `make eval`.
- Stream back responses to give some a better UX.
- Adding LLM-as-a-judge for better evaluations
	- Use an LLM to evaluate answer quality, relevance, and accuracy against golden questions.
	- Compare LLM judgments against human evaluations to validate grading consistency.
	- Can scale evaluation beyond manually-curated test cases to cover more scenarios.
	- Helps identify cases where the system's answer is correct but phrased differently than expected. 
- Multi-turn follow-ups — still exactly one LLM call per answer. Today every `/ask` is stateless: the chat route never sends prior turns, and history is persisted only for the sidebar. So "What are Apple's risk factors?" followed by "What about Microsoft?" retrieves on the literal string "What about Microsoft?".
	- Rule-based carry-forward, not conversation history in the prompt: when the current question resolves no companies, inherit the previous turn's entities, period and form from `retrieval_meta`, and show the model the prior *question* so an elliptical follow-up is readable. Roughly 70 lines across `src/query.py`, `src/retrieve.py`, `src/api.py`, `src/prompt.py` and the frontend chat route — it stays deterministic, so SPEC §5.2 holds.
	- Prior *assistant* text must never enter the prompt. It is uncited, and the first prompt rule is to answer only from cited context; feeding an answer back as context is how a paraphrase acquires a `[C#]` that does not support it.
	- Deferred because the failure is silent, which is this repo's recurring shape. "What are Apple's primary risk factors?" → "How does that compare across the sector?" resolves no entity, inherits `AAPL`, and answers a sector question filtered to one company — with every deterministic check passing and every citation resolving. The golden set is 25 single-turn questions, so nothing would catch it. Negative cases first (follow-ups that must *not* inherit), then the carry-forward.
- Spend more than one LLM call, where it measurably pays. The single-call rule is the assessment's constraint, not the architecture's; `src/llm.py` is the seam where it lifts.
	- An LLM query planner for questions the regex rules miss. Entity and time extraction are deterministic by design, and `unresolved_mentions` is explicitly a heuristic — a planner would resolve the cases the alias table cannot.
	- A self-check pass that re-reads the drafted answer against the retrieved chunks and flags claims their handle does not support: the model-side complement to `src/verify.py`, which can only confirm a `[C#]` resolves, not that it holds up the sentence.
	- Map-reduce over companies for comparatives wide enough to exceed the ~40k context budget, so a question naming many companies degrades by summarising each rather than by truncating some.
	- Each of these ships only if it beats the single-call baseline on the eval harness — same bar as the ablation table, not a vibe.
