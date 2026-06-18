"""
Stable angry neon face emotion: violet frame, red brows, filled cyan eyes,
cyan frown, animated exclamation mark.
"""

from __future__ import annotations

import math
import time

from kivy.clock import Clock
from kivy.graphics import Color, Line, Mesh, Rectangle
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp
from kivy.uix.widget import Widget

from theme import Theme

MOUTH_GLOW_LAYERS = [
    (0.07, 3.2),
    (0.14, 2.3),
    (0.26, 1.6),
    (0.45, 1.1),
]

RED_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
    (0.40, 1.15),
    (0.70, 0.85),
]

ANGRY_EYE_FILL_GLOW_LAYERS = [
    (0.10, 1.04),
    (0.16, 1.07),
]

ANGRY_EYE_GLOW_LAYERS = [
    (0.05, 1.35),
    (0.12, 1.2),
    (0.22, 1.08),
]

ANGRY_RED = (1.0, 0.12, 0.18, 1.0)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _rotate_point(x: float, y: float, angle: float) -> tuple[float, float]:
    ca = math.cos(angle)
    sa = math.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _slanted_semicircle_points(
    cx: float,
    cy: float,
    radius: float,
    angle: float,
    blink_scale: float,
    segments: int = 30,
) -> list[float]:
    points: list[float] = []
    left = _rotate_point(-radius, 0, angle)
    right = _rotate_point(radius, 0, angle)
    points.extend([cx + left[0], cy + left[1], cx + right[0], cy + right[1]])

    for i in range(segments + 1):
        t = i / segments
        local_x = radius * math.cos(t * math.pi)
        local_y = -radius * math.sin(t * math.pi) * blink_scale
        x, y = _rotate_point(local_x, local_y, angle)
        points.extend([cx + x, cy + y])
    return points


def _slanted_semicircle_fill_verts(
    cx: float,
    cy: float,
    radius: float,
    angle: float,
    blink_scale: float,
    size_mult: float = 1.0,
    segments: int = 30,
) -> list[float]:
    r = radius * size_mult
    inner_x, inner_y = _rotate_point(0, -r * 0.32 * blink_scale, angle)
    verts = [cx + inner_x, cy + inner_y]

    left = _rotate_point(-r, 0, angle)
    verts.extend([cx + left[0], cy + left[1]])

    for i in range(segments + 1):
        t = i / segments
        local_x = r * math.cos(t * math.pi)
        local_y = -r * math.sin(t * math.pi) * blink_scale
        x, y = _rotate_point(local_x, local_y, angle)
        verts.extend([cx + x, cy + y])
    return verts


