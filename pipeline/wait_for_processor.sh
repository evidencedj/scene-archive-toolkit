#!/usr/bin/env bash
#
# wait_for_processor.sh  v2.0.0
#
# Wartet, bis kein Lauf des Incoming Processors mehr aktiv ist. Gedacht fuer
# Backups oder ein geplantes Herunterfahren, damit nicht mitten in einem Lauf
# gesichert oder ausgeschaltet wird.
#
# VERSIONSHISTORIE
#   v1.0  Fassung des Originalsetups: wartet im rescene-worker Container, nach
#         dem Zeitlimit ein einziges SIGTERM (sauberes Beenden nach der aktuellen
#         Release), danach bis zu 15 Minuten Nachfrist.
#   v2.0.0  2026-11-01  Portable Edition (Toolkit 1.1.0). Erkennt einen laufenden
#           Processor ueber seine Sperrdatei im Archiv (.incoming_processor.lock)
#           statt ueber einen festen Container Namen, das SIGTERM geht an den
#           Container, in dem incoming_processor.py laeuft. Einstellungen aus
#           pipeline.env.
#
# AUFRUF:
#   ./wait_for_processor.sh [MAX_WARTEN_MINUTEN]      (Standard 120)
#
# EXIT CODE: 0 = nichts laeuft mehr, 1 = Processor laeuft noch

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"
: "${ARCHIVE:?ARCHIVE ist nicht gesetzt (pipeline.env anlegen)}"

MAX_WAIT_MIN="${1:-120}"
GRACE_MIN=15
LOCKFILE="$ARCHIVE/.incoming_processor.lock"

running() {
  [ -e "$LOCKFILE" ] || return 1
  # Sperre nicht bekommen = der Processor haelt sie = er laeuft
  ( exec 9<"$LOCKFILE"; flock -n 9 ) && return 1 || return 0
}

term_processor() {
  local ids
  ids=$(docker ps --no-trunc --format '{{.ID}} {{.Command}}' 2>/dev/null | awk '/incoming_processor.py/ {print $1}')
  [ -n "$ids" ] && docker kill -s TERM $ids >/dev/null 2>&1
}

if ! running; then
  echo "Kein Processor Lauf aktiv."
  exit 0
fi

echo "Processor laeuft, warte bis zu $MAX_WAIT_MIN Minuten..."
waited=0
while running && [ "$waited" -lt "$MAX_WAIT_MIN" ]; do
  sleep 60
  waited=$((waited + 1))
done

if running; then
  echo "Zeitlimit erreicht, sende SIGTERM (sauberes Beenden nach der aktuellen Release)..."
  term_processor
  waited=0
  while running && [ "$waited" -lt "$GRACE_MIN" ]; do
    sleep 60
    waited=$((waited + 1))
  done
fi

if running; then
  echo "Processor laeuft immer noch."
  exit 1
fi
echo "Processor ist fertig."
exit 0
