#!/usr/bin/env bash
# unimate_ctl.sh — detect / start / stop / inspect UniMate services.
#
# Services:
#   bridge      Wifi/raspi2.py via uvicorn, port 5000  (must run from Wifi/: CWD-relative
#               artifact dirs ../saved ../questions ../summaries; adds LED/ to sys.path)
#   ui          combined stack: shared_mic/capture_server.py spawns
#               mic capture server + alexa/voiceAgent2_shared.py + UIUX_FC2.main.shared_start()
#   ui-solo     UI only: UIUX_FC2/main.py (no shared audio queue)
#   voice-solo  standalone Gemini voice: alexa/voiceAgent2.py (opens the mic directly)
#   camera      Livefeed (mediamtx + ngrok), toggled through the bridge /online endpoint
#               so the bridge's camera_loop logic stays authoritative.
#
# Run with no arguments (from a TTY) for the curse dashboard (unimate_tui.py).
#
# Usage:
#   unimate_ctl.sh status [--json]
#   unimate_ctl.sh start  bridge|ui|ui-solo|voice-solo|all
#   unimate_ctl.sh stop   bridge|ui|ui-solo|voice-solo|all   [--force]
#   unimate_ctl.sh restart bridge|ui|all
#   unimate_ctl.sh logs   bridge|ui|ui-solo|voice-solo [-f] [-n N]
#   unimate_ctl.sh camera on|off|toggle|status
#   unimate_ctl.sh help
#
# Stop always sends SIGINT first (mirrors capture_server.py's KeyboardInterrupt cleanup
# and lets uvicorn's FastAPI shutdown event run), then SIGTERM, then SIGKILL.

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Worktree-safe imports (same logic as use_worktree.sh): our checkout wins over whatever
# ~/unimate/bin/activate hardcoded into PYTHONPATH (it pins the main checkout).
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/UIUX_FC2:${PYTHONPATH:-}"

PYBIN="$HOME/unimate/bin/python3"
UVICORN="$HOME/unimate/bin/uvicorn"
if [ ! -x "$PYBIN" ]; then PYBIN="$(command -v python3)"; fi
if [ ! -x "$UVICORN" ]; then UVICORN="$PYBIN -m uvicorn"; fi

BASE_URL="${UNIMATE_RASPI_BRIDGE_URL:-http://127.0.0.1:5000}"
BRIDGE_PORT="${BASE_URL##*:}"

# pgrep -f patterns (POSIX ERE against the full command line)
PAT_BRIDGE='uvicorn.*raspi2:app'
PAT_UI='shared_mic/capture_server\.py'
PAT_UI_SOLO='python3? +main\.py( |$)'
PAT_VOICE='alexa/voiceAgent2\.py( |$)'
PAT_EARS='ears/ear\.py'
PAT_FACE='CV/new/no_emo_flipped_headless\.py'

LOG_BRIDGE="$LOGS_DIR/bridge.log"
LOG_UI="$LOGS_DIR/ui.log"
LOG_UI_SOLO="$LOGS_DIR/ui-solo.log"
LOG_VOICE="$LOGS_DIR/voice-solo.log"
LOG_EARS="$LOGS_DIR/ears.log"
LOG_FACE="$LOGS_DIR/face_follow.log"

# ---------------------------------------------------------------- helpers

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

human_time() { # seconds -> "1d 2h 3m"
  local s=${1:-0} d h m
  [ "$s" -lt 0 ] && { echo "-"; return; }
  d=$((s / 86400)); h=$((s % 86400 / 3600)); m=$((s % 3600 / 60))
  if [ "$d" -gt 0 ]; then printf '%dd %dh' "$d" "$h"
  elif [ "$h" -gt 0 ]; then printf '%dh %dm' "$h" "$m"
  else printf '%dm' "$m"; fi
}

running_pids() { pgrep -f "$1" 2>/dev/null | sort -n; }
pid_of() { running_pids "$1" | head -1; }
up_of() { # pid -> etimes seconds or -1
  local v=""
  [ -n "${1:-}" ] && v="$(ps -o etimes= -p "$1" 2>/dev/null | tr -d ' ')"
  [ -n "$v" ] || v=-1
  printf '%s' "$v"
}

health() { curl -sf -m 2 "$BASE_URL/data" >/dev/null 2>&1; }

