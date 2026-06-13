"""
Morphing neon face: blends normal, sad, angry, and happy expressions with staged transitions.
"""

from __future__ import annotations

import math
import time
from typing import Literal

from kivy.clock import Clock
from kivy.graphics import Color, Line, Mesh, Rectangle
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp
from kivy.uix.widget import Widget

from emotions import happy as happy_face
from theme import Theme

Expression = Literal["normal", "sad", "angry", "happy"]

TRANSITION_DURATION = 0.52
HAPPY_TRANSITION_DURATION = 0.68

# normal ↔ happy: eyes → lashes → brows → mouth (overlapping, ease-in-out)
HAPPY_FORWARD_STAGES = {
    "eye": (0.00, 0.44),
    "extra": (0.14, 0.58),
    "brow": (0.30, 0.72),
    "mouth": (0.44, 0.96),
}
HAPPY_REVERSE_STAGES = {
    "mouth": (0.00, 0.30),
    "brow": (0.16, 0.46),
    "extra": (0.30, 0.58),
    "eye": (0.48, 0.98),
}

MOUTH_GLOW_LAYERS = [
    (0.07, 3.2),
    (0.14, 2.3),
    (0.26, 1.6),
    (0.45, 1.1),
]

EYE_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
    (0.40, 1.15),
    (0.70, 0.85),
]

BROW_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
]

TEAR_FILL_GLOW = [(0.10, 1.04), (0.16, 1.07)]
TEAR_GLOW_LAYERS = [(0.07, 2.8), (0.14, 2.0), (0.26, 1.5), (0.45, 1.1)]
SLANT_EYE_FILL_GLOW = [(0.10, 1.04), (0.16, 1.07)]
SLANT_EYE_GLOW = [(0.05, 1.35), (0.12, 1.2), (0.22, 1.08)]
RED_GLOW_LAYERS = [(0.06, 2.6), (0.12, 2.0), (0.22, 1.5), (0.40, 1.15), (0.70, 0.85)]
ANGRY_RED = (1.0, 0.12, 0.18, 1.0)

FORWARD_STAGES = {
    "brow": (0.00, 0.30),
    "eye": (0.10, 0.45),
    "mouth": (0.25, 0.60),
    "extra": (0.50, 0.98),
}
REVERSE_STAGES = {
    "extra": (0.00, 0.26),
    "mouth": (0.26, 0.48),
    "eye": (0.42, 0.64),
    "brow": (0.58, 0.95),
}


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp(t: float) -> float:
    return max(0.0, min(1.0, t))


