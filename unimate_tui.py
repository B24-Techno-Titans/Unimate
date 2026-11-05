#!/usr/bin/env python3
"""UniMate service dashboard — curses UI over unimate_ctl.sh (stdlib only, no deps).

Run via:  ./unimate_ctl.sh            (from a TTY)
or:       ~/unimate/bin/python3 unimate_tui.py
"""
from __future__ import annotations

import curses
import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CTL = os.environ.get("UNIMATE_CTL") or os.path.join(SCRIPT_DIR, "unimate_ctl.sh")

# Core group = everything "start all" manages; rendered on top of the dashboard.
# Other group = strictly individual services; separated by a visual rule line.
CORE_ROWS = [
    ("bridge",      "bridge",      "bridge",      "Wifi/raspi2.py uvicorn :5000"),
    ("ui",          "ui",          "ui stack",    "capture_server.py (mic+voice+UI)"),
    ("ears",        "ears",        "ears",        "ear touch sweep (PCA9685, ch4/5)"),
    ("face_follow", "face_follow", "face_follow", "camera face tracking + servos"),
    ("spotify",     "spotify",     "spotify",     "soloist device (ws :9090)"),
]
OTHER_ROWS = [
    ("ui-solo",     "ui_solo",     "ui-solo",     "UIUX_FC2/main.py standalone"),
    ("voice-solo",  "voice_solo",  "voice-solo",  "alexa/voiceAgent2.py standalone"),
    ("camera",      "camera",      "camera",      "mediamtx + ngrok (bridge /online)"),
]
ROWS = CORE_ROWS + OTHER_ROWS          # display + selection order (flattened)
SEPARATOR_LABEL = " other (managed individually) "

TARGETS = {row[0] for row in ROWS if row[0] != "camera"}

LOG_FILES = {
    "bridge": "logs/bridge.log",
    "ui": "logs/ui.log",
    "ui-solo": "logs/ui-solo.log",
    "voice-solo": "logs/voice-solo.log",
    "ears": "logs/ears.log",
    "face_follow": "logs/face_follow.log",
    "spotify": "logs/spotify.log",
}

C_GREEN, C_RED, C_YELLOW, C_CYAN = 1, 2, 3, 4

REFRESH_TICKS = 4  # 250 ms key tick -> status refresh every 1 s
MIN_H, MIN_W = len(ROWS) + 6, 62


def human_time(seconds) -> str:
    if seconds is None or seconds < 0:
        return "-"
    s = int(seconds)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h" if d else (f"{h}h {m}m" if h else f"{m}m")


