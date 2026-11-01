#!/bin/bash
#
# scene_nightly.sh  v1.1.0
#
# Nachtlauf des Scene Workflows. Ein einziger Zeitplan startet alle Schritte
# nacheinander, jeder Schritt wartet auf den vorherigen. Es gibt keine festen
# Uhrzeiten pro Job mehr, die sich bei langen Laeufen ueberholen.
#
# VERSIONSHISTORIE
#   1.0.0  2026-10-22  Erste Version (Originalsetup, Unraid). Schritte processor,
#                      links, mirror, stats, sorter, hetzner, mit Preflight, Sperre,
#                      Protokoll, Discord und Unraid Meldung, Haken after_pipeline.sh.
#   1.0.1  2026-10-24  Hetzner Vorpruefung korrigiert (nur Originalsetup).
#   1.0.2  2026-10-24  Stats: mutagen wird fuer den Container nachinstalliert
#                      (nur Originalsetup).
#   1.1.0  2026-11-01  Portable Edition (Toolkit 1.1.0). Alles, was nur zum
#                      Originalsetup gehoert, ist entfernt: Hetzner Schritt,
#                      UE Mover Sperre, feste Container (rescene-worker,
#                      gluetun-rescene), SSH Pruefung des zweiten Rechners, Pfade
#                      und Webhook aus secrets.env. Die Python Schritte laufen im
#                      Image des Toolkits (docker compose run), alle Einstellungen
#                      stehen in pipeline.env. Der Schritt "mirror" ist optional
#                      (MIRROR_SCRIPT), ohne Eintrag wird er uebersprungen.
#
# SCHRITTE (in dieser Reihenfolge):
#   processor  incoming verarbeiten (Scene Check, Verschieben, Links)
#   links      Symlinks in scenereleases abgleichen
#   mirror     optional: eigenes Skript (Kopie auf einen zweiten Rechner, Reindex)
#   stats      ARCHIVE_STATS.txt neu schreiben
#   sorter     _sorted_ Links neu aufbauen
#
# AUFRUF:
#   scene_nightly.sh                    alle Schritte
#   scene_nightly.sh --only stats,sorter
#   scene_nightly.sh --skip mirror
#   scene_nightly.sh --list             Schritte und Einstellungen anzeigen
#   scene_nightly.sh --dry-run          zeigen, was laufen wuerde, nichts tun
#   scene_nightly.sh --status           laeuft gerade etwas, wie war der letzte Lauf
#
# EXIT CODE: 0 alles ok, 1 mit Hinweisen, 2 mit Fehlern, 3 nicht gestartet

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"

# ---------------------------------------------------------------------------
# Einstellungen (aus pipeline.env oder Umgebung)
# ---------------------------------------------------------------------------
ARCHIVE="${ARCHIVE:-}"
PROCESSOR_DIR="${PROCESSOR_DIR:-$HERE/../processor}"
STATE_DIR="${STATE_DIR:-$HERE/state}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"

LOCK="$STATE_DIR/pipeline.lock"
LOCK_WAIT_MIN="${LOCK_WAIT_MIN:-120}"          # so lange auf einen Hand Lauf des Processors warten
MIN_ENTRIES="${MIN_ENTRIES:-0}"                # scenereleases_srr muss mindestens so viele Eintraege haben
LOG_KEEP_DAYS="${LOG_KEEP_DAYS:-30}"

PROC_WRAPPER="$HERE/run_incoming_processor.sh"
WAIT_PROCESSOR="$HERE/wait_for_processor.sh"
MIRROR_SCRIPT="${MIRROR_SCRIPT:-}"
AFTER_HOOK="${AFTER_HOOK:-$HERE/after_pipeline.sh}"
NOTIFY="${NOTIFY:-}"
NOTIFY_ON_OK="${NOTIFY_ON_OK:-0}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"

STEPS=(processor links mirror stats sorter)
declare -A STEP_TEXT=(
  [processor]="incoming verarbeiten"
  [links]="Links in scenereleases abgleichen"
  [mirror]="optional: eigenes Mirror Skript"
  [stats]="ARCHIVE_STATS.txt schreiben"
  [sorter]="_sorted_ Links aufbauen"
)

