# AGENTS.md

UniMate: Raspberry Pi smart desk companion — Kivy touch UI, FastAPI bridge to ESP32/room hardware, Gemini voice agent. Python, no lockfile. **No tests, no CI, no linter.**

## Docs are stale — trust code

- Root `README.md` and `UIUX_FC2/README.md` reference `UIUX3`/`UIUX2`/`UIUX4`, none of which exist. The current UI is **`UIUX_FC2/`**; the bridge is `Wifi/raspi2.py` (`raspi.py` is an old variant).

## How to run (all on the Pi)

Working directory matters — imports are flat/CWD-dependent. Wrong dir = `ImportError`.

- **Start first** — bridge API (also serves `/mcqs`, `/get-questions`, `/summary`, camera endpoints):
  ```bash
  cd Wifi && ~/unimate/bin/uvicorn raspi2:app --host 0.0.0.0 --port 5000
  ```
  (run from `Wifi/` so `LED/` and `shared_utils/` imports resolve)
- **Normal combined run**: `cd /home/unimate/Unimate && <venv-python> shared_mic/capture_server.py` — spawns three processes: mic capture server, `alexa/voiceAgent2_shared.py` (voice), and `UIUX_FC2.main.shared_start()` (UI). Run from repo root so `alexa` / `UIUX_FC2` resolve as packages.
- **UI only**: `cd UIUX_FC2 && python3 main.py` (flat imports like `from dashboard import …`; `~/nlp/bin/python3` is the interpreter `run_hdmi.sh` prefers because of Kivy). Standalone launch = no shared audio queue, so voice quiz input is limited.
- Deps install: `bash Requirements/install_requirements.sh` (uses `~/unimate/bin/pip` + piwheels; retry failures with `install_requirements_resume.sh`). Hardware-only deps (RPi.GPIO, etc.) can't install off-Pi.

## Mic sharing & cross-process JSON signaling

One physical mic is shared; processes communicate by reading/writing small JSON files under the repo — **these are git-tracked and change at runtime**, so a dirty `git status` with modified JSON is normal, not accidental:

- `shared_mic/mic_in_use.json` — UI writes this when the quiz mic is active; the capture server then feeds **silence** to the voice agent's queue (UI quiz takes priority over voice).
- `alexa/emotion_state.json` — voice agent writes; UI polls it to show the robot emotion.
- `alexa/voice_trigger.json` — UI writes to trigger a Gemini session; also `alexa/ui_state.json`, `pdf_mode/pdf_mode_status.json`, `Temp/temp_data.json`.

## Environment & secrets

- `~/unimate/bin/python3` (venv with uvicorn, most deps), `~/nlp/bin/python3` (Kivy), optional `UIUX_FC2/.venv`.
- Two `.env` files, git-ignored, keep them that way: `UIUX_FC2/.env` (OpenAI key for UI quiz flow), `alexa/.env` (`GEMINI_API_KEY`).
- `.env` overrides shown with `override=True` in both `alexa/voiceAgent2*.py` and `UIUX_FC2/nlp_functions.py` — an existing `.env` value wins over the shell env.
- UI→bridge URL override: `UNIMATE_RASPI_BRIDGE_URL` (default `http://127.0.0.1:5000`). `UNIMATE_WINDOWED=1` = windowed debug UI. `UNIMATE_DISPLAY=:0` forces X display.

## Hardware / gotchas

- Piper TTS binary + ONNX voice ship **inside the repo** (`piper/`); `UIUX_FC2/nlp_functions.py` sets up its env (espeak-ng data, LD_LIBRARY_PATH) itself — don't assume piper is on PATH.
- Devices are reached by mDNS: `unimate-esp.local` (ESP32 vitals), `smart-fan.local`, `led-controller.local`, `humidifier.local`. Without network/hardware the bridge still runs but sensors show "Awaiting data…" and device control no-ops; the UI degrades to mock values. The UI also auto-invents a `DISPLAY` when unset (common when starting from SSH).
- `Main` git branch is `main`; bare `test.py` files scattered around (`ears/`, `UIUX_FC2/`) are manual on-device scripts (drive servos/audio directly), not pytest suites — don't run them from a dev box.
