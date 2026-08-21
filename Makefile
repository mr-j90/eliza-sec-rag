# One door in front of the test suite.
#
# The suite has two tiers, measured rather than assumed (see tests/conftest.py):
#
#   285 python tests = 253 that need nothing + 32 that need a live OPENAI_API_KEY.
#   Of those 31, seventeen embed queries and eleven make REAL GENERATION CALLS.
#   There is no Qdrant-only tier: with Qdrant up and the key removed, all 31 still skip.
#   Plus 54 frontend tests that need nothing. 339 in total.
#
# Counts re-measured 2026-08-20 with the eval-summary work. The frontend figure had drifted
# (43 tests were reported as 34), which is the argument for measuring rather than incrementing.
#
# `make test` deselects the paying tier rather than letting it skip, so the run reports
# "253 passed, 32 deselected" instead of "253 passed, 32 skipped". The first is a claim you
# can read; the second is indistinguishable from a suite that quietly tested nothing.

.PHONY: help test test-py test-fe test-live test-all eval eval-summary check typecheck lint up down index answers

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  The default loop is 'make test'. It needs no Docker and no API key."
	@echo "  'make test-live' SPENDS MONEY — 11 real generation calls. Opt in deliberately."

test: test-py test-fe  ## Fast loop: 253 python + 54 frontend. No services, no key, no cost

test-py:  ## The 253 python tests that need nothing
	uv run pytest -m "not live" -q

test-fe:  ## The 54 frontend tests (node:test, SQLite is a file)
	cd frontend && bun run test

test-live:  ## The 31 that need a key. 11 make REAL generation calls — this costs money
	@echo "This runs 11 real generation calls against $$(grep -m1 DEFAULT_GENERATION_MODEL src/config.py | cut -d'"' -f2)."
	RAG_REQUIRE_LIVE=1 uv run pytest -m live -q

test-all: test test-live  ## Everything, including the paying tier

eval: ## Retrieval metrics over the golden set, then the page summary. Needs Qdrant + a key
	@echo "22 questions, ~2 min. RAG_RERANK=0 for the fusion-only row. See docs/EVALUATION.md."
	uv run python -m src.eval.metrics
	@$(MAKE) --no-print-directory eval-summary

eval-summary:  ## The cached plain-English summary the /evals page shows. One eval-time call
	@echo "One eval-time LLM call over eval/results/ — NOT the answer path. Skipped if current."
	uv run python -m src.eval.summarize

check: typecheck lint  ## Static checks nothing else currently runs

typecheck:
	cd frontend && bun run typecheck

lint:
	cd frontend && bun run lint

# --- services and data -------------------------------------------------------

up:  ## Start Qdrant (host port 6533 — deliberately not 6333, see docker-compose.yml)
	docker compose up -d

down:  ## Stop Qdrant, keeping the volume
	docker compose down

index:  ## Build the index (~15 min, ~$0.40). Required once on a fresh volume
	uv run python -m src.index

answers:  ## Start the backend the frontend expects on :8000
	uv run uvicorn src.api:app --port 8000