RUNNING="$STATE_DIR/running.txt"
LAST_RUN="$STATE_DIR/last_run.txt"
HISTORY="$STATE_DIR/history.tsv"
NOTE_FILE="$STATE_DIR/.step_note"

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
ts()  { date '+%F %T'; }
say() { if [ -n "${LOG:-}" ]; then echo "$(ts) $*" | tee -a "$LOG"; else echo "$(ts) $*"; fi; }
note() { printf '%s' "$1" > "$NOTE_FILE"; }

fmt_dur() {   # Sekunden -> "1h 12m" / "5m 03s" / "42s"
  local s=$1
  if   [ "$s" -ge 3600 ]; then printf '%dh %02dm' $((s/3600)) $(((s%3600)/60))
  elif [ "$s" -ge 60 ];   then printf '%dm %02ds' $((s/60)) $((s%60))
  else printf '%ds' "$s"; fi
}

# Einen Befehl im Image des Toolkits ausfuehren (ohne TTY, damit es auch per Cron geht)
in_image() { $COMPOSE_CMD -f "$PROCESSOR_DIR/docker-compose.yml" run --rm -T processor "$@"; }

usage() { sed -n '/^# AUFRUF/,/^# EXIT CODE/p' "$0" | sed 's/^# \{0,1\}//'; }

ONLY=""; SKIP=""; MODE="run"
while [ $# -gt 0 ]; do
  case "$1" in
    --only)    ONLY=",${2:-},"; shift 2 ;;
    --skip)    SKIP=",${2:-},"; shift 2 ;;
    --list)    MODE="list"; shift ;;
    --dry-run) MODE="dry"; shift ;;
    --status)  MODE="status"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unbekannte Option: $1"; usage; exit 3 ;;
  esac
done

for opt in "$ONLY" "$SKIP"; do
  for n in $(echo "$opt" | tr ',' ' '); do
    case " ${STEPS[*]} " in *" $n "*) ;; *) echo "Unbekannter Schritt: $n (gueltig: ${STEPS[*]})"; exit 3 ;; esac
  done
done

selected() {
  [ -z "$ONLY" ] || case "$ONLY" in *",$1,"*) ;; *) return 1 ;; esac
  case "$SKIP" in *",$1,"*) return 1 ;; esac
  return 0
}

# ---------------------------------------------------------------------------
# --list / --dry-run / --status (ohne Sperre, aendern nichts)
# ---------------------------------------------------------------------------
if [ "$MODE" = "list" ] || [ "$MODE" = "dry" ]; then
  [ "$MODE" = "dry" ] && echo "Trockenlauf, es wird nichts ausgefuehrt." || true
  echo "scene_nightly.sh v1.1.0"
  echo "  Archiv:        ${ARCHIVE:-(nicht gesetzt, pipeline.env anlegen)}"
  echo "  Processor:     $PROCESSOR_DIR"
  echo "  Status/Logs:   $STATE_DIR"
  echo "  Mirror Skript: ${MIRROR_SCRIPT:-keins (Schritt wird uebersprungen)}"
  echo "  Discord:       $([ -n "$DISCORD_WEBHOOK_URL" ] && echo eingerichtet || echo "nicht eingerichtet")"
  echo "  Haken danach:  $([ -f "$AFTER_HOOK" ] && echo "$AFTER_HOOK" || echo "keiner (after_pipeline.sh nicht vorhanden)")"
  echo "Schritte:"
  i=0
  for s in "${STEPS[@]}"; do
    i=$((i+1))
    if selected "$s"; then m="laeuft"; else m="ausgelassen"; fi
    printf '  %d %-10s %-45s %s\n' "$i" "$s" "${STEP_TEXT[$s]}" "$m"
  done
  exit 0
fi

if [ "$MODE" = "status" ]; then
  if [ -f "$RUNNING" ]; then
    pid=$(sed -n 's/^pid=//p' "$RUNNING")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "Die Pipeline LAEUFT."
      cat "$RUNNING"
      exit 0
    fi
  fi
  echo "Die Pipeline laeuft gerade nicht."
  [ -f "$LAST_RUN" ] && { echo; echo "Letzter Lauf:"; cat "$LAST_RUN"; }
  [ -f "$HISTORY" ] && { echo; echo "Letzte Laeufe:"; tail -n 7 "$HISTORY" | tr '\t' ' '; }
  exit 0