def _set_mesh_fan(mesh: Mesh, verts_xy: list[float]) -> None:
    vertices: list[float] = []
    for i in range(0, len(verts_xy), 2):
        vertices.extend([verts_xy[i], verts_xy[i + 1], 0, 0])
    mesh.vertices = vertices
    mesh.indices = list(range(len(verts_xy) // 2))


def _circle_arc_points(
    cx: float, cy: float, radius: float, start: float, end: float, segments: int = 36
) -> list[float]:
    points: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        a = start + (end - start) * t
        points.extend([cx + math.cos(a) * radius, cy + math.sin(a) * radius])
    return points


class RoboAngryWidget(Widget):
    """Neon angry face with blink, brow bob, mouth shake, and exclamation bounce."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._paused = False
        self._t0 = time.monotonic()
        self._phase = 0.0
        self._blink = 0.0
        self._blink_target = 0.0
        self._blink_hold = 0.0
        self._next_blink = 2.5
        self._glow_pulse = 1.0
        self._mouth_depth = 1.0

        self._border_lines: list[Line] = []
        self._bg_rect: Rectangle | None = None
        self._brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._brow_core: dict[str, Line] = {}
        self._eye_fill_glow: dict[str, list[Mesh]] = {"l": [], "r": []}
        self._eye_fill_core: dict[str, Mesh] = {}
        self._eye_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._eye_core: dict[str, Line] = {}
        self._mouth_glow: list[Line] = []
        self._mouth_core: Line | None = None
        self._exclaim_bar_glow: list[Line] = []
        self._exclaim_bar_core: Line | None = None
        self._exclaim_dot_glow: list[Ellipse] = []
        self._exclaim_dot_core: Ellipse | None = None

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
                for alpha, width_mult in RED_GLOW_LAYERS:
                    Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], alpha)
                    self._brow_glow[side].append(
                        Line(points=[0, 0, 1, 1], width=dp(5.5) * width_mult, cap="round")
                    )
                Color(*ANGRY_RED)
                self._brow_core[side] = Line(points=[0, 0, 1, 1], width=dp(5.5), cap="round")

            for side in ("l", "r"):
                for alpha, size_mult in ANGRY_EYE_FILL_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._eye_fill_glow[side].append(Mesh(mode="triangle_fan"))
                Color(*Theme.CYAN)
                self._eye_fill_core[side] = Mesh(mode="triangle_fan")

                for alpha, width_mult in ANGRY_EYE_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._eye_glow[side].append(
                        Line(points=[0, 0], width=dp(4.5) * width_mult, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._eye_core[side] = Line(points=[0, 0], width=dp(4.5), cap="round", joint="round")

            for alpha, width_mult in MOUTH_GLOW_LAYERS:
                Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                self._mouth_glow.append(
                    Line(points=[0, 0], width=dp(3.5) * width_mult, cap="round", joint="round")
                )
            Color(*Theme.CYAN)
            self._mouth_core = Line(points=[0, 0], width=dp(3.5), cap="round", joint="round")

            for alpha, width_mult in RED_GLOW_LAYERS:
                Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], alpha)
                self._exclaim_bar_glow.append(
                    Line(points=[0, 0, 0, 1], width=dp(4.4) * width_mult, cap="round")
                )
            Color(*ANGRY_RED)
            self._exclaim_bar_core = Line(points=[0, 0, 0, 1], width=dp(4.4), cap="round")

            for alpha, _size_mult in RED_GLOW_LAYERS[:3]:
                Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], alpha)
                self._exclaim_dot_glow.append(Ellipse())
            Color(*ANGRY_RED)
            self._exclaim_dot_core = Ellipse()

    def stop(self) -> None:
        if self._event is not None:
            self._event.cancel()
            self._event = None
        self._paused = True

    def start(self) -> None:
        self._paused = False
        if self._event is None:
            self._event = Clock.schedule_interval(self._tick, 1 / 60.0)

    def _tick(self, dt: float) -> None:
        if self._paused:
            return
        self._phase = time.monotonic() - self._t0
        self._glow_pulse = 0.84 + 0.16 * math.sin(self._phase * 2.8)
        self._mouth_depth = 0.94 + 0.06 * math.sin(self._phase * 4.0)

        self._next_blink -= dt
        if self._next_blink <= 0 and self._blink_target == 0:
            self._blink_target = 1.0
            self._blink_hold = 0.08
            self._next_blink = 2.8 + abs(math.sin(self._phase * 0.5)) * 1.8

        if self._blink_hold > 0:
            self._blink_hold -= dt
        elif self._blink_target == 1.0 and self._blink > 0.9:
            self._blink_target = 0.0

        speed = 18.0 if self._blink_target > self._blink else 12.0
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
        eye_radius = m * 0.088
        blink_scale = 1.0 - _ease_in_out_sine(self._blink) * 0.92

        brow_gap = m * 0.075
        brow_len = m * 0.209
        brow_bob = m * 0.014 * math.sin(self._phase * 3.4)
        mouth_shake_x = m * 0.009 * math.sin(self._phase * 16.0)
        ex_bob = m * 0.02 * math.sin(self._phase * 4.8)

        for side, sign in (("l", -1), ("r", 1)):
            ex = cx + sign * eye_dx
            eye_angle = sign * 0.34
            for fill_mesh, (_, size_mult) in zip(self._eye_fill_glow[side], ANGRY_EYE_FILL_GLOW_LAYERS):
                fill_verts = _slanted_semicircle_fill_verts(
                    ex, eye_y, eye_radius, eye_angle, blink_scale, size_mult=size_mult
                )
                _set_mesh_fan(fill_mesh, fill_verts)
            core_fill_verts = _slanted_semicircle_fill_verts(
                ex, eye_y, eye_radius, eye_angle, blink_scale
            )
            _set_mesh_fan(self._eye_fill_core[side], core_fill_verts)

            eye_pts = _slanted_semicircle_points(ex, eye_y, eye_radius, eye_angle, blink_scale)
            for line in self._eye_glow[side]:
                line.points = eye_pts
            self._eye_core[side].points = eye_pts

            brow_center_x = ex
            brow_center_y = eye_y + brow_gap + brow_bob
            brow_dx, brow_dy = _rotate_point(brow_len / 2, 0, eye_angle)
            brow_pts = [
                brow_center_x - brow_dx,
                brow_center_y - brow_dy,
                brow_center_x + brow_dx,
                brow_center_y + brow_dy,
            ]
            for line in self._brow_glow[side]:
                line.points = brow_pts
            self._brow_core[side].points = brow_pts

        mouth_y = self.y + self.height * 0.35
        mouth_radius = m * 0.135
        mouth_depth = m * 0.024 * (self._mouth_depth - 1.0)
        mouth_start = 0.18 * math.pi
        mouth_end = 0.82 * math.pi
        mouth_pts = _circle_arc_points(
            cx + mouth_shake_x,
            mouth_y + mouth_depth,
            mouth_radius,
            mouth_start,
            mouth_end,
        )
        for line in self._mouth_glow:
            line.points = mouth_pts
        if self._mouth_core is not None:
            self._mouth_core.points = mouth_pts

        ex_x = cx + eye_dx + m * 0.16
        ex_top = eye_y + m * 0.022 + ex_bob
        ex_bottom = eye_y - m * 0.121 + ex_bob
        ex_slant = m * 0.0132
        ex_bar = [ex_x + ex_slant, ex_top, ex_x - ex_slant, ex_bottom]
        for line in self._exclaim_bar_glow:
            line.points = ex_bar
        if self._exclaim_bar_core is not None:
            self._exclaim_bar_core.points = ex_bar

        dot_r = m * 0.0154 * pulse
        dot_cx = ex_x - ex_slant * 1.45
        dot_cy = ex_bottom - m * 0.033
        for ell in self._exclaim_dot_glow:
            glow_r = dot_r * 1.8
            ell.pos = (dot_cx - glow_r, dot_cy - glow_r)
            ell.size = (glow_r * 2, glow_r * 2)
        if self._exclaim_dot_core is not None:
            self._exclaim_dot_core.pos = (dot_cx - dot_r, dot_cy - dot_r)
            self._exclaim_dot_core.size = (dot_r * 2, dot_r * 2)
