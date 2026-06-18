"""
Stable happy neon face emotion: violet frame, cyan arc eyes/brows/lashes,
cyan-filled smile mouth.

Symmetry matches sad.py / angry.py: left-side geometry is built once, then
x-coordinates are mirrored across the face centre for the right side (same
curvature on both sides).
"""

from __future__ import annotations

import math
import time

from kivy.clock import Clock
from kivy.graphics import Color, Line, Mesh, Rectangle
from kivy.metrics import dp
from kivy.uix.widget import Widget

from theme import Theme

# ---------------------------------------------------------------------------
# Glow layer presets
# ---------------------------------------------------------------------------

MOUTH_GLOW_LAYERS = [
    (0.07, 3.2),
    (0.14, 2.3),
    (0.26, 1.6),
    (0.45, 1.1),
]

HAPPY_BROW_GLOW_LAYERS = [
    (0.06, 2.6),
    (0.12, 2.0),
    (0.22, 1.5),
]

HAPPY_EYE_GLOW_LAYERS = [
    (0.05, 1.35),
    (0.12, 1.2),
    (0.22, 1.08),
]

HAPPY_LASH_GLOW_LAYERS = [
    (0.05, 1.25),
    (0.12, 1.1),
]

HAPPY_MOUTH_FILL_GLOW_LAYERS = [
    (0.10, 1.04),
    (0.16, 1.07),
]

# ---------------------------------------------------------------------------
# Layout tuning — same style as sad.py / angry.py
# ---------------------------------------------------------------------------

# Eyes
EYE_Y_FRAC = 0.58              # vertical position (× widget height, from bottom)
EYE_DX_FRAC = 0.19             # horizontal distance between eyes (× widget width)
EYE_RADIUS_FRAC = 0.092        # eye arc curvature (× min(w, h))
EYE_ARC_START_PI = 0.0         # visible arc start (× π)
EYE_ARC_END_PI = 1.0           # visible arc end (× π)

# Eyebrows — offsets from each eye centre (ex, eye_y)
BROW_Y_OFFSET_FRAC = 0.055     # how far above eye centre (× min(w, h))
BROW_X_OFFSET_FRAC = 0.025     # shift toward outer edge of face (× min(w, h))
BROW_RADIUS_FRAC = 0.125       # brow arc curvature (× min(w, h))
BROW_ARC_START_PI = 0.35       # visible arc start (× π)
BROW_ARC_END_PI = 0.8         # visible arc end (× π)
BROW_LINE_WIDTH = 3.6         # brow stroke thickness (dp)

# Idle animations (amplitude × min(w,h), sin(phase × speed) — same pattern as sad/angry)
BROW_BOB_AMP_FRAC = 0.014     # eyebrows bob up/down
BROW_BOB_SPEED = 5.4
LASH_VIBRATE_AMP_FRAC = 0.008 # eyelashes shake left/right (outward axis)
LASH_VIBRATE_SPEED = 15.0
MOUTH_BOB_AMP_FRAC = 0.012    # mouth bobs up/down
MOUTH_BOB_SPEED = 6.5

# Eyelashes
LASH_RADIUS_FRAC = 0.082       # default lash arc curvature (× min(w, h))
# Each lash: (x_offset_frac, y_offset_frac, arc_start_pi, arc_end_pi)
#   x_offset_frac — outward from eye centre (× min(w, h); larger = further from eye)
#   y_offset_frac — vertical from eye centre (× min(w, h); + = above, − = below)
LASH_SPECS: tuple[tuple[float, float, float, float], ...] = (
    (0.145, 0.113, 1.2, 1.45),   # top lash
    (0.155, -0.073 , 0.5, 0.85),     # middle lash
    (0.13, -0.103, 0.6, 0.95),  # bottom lash
)

# Mouth (centred on face) — same ratio as sad.py / angry.py: self.y + self.height * MOUTH_Y_FRAC
MOUTH_Y_FRAC = 0.42            # vertical position (× widget height, from bottom; ↑ = nearer eyes)
MOUTH_RADIUS_FRAC = 0.155      # mouth size (× min(w, h))
MOUTH_TOP_SAG_FRAC = 0.012     # slight curve on flat top edge (× min(w, h))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


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
    cx: float,
    cy: float,
    radius: float,
    start: float,
    end: float,
    segments: int = 24,
    *,
    y_scale: float = 1.0,
) -> list[float]:
    points: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        a = start + (end - start) * t
        points.extend([cx + math.cos(a) * radius, cy + math.sin(a) * radius * y_scale])
    return points


