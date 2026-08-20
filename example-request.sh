#!/usr/bin/env bash
# An example request, ready to execute.
#
# Needs the backend running (`make answers`) and the index built. Everything below is one HTTP
# call to this system; the system makes exactly one LLM call to answer it.
#
#   ./example-request.sh                 # the panel's comparative question
#   ./example-request.sh "your question"
set -euo pipefail

QUESTION="${1:-What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?}"
API="${RAG_API_URL:-http://127.0.0.1:8000}"

if ! curl -fsS --max-time 5 "$API/health" >/dev/null 2>&1; then
  echo "The backend is not answering at $API." >&2
  echo "Start it with:  make up && make answers" >&2
  exit 1
fi

echo "--- asking: $QUESTION"
echo

PAYLOAD=$(QUESTION="$QUESTION" python3 -c \
  'import json,os; print(json.dumps({"question": os.environ["QUESTION"], "top_k": 20}))')

RESPONSE=$(curl -fsS --max-time 300 -X POST "$API/ask" \
  -H 'Content-Type: application/json' -d "$PAYLOAD")

RESPONSE="$RESPONSE" python3 - "$@" <<'FORMAT'
import json, os

body = json.loads(os.environ["RESPONSE"])
meta = body["retrieval_meta"]

print(body["answer"])
print()
print("=" * 78)

coverage = (meta.get("coverage") or {}).get("sentence")
if coverage:
    print(coverage)

if meta.get("no_matches"):
    # Nothing retrieved from a populated index: the question's own scope excluded everything.
    # No model call was made, so there is no model to name and no citation count to print.
    print("no filings matched the scope of this question — no LLM call was made")
    print(f"retrieval : {meta.get('retrieval')}")
    print(f"latency   : {meta.get('latency_ms')}")
    raise SystemExit(0)

check = meta.get("citation_check") or {}
line = (
    f"citations : {check.get('n_cited')} of {check.get('n_available')} passages cited"
    f"  |  verified: {check.get('verified')}"
)
if check.get("fabricated"):
    line += f"  |  FABRICATED: {check['fabricated']}"
print(line)
print(f"retrieval : {meta.get('retrieval')}")
print(f"model     : {meta.get('generation_model')}   prompt {meta.get('prompt_version')}")
print(f"latency   : {meta.get('latency_ms')}")
print()
print("sources:")
for citation in body["citations"]:
    period = citation.get("period_end") or f"FY{citation['fiscal_year']}"
    print(f"  [{citation['id']}] {citation['company']} — {citation['form_type']}, {period}")
    print(f"        {citation['section']}   ({citation['source_file']})")
FORMAT