class TUI:
    def __init__(self) -> None:
        self.sel = 0
        self.msg = "ready  (status: ./unimate_ctl.sh status)"
        self.data: dict = {}
        self.fetch_err = ""
        self.pending: dict[str, dict] = {}  # action-id -> {"proc","jkey","verb"}
        self.pending_by_sid: dict[str, dict] = {}

    # ------------------------------------------------------------- data

    def fetch_status(self) -> None:
        try:
            proc = subprocess.run(
                [CTL, "status", "--json"], capture_output=True, text=True, timeout=8,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                self.fetch_err = f"ctl status failed rc={proc.returncode} {proc.stderr.strip()[:80]}"
                return
            self.data = json.loads(proc.stdout)
            self.fetch_err = ""
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            self.fetch_err = f"status error: {exc}"[:110]

    def pid_of(self, jkey: str):
        info = self.data.get(jkey, {})
        pid = info.get("pid")
        return pid if pid else "-"

    def row_state(self, jkey: str):
        """-> (state_text, curses_pair, detail)."""
        if jkey == "camera":
            cam = self.data.get("camera", {})
            if cam.get("on"):
                pids = ",".join(str(x) for x in
                                (cam.get("mediamtx_pid"), cam.get("ngrok_pid")) if x)
                return "on", C_GREEN, f"pids {pids}"
            return "off", C_RED, "live feed stopped"
        info = self.data.get(jkey, {})
        if info.get("running"):
            if jkey == "bridge" and not info.get("healthy"):
                return "degraded", C_YELLOW, f"pid {info.get('pid')}, up {human_time(info.get('uptime_s'))}, /data no answer"
            return "running", C_GREEN, f"pid {info.get('pid')}, up {human_time(info.get('uptime_s'))}"
        return "stopped", C_RED, "-"

    # ------------------------------------------------------------- actions

    def spawn(self, verb: str, sid: str) -> None:
        if verb == "camera":
            target = "camera"
        elif sid == "all":
            target = "all"
        else:
            target = self.jkey_of(sid)
        for pend in self.pending.values():
            if pend["jkey"] in (target, "all"):
                self.msg = f"an action is already running ({pend['verb']} {pend['jkey']})…"
                return
        try:
            proc = subprocess.Popen(
                [CTL, verb, sid],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except OSError as exc:
            self.msg = f"cannot run ctl: {exc}"
            return
        self.pending[f"{verb} {sid}"] = {"proc": proc, "jkey": target, "verb": verb}
        self.msg = f"{verb} {sid} …"

    def jkey_of(self, sid: str) -> str:
        for row in ROWS:
            if row[0] == sid:
                return row[1]
        return sid

    def poll_pending(self) -> None:
        finished = []
        for aid, pend in self.pending.items():
            proc: subprocess.Popen = pend["proc"]
            if proc.poll() is None:
                continue
            finished.append(aid)
            try:
                lines = [ln.strip() for ln in (proc.stdout.read() or "").splitlines() if ln.strip()]
            except (OSError, ValueError):
                lines = []
            if proc.stdout:
                proc.stdout.close()
            self.msg = (f"{aid}: {lines[-1] if lines else f'exit code {proc.returncode}'}")[:150]
        for aid in finished:
            self.pending.pop(aid, None)

    def busy_jkeys(self) -> set[str]:
        return {p["jkey"] for p in self.pending.values()}

    # ------------------------------------------------------------- drawing

    def draw(self, stdscr) -> None:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        if h < MIN_H or w < MIN_W:
            stdscr.addnstr(0, 0, f"Terminal too small — need at least {MIN_W}x{MIN_H}.", max(0, w - 1))
            stdscr.refresh()
            return

        checkout = os.path.basename(self.data.get("checkout", SCRIPT_DIR))
        extras = []
        if not self.data.get("piper_ok", False):
            extras.append("piper missing")
        if not self.data.get("env_ui_ok", False):
            extras.append("UI .env missing")
        if not self.data.get("env_alexa_ok", False):
            extras.append("alexa .env missing")
        header = f"UniMate services — checkout: {checkout}"
        if extras:
            header += "   (warning: " + ", ".join(extras) + ")"
        if self.fetch_err:
            header += f"   [{self.fetch_err}]"
        stdscr.addnstr(0, 0, header[:w - 1], w - 1, curses.color_pair(C_CYAN) | curses.A_BOLD)
        stdscr.addnstr(1, 0, f"{'SERVICE':<12}{'STATE':>11}{'PID':>7}  DETAIL", w - 1, curses.A_DIM)

        running = self.pending  # alias
        self.pending_by_sid = {p["jkey"]: p for p in running.values()}

        y, flat = 2, 0
        for gnum, group in enumerate((CORE_ROWS, OTHER_ROWS)):
            if gnum > 0:  # visual rule between "all" managed and individually managed
                rule = ("─" * 3) + SEPARATOR_LABEL + ("─" * 60)
                stdscr.addnstr(y, 0, rule[:w - 1], w - 1, curses.A_DIM)
                y += 1
            for row in group:
                sid, jkey, label, desc = row
                pend = self.pending_by_sid.get(jkey) or self.pending_by_sid.get("all")
                if pend:
                    state, pair, detail = f"{pend['verb']}…", C_YELLOW, f"ctl {pend['verb']} in progress"
                else:
                    state, pair, detail = self.row_state(jkey)
                pid_txt = str(self.pid_of(jkey)) if state.startswith("running") else "-"
                line = f"{label:<12}{state:>11}{pid_txt:>7}  {detail}"
                attr = curses.A_REVERSE if flat == self.sel else 0
                stdscr.addnstr(y, 0, line[:w - 1], w - 1, attr | curses.color_pair(pair))
                y += 1
                flat += 1

        keys = "↑/↓ select  s start  x stop  r restart  l logs  c camera  a start-all  X stop-all  q quit"
        stdscr.addnstr(h - 2, 0, keys[:w - 1], w - 1, curses.A_DIM)
        low = self.msg.lower()
        pair = C_CYAN
        if any(w in low for w in ("error", "failed", "refus", "must be running", "not found")):
            pair = C_RED
        elif low.startswith(("start", "bridge: running", "ui: running", "camera: on")):
            pair = C_GREEN
        stdscr.addnstr(h - 1, 0, f"› {self.msg}"[:w - 1], w - 1, curses.color_pair(pair))
        stdscr.refresh()

    # ------------------------------------------------------------- input

    def handle_key(self, key, sid, jkey):
        """Returns None to continue, 'quit', or ('logs', sid)."""
        if key in (ord("q"), ord("Q"), curses.KEY_F10):
            return "quit"
        if key in (27, curses.KEY_EXIT):  # ESC / keyless exit
            return "quit"
        if key in (curses.KEY_UP, ord("k")):
            self.sel = (self.sel - 1) % len(ROWS)
            return None
        if key in (curses.KEY_DOWN, ord("j")):
            self.sel = (self.sel + 1) % len(ROWS)
            return None
        if key == ord("a"):
            self.spawn("start", "all")
            return None
        if key == ord("X"):
            self.spawn("stop", "all")
            return None
        if key == ord("l") and sid != "camera":
            return ("logs", sid)
        if key == ord("l") and sid == "camera":
            self.msg = "camera streams to the bridge log — select 'bridge' for logs"
            return None
        if not sid:
            return None
        if key == ord("s") and sid == "camera":
            self.spawn("camera", "on")
            return None
        if key == ord("x") and sid == "camera":
            self.spawn("camera", "off")
            return None
        if key == ord("c") and sid == "camera":
            self.spawn("camera", "toggle")
            return None
        if key == ord("s"):
            self.spawn("start", sid)
        elif key == ord("x"):
            self.spawn("stop", sid)
        elif key == ord("r") and sid in TARGETS:
            self.spawn("restart", sid)
        return None


def log_view(stdscr, tui: TUI, sid: str) -> None:
    """Scrollable in-curses log viewer (re-reads the file every tick to follow)."""
    path = os.path.join(SCRIPT_DIR, LOG_FILES.get(sid, ""))
    top: int | None = None          # None = follow tail
    stdscr.timeout(500)
    while True:
        h, w = stdscr.getmaxyx()
        body = max(1, h - 2)
        stdscr.erase()
        try:
            with open(path, errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = [f"(no log yet: {path})"]
        max_top = max(0, len(lines) - body)
        if top is None or top > max_top:
            top = max_top
        title = f"{path}   view: {'follow' if top is not None else 'scrolled'}"
        stdscr.addnstr(0, 0, title[:w - 1], w - 1, curses.A_DIM | curses.A_REVERSE)
        try:
            for i, ln in enumerate(lines[top:top + body]):
                stdscr.addnstr(1 + i, 0, ln[:w - 1], w - 1)
        except curses.error:
            pass
        hint = "↑/↓ scroll  PgUp/PgDn  g top  G bottom  r refresh  q back"
        try:
            stdscr.addnstr(h - 1, 0, hint[:w - 1], w - 1, curses.A_DIM)
        except curses.error:
            pass
        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27, curses.KEY_F10, curses.KEY_EXIT):
            break
        if key == curses.KEY_RESIZE:
            continue
        if key in (curses.KEY_UP, ord("k")):
            top = max(0, (top or 0) - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            if top is not None:
                top = min(max_top, top + 1)
        elif key == curses.KEY_PPAGE:
            top = max(0, (top or 0) - body)
        elif key == curses.KEY_NPAGE:
            if top is not None:
                top = min(max_top, top + body)
        elif key == ord("g"):
            top = 0
        elif key in (ord("G"),):
            top = None  # jump to follow tail
        elif key == ord("r"):
            if top is not None:
                top = min(max_top, top)
    stdscr.timeout(250)


def curses_main(stdscr, tui: TUI):
    curses.curs_set(0)
    curses.use_default_colors()
    for pair, color in ((C_GREEN, curses.COLOR_GREEN), (C_RED, curses.COLOR_RED),
                        (C_YELLOW, curses.COLOR_YELLOW), (C_CYAN, curses.COLOR_CYAN)):
        curses.init_pair(pair, color, -1)
    stdscr.keypad(True)
    stdscr.timeout(250)
    tick = 0
    while True:
        tui.poll_pending()
        if tick % REFRESH_TICKS == 0:
            tui.fetch_status()
        tui.draw(stdscr)
        tick += 1
        key = stdscr.getch()
        if key == curses.KEY_RESIZE:
            tui.fetch_status()
            tui.draw(stdscr)
            continue
        if key in (-1,):
            continue
        sid, jkey, _label, _desc = ROWS[tui.sel]
        result = tui.handle_key(key, sid, jkey)
        if result == "quit":
            return None
        if isinstance(result, tuple) and result[0] == "logs":
            log_view(stdscr, tui, result[1])
            tui.msg = f"closed log view ({result[1]})"


def main() -> int:
    if not os.path.isfile(CTL):
        print(f"ERROR: control script not found: {CTL}", file=sys.stderr)
        return 1
    tui = TUI()
    try:
        curses.wrapper(curses_main, tui)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
