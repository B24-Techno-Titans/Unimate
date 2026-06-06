"""
Kivy canvas robot face matching the UniMate neon kawaii reference:
navy rounded panel, violet frame glow, cyan glowing oval eyes + uwu mouth.

Public API mirrors the old RoboEyesWidget so callers can stop/start rendering;
expression helpers are no-ops (reference face stays minimal).
"""

from __future__ import annotations

import math
import time

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp
from kivy.uix.widget import Widget

from theme import Theme


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


EYE_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
    (0.40, 1.15),
    (0.70, 0.85),
]

MOUTH_GLOW_LAYERS = [
    (0.07, 3.2),
    (0.14, 2.3),
    (0.26, 1.6),
    (0.45, 1.1),
]


def _uwu_mouth_points(cx: float, cy: float, half_w: float, depth: float, segments: int = 40) -> list[float]:
    points: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        x = cx - half_w + 2 * half_w * t
        u = t * 2 if t <= 0.5 else (t - 0.5) * 2
        y = cy - depth * math.sin(u * math.pi)
        points.extend([x, y])
    return points


class RoboEyesWidget(Widget):
    """
    Reference-style face: violet glowing squircle frame, cyan eyes and uwu mouth.
    Subtle blink and glow pulse only.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._paused = False
        self._t0 = time.monotonic()
        self._phase = 0.0
        self._blink = 0.0
        self._blink_target = 0.0
        self._blink_hold = 0.0
        self._next_blink = 3.0
        self._glow_pulse = 1.0
        self._mouth_depth = 1.0

        self._border_lines: list[Line] = []
        self._eye_glow: dict[str, list[Ellipse]] = {"l": [], "r": []}
        self._eye_core: dict[str, Ellipse] = {}
        self._mouth_glow: list[Line] = []
        self._mouth_core: Line | None = None
        self._bg_rect: Rectangle | None = None

        self.bind(size=self._layout, pos=self._layout)
        self._build_canvas()
        self._event = Clock.schedule_interval(self._tick, 1 / 60.0)

    def _build_canvas(self) -> None:
        with self.canvas.before:
            Color(*Theme.FACE_BG)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)

        with self.canvas:
            for alpha, width_mult in Theme.FRAME_GLOW_LAYERS_VIOLET:
                Color(Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
                self._border_lines.append(
                    Line(
                        rounded_rectangle=(0, 0, 10, 10, 8),
                        width=dp(5) * width_mult,
                        cap="round",
                    )
                )

            for side in ("l", "r"):
                for _alpha, _size_mult in EYE_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _alpha)
                    self._eye_glow[side].append(Ellipse())
                Color(*Theme.CYAN)
                self._eye_core[side] = Ellipse()

            for alpha, width_mult in MOUTH_GLOW_LAYERS:
                Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                self._mouth_glow.append(
                    Line(points=[0, 0], width=dp(3.5) * width_mult, cap="round", joint="round")
                )
            Color(*Theme.CYAN)
            self._mouth_core = Line(points=[0, 0], width=dp(3.5), cap="round", joint="round")

    def stop(self) -> None:
        if self._event is not None:
            self._event.cancel()
            self._event = None
        self._paused = True

    def start(self) -> None:
        self._paused = False
        if self._event is None:
            self._event = Clock.schedule_interval(self._tick, 1 / 60.0)

    def _mono(self) -> float:
        return time.monotonic()

    def confuse(self, duration: float = 0.52) -> None:
        """No-op: reference face has no shake."""

    def laugh(self) -> None:
        """No-op."""

    def wink(self, *, left: bool = False, right: bool = True) -> None:
        """No-op."""

    def happy_flash(self, duration: float = 1.2) -> None:
        """No-op."""

    def _tick(self, dt: float) -> None:
        if self._paused:
            return
        self._phase = self._mono() - self._t0
        self._glow_pulse = 0.88 + 0.12 * math.sin(self._phase * 2.0)
        self._mouth_depth = 0.92 + 0.08 * math.sin(self._phase * 3.5)

        self._next_blink -= dt
        if self._next_blink <= 0 and self._blink_target == 0:
            self._blink_target = 1.0
            self._blink_hold = 0.1
            self._next_blink = 3.5 + abs(math.sin(self._phase * 0.4)) * 2.0

        if self._blink_hold > 0:
            self._blink_hold -= dt
        elif self._blink_target == 1.0 and self._blink > 0.9:
            self._blink_target = 0.0

        speed = 16.0 if self._blink_target > self._blink else 11.0
        self._blink = _lerp(self._blink, self._blink_target, min(1.0, dt * speed))
        self._layout()

    def _layout(self, *args):
        if self._bg_rect is None or self.width < 1 or self.height < 1:
            return

        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

        m = min(self.width, self.height)
        inset = m * 0.028
        fx, fy = self.x + inset, self.y + inset
        fw, fh = self.width - 2 * inset, self.height - 2 * inset
        radius = m * 0.11
        pulse = self._glow_pulse

        for line in self._border_lines:
            line.rounded_rectangle = (fx, fy, fw, fh, radius)

        cx = self.center_x
        eye_y = self.y + self.height * 0.58
        eye_dx = self.width * 0.19
        eye_r = m * 0.075
        blink_scale = 1.0 - _ease_in_out_sine(self._blink) * 0.94
        eye_h = eye_r * 2 * blink_scale

        for side, sign in (("l", -1), ("r", 1)):
            ex = cx + sign * eye_dx
            for ell, (_, size_mult) in zip(self._eye_glow[side], EYE_GLOW_LAYERS):
                glow_r = eye_r * size_mult * pulse
                ell.pos = (ex - glow_r, eye_y - glow_r * blink_scale)
                ell.size = (glow_r * 2, glow_r * 2 * blink_scale)

            core = self._eye_core[side]
            core.pos = (ex - eye_r, eye_y - eye_h / 2)
            core.size = (eye_r * 2, eye_h)

        mouth_y = self.y + self.height * 0.40
        mouth_half_w = m * 0.11
        mouth_depth = m * 0.028 * self._mouth_depth
        mouth_pts = _uwu_mouth_points(cx, mouth_y, mouth_half_w, mouth_depth)

        for line in self._mouth_glow:
            line.points = mouth_pts
        if self._mouth_core is not None:
            self._mouth_core.points = mouth_pts


def schedule_random_idle_charm(_eyes: RoboEyesWidget, interval: float = 8.0) -> None:
    """Reference face uses built-in blink/pulse only; no extra scheduled effects."""
    _, _ = _eyes, interval
    return