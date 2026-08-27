#!/bin/bash
# Run BU Bench V1 with Claude Code + browser-automation-cli, then score with BU's gemini-2.5-flash judge.
# RUN IN YOUR OWN TERMINAL. Usage:
#   ./run_suite.sh 10                 # pilot: first 10 tasks (across categories)
#   ./run_suite.sh InteractionTests   # all tasks in one category
#   ./run_suite.sh all                # all 100
#   ./run_suite.sh <task_id> [...]    # specific task ids
# Env: MODEL (default claude-opus-4-7), EFFORT (omit to match BU's default), and for the judge either
#   GOOGLE_CLOUD_PROJECT (+ GOOGLE_CLOUD_LOCATION) for Vertex/GCP via ADC, or GOOGLE_API_KEY for AI Studio.
set -u
cd "$(dirname "$0")"
PY=python3
sel="${1:-10}"; shift || true

# resolve the task id list
if [ "$sel" = "all" ]; then ids=$($PY loader.py ids)
elif [[ "$sel" =~ ^[0-9]+$ ]]; then ids=$($PY loader.py ids | head -n "$sel")
elif $PY loader.py ids | grep -qx "$sel"; then ids="$sel $*"      # a task_id
elif $PY loader.py count >/dev/null && $PY -c "import loader,sys; sys.exit(0 if '$sel' in {t['category'] for t in loader.load_tasks()} else 1)"; then
     ids=$($PY loader.py ids "$sel")                              # a category
else ids="$sel $*"; fi

n=$(echo $ids | wc -w | tr -d ' ')
echo ">> BU Bench V1 | Claude Code + browser-cli | model=${MODEL:-claude-opus-4-7} effort=${EFFORT:-(default)} | $n tasks"
[ -n "${GOOGLE_CLOUD_PROJECT:-}" ] && echo ">> judge: gemini-2.5-flash via Vertex (project $GOOGLE_CLOUD_PROJECT)" || echo ">> judge: gemini-2.5-flash via AI Studio (GOOGLE_API_KEY)"

# Modes: NO_JUDGE=1 -> capture only (run now, judge later). JUDGE_ONLY=1 -> judge existing raw bundles.
if [ "${JUDGE_ONLY:-0}" = 1 ]; then
  for f in raw/*.json; do
    id=$(basename "$f" .json)
    [ -f "results/$id.json" ] && continue
    $PY judge_runner.py "$id" || echo "judge failed: $id (check GOOGLE_* creds)"
  done
  echo; echo "=== summary ==="; $PY report.py; exit 0
fi

for id in $ids; do
  [ -f "results/$id.json" ] && { echo "-- skip (done): $id"; continue; }
  if [ -f "raw/$id.json" ] && [ "${RERUN:-0}" != 1 ]; then
    echo "-- skip run (captured): $id"                       # already captured; judge below
  else
    MODEL="${MODEL:-claude-opus-4-7}" $PY run_task.py "$id" ${EFFORT:+$EFFORT} || { echo "run_task failed: $id"; continue; }
  fi
  [ "${NO_JUDGE:-0}" = 1 ] && { echo "   (captured; judging skipped)"; continue; }
  $PY judge_runner.py "$id" || echo "judge failed: $id (check GOOGLE_* creds) — run later with JUDGE_ONLY=1"
done

echo; echo "=== summary ==="; $PY report.py 2>/dev/null || echo "(no judged results yet — run with GOOGLE_CLOUD_PROJECT set, or JUDGE_ONLY=1 later)"
