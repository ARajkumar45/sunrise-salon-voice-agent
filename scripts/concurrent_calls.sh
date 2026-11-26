#!/bin/sh
# Several calls at the same time against the running agent. Run on the server:
#     sh scripts/concurrent_calls.sh 3
# Starts N scripted callers at once, each asking five questions, then reports:
# how many calls completed, rate-limit errors seen by the agent, which fallbacks were
# used, and the reply latency under that load.
N=${1:-3}
A=tests/audio
START=$(date -u +%Y-%m-%dT%H:%M:%S)
OUT=$(mktemp -d)  # a fresh folder for the callers' output, so old results can never be read by mistake
FIRST=$(docker compose exec -T db sh -c 'psql -t -A -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT COALESCE(MAX(id),0)+1 FROM calls"')

i=1
while [ "$i" -le "$N" ]; do
  docker compose --profile test run --rm -T -v "$PWD/tests/audio:/srv/tests/audio:ro" tests \
    python scripts/fake_caller.py ask $A/mens_haircut.wav $A/facial_tuesday.wav $A/sunday.wav $A/colour.wav $A/upi.wav \
    > "$OUT/caller_$i.log" 2>&1 &
  i=$((i + 1))
done
wait

echo "===== $N CALLS AT ONCE ====="
i=1
while [ "$i" -le "$N" ]; do
  echo "caller $i: $(grep -c 'wav:' "$OUT/caller_$i.log") of 5 questions answered"
  i=$((i + 1))
done
LOGS=$(docker compose logs --since "$START" agent 2>&1)
echo "rate-limit (429) errors seen by the agent: $(echo "$LOGS" | grep -c 'Error code: 429')"
echo "fallbacks to the next model:              $(echo "$LOGS" | grep -c 'switching to next LLM')"
echo "replies where every model failed:         $(echo "$LOGS" | grep -c 'all LLMs failed')"
echo "peak container CPU and memory now:"
docker stats --no-stream --format '  {{.Name}}  cpu={{.CPUPerc}}  mem={{.MemUsage}}'
echo
docker compose exec -T web python -m app.manage latency sunrise-salon "$FIRST"
