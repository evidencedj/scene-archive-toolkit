#!/bin/bash
#
# scene_nightly.sh  v1.2.0
#
# Nightly run of the Scene workflow. One single schedule starts all steps one
# after the other, every step waits for the previous one. There are no fixed
# times per job any more that could overtake each other when runs take long.
#
# VERSION HISTORY
#   1.0.0  2026-10-22  First version (original setup, Unraid). Steps processor,
#                      links, mirror, stats, sorter, hetzner, with preflight,
#                      lock, log, Discord and Unraid notification, hook
#                      after_pipeline.sh.
#   1.0.1  2026-10-24  Hetzner preflight fixed (original setup only).
#   1.0.2  2026-10-24  Stats: mutagen is installed for the container
#                      (original setup only).
#   1.1.0  2026-11-01  Portable edition (toolkit 1.1.0). Everything that only
#                      belonged to the original setup is removed: Hetzner step,
#                      UE mover lock, fixed containers, SSH check of the second
#                      machine, paths and webhook from secrets.env. The Python
#                      steps run in the toolkit image (docker compose run), all
#                      settings are in pipeline.env. The step "mirror" is
#                      optional (MIRROR_SCRIPT), without an entry it is skipped.
#   1.2.0  2026-11-01  All messages and comments translated to English.
#
# STEPS (in this order):
#   processor  process incoming (scene check, move, links)
#   links      sync the symlinks in scenereleases
#   mirror     optional: your own script (copy to a second machine, reindex)
#   stats      rewrite ARCHIVE_STATS.txt
#   sorter     rebuild the _sorted_ links
#
# USAGE:
#   scene_nightly.sh                    all steps
#   scene_nightly.sh --only stats,sorter
#   scene_nightly.sh --skip mirror
#   scene_nightly.sh --list             show steps and settings
#   scene_nightly.sh --dry-run          show what would run, do nothing
#   scene_nightly.sh --status           is something running, how was the last run
#
# EXIT CODE: 0 all ok, 1 with warnings, 2 with errors, 3 not started

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/pipeline.env" ] && . "$HERE/pipeline.env"

# ---------------------------------------------------------------------------
# Settings (from pipeline.env or the environment)
# ---------------------------------------------------------------------------
ARCHIVE="${ARCHIVE:-}"
PROCESSOR_DIR="${PROCESSOR_DIR:-$HERE/../processor}"
STATE_DIR="${STATE_DIR:-$HERE/state}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"

LOCK="$STATE_DIR/pipeline.lock"
LOCK_WAIT_MIN="${LOCK_WAIT_MIN:-120}"          # how long to wait for a manual processor run
MIN_ENTRIES="${MIN_ENTRIES:-0}"                # scenereleases_srr must have at least this many entries
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
  [processor]="process incoming"
  [links]="sync links in scenereleases"
  [mirror]="optional: your own mirror script"
  [stats]="write ARCHIVE_STATS.txt"
  [sorter]="build _sorted_ links"
)

RUNNING="$STATE_DIR/running.txt"
LAST_RUN="$STATE_DIR/last_run.txt"
HISTORY="$STATE_DIR/history.tsv"
NOTE_FILE="$STATE_DIR/.step_note"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
ts()  { date '+%F %T'; }
say() { if [ -n "${LOG:-}" ]; then echo "$(ts) $*" | tee -a "$LOG"; else echo "$(ts) $*"; fi; }
note() { printf '%s' "$1" > "$NOTE_FILE"; }

fmt_dur() {   # seconds -> "1h 12m" / "5m 03s" / "42s"
  local s=$1
  if   [ "$s" -ge 3600 ]; then printf '%dh %02dm' $((s/3600)) $(((s%3600)/60))
  elif [ "$s" -ge 60 ];   then printf '%dm %02ds' $((s/60)) $((s%60))
  else printf '%ds' "$s"; fi
}

# Run a command in the toolkit image (without a TTY, so it also works from cron)
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
    *) echo "Unknown option: $1"; usage; exit 3 ;;
  esac
done

for opt in "$ONLY" "$SKIP"; do
  for n in $(echo "$opt" | tr ',' ' '); do
    case " ${STEPS[*]} " in *" $n "*) ;; *) echo "Unknown step: $n (valid: ${STEPS[*]})"; exit 3 ;; esac
  done
done

selected() {
  [ -z "$ONLY" ] || case "$ONLY" in *",$1,"*) ;; *) return 1 ;; esac
  case "$SKIP" in *",$1,"*) return 1 ;; esac
  return 0
}