camera_on() { pgrep -x mediamtx >/dev/null 2>&1; }

tail_log() { [ -f "$1" ] && tail -n "${2:-5}" "$1"; }

# stop_by_pattern PAT NAME GRACE: SIGINT -> SIGTERM -> SIGKILL, verify gone
stop_by_pattern() {
  local pat="$1" name="$2" grace="${3:-5}" pids left el
  pids="$(running_pids "$pat")"
  if [ -z "$pids" ]; then say "$name: not running"; return 0; fi
  say "$name: stopping (pids $(echo "$pids" | tr '\n' ' '))"
  kill -INT $pids 2>/dev/null
  el=0
  while [ "$el" -lt "$grace" ]; do
    left="$(running_pids "$pat")"
    [ -z "$left" ] && { say "$name: stopped"; return 0; }
    sleep 0.5; el=$((el + 1))
  done
  say "$name: SIGINT timeout, escalating"
  pids="$(running_pids "$pat")"
  [ -n "$pids" ] && kill -TERM $pids 2>/dev/null
  sleep 2
  pids="$(running_pids "$pat")"
  if [ -n "$pids" ]; then
    say "$name: force killing"
    kill -KILL $pids 2>/dev/null
    sleep 1
    running_pids "$pat" >/dev/null && say "$name: STILL RUNNING (kill -9 failed?)"
  else
    say "$name: stopped (forced)"
  fi
}

sweep_camera_orphans() {
  local pmm png pids
  pmm="$(pgrep -x mediamtx 2>/dev/null)"
  png="$(pgrep -x ngrok 2>/dev/null)"
  pids="$pmm $png"; pids="${pids// /}"
  [ -z "$pids" ] && return 0
  say "camera: killing orphan processes ($(echo "$pids" | tr '\n' ' '))"
  kill -TERM $pmm $png 2>/dev/null; sleep 2
  pmm="$(pgrep -x mediamtx 2>/dev/null)"; png="$(pgrep -x ngrok 2>/dev/null)"
  if [ -n "$pmm" ] || [ -n "$png" ]; then
    kill -KILL $pmm $png 2>/dev/null; sleep 1
  fi
  return 0
}

# ---------------------------------------------------------------- camera helpers

camera_post() {
  curl -sf -m 3 -X POST -H 'Content-Type: application/json' \
       -d "{\"requesting_toggle\": $1}" "$BASE_URL/online"
}

# ---------------------------------------------------------------- status