def _ease_in_out_sine(t: float) -> float:
    t = _clamp(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _ease_out_cubic(t: float) -> float:
    t = _clamp(t)
    return 1.0 - (1.0 - t) ** 3


def _stage_k(t: float, start: float, end: float, *, smooth: bool = False) -> float:
    if t <= start:
        return 0.0
    if t >= end:
        return 1.0
    u = (t - start) / (end - start)
    return _ease_in_out_sine(u) if smooth else _ease_out_cubic(u)


def _rotate_point(x: float, y: float, angle: float) -> tuple[float, float]:
    ca = math.cos(angle)
    sa = math.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _set_mesh_fan(mesh: Mesh, verts_xy: list[float]) -> None:
    if len(verts_xy) < 6:
        mesh.vertices = []
        mesh.indices = []
        return
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
        u = i / segments
        a = start + (end - start) * u
        points.extend([cx + math.cos(a) * radius, cy + math.sin(a) * radius])
    return points


def _uwu_mouth_points(cx: float, cy: float, half_w: float, depth: float, segments: int = 40) -> list[float]:
    points: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        x = cx - half_w + 2 * half_w * t
        u = t * 2 if t <= 0.5 else (t - 0.5) * 2
        y = cy - depth * math.sin(u * math.pi)
        points.extend([x, y])
    return points


def _slanted_semicircle_points(
    cx: float, cy: float, radius: float, angle: float, blink_scale: float, segments: int = 30
) -> list[float]:
    points: list[float] = []
    left = _rotate_point(-radius, 0, angle)
    right = _rotate_point(radius, 0, angle)
    points.extend([cx + left[0], cy + left[1], cx + right[0], cy + right[1]])
    for i in range(segments + 1):
        t = i / segments
        lx = radius * math.cos(t * math.pi)
        ly = -radius * math.sin(t * math.pi) * blink_scale
        x, y = _rotate_point(lx, ly, angle)
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
        lx = radius * math.cos(t * math.pi)
        ly = -r * math.sin(t * math.pi) * blink_scale
        x, y = _rotate_point(lx, ly, angle)
        verts.extend([cx + x, cy + y])
    return verts


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
        u = i / segments
        a = start_a + sweep * u
        points.extend([bcx + math.cos(a) * circle_r, bcy + math.sin(a) * circle_r])
    return points


def _angry_brow_points(
    cx: float, cy: float, brow_len: float, eye_angle: float, gap: float, bob: float
) -> list[float]:
    brow_center_y = cy + gap + bob
    brow_dx, brow_dy = _rotate_point(brow_len / 2, 0, eye_angle)
    return [
        cx - brow_dx,
        brow_center_y - brow_dy,
        cx + brow_dx,
        brow_center_y + brow_dy,
    ]


def _teardrop_fill_verts(cx: float, cy: float, height: float, width: float, segments: int = 18) -> list[float]:
    verts: list[float] = []
    top_y = cy + height * 0.5
    bulb_r = width * 0.5
    bulb_cy = cy - height * 0.12
    verts.extend([cx, top_y])
    for i in range(segments + 1):
        u = i / segments
        a = math.pi + u * math.pi
        verts.extend([cx + math.cos(a) * bulb_r, bulb_cy + math.sin(a) * bulb_r])
    return verts


def _teardrop_points(cx: float, cy: float, height: float, width: float, segments: int = 18) -> list[float]:
    points: list[float] = []
    top_y = cy + height * 0.5
    bulb_r = width * 0.5
    bulb_cy = cy - height * 0.12
    points.extend([cx, top_y])
    for i in range(segments + 1):
        u = i / segments
        a = math.pi + u * math.pi
        points.extend([cx + math.cos(a) * bulb_r, bulb_cy + math.sin(a) * bulb_r])
    points.extend([cx, top_y])
    return points


def _eye_bottom_y(cx: float, cy: float, radius: float, angle: float) -> float:
    bottom = _rotate_point(0, -radius, angle)
    return cy + bottom[1]


def _resample_polyline(points: list[float], count: int) -> list[float]:
    if len(points) < 4:
        return [0.0, 0.0] * (count + 1)
    lengths: list[float] = [0.0]
    total = 0.0
    for i in range(2, len(points), 2):
        dx = points[i] - points[i - 2]
        dy = points[i + 1] - points[i - 1]
        total += math.hypot(dx, dy)
        lengths.append(total)
    if total < 1e-6:
        return points[: (count + 1) * 2]
    out: list[float] = []
    for i in range(count + 1):
        target = total * i / count
        seg = 0
        while seg + 1 < len(lengths) and lengths[seg + 1] < target:
            seg += 1
        seg_len = lengths[seg + 1] - lengths[seg]
        t = 0.0 if seg_len < 1e-6 else (target - lengths[seg]) / seg_len
        x = _lerp(points[seg * 2], points[(seg + 1) * 2], t)
        y = _lerp(points[seg * 2 + 1], points[(seg + 1) * 2 + 1], t)
        out.extend([x, y])
    return out


def _lerp_polylines(a: list[float], b: list[float], t: float, count: int = 40) -> list[float]:
    ra = _resample_polyline(a, count)
    rb = _resample_polyline(b, count)
    out: list[float] = []
    for i in range(0, len(ra), 2):
        out.extend([_lerp(ra[i], rb[i], t), _lerp(ra[i + 1], rb[i + 1], t)])
    return out


class RoboMorphWidget(Widget):
    """Face that morphs between normal, sad, angry, and happy with staged animation."""

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

        self._settled: Expression = "normal"
        self._from_expr: Expression = "normal"
        self._to_expr: Expression = "normal"
        self._reverse = False
        self._trans_t = 1.0
        self._queued: Expression | None = None
        self._animating = False
        self._trans_duration = TRANSITION_DURATION

        self._border_lines: list[Line] = []
        self._bg_rect: Rectangle | None = None
        self._oval_glow: dict[str, list[Ellipse]] = {"l": [], "r": []}
        self._oval_core: dict[str, Ellipse] = {}
        self._slant_fill_glow: dict[str, list[Mesh]] = {"l": [], "r": []}
        self._slant_fill_core: dict[str, Mesh] = {}
        self._slant_line_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._slant_line_core: dict[str, Line] = {}
        self._sad_brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._sad_brow_core: dict[str, Line] = {}
        self._angry_brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._angry_brow_core: dict[str, Line] = {}
        self._mouth_glow: list[Line] = []
        self._mouth_core: Line | None = None
        self._tear_fill_glow: dict[str, list[Mesh]] = {"l": [], "r": []}
        self._tear_fill_core: dict[str, Mesh] = {}
        self._tear_line_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._tear_line_core: dict[str, Line] = {}
        self._exclaim_bar_glow: list[Line] = []
        self._exclaim_bar_core: Line | None = None
        self._exclaim_dot_glow: list[Ellipse] = []
        self._exclaim_dot_core: Ellipse | None = None
        self._happy_eye_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._happy_eye_core: dict[str, Line] = {}
        self._happy_brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._happy_brow_core: dict[str, Line] = {}
        self._happy_lash_glow: dict[str, list[list[Line]]] = {"l": [], "r": []}
        self._happy_lash_core: dict[str, list[Line]] = {"l": [], "r": []}
        self._happy_mouth_fill_glow: list[Mesh] = []
        self._happy_mouth_fill_core: Mesh | None = None

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
                    Line(rounded_rectangle=(0, 0, 10, 10, 8), width=dp(5) * width_mult, cap="round")
                )

            for side in ("l", "r"):
                for _a, _s in EYE_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._oval_glow[side].append(Ellipse())
                Color(*Theme.CYAN)
                self._oval_core[side] = Ellipse()

                for _a, _s in SLANT_EYE_FILL_GLOW:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._slant_fill_glow[side].append(Mesh(mode="triangle_fan"))
                Color(*Theme.CYAN)
                self._slant_fill_core[side] = Mesh(mode="triangle_fan")
                for _a, wm in SLANT_EYE_GLOW:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._slant_line_glow[side].append(
                        Line(points=[0, 0], width=dp(4.5) * wm, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._slant_line_core[side] = Line(points=[0, 0], width=dp(4.5), cap="round", joint="round")

                for _a, wm in BROW_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._sad_brow_glow[side].append(
                        Line(points=[0, 0], width=dp(3.2) * wm, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._sad_brow_core[side] = Line(points=[0, 0], width=dp(3.2), cap="round", joint="round")

                for _a, wm in RED_GLOW_LAYERS[:3]:
                    Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], _a)
                    self._angry_brow_glow[side].append(
                        Line(points=[0, 0, 1, 1], width=dp(5.5) * wm, cap="round")
                    )
                Color(*ANGRY_RED)
                self._angry_brow_core[side] = Line(points=[0, 0, 1, 1], width=dp(5.5), cap="round")

                for _a, sm in TEAR_FILL_GLOW:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._tear_fill_glow[side].append(Mesh(mode="triangle_fan"))
                Color(*Theme.CYAN)
                self._tear_fill_core[side] = Mesh(mode="triangle_fan")
                for _a, wm in TEAR_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._tear_line_glow[side].append(
                        Line(points=[0, 0], width=dp(3.0) * wm, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._tear_line_core[side] = Line(points=[0, 0], width=dp(3.0), cap="round", joint="round")

            for _a, wm in MOUTH_GLOW_LAYERS:
                Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                self._mouth_glow.append(
                    Line(points=[0, 0], width=dp(3.5) * wm, cap="round", joint="round")
                )
            Color(*Theme.CYAN)
            self._mouth_core = Line(points=[0, 0], width=dp(3.5), cap="round", joint="round")

            for _a, wm in RED_GLOW_LAYERS:
                Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], _a)
                self._exclaim_bar_glow.append(Line(points=[0, 0, 0, 1], width=dp(4.4) * wm, cap="round"))
            Color(*ANGRY_RED)
            self._exclaim_bar_core = Line(points=[0, 0, 0, 1], width=dp(4.4), cap="round")
            for _a, _s in RED_GLOW_LAYERS[:3]:
                Color(ANGRY_RED[0], ANGRY_RED[1], ANGRY_RED[2], _a)
                self._exclaim_dot_glow.append(Ellipse())
            Color(*ANGRY_RED)
            self._exclaim_dot_core = Ellipse()
            off = (-9999.0, -9999.0)
            for line in self._exclaim_bar_glow:
                line.points = list(off) * 2
            if self._exclaim_bar_core is not None:
                self._exclaim_bar_core.points = list(off) * 2
            for ell in self._exclaim_dot_glow:
                ell.pos = off
                ell.size = (0, 0)
            if self._exclaim_dot_core is not None:
                self._exclaim_dot_core.pos = off
                self._exclaim_dot_core.size = (0, 0)

            for side in ("l", "r"):
                for _a, wm in happy_face.HAPPY_EYE_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._happy_eye_glow[side].append(
                        Line(points=[0, 0], width=dp(4.8) * wm, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._happy_eye_core[side] = Line(
                    points=[0, 0], width=dp(4.8), cap="round", joint="round"
                )

                for _a, wm in happy_face.HAPPY_BROW_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                    self._happy_brow_glow[side].append(
                        Line(
                            points=[0, 0],
                            width=dp(happy_face.BROW_LINE_WIDTH) * wm,
                            cap="round",
                            joint="round",
                        )
                    )
                Color(*Theme.CYAN)
                self._happy_brow_core[side] = Line(
                    points=[0, 0],
                    width=dp(happy_face.BROW_LINE_WIDTH),
                    cap="round",
                    joint="round",
                )

                self._happy_lash_glow[side] = []
                self._happy_lash_core[side] = []
                for _ in happy_face.LASH_SPECS:
                    glow_group: list[Line] = []
                    for _a, wm in happy_face.HAPPY_LASH_GLOW_LAYERS:
                        Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                        glow_group.append(
                            Line(points=[0, 0], width=dp(3.2) * wm, cap="round", joint="round")
                        )
                    self._happy_lash_glow[side].append(glow_group)
                    Color(*Theme.CYAN)
                    self._happy_lash_core[side].append(
                        Line(points=[0, 0], width=dp(3.2), cap="round", joint="round")
                    )

            for _a, sm in happy_face.HAPPY_MOUTH_FILL_GLOW_LAYERS:
                Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], _a)
                self._happy_mouth_fill_glow.append(Mesh(mode="triangle_fan"))
            Color(*Theme.CYAN)
            self._happy_mouth_fill_core = Mesh(mode="triangle_fan")

    @property
    def settled_expression(self) -> Expression:
        return self._settled

    @property
    def is_animating(self) -> bool:
        return self._animating

    def set_expression(self, target: Expression) -> None:
        if self._animating:
            self._queued = target
            return
        current = self._settled
        if current == target:
            return
        if current != "normal" and target != "normal":
            self._queued = target
            self._begin_transition(current, "normal", reverse=True)
            return
        self._begin_transition(current, target, reverse=(target == "normal"))

    def _begin_transition(self, src: Expression, dst: Expression, *, reverse: bool) -> None:
        self._from_expr = src
        self._to_expr = dst
        self._reverse = reverse
        self._trans_t = 0.0
        self._animating = True
        self._trans_duration = (
            HAPPY_TRANSITION_DURATION
            if "happy" in (src, dst)
            else TRANSITION_DURATION
        )

    def _finish_transition(self) -> None:
        self._settled = self._to_expr
        self._trans_t = 1.0
        self._animating = False
        if self._queued and self._queued != self._settled:
            nxt = self._queued
            self._queued = None
            # Chain immediately — no idle frame where the wrong expression can flash.
            self._begin_transition(self._settled, nxt, reverse=(nxt == "normal"))
        else:
            self._queued = None
        self._layout()

    def _is_happy_transition(self) -> bool:
        if not self._animating:
            return self._settled == "happy"
        if self._reverse:
            return self._from_expr == "happy"
        return self._to_expr == "happy"

    def _component_k(self, name: str) -> float:
        if self._is_happy_transition():
            stages = HAPPY_REVERSE_STAGES if self._reverse else HAPPY_FORWARD_STAGES
            smooth = True
        else:
            stages = REVERSE_STAGES if self._reverse else FORWARD_STAGES
            smooth = False
        lo, hi = stages[name]
        return _stage_k(self._trans_t, lo, hi, smooth=smooth)

    def _happy_visibility(self, name: str) -> float:
        """Stage progress mapped to visible amount (1 = fully shown, 0 = hidden)."""
        raw = self._component_k(name)
        if self._reverse:
            return 1.0 - raw
        return raw

    def _blend_to_target(self, component: str) -> float:
        if not self._animating:
            return 1.0 if self._settled != "normal" else 0.0
        k = self._component_k(component)
        if self._reverse:
            return 1.0 - k
        return k

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

        if self._animating:
            self._trans_t = min(1.0, self._trans_t + dt / self._trans_duration)
            if self._trans_t >= 1.0:
                self._finish_transition()

        if not self._animating:
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

    def _mouth_for(
        self,
        expr: Expression,
        cx: float,
        m: float,
        shake: float,
        *,
        animate: bool = True,
        mouth_bob: float = 0.0,
    ) -> list[float]:
        depth = self._mouth_depth if animate else 1.0
        if expr == "normal":
            mouth_y = self.y + self.height * 0.40
            return _uwu_mouth_points(cx, mouth_y, m * 0.11, m * 0.028 * depth)
        if expr == "happy":
            mouth_y = self.y + self.height * happy_face.MOUTH_Y_FRAC + mouth_bob
            top_sag = m * happy_face.MOUTH_TOP_SAG_FRAC
            return happy_face._smile_mouth_outline_points(
                cx, mouth_y, m * happy_face.MOUTH_RADIUS_FRAC, top_sag=top_sag
            )
        if expr == "sad":
            mouth_y = self.y + self.height * 0.36
            return _circle_arc_points(
                cx + shake,
                mouth_y - m * 0.022 * depth,
                m * 0.152,
                0.11 * math.pi,
                0.89 * math.pi,
            )
        mouth_y = self.y + self.height * 0.35
        d = m * 0.024 * (depth - 1.0)
        return _circle_arc_points(cx + shake, mouth_y + d, m * 0.135, 0.18 * math.pi, 0.82 * math.pi)

    def _layout(self, *args):
        if self._bg_rect is None or self.width < 1 or self.height < 1:
            return

        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

        m = min(self.width, self.height)
        inset = m * 0.028
        fx, fy = self.x + inset, self.y + inset
        fw, fh = self.width - 2 * inset, self.height - 2 * inset
        frame_r = m * 0.11
        pulse = self._glow_pulse

        for line in self._border_lines:
            line.rounded_rectangle = (fx, fy, fw, fh, frame_r)

        cx = self.center_x
        eye_y = self.y + self.height * 0.58
        eye_dx = self.width * 0.19
        blink_scale = 1.0 - _ease_in_out_sine(self._blink) * 0.94

        active = self._settled if not self._animating else (self._to_expr if not self._reverse else self._from_expr)
        idle = not self._animating
        in_happy = self._is_happy_transition()
        brow_bob = m * 0.016 * math.sin(self._phase * 12.0) if idle and active == "sad" else 0.0
        angry_bob = m * 0.014 * math.sin(self._phase * 3.4) if idle and active == "angry" else 0.0
        mouth_shake = m * 0.011 * math.sin(self._phase * 15.0) if idle and active in ("sad", "angry") else 0.0
        tear_bob = m * 0.018 * math.sin(self._phase * 3.0) if idle and active == "sad" else 0.0
        ex_bob = m * 0.02 * math.sin(self._phase * 4.8) if idle and active == "angry" else 0.0
        happy_brow_bob = (
            m * happy_face.BROW_BOB_AMP_FRAC * math.sin(self._phase * happy_face.BROW_BOB_SPEED)
            if idle and active == "happy"
            else 0.0
        )
        happy_lash_vibrate = (
            m * happy_face.LASH_VIBRATE_AMP_FRAC * math.sin(self._phase * happy_face.LASH_VIBRATE_SPEED)
            if idle and active == "happy"
            else 0.0
        )
        happy_mouth_bob = (
            m * happy_face.MOUTH_BOB_AMP_FRAC * math.sin(self._phase * happy_face.MOUTH_BOB_SPEED)
            if idle and active == "happy"
            else 0.0
        )

        sad_brow_k = 0.0
        angry_brow_k = 0.0
        tear_k = 0.0
        ex_k = 0.0
        sad_brow_lift = 0.0
        angry_brow_lift = 0.0

        if self._animating:
            if self._reverse:
                if self._from_expr == "sad":
                    ek = self._component_k("extra")
                    bk = self._component_k("brow")
                    sad_brow_k = 1.0 - bk
                    tear_k = 1.0 - ek
                    sad_brow_lift = m * 0.16 * (1.0 - sad_brow_k)
                elif self._from_expr == "angry":
                    ek = self._component_k("extra")
                    bk = self._component_k("brow")
                    angry_brow_k = 1.0 - bk
                    ex_k = 1.0 - ek
                    angry_brow_lift = m * 0.16 * (1.0 - angry_brow_k)
            else:
                if self._to_expr == "sad":
                    sad_brow_k = self._component_k("brow")
                    tear_k = self._component_k("extra")
                elif self._to_expr == "angry":
                    angry_brow_k = self._component_k("brow")
                    ex_k = self._component_k("extra")
        elif self._settled == "sad":
            sad_brow_k = tear_k = 1.0
        elif self._settled == "angry":
            angry_brow_k = ex_k = 1.0

        happy_eye_k = 0.0
        happy_lash_k = 0.0
        happy_brow_k = 0.0
        happy_mouth_fill_k = 0.0
        happy_lash_offset = 0.0
        happy_brow_y_shift = 0.0
        if in_happy:
            if not self._animating:
                happy_eye_k = happy_lash_k = happy_brow_k = happy_mouth_fill_k = 1.0
            else:
                happy_eye_k = self._happy_visibility("eye")
                happy_lash_k = self._happy_visibility("extra")
                happy_brow_k = self._happy_visibility("brow")
                happy_mouth_fill_k = self._happy_visibility("mouth")
                # Brows: drop in from above on enter, rise up on exit.
                happy_brow_y_shift = m * 0.14 * _ease_in_out_sine(1.0 - happy_brow_k)
                if self._reverse:
                    lash_exit = 1.0 - happy_lash_k
                    happy_lash_offset = m * 0.15 * _ease_in_out_sine(lash_exit)
                else:
                    lash_enter = 1.0 - happy_lash_k
                    happy_lash_offset = m * 0.11 * _ease_in_out_sine(lash_enter)

        angry_extra = (
            self._settled == "angry"
            or (self._animating and self._to_expr == "angry" and not self._reverse)
            or (self._animating and self._from_expr == "angry" and self._reverse)
        )
        if not angry_extra:
            ex_k = 0.0

        if in_happy:
            if not self._animating:
                oval_k = 0.0
                slant_k = 0.0
            else:
                oval_k = (1.0 - _ease_in_out_sine(happy_eye_k)) ** 1.05
                slant_k = 0.0
        elif not self._animating:
            oval_k = 1.0 if self._settled == "normal" else 0.0
            slant_k = 0.0 if self._settled == "normal" else 1.0
        else:
            slant_k = self._blend_to_target("eye")
            oval_k = 1.0 - slant_k

        normal_r = m * 0.075
        slant_r = m * 0.088
        eye_h = normal_r * 2 * blink_scale

        mouth_anim = not self._animating or in_happy
        mouth_bob = happy_mouth_bob if active == "happy" else 0.0
        if self._animating:
            mouth_src = self._from_expr
            mouth_dst = self._to_expr
            mouth_blend = _ease_in_out_sine(self._component_k("mouth"))
            from_mouth = self._mouth_for(mouth_src, cx, m, 0.0, animate=False, mouth_bob=0.0)
            to_mouth = self._mouth_for(mouth_dst, cx, m, 0.0, animate=False, mouth_bob=0.0)
            mouth_pts = _lerp_polylines(from_mouth, to_mouth, mouth_blend)
        else:
            mouth_pts = self._mouth_for(
                self._settled, cx, m, mouth_shake, animate=mouth_anim, mouth_bob=mouth_bob
            )

        for line in self._mouth_glow:
            line.points = mouth_pts
        if self._mouth_core is not None:
            self._mouth_core.points = mouth_pts

        show_happy_fill = happy_mouth_fill_k > 0.015
        mouth_y_h = self.y + self.height * happy_face.MOUTH_Y_FRAC + mouth_bob
        mouth_r_h = m * happy_face.MOUTH_RADIUS_FRAC
        top_sag_h = m * happy_face.MOUTH_TOP_SAG_FRAC
        fill_ease = _ease_in_out_sine(happy_mouth_fill_k)
        fill_scale = fill_ease if self._animating else 1.0
        if show_happy_fill and fill_scale > 0.01:
            for fill_mesh, (_, sm) in zip(self._happy_mouth_fill_glow, happy_face.HAPPY_MOUTH_FILL_GLOW_LAYERS):
                fill_verts = happy_face._smile_mouth_fill_verts(
                    cx,
                    mouth_y_h,
                    mouth_r_h * fill_scale,
                    size_mult=sm * pulse,
                    top_sag=top_sag_h * fill_scale,
                )
                _set_mesh_fan(fill_mesh, fill_verts)
            if self._happy_mouth_fill_core is not None:
                _set_mesh_fan(
                    self._happy_mouth_fill_core,
                    happy_face._smile_mouth_fill_verts(
                        cx, mouth_y_h, mouth_r_h * fill_scale, top_sag=top_sag_h * fill_scale
                    ),
                )
        else:
            for fill_mesh in self._happy_mouth_fill_glow:
                _set_mesh_fan(fill_mesh, [])
            if self._happy_mouth_fill_core is not None:
                _set_mesh_fan(self._happy_mouth_fill_core, [])

        happy_eye_y = self.y + self.height * happy_face.EYE_Y_FRAC
        happy_eye_dx = self.width * happy_face.EYE_DX_FRAC
        happy_eye_r = m * happy_face.EYE_RADIUS_FRAC
        happy_brow_y_off = m * happy_face.BROW_Y_OFFSET_FRAC
        happy_brow_x_off = m * happy_face.BROW_X_OFFSET_FRAC
        happy_brow_r = m * happy_face.BROW_RADIUS_FRAC
        happy_lash_r = m * happy_face.LASH_RADIUS_FRAC
        ex_left = cx - happy_eye_dx
        eye_open = _ease_in_out_sine(happy_eye_k)
        happy_blink = _lerp(0.06, blink_scale, eye_open) if in_happy else 1.0

        happy_eye_pts_l = happy_face._rotated_arc_points(
            ex_left,
            happy_eye_y,
            happy_eye_r * _lerp(0.85, 1.0, eye_open),
            happy_face.EYE_ARC_START_PI,
            happy_face.EYE_ARC_END_PI,
            y_scale=happy_blink,
            segments=30,
        )
        happy_eye_pts_r = happy_face._mirror_points_x(happy_eye_pts_l, cx)
        happy_brow_pts_l = happy_face._rotated_arc_points(
            ex_left - happy_brow_x_off,
            happy_eye_y + happy_brow_y_off + happy_brow_bob + happy_brow_y_shift,
            happy_brow_r,
            happy_face.BROW_ARC_START_PI,
            happy_face.BROW_ARC_END_PI,
            segments=18,
        )
        happy_brow_pts_r = happy_face._mirror_points_x(happy_brow_pts_l, cx)
        happy_lash_pts_l_list: list[list[float]] = []
        for lash_x_frac, lash_y_frac, lash_start, lash_end in happy_face.LASH_SPECS:
            lash_x = ex_left - lash_x_frac * m - happy_lash_vibrate - happy_lash_offset
            happy_lash_pts_l_list.append(
                happy_face._rotated_arc_points(
                    lash_x,
                    happy_eye_y + lash_y_frac * m,
                    happy_lash_r,
                    lash_start,
                    lash_end,
                    segments=12,
                )
            )
        happy_lash_pts_r_list = [happy_face._mirror_points_x(pts, cx) for pts in happy_lash_pts_l_list]

        show_happy_eyes = happy_eye_k > 0.008
        show_happy_brows = happy_brow_k > 0.008
        show_happy_lashes = happy_lash_k > 0.008
        _hide = [0.0, 0.0]
        for side, eye_pts, brow_pts, lash_list in (
            ("l", happy_eye_pts_l, happy_brow_pts_l, happy_lash_pts_l_list),
            ("r", happy_eye_pts_r, happy_brow_pts_r, happy_lash_pts_r_list),
        ):
            ep = eye_pts if show_happy_eyes else _hide
            for line in self._happy_eye_glow[side]:
                line.points = ep
            self._happy_eye_core[side].points = ep

            bp = brow_pts if show_happy_brows else _hide
            for line in self._happy_brow_glow[side]:
                line.points = bp
            self._happy_brow_core[side].points = bp

            for i, lash_pts in enumerate(lash_list):
                lp = lash_pts if show_happy_lashes else _hide
                for line in self._happy_lash_glow[side][i]:
                    line.points = lp
                self._happy_lash_core[side][i].points = lp

        if not in_happy:
            for side in ("l", "r"):
                for line in self._happy_eye_glow[side]:
                    line.points = _hide
                self._happy_eye_core[side].points = _hide
                for line in self._happy_brow_glow[side]:
                    line.points = _hide
                self._happy_brow_core[side].points = _hide
                for i in range(len(self._happy_lash_core[side])):
                    for line in self._happy_lash_glow[side][i]:
                        line.points = _hide
                    self._happy_lash_core[side][i].points = _hide
            for fill_mesh in self._happy_mouth_fill_glow:
                _set_mesh_fan(fill_mesh, [])
            if self._happy_mouth_fill_core is not None:
                _set_mesh_fan(self._happy_mouth_fill_core, [])

        for side, sign in (("l", -1), ("r", 1)):
            ex = cx + sign * eye_dx

            for ell, (_, sm) in zip(self._oval_glow[side], EYE_GLOW_LAYERS):
                glow_r = normal_r * sm * pulse * oval_k
                ell.pos = (ex - glow_r, eye_y - glow_r * blink_scale)
                ell.size = (glow_r * 2, max(0.0, glow_r * 2 * blink_scale))
            core = self._oval_core[side]
            core.pos = (ex - normal_r * oval_k, eye_y - eye_h * oval_k / 2)
            core.size = (max(0.0, normal_r * 2 * oval_k), max(0.0, eye_h * oval_k))

            sad_angle = -sign * 0.34
            angry_angle = sign * 0.34
            if slant_k < 0.01:
                angle = 0.0
            elif self._animating and self._to_expr == "angry" and not self._reverse:
                angle = angry_angle * slant_k
            elif self._animating and self._from_expr == "angry" and self._reverse:
                angle = angry_angle * slant_k
            elif self._settled == "angry" or (self._animating and self._to_expr == "angry"):
                angle = angry_angle * slant_k
            else:
                angle = sad_angle * slant_k

            for fill_mesh, (_, sm) in zip(self._slant_fill_glow[side], SLANT_EYE_FILL_GLOW):
                verts = _slanted_semicircle_fill_verts(
                    ex, eye_y, slant_r, angle, blink_scale, size_mult=sm * pulse
                )
                _set_mesh_fan(fill_mesh, verts if slant_k > 0.01 else [])
            _set_mesh_fan(
                self._slant_fill_core[side],
                _slanted_semicircle_fill_verts(ex, eye_y, slant_r, angle, blink_scale)
                if slant_k > 0.01
                else [],
            )
            slant_pts = _slanted_semicircle_points(ex, eye_y, slant_r, angle, blink_scale)
            pts = slant_pts if slant_k > 0.01 else [0, 0]
            for line in self._slant_line_glow[side]:
                line.points = pts
            self._slant_line_core[side].points = pts

            sad_pts = _sad_brow_points(
                ex,
                eye_y,
                slant_r,
                sad_angle,
                m * 0.118,
                1.2,
                m * 0.2,
                offset_y=brow_bob + sad_brow_lift,
            )
            sp = sad_pts if sad_brow_k > 0.01 else [0, 0]
            for line in self._sad_brow_glow[side]:
                line.points = sp
            self._sad_brow_core[side].points = sp

            angry_pts = _angry_brow_points(
                ex, eye_y, m * 0.209, angry_angle, m * 0.075, angry_bob + angry_brow_lift
            )
            ap = angry_pts if angry_brow_k > 0.01 else [0, 0, 0, 0]
            for line in self._angry_brow_glow[side]:
                line.points = ap
            self._angry_brow_core[side].points = ap

            tear_h = m * 0.078
            tear_w = m * 0.04
            eye_bottom = _eye_bottom_y(ex, eye_y, slant_r, sad_angle if slant_k > 0.5 else angle)
            tear_base = eye_bottom - m * 0.085 - tear_h * 0.5
            tear_slide = (
                m * 0.10 * (1.0 - tear_k)
                if self._animating and not self._reverse and self._to_expr == "sad"
                else 0.0
            )
            tear_fall = (
                m * 0.38 * (1.0 - tear_k) ** 1.4
                if self._animating and self._reverse and self._from_expr == "sad"
                else 0.0
            )
            tear_cy = tear_base + tear_bob - tear_slide - tear_fall
            show_tears = tear_k > 0.02
            tverts = _teardrop_fill_verts(ex, tear_cy, tear_h, tear_w) if show_tears else []
            for fill_mesh, (_, sm) in zip(self._tear_fill_glow[side], TEAR_FILL_GLOW):
                _set_mesh_fan(
                    fill_mesh,
                    _teardrop_fill_verts(ex, tear_cy, tear_h * sm, tear_w * sm) if show_tears else [],
                )
            _set_mesh_fan(self._tear_fill_core[side], tverts)
            tp = _teardrop_points(ex, tear_cy, tear_h, tear_w) if show_tears else [0, 0]
            for line in self._tear_line_glow[side]:
                line.points = tp
            self._tear_line_core[side].points = tp

        ex_x = cx + eye_dx + m * 0.16
        ex_top_rest = eye_y + m * 0.022 + ex_bob
        ex_bottom_rest = eye_y - m * 0.121 + ex_bob
        ex_slant = m * 0.0132
        ex_drop = (
            m * 0.14 * (1.0 - ex_k)
            if self._animating and not self._reverse and self._to_expr == "angry"
            else 0.0
        )
        ex_fall = (
            m * 0.24 * (1.0 - ex_k) ** 1.2
            if self._animating and self._reverse and self._from_expr == "angry"
            else 0.0
        )
        ex_top = ex_top_rest + ex_drop - ex_fall
        ex_bottom = ex_bottom_rest + ex_drop - ex_fall
        show_ex = ex_k > 0.02
        _off = (-9999.0, -9999.0, -9999.0, -9998.0)
        ex_bar = (
            [ex_x + ex_slant, ex_top, ex_x - ex_slant, ex_bottom]
            if show_ex
            else _off
        )
        for line in self._exclaim_bar_glow:
            line.points = ex_bar
        if self._exclaim_bar_core is not None:
            self._exclaim_bar_core.points = ex_bar
        dot_r = m * 0.0154 * pulse * ex_k
        dot_cx = ex_x - ex_slant * 1.45
        dot_cy = ex_bottom - m * 0.033
        off = (-9999.0, -9999.0)
        if show_ex:
            for ell in self._exclaim_dot_glow:
                gr = dot_r * 1.8
                ell.pos = (dot_cx - gr, dot_cy - gr)
                ell.size = (gr * 2, gr * 2)
            if self._exclaim_dot_core is not None:
                self._exclaim_dot_core.pos = (dot_cx - dot_r, dot_cy - dot_r)
                self._exclaim_dot_core.size = (dot_r * 2, dot_r * 2)
        else:
            for ell in self._exclaim_dot_glow:
                ell.pos = off
                ell.size = (0, 0)
            if self._exclaim_dot_core is not None:
                self._exclaim_dot_core.pos = off
                self._exclaim_dot_core.size = (0, 0)
