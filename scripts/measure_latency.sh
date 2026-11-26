#!/bin/sh
# Latency measurement against the running agent. Run on the server, from the project folder:
#     sh scripts/measure_latency.sh
# It makes seven real voice calls with a scripted caller (22+ caller turns: plain questions,
# availability checks, a booking, a cancellation), then prints the report from the call logs.
# The numbers come from the agent's own clock, recorded per reply in the database.
set -e
A=tests/audio
CALLER="docker compose --profile test run --rm -T -v $PWD/tests/audio:/srv/tests/audio:ro tests python scripts/fake_caller.py ask"
FIRST=$(docker compose exec -T db sh -c 'psql -t -A -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT COALESCE(MAX(id),0)+1 FROM calls"')
PAUSE=${PAUSE:-10}

$CALLER $A/mens_haircut.wav $A/sunday.wav $A/where.wav $A/colour.wav $A/upi.wav;  sleep $PAUSE
$CALLER $A/book_haircut.wav $A/name_phone.wav $A/yes.wav;                          sleep $PAUSE
$CALLER $A/cancel.wav $A/yes.wav;                                                  sleep $PAUSE
$CALLER $A/facial_tuesday.wav $A/poem.wav $A/where.wav;                            sleep $PAUSE
$CALLER $A/upi.wav $A/colour.wav $A/sunday.wav $A/mens_haircut.wav;                sleep $PAUSE
$CALLER $A/book_haircut.wav $A/name_phone.wav $A/yes.wav;                          sleep $PAUSE
$CALLER $A/cancel.wav $A/yes.wav

echo
echo "===== LATENCY REPORT (calls from id $FIRST) ====="
docker compose exec -T web python -m app.manage latency sunrise-salon "$FIRST"