# ---------------------------------------------------------------------------
# --list / --dry-run / --status (without lock, they change nothing)
# ---------------------------------------------------------------------------
if [ "$MODE" = "list" ] || [ "$MODE" = "dry" ]; then
  [ "$MODE" = "dry" ] && echo "Dry run, nothing is executed." || true
  echo "scene_nightly.sh v1.2.0"
  echo "  Archive:       ${ARCHIVE:-(not set, create pipeline.env)}"
  echo "  Processor:     $PROCESSOR_DIR"
  echo "  State/logs:    $STATE_DIR"
  echo "  Mirror script: ${MIRROR_SCRIPT:-none (step is skipped)}"
  echo "  Discord:       $([ -n "$DISCORD_WEBHOOK_URL" ] && echo configured || echo "not configured")"
  echo "  After hook:    $([ -f "$AFTER_HOOK" ] && echo "$AFTER_HOOK" || echo "none (after_pipeline.sh does not exist)")"
  echo "Steps:"
  i=0
  for s in "${STEPS[@]}"; do
    i=$((i+1))
    if selected "$s"; then m="runs"; else m="skipped"; fi
    printf '  %d %-10s %-45s %s\n' "$i" "$s" "${STEP_TEXT[$s]}" "$m"
  done
  exit 0
fi

if [ "$MODE" = "status" ]; then
  if [ -f "$RUNNING" ]; then
    pid=$(sed -n 's/^pid=//p' "$RUNNING")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "The pipeline is RUNNING."
      cat "$RUNNING"
      exit 0
    fi
  fi
  echo "The pipeline is not running right now."
  [ -f "$LAST_RUN" ] && { echo; echo "Last run:"; cat "$LAST_RUN"; }
  [ -f "$HISTORY" ] && { echo; echo "Recent runs:"; tail -n 7 "$HISTORY" | tr '\t' ' '; }
  exit 0
fi

if [ -z "$ARCHIVE" ] || [ ! -d "$ARCHIVE" ]; then
  echo "ARCHIVE is not set or the folder does not exist (create pipeline.env, see pipeline.env.example)."
  exit 3
fi

# ---------------------------------------------------------------------------
# Locks: only one run, and no manual processor run at the same time
# ---------------------------------------------------------------------------
mkdir -p "$STATE_DIR" || { echo "Cannot create state folder $STATE_DIR"; exit 3; }

if [ -f "$RUNNING" ]; then
  opid=$(sed -n 's/^pid=//p' "$RUNNING")
  if [ -n "$opid" ] && kill -0 "$opid" 2>/dev/null && grep -q scene_nightly "/proc/$opid/cmdline" 2>/dev/null; then
    echo "The pipeline is already running (PID $opid). Aborting."
    exit 3
  fi
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(ts) Lock is held (probably a manual processor run), waiting up to $LOCK_WAIT_MIN minutes ..."
  if ! flock -w $((LOCK_WAIT_MIN * 60)) 9; then
    echo "$(ts) Lock still held after $LOCK_WAIT_MIN minutes, aborting."
    [ -n "$NOTIFY" ] && [ -x "$NOTIFY" ] && "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly not started" -d "Lock is held, see scene_nightly.sh --status" -i warning
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
  echo "step=preparing"
} > "$RUNNING"

set_current() { sed -i "s/^step=.*/step=$1 (since $(date '+%H:%M'))/" "$RUNNING" 2>/dev/null; }

RES_NAME=(); RES_STATUS=(); RES_NOTE=(); RES_DUR=()
FINALIZED=0

record() {   # name status note duration
  RES_NAME+=("$1"); RES_STATUS+=("$2"); RES_NOTE+=("$3"); RES_DUR+=("$4")
}

# ---------------------------------------------------------------------------
# Discord and optional notification
# ---------------------------------------------------------------------------
post_discord() {
  local msg esc code
  [ -n "$DISCORD_WEBHOOK_URL" ] || return 1
  msg=${1:0:1900}
  esc=$(printf '%s' "$msg" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{printf "%s\\n", $0}')
  code=$(curl -s -m 15 -o /dev/null -w '%{http_code}' -H "Content-Type: application/json" \
    -d "{\"username\":\"Scene Nightly\",\"flags\":4,\"allowed_mentions\":{\"parse\":[]},\"content\":\"$esc\"}" \
    "$DISCORD_WEBHOOK_URL")
  case "$code" in 2??) return 0 ;; *) say "Discord message failed (HTTP ${code:-no response})"; return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Finish: summary, notifications, hook (also on abort)