def _rotate_point(x: float, y: float, angle: float) -> tuple[float, float]:
    ca = math.cos(angle)
    sa = math.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _mirror_points_x(points: list[float], axis_x: float) -> list[float]:
    """Reflect polyline across a vertical axis (exact left/right symmetry)."""
    mirrored: list[float] = []
    for i in range(0, len(points), 2):
        mirrored.extend([2 * axis_x - points[i], points[i + 1]])
    return mirrored


def _rotated_arc_points(
    cx: float,
    cy: float,
    radius: float,
    start_pi: float,
    end_pi: float,
    angle: float = 0.0,
    *,
    y_scale: float = 1.0,
    segments: int = 24,
) -> list[float]:
    """Arc on a circle, optionally rotated (sad.py uses angle = -sign * tilt)."""
    points: list[float] = []
    start = start_pi * math.pi
    end = end_pi * math.pi
    for i in range(segments + 1):
        t = i / segments
        a = start + (end - start) * t
        lx = math.cos(a) * radius
        ly = math.sin(a) * radius * y_scale
        rx, ry = _rotate_point(lx, ly, angle)
        points.extend([cx + rx, cy + ry])
    return points


def _smile_mouth_fill_verts(
    cx: float,
    cy: float,
    radius: float,
    size_mult: float = 1.0,
    segments: int = 36,
    top_sag: float = 0.0,
) -> list[float]:
    r = radius * size_mult
    verts: list[float] = [cx - r, cy]
    for i in range(segments + 1):
        t = i / segments
        x = cx - r + 2 * r * t
        sag_y = cy - top_sag * 4 * t * (1 - t)
        verts.extend([x, sag_y])
    for i in range(segments + 1):
        t = i / segments
        a = math.pi + t * math.pi
        verts.extend([cx + math.cos(a) * r, cy + math.sin(a) * r])
    verts.extend([cx + r, cy])
    return verts


def _smile_mouth_outline_points(
    cx: float,
    cy: float,
    radius: float,
    segments: int = 36,
    top_sag: float = 0.0,
) -> list[float]:
    left_x = cx - radius
    top_pts: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        x = cx - radius + 2 * radius * t
        y = cy - top_sag * 4 * t * (1 - t)
        top_pts.extend([x, y])
    arc = _circle_arc_points(cx, cy, radius, math.pi, 2 * math.pi, segments)
    return [*top_pts, *arc, left_x, cy]


