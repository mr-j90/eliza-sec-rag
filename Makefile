# One door in front of the test suite.
#
# The suite has two tiers, measured rather than assumed (see tests/conftest.py):
#
#   122 python tests = 93 that need nothing + 29 that need a live OPENAI_API_KEY.
#   Of those 29, seventeen embed queries and eleven make REAL GENERATION CALLS.
#   There is no Qdrant-only tier: with Qdrant up and the key removed, all 29 still skip.
#   Plus 34 frontend tests that need nothing. 156 in total.
#
# `make test` deselects the paying tier rather than letting it skip, so the run reports
# "93 passed, 29 deselected" instead of "93 passed, 29 skipped". The first is a claim you
# can read; the second is indistinguishable from a suite that quietly tested nothing.

.PHONY: help test test-py test-fe test-live test-all check typecheck lint up down index answers

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  The default loop is 'make test'. It needs no Docker and no API key."
	@echo "  'make test-live' SPENDS MONEY — 11 real generation calls. Opt in deliberately."

test: test-py test-fe  ## Fast loop: 93 python + 34 frontend. No services, no key, no cost

test-py:  ## The 93 python tests that need nothing
	uv run pytest -m "not live" -q

test-fe:  ## The 34 frontend tests (node:test, SQLite is a file)
	cd frontend && bun run test

test-live:  ## The 29 that need a key. 11 make REAL generation calls — this costs money
	@echo "This runs 11 real generation calls against $$(grep -m1 DEFAULT_GENERATION_MODEL src/config.py | cut -d'"' -f2)."
	RAG_REQUIRE_LIVE=1 uv run pytest -m live -q

test-all: test test-live  ## Everything, including the paying tier

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

index:  ## Build the index. NOT needed if the volume already holds 29,499 points
	uv run python -m src.index

answers:  ## Start the backend the frontend expects on :8000
	uv run uvicorn src.api:app --port 8000
