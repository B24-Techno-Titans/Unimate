#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
import atexit  # NEW
from pathlib import Path

# ================= CONFIG =================
DEFAULT_DOMAIN = "george-superprepared-discrepantly.ngrok-free.dev"
DEFAULT_PORT = "8889"
SHUTDOWN_TIMEOUT_SECONDS = 8

# ============== GLOBAL STATE ==============
_processes: list[tuple[str, subprocess.Popen[str]]] = []
_running = False
_lock = threading.Lock()


# ============== CORE UTILS ==============
def _stream_output(name: str, process: subprocess.Popen[str]) -> None:
    if process.stdout is None:
        return

    for line in process.stdout:
        print(f"[{name}] {line}", end="", flush=True)


def _start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen[str]:
    print(f"Starting {name}: {' '.join(command)}", flush=True)

    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=os.setsid,
    )

    thread = threading.Thread(
        target=_stream_output, args=(name, process), daemon=True
    )
    thread.start()

    return process


def _stop_process(name: str, process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    print(f"Stopping {name}...", flush=True)

    try:
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        print(f"{name} force killing...", flush=True)
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except ProcessLookupError:
        pass


def _ensure_command_exists(path: Path, description: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")
    if not os.access(path, os.X_OK):
        raise PermissionError(f"{description} is not executable: {path}")


# ============== MAIN CONTROL ==============
def _start_live_feed(domain: str, port: str) -> None:
    global _processes, _running

    livefeed_dir = Path(__file__).resolve().parent
    mediamtx = livefeed_dir / "mediamtx"

    _ensure_command_exists(mediamtx, "MediaMTX binary")

    if shutil.which("ngrok") is None:
        raise RuntimeError("ngrok not found in PATH")

    _processes.clear()

    mediamtx_proc = _start_process(
        "mediamtx",
        [str(mediamtx)],
        livefeed_dir,
    )
    _processes.append(("mediamtx", mediamtx_proc))

    time.sleep(1)

    if mediamtx_proc.poll() is not None:
        raise RuntimeError("MediaMTX failed to start")

    ngrok_proc = _start_process(
        "ngrok",
        ["ngrok", "http", f"--domain={domain}", port],
        livefeed_dir,
    )
    _processes.append(("ngrok", ngrok_proc))

    _running = True
    print("\n✅ Live feed STARTED\n")


def _stop_live_feed() -> None:
    global _processes, _running

    print("\nClosing live feed...\n")

    for name, process in reversed(_processes):
        _stop_process(name, process)

    _processes.clear()
    _running = False

    print("\n🛑 Live feed STOPPED\n")


# ============== PUBLIC FUNCTION ==============
def toggle_live_feed(
    state: str | None = None,
    domain: str = DEFAULT_DOMAIN,
    port: str = DEFAULT_PORT,
) -> bool:
    global _running

    with _lock:
        if state is not None:
            state = state.lower()

        if state == "on":
            if not _running:
                _start_live_feed(domain, port)
            else:
                print("Live feed already running.")
            return True

        elif state == "off":
            if _running:
                _stop_live_feed()
            else:
                print("Live feed already stopped.")
            return False

        else:
            if not _running:
                _start_live_feed(domain, port)
                return True
            else:
                _stop_live_feed()
                return False


# ============== CLEANUP HANDLER ==============
def _cleanup():  # NEW
    if _running:  # NEW
        print("\n[Cleanup] Stopping live feed before exit...", flush=True)  # NEW
        _stop_live_feed()  # NEW


atexit.register(_cleanup)  # NEW


# ============== OPTIONAL CLI ==============
if __name__ == "__main__":
    print("Press Ctrl+C to stop...\n")

    try:
        toggle_live_feed("on")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        toggle_live_feed("off")