fi

if [ -z "$ARCHIVE" ] || [ ! -d "$ARCHIVE" ]; then
  echo "ARCHIVE ist nicht gesetzt oder der Ordner existiert nicht (pipeline.env anlegen, siehe pipeline.env.example)."
  exit 3
fi

# ---------------------------------------------------------------------------
# Sperren: nur ein Lauf, und kein Hand Lauf des Processors gleichzeitig
# ---------------------------------------------------------------------------
mkdir -p "$STATE_DIR" || { echo "Statusordner $STATE_DIR nicht anlegbar"; exit 3; }

if [ -f "$RUNNING" ]; then
  opid=$(sed -n 's/^pid=//p' "$RUNNING")
  if [ -n "$opid" ] && kill -0 "$opid" 2>/dev/null && grep -q scene_nightly "/proc/$opid/cmdline" 2>/dev/null; then
    echo "Die Pipeline laeuft schon (PID $opid). Abbruch."
    exit 3
  fi
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(ts) Sperre belegt (vermutlich ein Hand Lauf des Processors), warte bis zu $LOCK_WAIT_MIN Minuten ..."
  if ! flock -w $((LOCK_WAIT_MIN * 60)) 9; then
    echo "$(ts) Sperre nach $LOCK_WAIT_MIN Minuten nicht frei, Abbruch."
    [ -n "$NOTIFY" ] && [ -x "$NOTIFY" ] && "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly nicht gestartet" -d "Sperre belegt, siehe scene_nightly.sh --status" -i warning
    exit 3
  fi
fi

START_EPOCH=$(date +%s)
START_TEXT=$(ts)
RUN_ID=$(date +%F_%H%M)
LOG="$STATE_DIR/scene_nightly_$RUN_ID.log"
: > "$LOG"

{
  echo "pid=$$"
  echo "start=$START_TEXT"
  echo "schritt=Vorbereitung"
} > "$RUNNING"

set_current() { sed -i "s/^schritt=.*/schritt=$1 (seit $(date '+%H:%M'))/" "$RUNNING" 2>/dev/null; }

RES_NAME=(); RES_STATUS=(); RES_NOTE=(); RES_DUR=()
FINALIZED=0

record() {   # name status note dauer
  RES_NAME+=("$1"); RES_STATUS+=("$2"); RES_NOTE+=("$3"); RES_DUR+=("$4")
}

# ---------------------------------------------------------------------------
# Discord und optionale Benachrichtigung
# ---------------------------------------------------------------------------
post_discord() {
  local msg esc code
  [ -n "$DISCORD_WEBHOOK_URL" ] || return 1
  msg=${1:0:1900}
  esc=$(printf '%s' "$msg" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{printf "%s\\n", $0}')
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -H "Content-Type: application/json" \
    -d "{\"username\":\"Scene Nightly\",\"flags\":4,\"allowed_mentions\":{\"parse\":[]},\"content\":\"$esc\"}" \
    "$DISCORD_WEBHOOK_URL")
  case "$code" in 2??) return 0 ;; *) say "Discord Meldung fehlgeschlagen (HTTP ${code:-keine Antwort})"; return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Abschluss: Zusammenfassung, Meldungen, Haken (auch bei Abbruch)