cmd_status() {
  local as_json=0 a
  for a in "$@"; do [ "$a" = "--json" ] && as_json=1; done

  local b_pid b_up b_health ui_pid ui_up us_pid us_up vs_pid vs_up e_pid e_up ff_pid ff_up
  local cam cmm cng
  b_pid="$(pid_of "$PAT_BRIDGE")";    b_up="$(up_of "$b_pid")"
  ui_pid="$(pid_of "$PAT_UI")";       ui_up="$(up_of "$ui_pid")"
  us_pid="$(pid_of "$PAT_UI_SOLO")";  us_up="$(up_of "$us_pid")"
  vs_pid="$(pid_of "$PAT_VOICE")";    vs_up="$(up_of "$vs_pid")"
  e_pid="$(pid_of "$PAT_EARS")";      e_up="$(up_of "$e_pid")"
  ff_pid="$(pid_of "$PAT_FACE")";     ff_up="$(up_of "$ff_pid")"
  cmm="$(pgrep -x mediamtx 2>/dev/null | head -1)"
  cng="$(pgrep -x ngrok 2>/dev/null | head -1)"
  if [ -n "$cmm" ]; then cam=on; else cam=off; fi
  b_health=0; health && b_health=1

  if [ "$as_json" = 1 ]; then
    printf '{"checkout":"%s","python":"%s","base_url":"%s","logs_dir":"%s"' \
      "$SCRIPT_DIR" "$PYBIN" "$BASE_URL" "$LOGS_DIR"
    printf ',"piper_ok":%s,"env_ui_ok":%s,"env_alexa_ok":%s' \
      "$([ -d "$SCRIPT_DIR/piper" ] && echo true || echo false)" \
      "$([ -f "$SCRIPT_DIR/UIUX_FC2/.env" ] && echo true || echo false)" \
      "$([ -f "$SCRIPT_DIR/alexa/.env" ] && echo true || echo false)"
    printf ',"bridge":{"running":%s,"pid":%s,"uptime_s":%d,"healthy":%s}' \
      "$([ -n "$b_pid" ] && echo true || echo false)" \
      "${b_pid:-null}" "${b_up%%.*}" "$([ "$b_health" = 1 ] && echo true || echo false)"
    printf ',"ui":{"running":%s,"pid":%s,"uptime_s":%d}' \
      "$([ -n "$ui_pid" ] && echo true || echo false)" \
      "${ui_pid:-null}" "${ui_up%%.*}"
    printf ',"ui_solo":{"running":%s,"pid":%s,"uptime_s":%d}' \
      "$([ -n "$us_pid" ] && echo true || echo false)" \
      "${us_pid:-null}" "${us_up%%.*}"
    printf ',"voice_solo":{"running":%s,"pid":%s,"uptime_s":%d}' \
      "$([ -n "$vs_pid" ] && echo true || echo false)" \
      "${vs_pid:-null}" "${vs_up%%.*}"
    printf ',"ears":{"running":%s,"pid":%s,"uptime_s":%d}' \
      "$([ -n "$e_pid" ] && echo true || echo false)" \
      "${e_pid:-null}" "${e_up%%.*}"
    printf ',"face_follow":{"running":%s,"pid":%s,"uptime_s":%d}' \
      "$([ -n "$ff_pid" ] && echo true || echo false)" \
      "${ff_pid:-null}" "${ff_up%%.*}"
    printf ',"camera":{"on":%s,"mediamtx_pid":%s,"ngrok_pid":%s}' \
      "$([ "$cam" = on ] && echo true || echo false)" \
      "${cmm:-null}" "${cng:-null}"
    printf '}\n'
  else
    say "UniMate services   checkout: $SCRIPT_DIR   bridge: $BASE_URL"
    printf '%-11s %-15s %-8s %-9s %s\n' "SERVICE" "STATE" "PID" "UPTIME" "DETAIL"
    local st
    st=Stopped; [ -n "$b_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "bridge" "$st" "${b_pid:--}" "$(human_time "$b_up")" \
      "$([ "$b_health" = 1 ] && echo "/data OK" || echo "no answer on :$BRIDGE_PORT")"
    st=Stopped; [ -n "$ui_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "ui" "$st" "${ui_pid:--}" "$(human_time "$ui_up")" \
      "capture_server.py (mic+voice+UI)"
    st=Stopped; [ -n "$us_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "ui-solo" "$st" "${us_pid:--}" "$(human_time "$us_up")" \
      "UIUX_FC2/main.py standalone"
    st=Stopped; [ -n "$vs_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "voice-solo" "$st" "${vs_pid:--}" "$(human_time "$vs_up")" \
      "alexa/voiceAgent2.py standalone"
    st=Stopped; [ -n "$e_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "ears" "$st" "${e_pid:--}" "$(human_time "$e_up")" \
      "ear touch sweep (PCA9685)"
    st=Stopped; [ -n "$ff_pid" ] && st=Running
    printf '%-11s %-15s %-8s %-9s %s\n' "face_follow" "$st" "${ff_pid:--}" "$(human_time "$ff_up")" \
      "camera face tracking + servos"
    printf '%-11s %-15s %-8s %-9s %s\n' "camera" "$cam" "${cmm:--}" "-" \
      "$([ "$cam" = on ] && echo "mediamtx pid $cmm${cng:+ + ngrok pid $cng}" || echo "not running")"
    return 0
  fi
}

# ---------------------------------------------------------------- start

start_bridge() {
  if [ -n "$(pid_of "$PAT_BRIDGE")" ]; then say "bridge: already running ($(pid_of "$PAT_BRIDGE"))"; return 0; fi
  say "bridge: starting uvicorn raspi2:app from $SCRIPT_DIR/Wifi (log: $LOG_BRIDGE)"
  (
    cd "$SCRIPT_DIR/Wifi" || exit 1
    exec setsid "$UVICORN" raspi2:app --host 0.0.0.0 --port 5000
  ) >>"$LOG_BRIDGE" 2>&1 &
  disown
  local el=0
  while [ "$el" -lt 20 ]; do
    if [ -n "$(pid_of "$PAT_BRIDGE")" ] && health; then
      say "bridge: running, /data answers on :$BRIDGE_PORT"
      return 0
    fi
    sleep 0.5; el=$((el + 1))
  done
  die "bridge: failed to start (last log lines:) $(tail_log "$LOG_BRIDGE")"
}

ui_stack_assets_warn() {
  [ -d "$SCRIPT_DIR/piper" ] || warn "piper/ not found — Piper TTS unavailable (hole in worktrees; lives only in /home/unimate/Unimate)"
  [ -f "$SCRIPT_DIR/UIUX_FC2/.env" ] || warn "UIUX_FC2/.env not found — OPENAI/GEMINI keys must come from the shell"
  [ -f "$SCRIPT_DIR/alexa/.env" ]   || warn "alexa/.env not found — GEMINI_API_KEY must come from the shell"
}

start_ui() {
  if [ -n "$(pid_of "$PAT_UI")" ]; then say "ui: already running ($(pid_of "$PAT_UI"))"; return 0; fi
  ui_stack_assets_warn
  health || warn "bridge is not running — UI will degrade to mock sensor/control data"
  say "ui: starting combined stack mic + voice + UI (log: $LOG_UI)"
  (
    cd "$SCRIPT_DIR" || exit 1
    exec setsid "$PYBIN" shared_mic/capture_server.py
  ) >>"$LOG_UI" 2>&1 &
  disown
  sleep 2
  if [ -n "$(pid_of "$PAT_UI")" ]; then
    say "ui: running (pid $(pid_of "$PAT_UI")) — window opens shortly on the display"
  else
    die "ui: failed to start (last log lines:) $(tail_log "$LOG_UI")"
  fi
}

start_ui_solo() {
  if [ -n "$(pid_of "$PAT_UI_SOLO")" ]; then say "ui-solo: already running ($(pid_of "$PAT_UI_SOLO"))"; return 0; fi
  if [ -n "$(pid_of "$PAT_UI")" ] && [ "${FORCE:-0}" != 1 ]; then
    die "ui-solo: combined stack is running — 'stop ui' first (or --force)"
  fi
  ui_stack_assets_warn
  health || warn "bridge is not running — UI will degrade to mock data"
  say "ui-solo: starting $PYBIN main.py in UIUX_FC2 (log: $LOG_UI_SOLO)"
  (
    cd "$SCRIPT_DIR/UIUX_FC2" || exit 1
    exec setsid "$PYBIN" main.py
  ) >>"$LOG_UI_SOLO" 2>&1 &
  disown
  sleep 2
  if [ -n "$(pid_of "$PAT_UI_SOLO")" ]; then
    say "ui-solo: running (pid $(pid_of "$PAT_UI_SOLO"))"
  else
    die "ui-solo: failed to start (last log lines:) $(tail_log "$LOG_UI_SOLO")"
  fi
}

start_voice_solo() {
  if [ -n "$(pid_of "$PAT_VOICE")" ]; then say "voice-solo: already running ($(pid_of "$PAT_VOICE"))"; return 0; fi
  if [ -n "$(pid_of "$PAT_UI")" ] && [ "${FORCE:-0}" != 1 ]; then
    die "voice-solo: combined stack is running (owns the mic) — 'stop ui' first (or --force)"
  fi
  [ -f "$SCRIPT_DIR/alexa/.env" ] || warn "alexa/.env not found — GEMINI_API_KEY must come from the shell"
  say "voice-solo: starting alexa/voiceAgent2.py (log: $LOG_VOICE)"
  (
    cd "$SCRIPT_DIR" || exit 1
    exec setsid "$PYBIN" alexa/voiceAgent2.py
  ) >>"$LOG_VOICE" 2>&1 &
  disown
  sleep 2
  if [ -n "$(pid_of "$PAT_VOICE")" ]; then
    say "voice-solo: running (pid $(pid_of "$PAT_VOICE"))"
  else
    die "voice-solo: failed to start (last log lines:) $(tail_log "$LOG_VOICE")"
  fi
}

start_ears() {
  if [ -n "$(pid_of "$PAT_EARS")" ]; then say "ears: already running ($(pid_of "$PAT_EARS"))"; return 0; fi
  say "ears: starting ears/ear.py (log: $LOG_EARS)"
  (
    cd "$SCRIPT_DIR" || exit 1
    exec setsid "$PYBIN" ears/ear.py
  ) >>"$LOG_EARS" 2>&1 &
  disown
  sleep 2
  if [ -n "$(pid_of "$PAT_EARS")" ]; then
    say "ears: running (pid $(pid_of "$PAT_EARS"))"
  else
    die "ears: failed to start (last log lines:) $(tail_log "$LOG_EARS")"
  fi
}

start_face_follow() {
  if [ -n "$(pid_of "$PAT_FACE")" ]; then say "face_follow: already running ($(pid_of "$PAT_FACE"))"; return 0; fi
  if camera_on; then
    warn "face_follow: camera feed (mediamtx) is running — the Pi camera is an exclusive resource"
  fi
  say "face_follow: starting CV face tracking + servos (log: $LOG_FACE)"
  (
    cd "$SCRIPT_DIR" || exit 1
    exec setsid "$PYBIN" CV/new/no_emo_flipped_headless.py
  ) >>"$LOG_FACE" 2>&1 &
  disown
  sleep 2
  if [ -n "$(pid_of "$PAT_FACE")" ]; then
    say "face_follow: running (pid $(pid_of "$PAT_FACE"))"
  else
    die "face_follow: failed to start (last log lines:) $(tail_log "$LOG_FACE")"
  fi
}

cmd_start() {
  case "${1:-}" in
    bridge) start_bridge ;;
    ui) start_ui ;;
    ui-solo) start_ui_solo ;;
    voice-solo) start_voice_solo ;;
    ears) start_ears ;;
    face_follow) start_face_follow ;;
    all) start_bridge; start_ui ;;
    *) die "start: expected bridge|ui|ui-solo|voice-solo|ears|face_follow|all" ;;
  esac
}

