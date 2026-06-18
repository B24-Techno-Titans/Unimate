"""
Stable sad neon face emotion: violet frame, cyan slanted-cut eyes, curved brows,
downward frown, filled teardrops, brow bob, mouth shake, tear drip.
"""

from __future__ import annotations

import math
import time

from kivy.clock import Clock
from kivy.graphics import Color, Line, Mesh, Rectangle
from kivy.metrics import dp
from kivy.uix.widget import Widget

from theme import Theme

MOUTH_GLOW_LAYERS = [
    (0.07, 3.2),
    (0.14, 2.3),
    (0.26, 1.6),
    (0.45, 1.1),
]

SAD_BROW_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
    (0.40, 1.15),
    (0.70, 0.85),
]

SAD_EYE_FILL_GLOW_LAYERS = [
    (0.10, 1.04),
    (0.16, 1.07),
]

SAD_EYE_GLOW_LAYERS = [
    (0.05, 1.35),
    (0.12, 1.2),
    (0.22, 1.08),
]

SAD_TEAR_FILL_GLOW_LAYERS = [
    (0.10, 1.04),
    (0.16, 1.07),
]

SAD_TEAR_GLOW_LAYERS = [
    (0.07, 2.8),
    (0.14, 2.0),
    (0.26, 1.5),
    (0.45, 1.1),
]


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


def _sad_brow_points(
    cx: float,
    cy: float,
    radius: float,
    angle: float,
    gap: float,
    length_mult: float,
    curve_depth: float,
    offset_y: float = 0.0,
    segments: int = 22,
) -> list[float]:
    """Brow arc curving away from the eyes; circle centroid above the chord."""
    cy += offset_y
    brow_half = radius * length_mult
    left = _rotate_point(-brow_half, gap, angle)
    right = _rotate_point(brow_half, gap, angle)
    center = _rotate_point(0, gap + curve_depth, angle)

    bcx = cx + center[0]
    bcy = cy + center[1]
    lx = cx + left[0]
    ly = cy + left[1]
    rx = cx + right[0]
    ry = cy + right[1]

    circle_r = math.hypot(brow_half, curve_depth)
    start_a = math.atan2(ly - bcy, lx - bcx)
    end_a = math.atan2(ry - bcy, rx - bcx)

    sweep = end_a - start_a
    if sweep < 0:
        sweep += 2 * math.pi

    points: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        a = start_a + sweep * t
        points.extend([bcx + math.cos(a) * circle_r, bcy + math.sin(a) * circle_r])
    return points


def _teardrop_fill_verts(
    cx: float,
    cy: float,
    height: float,
    width: float,
    segments: int = 18,
) -> list[float]:
    """Filled teardrop: fan from pointed top through rounded bottom."""
    verts: list[float] = []
    top_y = cy + height * 0.5
    bulb_r = width * 0.5
    bulb_cy = cy - height * 0.12

    verts.extend([cx, top_y])
    for i in range(segments + 1):
        t = i / segments
        a = math.pi + t * math.pi
        verts.extend([cx + math.cos(a) * bulb_r, bulb_cy + math.sin(a) * bulb_r])
    return verts


def _teardrop_points(
    cx: float,
    cy: float,
    height: float,
    width: float,
    segments: int = 18,
) -> list[float]:
    """Hanging teardrop outline: pointed top, rounded bottom."""
    points: list[float] = []
    top_y = cy + height * 0.5
    bulb_r = width * 0.5
    bulb_cy = cy - height * 0.12

    points.extend([cx, top_y])
    for i in range(segments + 1):
        t = i / segments
        a = math.pi + t * math.pi
        points.extend([cx + math.cos(a) * bulb_r, bulb_cy + math.sin(a) * bulb_r])
    points.extend([cx, top_y])
    return points


def _eye_bottom_y(cx: float, cy: float, radius: float, angle: float, blink_scale: float) -> float:
    bottom = _rotate_point(0, -radius * blink_scale, angle)
    return cy + bottom[1]


