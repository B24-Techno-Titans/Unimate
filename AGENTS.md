# AGENTS.md

UniMate: Raspberry Pi smart desk companion — Kivy touch UI, FastAPI bridge to ESP32/room hardware, Gemini voice agent. Python, no lockfile. **No tests, no CI, no linter.**

## Docs are stale — trust code

- Root `README.md` points at `UIUX3`/`UIUX4` and `UIUX_FC2/README.md` at `UIUX2`; none of those dirs exist. The real UI is **`UIUX_FC2/`**, the bridge is **`Wifi/raspi2.py`** (`raspi.py` and `alexa/voiceAgent.py` are old variants; `voiceAgent2.py` is the standalone-mic voice variant, `voiceAgent2_shared.py` is the shared-mic one).

## Worktree gotcha (this checkout)

- `/home/unimate/Unimate-tree2` is a linked git worktree (branch `main`) of the main checkout `/home/unimate/Unimate` (on a different branch). `~/unimate/bin/activate` **hardcodes** `PYTHONPATH=/home/unimate/Unimate:/home/unimate/Unimate/UIUX_FC2`, so worktree code is silently shadowed by the main checkout — `source ./use_worktree.sh` first to point PYTHONPATH here.
- Untracked runtime assets exist only in the main checkout, **not in worktrees**: `piper/`, `UIUX_FC2/.env`, `alexa/.env`, `Requirements/install_requirements*.sh` (`piper/` and `Requirements/` are gitignored wholesale).

## How to run (all on the Pi)

Imports are flat/root-relative (`from alexa import …`, `from dashboard import …`) and resolve via PYTHONPATH, not the cwd — when code "mysteriously" imports the wrong copy, check `PYTHONPATH`.

- **Start first — bridge** (must run from `Wifi/`: raspi2 writes quiz artifacts to relative dirs `../saved/`, `../questions/`, `../summaries/`; it also puts `LED/` on `sys.path` itself, `shared_utils`/`Livefeed` come from PYTHONPATH):
  ```bash
  cd Wifi && ~/unimate/bin/uvicorn raspi2:app --host 0.0.0.0 --port 5000
  ```
  Serves `/data`, `/set-*`, `/device-state`, quiz endpoints `/mcqs`/`/get-questions`/`/summary`, and `/online`, which toggles the Livefeed camera (MediaMTX + ngrok).
- **Normal combined run** — from the checkout root: `<venv-python> shared_mic/capture_server.py` (`~/unimate/bin/python3`). Spawns three processes: mic capture server, `alexa/voiceAgent2_shared.py` (voice), `UIUX_FC2.main.shared_start()` (UI).
- **UI only**: `cd UIUX_FC2 && ~/unimate/bin/python3 main.py`. Don't rely on `run_hdmi.sh` — it execs bare `python3`, which lacks Kivy unless a venv is already active. Standalone launch = no shared audio queue, so quiz voice input is limited.
- Deps install (the scripts are untracked and only in the main checkout): `bash /home/unimate/Unimate/Requirements/install_requirements.sh` (uses `~/unimate/bin/pip` + piwheels; `install_requirements_resume.sh` retries failures). Hardware-only deps (RPi.GPIO etc.) can't install off-Pi.

## Mic sharing & cross-process JSON signaling

One physical mic is shared; processes coordinate via small **git-tracked JSON files** under the repo — a dirty `git status` with modified JSON is normal runtime churn, not accidental edits:

- `shared_mic/mic_in_use.json` — UI writes it when the quiz mic is active; the capture server then feeds **silence** to the voice agent's queue (UI quiz takes priority over voice).
- `alexa/voice_trigger.json` — UI writes it to start a Gemini session; `alexa/emotion_state.json` — voice agent writes, UI polls it for the robot emotion; also `alexa/ui_state.json`, `alexa/voice_control.json`.
- `pdf_mode/pdf_mode_status.json` — PDF-study mode status (UI ↔ voice agent).
- Quiz outputs `saved/`, `questions/`, `summaries/*.json` are also git-tracked and rewritten by the bridge.

## Environment & secrets

- Only the `~/unimate` venv exists here — it has both Kivy 2.3.1 and the fastapi/uvicorn stack; system `python3` has neither, and `~/nlp` / `UIUX_FC2/.venv` (referenced by scripts/docs) don't exist.
- Two `.env` files, git-ignored, keep them that way: `UIUX_FC2/.env` (`OPENAI_API_KEY` + `GEMINI_API_KEY` — the quiz flow uses both), `alexa/.env` (`GEMINI_API_KEY`).
- `.env` is loaded with `override=True` everywhere (`UIUX_FC2/nlp_functions.py`, `alexa/voiceAgent2*.py`) — a present `.env` value always beats the shell env.
- UI→bridge URL override: `UNIMATE_RASPI_BRIDGE_URL` (default `http://127.0.0.1:5000`). `UNIMATE_WINDOWED=1` = windowed debug UI. `UNIMATE_DISPLAY=:0` forces X display; `UIUX_FC2/main.py` otherwise invents a `DISPLAY` by scanning `/tmp/.X11-unix` (common when starting over SSH).

## Hardware / gotchas

- Piper TTS binary + ONNX voice live only on the main checkout (`piper/`, gitignored); `UIUX_FC2/nlp_functions.py` wires its env (espeak-ng data, `LD_LIBRARY_PATH`) itself — don't assume piper is on PATH.
- Devices are reached by mDNS: `unimate-esp.local` (ESP32 vitals), `smart-fan.local`, `led-controller.local`, `humidifier.local`. Without network/hardware the bridge still runs but sensors show "Awaiting data…", device control no-ops, and the UI degrades to mock values.
- Bare `test.py` files (in `ears/`, `UIUX_FC2/`, `Temp/`) plus `UIUX_FC2/test_emotion_reset.py` are manual on-device scripts (drive servos/audio/GUI directly), not pytest suites — don't run them from a dev box.