# ---------------------------------------------------------------- stop

stop_bridge()     { stop_by_pattern "$PAT_BRIDGE"  "bridge" 15; }
stop_ui()         { stop_by_pattern "$PAT_UI"     "ui" 8; }
stop_ui_solo()    { stop_by_pattern "$PAT_UI_SOLO" "ui-solo" 5; }
stop_voice()      { stop_by_pattern "$PAT_VOICE"  "voice-solo" 5; }
stop_ears()       { stop_by_pattern "$PAT_EARS"   "ears" 5; }
stop_face_follow(){ stop_by_pattern "$PAT_FACE"   "face_follow" 5; }

camera_off() {
  if ! health; then warn "bridge not running — only orphan sweep"; else
    if camera_post false >/dev/null; then
      say "camera: bridge told to stop the loop"
    else
      warn "camera: POST /online failed, falling back to process kill"
      local pids; pids="$(pgrep -x mediamtx 2>/dev/null; pgrep -x ngrok 2>/dev/null)"
      if [ -n "$pids" ]; then kill -INT $pids 2>/dev/null; fi
    fi
    local el=0
    while camera_on && [ "$el" -lt 12 ]; do sleep 0.5; el=$((el + 1)); done
  fi
  sweep_camera_orphans
  say "camera: off"
}

