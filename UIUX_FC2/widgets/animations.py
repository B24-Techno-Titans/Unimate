"""Animated canvas widgets for controls and sensors."""

from __future__ import annotations

import math

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, Rotate
from kivy.metrics import dp
from kivy.uix.widget import Widget

from mock_state import MockState
from theme import Theme
from widgets.common import (
    FAN_PHASE_L1,
    FAN_PHASE_L2,
    FAN_ROTATE,
    HUM_PHASE_L1,
    HUM_PHASE_L2,
    HUM_PULSE,
    HUM_RISE_L1,
    HUM_RISE_L2,
    LED_OFF_EPS,
    LED_PHASE_BASE,
    LED_PHASE_BRIGHT,
    LED_ROTATE_BASE,
    LED_ROTATE_BRIGHT,
    device_icon_texture,
)

class DeviceViz(Widget):
    """PNG device icons from UIUX2/icons with level-based animation."""

    def __init__(self, kind: str, state: MockState, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.state = state
        self.phase = 0.0
        self._texture = device_icon_texture(kind)
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_interval(self._tick, 1 / 30)

    def _tick(self, dt: float) -> None:
        if self.kind == "fan":
            if self.state.fan_level > 0:
                spd = FAN_PHASE_L1 if self.state.fan_level == 1 else FAN_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "humidifier":
            if self.state.humidifier_level > 0:
                spd = HUM_PHASE_L1 if self.state.humidifier_level == 1 else HUM_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "led" and self.state.led_on and self.state.led_brightness > 0:
            br = self.state.led_brightness
            self.phase = (self.phase + dt * (LED_PHASE_BASE + LED_PHASE_BRIGHT * br)) % 10
        self._draw()

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 10 or self.height < 10:
            return
        cx, cy = self.center
        r = min(self.width, self.height) * 0.42
        side = r * 1.65
        ix = cx - side / 2
        iy = cy - side / 2
        c_c = Theme.CYAN
        rotate_deg = 0.0
        alpha = 1.0
        tint = c_c

        if self.kind == "fan":
            active = self.state.fan_level > 0
            alpha = 1.0 if active else 0.28
            glow_a = 0.12 if active else 0.03
            rotate_deg = math.degrees(self.phase * FAN_ROTATE) if active else 0.0
            with self.canvas:
                Color(c_c[0], c_c[1], c_c[2], glow_a)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(*tint, alpha)
                PushMatrix()
                Rotate(angle=rotate_deg, origin=(cx, cy))
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                PopMatrix()

        elif self.kind == "humidifier":
            lvl = self.state.humidifier_level
            alpha = 1.0 if lvl > 0 else 0.28
            pulse = 0.85 + 0.15 * math.sin(self.phase * HUM_PULSE) if lvl > 0 else 1.0
            bubbles = 3 if lvl == 1 else (5 if lvl == 2 else 0)
            rise_mul = HUM_RISE_L1 if lvl == 1 else (HUM_RISE_L2 if lvl == 2 else 0)
            with self.canvas:
                Color(c_c[0], c_c[1], c_c[2], 0.1 if lvl > 0 else 0.03)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(*tint, alpha * pulse)
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                if bubbles:
                    for i in range(bubbles):
                        ox = (i - (bubbles - 1) / 2) * r * 0.28 + r * 0.38
                        rise = (self.phase * rise_mul + i * 17) % (r * 1.0)
                        br = r * (0.09 if lvl == 1 else 0.12)
                        Color(c_c[0], c_c[1], c_c[2], 0.55 * pulse)
                        Line(circle=(cx + ox, cy - r * 0.1 + rise, br), width=max(dp(1.5), r * 0.035))

        else:  # LED — tint with selected color
            lc = self.state.led_color
            br = self.state.led_brightness if self.state.led_on else 0.0
            alpha = 0.35 + 0.65 * br
            glow_a = 0.14 * alpha
            rotate_deg = (
                math.degrees(self.phase * (LED_ROTATE_BASE + LED_ROTATE_BRIGHT * br)) if br > 0 else 0.0
            )
            with self.canvas:
                Color(lc[0], lc[1], lc[2], glow_a)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(lc[0], lc[1], lc[2], alpha)
                PushMatrix()
                Rotate(angle=rotate_deg, origin=(cx, cy))
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                PopMatrix()



class CircuitBackdrop(Widget):
    """Faint circuit-board lines behind the sensor dashboard."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 20 or self.height < 20:
            return
        w, h = self.width, self.height
        x0, y0 = self.x, self.y
        lines = [
            (0.08, 0.22, 0.42, 0.22),
            (0.42, 0.22, 0.42, 0.55),
            (0.42, 0.55, 0.78, 0.55),
            (0.78, 0.55, 0.78, 0.82),
            (0.15, 0.68, 0.55, 0.68),
            (0.55, 0.68, 0.55, 0.38),
            (0.55, 0.38, 0.92, 0.38),
            (0.25, 0.88, 0.65, 0.88),
            (0.65, 0.88, 0.65, 0.48),
        ]
        with self.canvas:
            Color(0.12, 0.28, 0.48, 0.22)
            for x1r, y1r, x2r, y2r in lines:
                Line(
                    points=[x0 + x1r * w, y0 + y1r * h, x0 + x2r * w, y0 + y2r * h],
                    width=dp(1.2),
                )
            for xr, yr in ((0.42, 0.22), (0.42, 0.55), (0.55, 0.68), (0.65, 0.88)):
                Line(circle=(x0 + xr * w, y0 + yr * h, dp(3)), width=dp(1))
