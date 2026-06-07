#!/usr/bin/env python3
"""UniMate Kivy UI: neon kawaii face + study, sensors, controls (Raspberry Pi kiosk)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

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
from kivy.graphics import Color, Rectangle  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition  # noqa: E402

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
from robo_eyes import RoboEyesWidget, schedule_random_idle_charm  # noqa: E402
from theme import Theme  # noqa: E402


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

SCREEN_ORDER = ("study", "face", "emotion", "sensors", "controls")

# Touch: Study ← Face → Emotion → Sensors → Controls. Swipe left (dx < 0) → next; right → previous.
_SWIPE_PREV = {
    "face": "study",
    "emotion": "face",
    "sensors": "emotion",
    "controls": "sensors",
}
_SWIPE_NEXT = {
    "study": "face",
    "face": "emotion",
    "emotion": "sensors",
    "sensors": "controls",
}

IDLE_FACE_TIMEOUT_S = 120.0


class FourScreenSwipeManager(ScreenManager):
    """Horizontal swipe: Study—Face—Emotion—Sensors—Controls (no chrome)."""

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
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=0, spacing=0, **kwargs)
        self.state = MockState()
        self.sensors_refs: SensorsRefs | None = None
        self._sensor_poll_busy = False

        self.manager = FourScreenSwipeManager(transition=SlideTransition(duration=0.22), size_hint=(1, 1))

        study = build_study_screen()
        self.manager.add_widget(study)

        self.eyes_widget = RoboEyesWidget()
        self.morph_widget = RoboMorphWidget()
        self.manager.add_widget(self._face_screen())
        self.manager.add_widget(build_emotion_screen(self.morph_widget))

        sensors, srefs = build_sensors_screen(self.state)
        self.sensors_refs = srefs
        self.manager.add_widget(sensors)

        self.manager.add_widget(build_controls_screen(self.state))

        self.add_widget(self.manager)

        self.manager.bind(current=self._on_screen_changed)

        Clock.schedule_interval(lambda *_: self._tick_state(), 2.5)
        schedule_random_idle_charm(self.eyes_widget, interval=9.0)
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

    def _face_screen(self) -> Screen:
        screen = Screen(name="face")
        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*Theme.FACE_BG)
            self._eyes_bg_rect = Rectangle(pos=root.pos, size=root.size)

        def _sync_bg(*_a):
            self._eyes_bg_rect.pos = root.pos
            self._eyes_bg_rect.size = root.size

        root.bind(pos=_sync_bg, size=_sync_bg)
        root.add_widget(self.eyes_widget)
        screen.add_widget(root)
        return screen

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
        if readings.heart_bpm is not None:
            self.state.heart_bpm = readings.heart_bpm
            r.heart.set_value(f"{readings.heart_bpm} bpm", "Real-time, Last 5 mins")
        if readings.body_temp_c is not None:
            self.state.body_temp_c = readings.body_temp_c
            r.body_temp.set_value(f"{readings.body_temp_c:.1f} °C", "Status: Normal")
        if readings.spo2_pct is not None:
            self.state.spo2_pct = readings.spo2_pct
            r.spo2.set_value(f"{readings.spo2_pct:.0f}%", "Status: Optimal")

    def _on_screen_changed(self, *_args) -> None:
        cur = self.manager.current
        if cur == "face":
            self.eyes_widget.start()
            self.morph_widget.stop()
        elif cur == "emotion":
            self.eyes_widget.stop()
            self.morph_widget.start()
        else:
            self.eyes_widget.stop()
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
        return UniMateKivyUI()


if __name__ == "__main__":
    UniMateApp().run()