camera_on_cmd() {
  health || die "camera: bridge must be running first ('start bridge')"
  if camera_post true >/dev/null; then
    local el=0
    while ! camera_on && [ "$el" -lt 12 ]; do sleep 0.5; el=$((el + 1)); done
    say "camera: on"
  else
    die "camera: POST $BASE_URL/online failed"
  fi
}

cmd_camera() {
  case "${1:-}" in
    on) camera_on_cmd ;;
    off) camera_off ;;
    toggle)
      if camera_on; then camera_off; else camera_on_cmd; fi ;;
    status)
      if camera_on; then say "camera: on $(pgrep -x mediamtx 2>/dev/null | tr '\n' ' ')"; else say "camera: off"; fi ;;
    *) die "camera: expected on|off|toggle|status" ;;
  esac
}

cmd_stop() {
  local target="" force=0 a
  for a in "$@"; do
    case "$a" in --force) force=1 ;; *) target="$a" ;; esac
  done
  target="${target:-all}"
  [ "$force" = 1 ] && [ "$target" != "all" ] && FORCE=1
  case "$target" in
    bridge) stop_bridge ;;
    ui) stop_ui ;;
    ui-solo) stop_ui_solo ;;
    voice-solo) stop_voice ;;
    ears) stop_ears ;;
    face_follow) stop_face_follow ;;
    all)
      # all = core only; solo services (ui-solo, voice-solo, ears, face_follow) are
      # managed strictly individually and are never touched by all.
      camera_off
      stop_ui
      stop_bridge
      ;;
    *) die "stop: expected bridge|ui|ui-solo|voice-solo|ears|face_follow|all [--force]" ;;
  esac
}

