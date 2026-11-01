#!/usr/bin/env bash
#
# wait_for_processor.sh  v2.1.0
#
# Waits until no Incoming Processor run is active any more. Meant for
# backups or a scheduled shutdown, so that nothing is backed up or powered
# off in the middle of a run.
#
# VERSION HISTORY
#   v1.0  Original setup version: waits inside a fixed container, after the
#         time limit a single SIGTERM (clean stop after the current release),
#         then up to 15 more minutes of grace.
#   v2.0.0  2026-11-01  Portable edition (toolkit 1.1.0). Detects a running
#           processor through its lock file in the archive
#           (.incoming_processor.lock) instead of a fixed container name; the
#           SIGTERM goes to the container that runs incoming_processor.py.
#           Settings from pipeline.env.
#   v2.1.0  2026-11-01  All messages translated to English.
#
# USAGE:
#   ./wait_for_processor.sh [MAX_WAIT_MINUTES]      (default 120)
#
# EXIT CODE: 0 = nothing is running any more, 1 = processor is still running

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"
: "${ARCHIVE:?ARCHIVE is not set (create pipeline.env)}"

MAX_WAIT_MIN="${1:-120}"
GRACE_MIN=15
LOCKFILE="$ARCHIVE/.incoming_processor.lock"

running() {
  [ -e "$LOCKFILE" ] || return 1
  # cannot get the lock = the processor holds it = it is running
  ( exec 9<"$LOCKFILE"; flock -n 9 ) && return 1 || return 0
}

term_processor() {
  local ids
  ids=$(docker ps --no-trunc --format '{{.ID}} {{.Command}}' 2>/dev/null | awk '/incoming_processor.py/ {print $1}')
  [ -n "$ids" ] && docker kill -s TERM $ids >/dev/null 2>&1
}

if ! running; then
  echo "No processor run active."
  exit 0
fi

echo "Processor is running, waiting up to $MAX_WAIT_MIN minutes..."
waited=0
while running && [ "$waited" -lt "$MAX_WAIT_MIN" ]; do
  sleep 60
  waited=$((waited + 1))
done

if running; then
  echo "Time limit reached, sending SIGTERM (clean stop after the current release)..."
  term_processor
  waited=0
  while running && [ "$waited" -lt "$GRACE_MIN" ]; do
    sleep 60
    waited=$((waited + 1))
  done
fi

if running; then
  echo "Processor is still running."
  exit 1
fi
echo "Processor is finished."
exit 0