class RoboSadWidget(Widget):
    """Neon sad face with blink, glow pulse, brow bob, mouth shake, and tear drip."""

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
        self._bg_rect: Rectangle | None = None
        self._brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._brow_core: dict[str, Line] = {}
        self._eye_fill_glow: dict[str, list[Mesh]] = {"l": [], "r": []}
        self._eye_fill_core: dict[str, Mesh] = {}
        self._eye_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._eye_core: dict[str, Line] = {}
        self._mouth_glow: list[Line] = []
        self._mouth_core: Line | None = None
        self._tear_fill_glow: dict[str, list[Mesh]] = {"l": [], "r": []}
        self._tear_fill_core: dict[str, Mesh] = {}
        self._tear_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._tear_core: dict[str, Line] = {}

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
                for alpha, width_mult in SAD_BROW_GLOW_LAYERS[:3]:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._brow_glow[side].append(
                        Line(points=[0, 0], width=dp(3.2) * width_mult, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._brow_core[side] = Line(points=[0, 0], width=dp(3.2), cap="round", joint="round")

            for side in ("l", "r"):
                for alpha, size_mult in SAD_EYE_FILL_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._eye_fill_glow[side].append(Mesh(mode="triangle_fan"))
                Color(*Theme.CYAN)
                self._eye_fill_core[side] = Mesh(mode="triangle_fan")

                for alpha, width_mult in SAD_EYE_GLOW_LAYERS:
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

            for side in ("l", "r"):
                for alpha, size_mult in SAD_TEAR_FILL_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._tear_fill_glow[side].append(Mesh(mode="triangle_fan"))
                Color(*Theme.CYAN)
                self._tear_fill_core[side] = Mesh(mode="triangle_fan")

                for alpha, width_mult in SAD_TEAR_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._tear_glow[side].append(
                        Line(points=[0, 0], width=dp(3.0) * width_mult, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._tear_core[side] = Line(points=[0, 0], width=dp(3.0), cap="round", joint="round")

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
        eye_radius = m * 0.088
        blink_scale = 1.0 - _ease_in_out_sine(self._blink) * 0.94

        brow_gap = m * 0.118
        brow_length_mult = 1.2
        brow_curve = m * 0.2
        brow_bob = m * 0.016 * math.sin(self._phase * 12.0)
        mouth_shake_x = m * 0.011 * math.sin(self._phase * 15.0)
        tear_bob = m * 0.018 * math.sin(self._phase * 3.0)

        for side, sign in (("l", -1), ("r", 1)):
            ex = cx + sign * eye_dx
            eye_angle = -sign * 0.34

            for fill_mesh, (_, size_mult) in zip(self._eye_fill_glow[side], SAD_EYE_FILL_GLOW_LAYERS):
                fill_verts = _slanted_semicircle_fill_verts(
                    ex,
                    eye_y,
                    eye_radius,
                    eye_angle,
                    blink_scale,
                    size_mult=size_mult * pulse,
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

            brow_pts = _sad_brow_points(
                ex,
                eye_y,
                eye_radius,
                eye_angle,
                brow_gap,
                brow_length_mult,
                brow_curve,
                offset_y=brow_bob,
            )
            for line in self._brow_glow[side]:
                line.points = brow_pts
            self._brow_core[side].points = brow_pts

            eye_bottom = _eye_bottom_y(ex, eye_y, eye_radius, eye_angle, 1.0)
            tear_gap = m * 0.085
            tear_h = m * 0.078
            tear_w = m * 0.04
            tear_top = eye_bottom - tear_gap
            tear_cy = tear_top - tear_h * 0.5 + tear_bob
            for fill_mesh, (_, size_mult) in zip(self._tear_fill_glow[side], SAD_TEAR_FILL_GLOW_LAYERS):
                fill_verts = _teardrop_fill_verts(
                    ex, tear_cy, tear_h * size_mult, tear_w * size_mult
                )
                _set_mesh_fan(fill_mesh, fill_verts)
            _set_mesh_fan(
                self._tear_fill_core[side],
                _teardrop_fill_verts(ex, tear_cy, tear_h, tear_w),
            )
            tear_pts = _teardrop_points(ex, tear_cy, tear_h, tear_w)
            for line in self._tear_glow[side]:
                line.points = tear_pts
            self._tear_core[side].points = tear_pts

        mouth_y = self.y + self.height * 0.36
        mouth_radius = m * 0.152
        mouth_depth = m * 0.022 * self._mouth_depth
        mouth_start = 0.11 * math.pi
        mouth_end = 0.89 * math.pi
        mouth_pts = _circle_arc_points(
            cx + mouth_shake_x, mouth_y - mouth_depth, mouth_radius, mouth_start, mouth_end
        )
        for line in self._mouth_glow:
            line.points = mouth_pts
        if self._mouth_core is not None:
            self._mouth_core.points = mouth_pts