class RoboHappyWidget(Widget):
    """Neon happy face with blink, glow pulse, brow bob, lash vibrate, and mouth bob."""

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

        self._border_lines: list[Line] = []
        self._bg_rect: Rectangle | None = None
        self._brow_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._brow_core: dict[str, Line] = {}
        self._eye_glow: dict[str, list[Line]] = {"l": [], "r": []}
        self._eye_core: dict[str, Line] = {}
        self._lash_glow: dict[str, list[list[Line]]] = {"l": [], "r": []}
        self._lash_core: dict[str, list[Line]] = {"l": [], "r": []}
        self._mouth_fill_glow: list[Mesh] = []
        self._mouth_fill_core: Mesh | None = None
        self._mouth_glow: list[Line] = []
        self._mouth_core: Line | None = None

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
                for alpha, width_mult in HAPPY_BROW_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._brow_glow[side].append(
                        Line(
                            points=[0, 0],
                            width=dp(BROW_LINE_WIDTH) * width_mult,
                            cap="round",
                            joint="round",
                        )
                    )
                Color(*Theme.CYAN)
                self._brow_core[side] = Line(
                    points=[0, 0],
                    width=dp(BROW_LINE_WIDTH),
                    cap="round",
                    joint="round",
                )

            for side in ("l", "r"):
                for alpha, width_mult in HAPPY_EYE_GLOW_LAYERS:
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    self._eye_glow[side].append(
                        Line(points=[0, 0], width=dp(4.8) * width_mult, cap="round", joint="round")
                    )
                Color(*Theme.CYAN)
                self._eye_core[side] = Line(points=[0, 0], width=dp(4.8), cap="round", joint="round")

                self._lash_glow[side] = []
                self._lash_core[side] = []
                for _ in LASH_SPECS:
                    glow_group: list[Line] = []
                    for alpha, width_mult in HAPPY_LASH_GLOW_LAYERS:
                        Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                        glow_group.append(
                            Line(points=[0, 0], width=dp(3.2) * width_mult, cap="round", joint="round")
                        )
                    self._lash_glow[side].append(glow_group)
                    Color(*Theme.CYAN)
                    self._lash_core[side].append(
                        Line(points=[0, 0], width=dp(3.2), cap="round", joint="round")
                    )

            for alpha, size_mult in HAPPY_MOUTH_FILL_GLOW_LAYERS:
                Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                self._mouth_fill_glow.append(Mesh(mode="triangle_fan"))
            Color(*Theme.CYAN)
            self._mouth_fill_core = Mesh(mode="triangle_fan")

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

    def _tick(self, dt: float) -> None:
        if self._paused:
            return
        self._phase = time.monotonic() - self._t0
        self._glow_pulse = 0.88 + 0.12 * math.sin(self._phase * 2.0)

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
        frame_r = m * 0.11
        pulse = self._glow_pulse

        for line in self._border_lines:
            line.rounded_rectangle = (fx, fy, fw, fh, frame_r)

        cx = self.center_x
        eye_y = self.y + self.height * EYE_Y_FRAC
        eye_dx = self.width * EYE_DX_FRAC
        eye_radius = m * EYE_RADIUS_FRAC
        blink_scale = 1.0 - _ease_in_out_sine(self._blink) * 0.94
        brow_bob = m * BROW_BOB_AMP_FRAC * math.sin(self._phase * BROW_BOB_SPEED)
        lash_vibrate = m * LASH_VIBRATE_AMP_FRAC * math.sin(self._phase * LASH_VIBRATE_SPEED)
        mouth_bob = m * MOUTH_BOB_AMP_FRAC * math.sin(self._phase * MOUTH_BOB_SPEED)

        brow_y_off = m * BROW_Y_OFFSET_FRAC
        brow_x_off = m * BROW_X_OFFSET_FRAC
        brow_radius = m * BROW_RADIUS_FRAC
        lash_radius = m * LASH_RADIUS_FRAC

        # Build left side once, mirror x for right (exact symmetry).
        ex_left = cx - eye_dx

        eye_pts_l = _rotated_arc_points(
            ex_left,
            eye_y,
            eye_radius,
            EYE_ARC_START_PI,
            EYE_ARC_END_PI,
            y_scale=blink_scale,
            segments=30,
        )
        eye_pts_r = _mirror_points_x(eye_pts_l, cx)

        brow_pts_l = _rotated_arc_points(
            ex_left - brow_x_off,
            eye_y + brow_y_off + brow_bob,
            brow_radius,
            BROW_ARC_START_PI,
            BROW_ARC_END_PI,
            segments=18,
        )
        brow_pts_r = _mirror_points_x(brow_pts_l, cx)

        lash_pts_l_list: list[list[float]] = []
        for lash_x_frac, lash_y_frac, lash_start, lash_end in LASH_SPECS:
            lash_pts_l_list.append(
                _rotated_arc_points(
                    ex_left - lash_x_frac * m - lash_vibrate,
                    eye_y + lash_y_frac * m,
                    lash_radius,
                    lash_start,
                    lash_end,
                    segments=12,
                )
            )
        lash_pts_r_list = [_mirror_points_x(pts, cx) for pts in lash_pts_l_list]

        for side, eye_pts, brow_pts, lash_list in (
            ("l", eye_pts_l, brow_pts_l, lash_pts_l_list),
            ("r", eye_pts_r, brow_pts_r, lash_pts_r_list),
        ):
            for line in self._eye_glow[side]:
                line.points = eye_pts
            self._eye_core[side].points = eye_pts

            for line in self._brow_glow[side]:
                line.points = brow_pts
            self._brow_core[side].points = brow_pts

            for i, lash_pts in enumerate(lash_list):
                for line in self._lash_glow[side][i]:
                    line.points = lash_pts
                self._lash_core[side][i].points = lash_pts

        mouth_y = self.y + self.height * MOUTH_Y_FRAC + mouth_bob
        mouth_radius = m * MOUTH_RADIUS_FRAC
        top_sag = m * MOUTH_TOP_SAG_FRAC

        for fill_mesh, (_, size_mult) in zip(self._mouth_fill_glow, HAPPY_MOUTH_FILL_GLOW_LAYERS):
            fill_verts = _smile_mouth_fill_verts(
                cx, mouth_y, mouth_radius, size_mult=size_mult * pulse, top_sag=top_sag
            )
            _set_mesh_fan(fill_mesh, fill_verts)
        if self._mouth_fill_core is not None:
            _set_mesh_fan(
                self._mouth_fill_core,
                _smile_mouth_fill_verts(cx, mouth_y, mouth_radius, top_sag=top_sag),
            )

        mouth_pts = _smile_mouth_outline_points(cx, mouth_y, mouth_radius, top_sag=top_sag)
        for line in self._mouth_glow:
            line.points = mouth_pts
        if self._mouth_core is not None:
            self._mouth_core.points = mouth_pts
