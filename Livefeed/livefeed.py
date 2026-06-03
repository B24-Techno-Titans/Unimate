#!/usr/bin/env python3
"""Start and stop the MediaMTX live feed and ngrok tunnel together."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


DEFAULT_DOMAIN = "george-superprepared-discrepantly.ngrok-free.dev"
DEFAULT_PORT = "8889"
SHUTDOWN_TIMEOUT_SECONDS = 8


def stream_output(name: str, process: subprocess.Popen[str]) -> None:
    """Prefix each child process line so both logs can share one terminal."""
    if process.stdout is None:
        return

    for line in process.stdout:
        print(f"[{name}] {line}", end="", flush=True)


def start_process(
    name: str,
    command: list[str],
    cwd: Path,
) -> subprocess.Popen[str]:
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

    thread = threading.Thread(target=stream_output, args=(name, process), daemon=True)
    thread.start()
    return process


def stop_process(name: str, process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    print(f"Stopping {name}...", flush=True)
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        print(f"{name} did not stop in time; forcing it to close.", flush=True)
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except ProcessLookupError:
        pass


def ensure_command_exists(path: Path, description: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")
    if not os.access(path, os.X_OK):
        raise PermissionError(f"{description} is not executable: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MediaMTX and ngrok for the Raspberry Pi live feed.",
    )
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help=f"ngrok domain to use (default: {DEFAULT_DOMAIN})",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"local WebRTC port to expose through ngrok (default: {DEFAULT_PORT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    livefeed_dir = Path(__file__).resolve().parent
    mediamtx = livefeed_dir / "mediamtx"

    try:
        ensure_command_exists(mediamtx, "MediaMTX binary")
    except (FileNotFoundError, PermissionError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if shutil.which("ngrok") is None:
        print("Error: ngrok was not found in PATH.", file=sys.stderr)
        return 1

    processes: list[tuple[str, subprocess.Popen[str]]] = []
    stopping = False

    def request_stop(signum: int | None = None, frame: object | None = None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print("\nClosing live feed...", flush=True)
        for process_name, process in reversed(processes):
            stop_process(process_name, process)

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        processes.append(
            (
                "mediamtx",
                start_process("mediamtx", [str(mediamtx)], livefeed_dir),
            )
        )
        time.sleep(1)
        if processes[0][1].poll() is not None:
            return processes[0][1].returncode or 1

        processes.append(
            (
                "ngrok",
                start_process(
                    "ngrok",
                    ["ngrok", "http", f"--domain={args.domain}", args.port],
                    livefeed_dir,
                ),
            )
        )

        print(
            "\nLive feed is running. Press Ctrl+C to close MediaMTX and ngrok.",
            flush=True,
        )

        while not stopping:
            for process_name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(
                        f"\n{process_name} exited with code {exit_code}; closing live feed.",
                        flush=True,
                    )
                    request_stop()
                    return exit_code
            time.sleep(0.5)
    finally:
        request_stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