# ---------------------------------------------------------------------------
finalize() {
  local result="$1" end_epoch total i icon line text rc_out
  [ "$FINALIZED" = 1 ] && return
  FINALIZED=1
  end_epoch=$(date +%s)
  total=$(fmt_dur $((end_epoch - START_EPOCH)))

  text="Scene Nightly $START_TEXT, duration $total: $result"$'\n'
  for i in "${!RES_NAME[@]}"; do
    case "${RES_STATUS[$i]}" in
      OK) icon="✅" ;; WARN) icon="⚠️" ;; FAIL) icon="❌" ;; *) icon="⏭️" ;;
    esac
    line="$icon ${RES_NAME[$i]}"
    [ "${RES_STATUS[$i]}" != "SKIP" ] && [ "${RES_DUR[$i]}" -gt 0 ] && line+=" ($(fmt_dur "${RES_DUR[$i]}"))"
    [ -n "${RES_NOTE[$i]}" ] && line+=": ${RES_NOTE[$i]}"
    text+="$line"$'\n'
  done

  say "=== Summary ==="
  printf '%s' "$text" | tee -a "$LOG"
  printf '%s' "$text" > "$LAST_RUN"
  printf '%s\t%s\t%s\t%s\n' "$START_TEXT" "$total" "$result" "$(IFS=,; echo "${RES_NAME[*]}")" >> "$HISTORY"

  post_discord "$text" || true

  if [ -n "$NOTIFY" ] && [ -x "$NOTIFY" ]; then
    case "$result" in
      ERROR)         "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: error" -d "$(printf '%s' "$text" | head -c 400)" -i alert ;;
      "WITH WARNINGS") "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: warnings" -d "$(printf '%s' "$text" | head -c 400)" -i warning ;;
      *) [ "$NOTIFY_ON_OK" = 1 ] && "$NOTIFY" -e "Scene Nightly" -s "Scene Nightly: ok ($total)" -d "all steps ok" -i normal ;;
    esac
  fi

  find "$STATE_DIR" -name 'scene_nightly_*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null

  if [ -f "$AFTER_HOOK" ] && [ "$result" = "ABORTED" ]; then
    say "Hook $AFTER_HOOK is not started after a manual abort."
  elif [ -f "$AFTER_HOOK" ]; then
    say "Starting hook: $AFTER_HOOK ($result)"
    bash "$AFTER_HOOK" "$result" >> "$LOG" 2>&1
    rc_out=$?
    say "Hook finished with code $rc_out"
  fi
  rm -f "$RUNNING" "$NOTE_FILE"
}

on_signal() { say "Aborted by signal."; record "abort" FAIL "Pipeline was stopped" 0; finalize "ABORTED"; exit 130; }
trap on_signal INT TERM

say "scene_nightly.sh v1.2.0 started, log: $LOG"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
PRE_FAIL=""; PRE_WARN=""

preflight() {
  local n
  [ -d "$ARCHIVE/scenereleases_srr" ] || { PRE_FAIL="Folder scenereleases_srr is missing (v3 layout required, see docs/MIGRATION.md)"; return 1; }
  if [ "$MIN_ENTRIES" -gt 0 ]; then
    n=$(find "$ARCHIVE/scenereleases_srr" -mindepth 1 -maxdepth 1 2>/dev/null | head -n "$MIN_ENTRIES" | wc -l)
    if [ "$n" -lt "$MIN_ENTRIES" ]; then
      PRE_FAIL="scenereleases_srr has fewer than $MIN_ENTRIES entries, is the drive mounted?"
      return 1
    fi
  fi
  [ -d "$ARCHIVE/incoming" ] || { PRE_FAIL="Folder incoming is missing"; return 1; }
  [ -f "$PROCESSOR_DIR/docker-compose.yml" ] || { PRE_FAIL="$PROCESSOR_DIR/docker-compose.yml is missing"; return 1; }
  if ! docker info >/dev/null 2>&1; then
    PRE_FAIL="Docker is not running or not reachable for this user"; return 1
  fi
  if [ -n "$MIRROR_SCRIPT" ] && [ ! -f "$MIRROR_SCRIPT" ]; then
    PRE_WARN+="MIRROR_SCRIPT $MIRROR_SCRIPT not found. "
  fi
  return 0
}

