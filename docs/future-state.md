# Future State


- Being able to have inline citations and backlinks to the document section and such.
	- Should be able to anchor back on the HTML since are txt documents do have a source URL.
- Being able to have a entry point for users to manage CIKs and start-end dates of documents that would be desired to be pulled into our RAG solution.
- More robust evaluation suit; we could log all user prompts so that we are able to run evaluations based on what we are seeing users search for. 
- Score refusals instead of just testing one. Today the three unanswerable questions are excluded from every metric, so there is no false-refusal number next to the correct-refusal one — nothing catches the system declining a question the corpus can actually answer.
	- A year filter that parses wrong looks exactly like a year the corpus lacks: both come back with zero passages and the same refusal. `parser_window_agrees` already disagrees on all five temporal questions ("last two years" resolves to 2024-2025 and drops every 2026 filing), and that flag currently fails nothing.
	- Cheap version needs no judge: `expect_refusal` on each golden question, report refusal rate over answerable and unanswerable separately off `no_matches` / `n_cited`, add a few year-scoped questions at the 2022 and 2026 edges that must *not* refuse, and make the parser-window disagreement fail `make eval`.
- Stream back responses to give some a better UX.