# ---------------------------------------------------------------------------
finalize() {
  local result="$1" end_epoch total i icon line text rc_out
  [ "$FINALIZED" = 1 ] && return
  FINALIZED=1
  end_epoch=$(date +%s)
  total=$(fmt_dur $((end_epoch - START_EPOCH)))

  text="Scene Nightly $START_TEXT, Dauer $total: $result"$'\n'
  for i in "${!RES_NAME[@]}"; do
    case "${RES_STATUS[$i]}" in
      OK) icon="✅" ;; WARN) icon="⚠️" ;; FAIL) icon="❌" ;; *) icon="⏭️" ;;
    esac
    line="$icon ${RES_NAME[$i]}"
    [ "${RES_STATUS[$i]}" != "SKIP" ] && [ "${RES_DUR[$i]}" -gt 0 ] && line+=" ($(fmt_dur "${RES_DUR[$i]}"))"
    [ -n "${RES_NOTE[$i]}" ] && line+=": ${RES_NOTE[$i]}"
    text+="$line"$'\n'
  done

  say "=== Zusammenfassung ==="
  printf '%s' "$text" | tee -a "$LOG"
  printf '%s' "$text" > "$LAST_RUN"
  printf '%s\t%s\t%s\t%s\n' "$START_TEXT" "$total" "$result" "$(IFS=,; echo "${RES_NAME[*]}")" >> "$HISTORY"

  post_discord "$text" || true

  if [ -n "$NOTIFY" ] && [ -x "$NOTIFY" ]; then
    case "$result" in
      FEHLER)         "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: Fehler" -d "$(printf '%s' "$text" | head -c 400)" -i alert ;;
      "MIT HINWEISEN") "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: Hinweise" -d "$(printf '%s' "$text" | head -c 400)" -i warning ;;
      *) [ "$NOTIFY_ON_OK" = 1 ] && "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: ok ($total)" -d "alle Schritte ok" -i normal ;;
    esac
  fi

  find "$STATE_DIR" -name 'scene_nightly_*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null

  if [ -f "$AFTER_HOOK" ] && [ "$result" = "ABGEBROCHEN" ]; then
    say "Haken $AFTER_HOOK wird bei einem Abbruch von Hand nicht gestartet."
  elif [ -f "$AFTER_HOOK" ]; then
    say "Starte Haken: $AFTER_HOOK ($result)"
    bash "$AFTER_HOOK" "$result" >> "$LOG" 2>&1
    rc_out=$?
    say "Haken beendet mit Code $rc_out"
  fi
  rm -f "$RUNNING" "$NOTE_FILE"
}

on_signal() { say "Abbruch durch Signal."; record "abbruch" FAIL "Pipeline wurde beendet" 0; finalize "ABGEBROCHEN"; exit 130; }
trap on_signal INT TERM

say "scene_nightly.sh v1.1.0 gestartet, Log: $LOG"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
PRE_FAIL=""; PRE_WARN=""

preflight() {
  local n
  [ -d "$ARCHIVE/scenereleases_srr" ] || { PRE_FAIL="Ordner scenereleases_srr fehlt (Layout v3 noetig, siehe docs/UPGRADE_FROM_2.2.md)"; return 1; }
  if [ "$MIN_ENTRIES" -gt 0 ]; then
    n=$(find "$ARCHIVE/scenereleases_srr" -mindepth 1 -maxdepth 1 2>/dev/null | head -n "$MIN_ENTRIES" | wc -l)
    if [ "$n" -lt "$MIN_ENTRIES" ]; then
      PRE_FAIL="scenereleases_srr hat weniger als $MIN_ENTRIES Eintraege, Laufwerk eingebunden?"
      return 1
    fi
  fi
  [ -d "$ARCHIVE/incoming" ] || { PRE_FAIL="Ordner incoming fehlt"; return 1; }
  [ -f "$PROCESSOR_DIR/docker-compose.yml" ] || { PRE_FAIL="$PROCESSOR_DIR/docker-compose.yml fehlt"; return 1; }
  if ! docker info >/dev/null 2>&1; then
    PRE_FAIL="Docker laeuft nicht oder ist fuer diesen Benutzer nicht erreichbar"; return 1
  fi
  if [ -n "$MIRROR_SCRIPT" ] && [ ! -f "$MIRROR_SCRIPT" ]; then
    PRE_WARN+="MIRROR_SCRIPT $MIRROR_SCRIPT nicht gefunden. "
  fi
  return 0
}

if ! preflight; then
  say "PREFLIGHT FEHLGESCHLAGEN: $PRE_FAIL"
  record "preflight" FAIL "$PRE_FAIL" 0
  finalize "FEHLER"
  exit 2
fi
say "Preflight ok. incoming: $(find "$ARCHIVE/incoming" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l) Eintraege. Frei: $(df -h --output=avail "$ARCHIVE" 2>/dev/null | tail -n 1 | tr -d ' ')"
if [ -n "$PRE_WARN" ]; then
  PRE_WARN="${PRE_WARN% }"
  say "Hinweise: $PRE_WARN"
  record "preflight" WARN "$PRE_WARN" 0
fi

