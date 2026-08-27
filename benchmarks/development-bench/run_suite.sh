#!/bin/bash
# Run the agent benchmark headlessly: for each task, setup -> fresh `claude -p` agent -> verify.
# Usage: run_suite.sh <model> <label> [attempts]   e.g. run_suite.sh haiku haiku 2
# Env: BROWSER_CLI / BROWSER_DAEMON select the implementation (default: Python from .venv).
set -u
cd "$(dirname "$0")/../.."
MODEL=${1:-haiku}; LABEL=${2:-$MODEL}; ATTEMPTS=${3:-2}
PY=.venv/bin/python; H=benchmarks/development-bench/harness.py; LOG=benchmarks/development-bench/results/suite-$LABEL.log
ANSWER_TASKS="t5_extract_count t6_extract_account t7_live_wikipedia h1_canvas_chart h4_audit_delayed h6_infinite_scroll h9_reauth_export"
echo "=== suite $LABEL model=$MODEL attempts=$ATTEMPTS cli=${BROWSER_CLI:-python} $(date)" >> "$LOG"
for a in $(seq 1 "$ATTEMPTS"); do
  RUN=$LABEL; [ "$a" -gt 1 ] && RUN="$LABEL-$a"
  for t in $($PY $H tasks); do
    prompt=$($PY $H setup "$t")
    prompt="${prompt%%Set the environment variable*}Use the \`browser\` binary on PATH (${BROWSER_CLI:-browser})."
    out=$(claude -p "$prompt" --model "$MODEL" --allowedTools "Bash" --output-format json --max-turns 60 2>>"$LOG")
    text=$(printf '%s' "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',''))" 2>/dev/null)
    tokens=$(printf '%s' "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); u=d.get('usage',{}); print(u.get('input_tokens',0)+u.get('output_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0))" 2>/dev/null || echo 0)
    ans=""; case " $ANSWER_TASKS " in *" $t "*) ans=$(printf '%s\n' "$text" | grep -E '^ANSWER:' | tail -1 | sed 's/^ANSWER:[[:space:]]*//');; esac
    if [ -n "$ans" ]; then res=$($PY $H verify "$t" "answer=$ans" "tokens=$tokens" "run=$RUN"); else res=$($PY $H verify "$t" "tokens=$tokens" "run=$RUN"); fi
    ok=$(printf '%s' "$res" | python3 -c "import sys,json; print('PASS' if json.load(sys.stdin)['success'] else 'FAIL')" 2>/dev/null || echo "?")
    calls=$(printf '%s' "$res" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d['cli_calls']} calls/{d['failed_calls']} failed/{d['wall_s']}s\")" 2>/dev/null)
    echo "$(date +%H:%M:%S) $RUN $t $ok $calls answer=[$ans]" | tee -a "$LOG"
  done
done
echo "=== done $(date)" >> "$LOG"
$PY $H passk >> "$LOG"
