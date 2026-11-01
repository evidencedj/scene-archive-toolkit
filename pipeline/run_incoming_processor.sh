#!/usr/bin/env bash
#
# run_incoming_processor.sh  v2.1.0
#
# Starts the Incoming Processor by hand (or on a schedule), with a lock,
# a log file and a check whether incoming contains anything at all.
#
# VERSION HISTORY
#   v1.0-v1.2  Original setup version (fixed container, Unraid User Scripts):
#              start inside the container, one log per run via tee, locks
#              against the nightly pipeline, cleanup of old logs.
#   v2.0.0  2026-11-01  Portable edition (toolkit 1.1.0). Starts the processor
#           via docker compose (processor/docker-compose.yml) instead of a
#           fixed container. Paths and settings come from pipeline.env.
#           Additional arguments are passed on to the processor, e.g. --dry-run.
#   v2.1.0  2026-11-01  All messages translated to English.
#
# USAGE:
#   ./run_incoming_processor.sh              real run
#   ./run_incoming_processor.sh --dry-run    preview, nothing is changed
#
# EXIT CODE: code of the processor, 3 = lock is held (pipeline is running), 0 = nothing to do

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"
: "${ARCHIVE:?ARCHIVE is not set (create pipeline.env, see pipeline.env.example)}"
PROCESSOR_DIR="${PROCESSOR_DIR:-$HERE/../processor}"
STATE_DIR="${STATE_DIR:-$HERE/state}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
LOG_KEEP_DAYS="${LOG_KEEP_DAYS:-30}"

PIPE_LOCK="$STATE_DIR/pipeline.lock"
LOGDIR="$STATE_DIR/logs"
LOG="$LOGDIR/incoming_$(date +%F_%H%M).log"
mkdir -p "$LOGDIR" "$STATE_DIR"

# The nightly pipeline calls this script with SCENE_PIPELINE=1 and holds the lock itself.
if [ "${SCENE_PIPELINE:-0}" != "1" ]; then
  exec 8>"$PIPE_LOCK"
  if ! flock -n 8; then
    echo "The nightly pipeline (or another processor run) holds the lock."
    echo "Details: $HERE/scene_nightly.sh --status"
    exit 3
  fi
fi

if [ -z "$(ls -A "$ARCHIVE/incoming" 2>/dev/null)" ]; then
  echo "incoming is empty or not reachable, nothing to do."
  exit 0
fi

echo "Start: $(date '+%F %T'), log: $LOG"
$COMPOSE_CMD -f "$PROCESSOR_DIR/docker-compose.yml" run --rm -T processor \
  python -u /app/incoming_processor.py "$@" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "End: $(date '+%F %T'), exit code $RC"

find "$LOGDIR" -name 'incoming_*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
exit "$RC"
