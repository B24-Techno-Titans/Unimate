#!/usr/bin/env python3
"""UniMate Kivy UI: neon kawaii face + study, sensors, controls (Raspberry Pi kiosk)."""

from __future__ import annotations

import os
import threading
from pathlib import Path
import json

# ---------------------------------------------------------------------------
# Display + Kivy graphics must be configured before importing Window/widgets
# ---------------------------------------------------------------------------


def _ensure_display() -> None:
    """Point at local X desktop when DISPLAY is unset (common over SSH)."""
    if os.environ.get("DISPLAY"):
        return
    forced = os.environ.get("UNIMATE_DISPLAY", "").strip()
    if forced:
        os.environ["DISPLAY"] = forced
        return
    xdir = Path("/tmp/.X11-unix")
    if xdir.is_dir():
        for entry in sorted(xdir.glob("X*")):
            name = entry.name
            if name.startswith("X") and name[1:].isdigit():
                os.environ["DISPLAY"] = f":{name[1:]}"
                return
    os.environ.setdefault("DISPLAY", ":0")


_ensure_display()

_WINDOWED = os.environ.get("UNIMATE_WINDOWED", "").strip().lower() in {"1", "true", "yes"}

from kivy.config import Config  # noqa: E402

if _WINDOWED:
    Config.set("graphics", "fullscreen", "0")
    Config.set("graphics", "borderless", "0")
    Config.set("graphics", "resizable", "1")
    Config.set("graphics", "width", "1024")
    Config.set("graphics", "height", "600")
    Config.set("graphics", "minimum_width", "800")
    Config.set("graphics", "minimum_height", "480")
else:
    Config.set("graphics", "fullscreen", "auto")
    Config.set("graphics", "borderless", "1")

Config.set("graphics", "multisamples", "4")

try:
    Config.write()
except OSError:
    pass

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.screenmanager import ScreenManager, SlideTransition  # noqa: E402

from dashboard import (  # noqa: E402
    SensorsRefs,
    build_controls_screen,
    build_sensors_screen,
    build_study_screen,
)
from mock_state import MockState  # noqa: E402
from raspi_bridge import SensorReadings, fetch_sensors  # noqa: E402
from emotions.morph import RoboMorphWidget  # noqa: E402
from emotions.selector import build_emotion_screen  # noqa: E402
from theme import Theme  # noqa: E402
from nlp_functions import set_shared_audio_queue  # noqa: E402
from widgets.common import write_mic_in_use  # noqa: E402


def _silence_probesysfs_xinput_warnings() -> None:
    """ProbeSysfs runs xinput on Xwayland; warnings are harmless but very noisy."""
    try:
        import subprocess

        from kivy.input.providers import probesysfs

        _orig_getout = probesysfs.getout

        def _getout(*args):
            if args and args[0] == "xinput":
                try:
                    return subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    ).communicate()[0]
                except OSError:
                    return b""
            return _orig_getout(*args)

        probesysfs.getout = _getout
    except ImportError:
        pass


_silence_probesysfs_xinput_warnings()

SCREEN_ORDER = ("study", "face", "sensors", "controls")

# Touch: Study ← Face → Sensors → Controls. Swipe left (dx < 0) → next; right → previous.
_SWIPE_PREV = {
    "face": "study",
    "sensors": "face",
    "controls": "sensors",
}
_SWIPE_NEXT = {
    "study": "face",
    "face": "sensors",
    "sensors": "controls",
}

IDLE_FACE_TIMEOUT_S = 120.0