if ! preflight; then
  say "PREFLIGHT FAILED: $PRE_FAIL"
  record "preflight" FAIL "$PRE_FAIL" 0
  finalize "ERROR"
  exit 2
fi
say "Preflight ok. incoming: $(find "$ARCHIVE/incoming" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l) entries. Free: $(df -h --output=avail "$ARCHIVE" 2>/dev/null | tail -n 1 | tr -d ' ')"
if [ -n "$PRE_WARN" ]; then
  PRE_WARN="${PRE_WARN% }"
  say "Warnings: $PRE_WARN"
  record "preflight" WARN "$PRE_WARN" 0
fi

# ---------------------------------------------------------------------------
# Steps. Return code: 0 ok, 1 error, 2 warning, 3 skipped
# ---------------------------------------------------------------------------
step_processor() {
  local n rc detail
  n=$(find "$ARCHIVE/incoming" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { note "incoming is empty"; return 3; }
  echo "incoming contains $n entries"
  "$WAIT_PROCESSOR" 60 || { note "another processor run could not be stopped"; return 1; }
  SCENE_PIPELINE=1 "$PROC_WRAPPER" 2>&1 | tee "$STATE_DIR/last_processor.out"
  rc=${PIPESTATUS[0]}
  detail=$(sed -nE 's/^  → (.*):[[:space:]]+([0-9]+)$/\1|\2/p' "$STATE_DIR/last_processor.out" \
    | awk -F'|' '$2>0 {sub(/^scenereleases_/,"",$1); printf "%s%s %s", (c++?", ":""), $1, $2}')
  note "${detail:-nothing moved}"
  [ "$rc" -eq 0 ] || { note "Processor ended with code $rc. ${detail}"; return 1; }
  return 0
}

step_links() {
  local out rc
  out=$(in_image python /app/tools/sync_scene_links.py --archive /archive --apply 2>&1)
  rc=$?
  echo "$out"
  note "$(echo "$out" | grep -E '^created:' | sed -E 's/^ +//')"
  [ "$rc" -eq 0 ] || { note "sync_scene_links.py ended with code $rc"; return 1; }
  return 0
}

step_mirror() {
  [ -n "$MIRROR_SCRIPT" ] || { note "no MIRROR_SCRIPT configured"; return 3; }
  [ -f "$MIRROR_SCRIPT" ] || { note "$MIRROR_SCRIPT is missing"; return 1; }
  bash "$MIRROR_SCRIPT" 2>&1
  case $? in
    0) return 0 ;;
    2) note "Mirror ok, with a warning (see log)"; return 2 ;;
    *) note "Mirror script failed"; return 1 ;;
  esac
}

step_stats() {
  mkdir -p "$STATE_DIR"
  in_image python /app/tools/archive_stats.py >> "$STATE_DIR/archive_stats.log" 2>&1
  local rc=$?
  tail -n 4 "$STATE_DIR/archive_stats.log"
  [ "$rc" -eq 0 ] || { note "archive_stats.py ended with code $rc"; return 1; }
  grep -qi "genre statistics skipped" "$ARCHIVE/ARCHIVE_STATS.txt" 2>/dev/null && { note "Genre part skipped, see ARCHIVE_STATS.txt"; return 2; }
  return 0
}

step_sorter() {
  in_image python /app/tools/archive_sorter.py >> "$STATE_DIR/archive_sorter.log" 2>&1
  local rc=$?
  tail -n 4 "$STATE_DIR/archive_sorter.log"
  [ "$rc" -eq 0 ] || { note "archive_sorter.py ended with code $rc"; return 1; }
  return 0
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
ANY_FAIL=0; ANY_WARN=0
[ -n "$PRE_WARN" ] && ANY_WARN=1

for s in "${STEPS[@]}"; do
  selected "$s" || continue
  set_current "$s"
  say "=== Step $s: ${STEP_TEXT[$s]} ==="
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
  say "Step $s: $st in $(fmt_dur "$dur")${n:+ ($n)}"
  record "$s" "$st" "$n" "$dur"
done

if   [ "$ANY_FAIL" = 1 ]; then RESULT="ERROR";         EXIT=2
elif [ "$ANY_WARN" = 1 ]; then RESULT="WITH WARNINGS";  EXIT=1
else RESULT="OK"; EXIT=0; fi
finalize "$RESULT"
exit $EXIT