# ---------------------------------------------------------------------------
# Schritte. Rueckgabe: 0 ok, 1 Fehler, 2 Hinweis, 3 uebersprungen
# ---------------------------------------------------------------------------
step_processor() {
  local n rc detail
  n=$(find "$ARCHIVE/incoming" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { note "incoming ist leer"; return 3; }
  echo "incoming enthaelt $n Eintraege"
  "$WAIT_PROCESSOR" 60 || { note "ein anderer Processor Lauf war nicht beendbar"; return 1; }
  SCENE_PIPELINE=1 "$PROC_WRAPPER" 2>&1 | tee "$STATE_DIR/last_processor.out"
  rc=${PIPESTATUS[0]}
  detail=$(sed -nE 's/^  → (.*):[[:space:]]+([0-9]+)$/\1|\2/p' "$STATE_DIR/last_processor.out" \
    | awk -F'|' '$2>0 {sub(/^scenereleases_/,"",$1); printf "%s%s %s", (c++?", ":""), $1, $2}')
  note "${detail:-nichts verschoben}"
  [ "$rc" -eq 0 ] || { note "Processor endete mit Code $rc. ${detail}"; return 1; }
  return 0
}

step_links() {
  local out rc
  out=$(in_image python /app/tools/sync_scene_links.py --archive /archive --apply 2>&1)
  rc=$?
  echo "$out"
  note "$(echo "$out" | grep -E '^angelegt:' | sed -E 's/^ +//')"
  [ "$rc" -eq 0 ] || { note "sync_scene_links.py endete mit Code $rc"; return 1; }
  return 0
}

step_mirror() {
  [ -n "$MIRROR_SCRIPT" ] || { note "kein MIRROR_SCRIPT eingerichtet"; return 3; }
  [ -f "$MIRROR_SCRIPT" ] || { note "$MIRROR_SCRIPT fehlt"; return 1; }
  bash "$MIRROR_SCRIPT" 2>&1
  case $? in
    0) return 0 ;;
    2) note "Mirror ok, mit Hinweis (siehe Protokoll)"; return 2 ;;
    *) note "Mirror Skript fehlgeschlagen"; return 1 ;;
  esac
}

step_stats() {
  mkdir -p "$STATE_DIR"
  in_image python /app/tools/archive_stats.py >> "$STATE_DIR/archive_stats.log" 2>&1
  local rc=$?
  tail -n 4 "$STATE_DIR/archive_stats.log"
  [ "$rc" -eq 0 ] || { note "archive_stats.py endete mit Code $rc"; return 1; }
  grep -qi "genre statistics skipped" "$ARCHIVE/ARCHIVE_STATS.txt" 2>/dev/null && { note "Genre Teil uebersprungen, siehe ARCHIVE_STATS.txt"; return 2; }
  return 0
}

step_sorter() {
  in_image python /app/tools/archive_sorter.py >> "$STATE_DIR/archive_sorter.log" 2>&1
  local rc=$?
  tail -n 4 "$STATE_DIR/archive_sorter.log"
  [ "$rc" -eq 0 ] || { note "archive_sorter.py endete mit Code $rc"; return 1; }
  return 0
}

# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------
ANY_FAIL=0; ANY_WARN=0
[ -n "$PRE_WARN" ] && ANY_WARN=1

for s in "${STEPS[@]}"; do
  selected "$s" || continue
  set_current "$s"
  say "=== Schritt $s: ${STEP_TEXT[$s]} ==="
  : > "$NOTE_FILE"
  t0=$(date +%s)
  "step_$s" 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  dur=$(( $(date +%s) - t0 ))
  n=$(cat "$NOTE_FILE" 2>/dev/null)
  case $rc in
    0) st=OK ;;
    2) st=WARN; ANY_WARN=1 ;;
    3) st=SKIP ;;
    *) st=FAIL; ANY_FAIL=1 ;;
  esac
  say "Schritt $s: $st in $(fmt_dur "$dur")${n:+ ($n)}"
  record "$s" "$st" "$n" "$dur"
done

if   [ "$ANY_FAIL" = 1 ]; then RESULT="FEHLER";         EXIT=2
elif [ "$ANY_WARN" = 1 ]; then RESULT="MIT HINWEISEN";  EXIT=1
else RESULT="OK"; EXIT=0; fi
finalize "$RESULT"
exit $EXIT