class FourScreenSwipeManager(ScreenManager):
    """Horizontal swipe: Study—Face—Sensors—Controls (no chrome)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.threshold_px = dp(24)
        self._swipe_origin: tuple[float, float] | None = None
        self._swipe_touch = None

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos):
            self._swipe_origin = (touch.x, touch.y)
            self._swipe_touch = touch
        return False

    def _navigate_to(self, target: str | None, *, direction: str) -> None:
        if target and target != self.current:
            self.transition.direction = direction
            self.current = target

    def _clear_swipe(self, touch) -> None:
        if self._swipe_touch is touch:
            self._swipe_origin = None
            self._swipe_touch = None

    def on_touch_up(self, touch):
        if (
            self._swipe_origin is not None
            and self._swipe_touch is touch
            and touch.grab_current is None
        ):
            x0, y0 = self._swipe_origin
            dx = touch.x - x0
            dy = touch.y - y0
            if abs(dx) >= self.threshold_px and abs(dx) > abs(dy):
                cur = self.current
                if dx < 0:
                    self._navigate_to(_SWIPE_NEXT.get(cur), direction="left")
                else:
                    self._navigate_to(_SWIPE_PREV.get(cur), direction="right")
        self._clear_swipe(touch)
        return super().on_touch_up(touch)


class UniMateKivyUI(BoxLayout):
    def _read_emotion_timestamp(self) -> float:
        try:
            path = Path(__file__).parent.parent / "alexa" / "emotion_state.json"
            with open(path) as f:
                return float(json.load(f).get("timestamp", 0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return 0.0

    def _poll_emotion(self, *_args):
        try:
            path = Path(__file__).parent.parent / "alexa" / "emotion_state.json"
            with open(path) as f:
                data = json.load(f)
            ts = data.get("timestamp", 0)
            emotion = data.get("emotion", "normal")
            print(f"[EMOTION POLL] ts={ts}, last={self._last_emotion_ts}, emotion={emotion}")
            if ts > self._last_emotion_ts:
                self._last_emotion_ts = ts
                print(f"[EMOTION] Triggering set_expression({emotion})")
                Clock.schedule_once(lambda *_: self.morph_widget.set_expression(emotion), 0)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[EMOTION POLL ERROR]: {e}")
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=0, spacing=0, **kwargs)
        self.state = MockState()
        self.sensors_refs: SensorsRefs | None = None
        self._sensor_poll_busy = False

        self.manager = FourScreenSwipeManager(
            transition=SlideTransition(duration=0.22),
            size_hint=(1, 1)
        )

        study = build_study_screen()
        self.manager.add_widget(study)

        self.morph_widget = RoboMorphWidget()
        self.manager.add_widget(build_emotion_screen(self.morph_widget))

        self._last_emotion_ts = self._read_emotion_timestamp()
        Clock.schedule_interval(self._poll_emotion, 1.0)

        sensors, srefs = build_sensors_screen(self.state)
        self.sensors_refs = srefs
        self.manager.add_widget(sensors)

        self.manager.add_widget(build_controls_screen(self.state))

        self.add_widget(self.manager)

        self.manager.bind(current=self._on_screen_changed)

        Clock.schedule_interval(lambda *_: self._tick_state(), 2.5)
        Window.bind(on_key_down=self._on_key_down)
        Window.bind(
            on_touch_down=self._on_user_activity,
            on_touch_up=self._on_user_activity,
            on_touch_move=self._on_user_activity,
        )

        self._idle_ev = None
        self._reset_idle_timer()

        self.manager.current = "face"
        self._on_screen_changed()
        self._tick_state()

    def _tick_state(self, *_args) -> None:
        if not self.sensors_refs or self._sensor_poll_busy:
            return
        self._sensor_poll_busy = True

        def _poll() -> None:
            readings = fetch_sensors()
            Clock.schedule_once(lambda _dt: self._apply_sensor_readings(readings), 0)

        threading.Thread(target=_poll, daemon=True).start()

    def _apply_sensor_readings(self, readings: SensorReadings | None) -> None:
        self._sensor_poll_busy = False
        if readings is None or not self.sensors_refs:
            return

        r = self.sensors_refs
        if readings.room_temp_c is not None:
            self.state.room_temp_c = readings.room_temp_c
            r.temp.set_value(f"{readings.room_temp_c:.1f} °C", "Avg. Main Room")
        if readings.humidity_pct is not None:
            self.state.humidity_pct = readings.humidity_pct
            r.humidity.set_value(f"{readings.humidity_pct:.0f}%", "Main Room")
        if readings.lux is not None:
            self.state.lux = readings.lux
            r.lux.set_value(f"{readings.lux:.0f} lx", "Lux Intensity")
        if (
            readings.heart_bpm is not None
            and readings.body_temp_c is not None
            and readings.spo2_pct is not None
        ):
            self.state.vitals_buffer.push(
                readings.heart_bpm,
                readings.body_temp_c,
                readings.spo2_pct,
            )
        r.refresh_vitals(self.state)

    def _on_screen_changed(self, *_args) -> None:
        if self.manager.current == "face":
            self.morph_widget.start()
        else:
            self.morph_widget.stop()

    def _on_user_activity(self, *_args) -> bool:
        self._reset_idle_timer()
        return False

    def _reset_idle_timer(self) -> None:
        if self._idle_ev is not None:
            self._idle_ev.cancel()
        self._idle_ev = Clock.schedule_once(self._on_idle_timeout, IDLE_FACE_TIMEOUT_S)

    def _on_idle_timeout(self, _dt: float) -> None:
        self._idle_ev = None
        if self.manager.current != "face":
            order = list(SCREEN_ORDER)
            cur_i = order.index(self.manager.current)
            face_i = order.index("face")
            self.manager.transition.direction = "right" if cur_i > face_i else "left"
            self.manager.current = "face"
        self._reset_idle_timer()

    def _move_screen_delta(self, delta: int) -> None:
        order = list(SCREEN_ORDER)
        i = max(0, order.index(self.manager.current))
        ni = (i + delta) % len(order)
        self.manager.transition.direction = "left" if delta > 0 else "right"
        self.manager.current = order[ni]

    def _on_key_down(self, _window, key, *_args):
        self._reset_idle_timer()
        if key == 275:
            self._move_screen_delta(1)
            return True
        if key == 276:
            self._move_screen_delta(-1)
            return True
        if key == 27:
            Window.fullscreen = False
            return False
        return False


class UniMateApp(App):
    title = "UniMate Kivy"

    def build(self):
        Window.clearcolor = Theme.BG
        if _WINDOWED:
            Window.fullscreen = False
        self.root_widget = UniMateKivyUI()
        return self.root_widget

def shared_start(audio_queue) -> None:
    """Entry point for shared_mic/capture_server.py child process."""
    write_mic_in_use(False)
    set_shared_audio_queue(audio_queue)
    UniMateApp().run()


if __name__ == "__main__":
    UniMateApp().run()