cmd_restart() {
  case "${1:-}" in
    bridge) stop_bridge;  start_bridge ;;
    ui)     stop_ui;      start_ui ;;
    ears)   stop_ears;    start_ears ;;
    face_follow) stop_face_follow; start_face_follow ;;
    all)    cmd_stop all; start_bridge; start_ui ;;
    *) die "restart: expected bridge|ui|ears|face_follow|all" ;;
  esac
}

print_help() {
  cat <<'EOF'
UniMate service manager. No arguments (from a TTY) opens the curses dashboard.

Usage:
  unimate_ctl.sh status [--json]
  unimate_ctl.sh start  bridge|ui|ui-solo|voice-solo|ears|face_follow|all
  unimate_ctl.sh stop   bridge|ui|ui-solo|voice-solo|ears|face_follow|all [--force]
  unimate_ctl.sh restart bridge|ui|ears|face_follow|all
  unimate_ctl.sh logs   bridge|ui|ui-solo|voice-solo|ears|face_follow [-f] [-n N]
  unimate_ctl.sh camera on|off|toggle|status

Notes:
- "all" = the core only: bridge + ui stack (+ camera off on stop). Solo services
  (ui-solo, voice-solo, ears, face_follow) are never started/stopped by "all";
  manage them individually.
- stop sends SIGINT first (mirrors capture_server.py's KeyboardInterrupt cleanup,
  ears' GPIO.cleanup(), and uvicorn's FastAPI shutdown LED-off), then SIGTERM, then SIGKILL.
- bridge always runs from Wifi/ and expects port 5000; the rest run from the checkout root.
- honors UNIMATE_RASPI_BRIDGE_URL and UNIMATE_WINDOWED; PYTHONPATH is set by the script
  itself (same logic as use_worktree.sh) so run it from any checkout.
EOF
}

cmd_logs() {
  local which="${1:-}" follow=0 n=40
  [ -z "$which" ] && die "logs: expected bridge|ui|ui-solo|voice-solo|ears|face_follow"
  shift
  local file
  case "$which" in
    bridge) file="$LOG_BRIDGE" ;;
    ui) file="$LOG_UI" ;;
    ui-solo) file="$LOG_UI_SOLO" ;;
    voice-solo) file="$LOG_VOICE" ;;
    ears) file="$LOG_EARS" ;;
    face_follow) file="$LOG_FACE" ;;
    *) die "logs: expected bridge|ui|ui-solo|voice-solo|ears|face_follow" ;;
  esac
  while [ $# -gt 0 ]; do
    case "$1" in
      -f) follow=1 ;;
      -n) n="$2"; shift ;;
      *) die "logs: unknown arg $1" ;;
    esac
    shift
  done
  if [ "$follow" = 1 ]; then
    tail -n "$n" -f "$file" 2>/dev/null
  else
    if [ -f "$file" ]; then tail -n "$n" "$file"; else say "(no log yet: $file)"; fi
  fi
}

main() {
  if [ $# -eq 0 ]; then
    if [ -t 0 ] && [ -t 1 ]; then
      exec "$PYBIN" "$SCRIPT_DIR/unimate_tui.py"
    else
      cmd_status; say; die "no TTY — pass a command, see: $SCRIPT_DIR/unimate_ctl.sh help"
    fi
  fi
  case "$1" in
    status) shift; cmd_status "$@" ;;
    start) shift; cmd_start "$@" ;;
    stop) shift; cmd_stop "$@" ;;
    restart) shift; cmd_restart "$@" ;;
    logs) shift; cmd_logs "$@" ;;
    camera) shift; cmd_camera "$@" ;;
    -h|--help|help) print_help ;;
    *) die "unknown command '$1' — try '$SCRIPT_DIR/unimate_ctl.sh help'" ;;
  esac
}

main "$@"
