# UniMate Kivy UI (UIUX2)

Kiosk UI for Raspberry Pi HDMI: **neon kawaii** robot face (navy canvas, violet frame glow, cyan eyes + mouth) plus swipeable full-screen panels for **Study**, **Sensors**, and **Controls** with level-based device animations (mock state).

Layouts are minimal: **no logo**, **no footer dots**, **no swipe hint text**. Navigation is horizontal touch swipes between panels (keyboard arrows supported for debugging).

Animations for fan blades, humidifier bubbles, and light rays speed up / intensify with **fan level**, **humidifier level**, and **LED brightness**.

## Run on the Pi (HDMI desktop)

From a terminal **on the Pi** (or SSH with X forwarding / `DISPLAY=:0`):

```bash
cd UIUX2
chmod +x run_hdmi.sh   # once
./run_hdmi.sh
```

`run_hdmi.sh` sets `DISPLAY=:0` and prefers `~/nlp/bin/python3` if that environment has Kivy installed.

### Windowed debugging

```bash
cd UIUX2
UNIMATE_WINDOWED=1 ./run_hdmi.sh
```

### Virtual environment (PEP 668)

If system `pip` blocks installs:

```bash
cd UIUX2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

### If the window does not appear

- Ensure a desktop session is running on HDMI and `DISPLAY` is correct (`:0` is typical).
- Over SSH, you may need to allow local X access once on the Pi desktop: `xhost +local:`

## Four windows (navigation)

Order: **Study → Face → Sensors → Controls** (also the order used by keyboard).

- **Touch:** swipe **left** (finger moves left) for the **previous** panel; swipe **right** for the **next**. From **Study**, only right goes to **Face**; from **Controls**, only left goes to **Sensors**.
- **Arrow keys:** **Right** → next panel · **Left** → previous (wraps end-to-end).
- **Esc:** exit fullscreen (if applicable).

## Files

| Path | Role |
|------|------|
| `main.py` | Four-screen `ScreenManager`, swipe rules, fullscreen shell |
| `robo_eyes.py` | Reference-style face canvas (blink / glow pulse) |
| `dashboard.py` | Study quiz, neon sensor cards, device rows + viz |
| `theme.py` | Navy / violet / cyan design tokens |
| `mock_state.py` | Mock telemetry + fan/humidity levels + LED brightness |
| `run_hdmi.sh` | Pi-friendly launcher |

The older Tkinter UI remains in `../UIUX` and is untouched.
