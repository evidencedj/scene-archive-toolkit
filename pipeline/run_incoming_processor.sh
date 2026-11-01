#!/usr/bin/env bash
#
# run_incoming_processor.sh  v2.0.0
#
# Startet den Incoming Processor von Hand (oder per Zeitplan), mit Sperre,
# Protokoll und Pruefung, ob in incoming ueberhaupt etwas liegt.
#
# VERSIONSHISTORIE
#   v1.0-v1.2  Fassung des Originalsetups (rescene-worker Container, Unraid User
#              Scripts): Start im Container, Protokoll pro Lauf mit tee, Sperren
#              gegen die Nachtpipeline und den UE Mover, Aufraeumen alter Logs.
#   v2.0.0  2026-11-01  Portable Edition (Toolkit 1.1.0). Startet den Processor
#           ueber docker compose (processor/docker-compose.yml) statt in einem
#           festen Container. Pfade und Einstellungen kommen aus pipeline.env.
#           Der UE Mover Lock entfaellt. Weitere Argumente werden an den
#           Processor weitergereicht, z.B. --dry-run.
#
# AUFRUF:
#   ./run_incoming_processor.sh              echter Lauf
#   ./run_incoming_processor.sh --dry-run    Vorschau, nichts wird veraendert
#
# EXIT CODE: Code des Processors, 3 = Sperre belegt (Pipeline laeuft), 0 = nichts zu tun

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"
: "${ARCHIVE:?ARCHIVE ist nicht gesetzt (pipeline.env anlegen, siehe pipeline.env.example)}"
PROCESSOR_DIR="${PROCESSOR_DIR:-$HERE/../processor}"
STATE_DIR="${STATE_DIR:-$HERE/state}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
LOG_KEEP_DAYS="${LOG_KEEP_DAYS:-30}"

PIPE_LOCK="$STATE_DIR/pipeline.lock"
LOGDIR="$STATE_DIR/logs"
LOG="$LOGDIR/incoming_$(date +%F_%H%M).log"
mkdir -p "$LOGDIR" "$STATE_DIR"

# Die Nachtpipeline ruft dieses Skript mit SCENE_PIPELINE=1 auf und haelt die Sperre selbst.
if [ "${SCENE_PIPELINE:-0}" != "1" ]; then
  exec 8>"$PIPE_LOCK"
  if ! flock -n 8; then
    echo "Die Nachtpipeline (oder ein anderer Processor Lauf) haelt die Sperre."
    echo "Details: $HERE/scene_nightly.sh --status"
    exit 3
  fi
fi

if [ -z "$(ls -A "$ARCHIVE/incoming" 2>/dev/null)" ]; then
  echo "incoming ist leer oder nicht erreichbar, nichts zu tun."
  exit 0
fi

echo "Start: $(date '+%F %T'), Log: $LOG"
$COMPOSE_CMD -f "$PROCESSOR_DIR/docker-compose.yml" run --rm -T processor \
  python -u /app/incoming_processor.py "$@" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "Ende: $(date '+%F %T'), Exit-Code $RC"

find "$LOGDIR" -name 'incoming_*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
exit "$RC"
