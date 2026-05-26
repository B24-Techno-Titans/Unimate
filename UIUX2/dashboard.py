"""Smart Home & Health: study, sensor, and control screens for UniMate Kivy UI."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Rotate, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from mock_state import MockState
from theme import Theme

_ICONS_DIR = Path(__file__).resolve().parent / "icons"
_DEVICE_ICON_FILES = {
    "fan": "fan_mask.png",
    "humidifier": "drop_mask.png",
    "led": "sun_mask.png",
}
_icon_texture_cache: dict[str, object] = {}
_sensor_icon_cache: dict[str, object] = {}

# Sensors dashboard — sized for 1024×600 kiosk
SENSOR_PAD = dp(14)
SENSOR_HEADER_H = dp(52)
SENSOR_FOOTER_H = dp(36)
SENSOR_GRID_GAP = dp(10)
SENSOR_CARD_H = dp(160)
SENSOR_ICON = dp(84)
SENSOR_ICON_SLOT = dp(112)
# Typography aligned with Controls tab (CONTROL_* / Theme.TITLE)
SENSOR_STATUS = sp(12)


def _device_icon_texture(kind: str):
    if kind not in _icon_texture_cache:
        fname = _DEVICE_ICON_FILES[kind]
        path = _ICONS_DIR / fname
        if not path.is_file():
            raise FileNotFoundError(f"Device icon not found: {path}")
        _icon_texture_cache[kind] = CoreImage(str(path)).texture
    return _icon_texture_cache[kind]


def _sensor_icon_texture(filename: str):
    if filename not in _sensor_icon_cache:
        path = _ICONS_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Sensor icon not found: {path}")
        _sensor_icon_cache[filename] = CoreImage(str(path)).texture
    return _sensor_icon_cache[filename]


# Controls grid — sized for 1024×600 windowed / fullscreen kiosk
CONTROL_CARD_H = dp(248)
CONTROL_ICON = dp(112)
CONTROL_ICON_SLOT = dp(148)
CONTROL_SMALL_ICON = dp(70)
CONTROL_GRID_GAP = dp(12)
CONTROL_PAD = dp(12)
CONTROL_TITLE = sp(25)
CONTROL_STATUS = sp(17)
SENSOR_CLOCK = sp(22)
CONTROL_BUTTON_TEXT = sp(14)

# Controls device icon animation — per-effect rates (lower = slower)
_FAN_PHASE_L1 = 2.4
_FAN_PHASE_L2 = 4.8
_FAN_ROTATE = 3.6
_HUM_PHASE_L1 = 8.8
_HUM_PHASE_L2 = 16.0
_HUM_PULSE = 0.95
_HUM_RISE_L1 = 13.5
_HUM_RISE_L2 = 21.0
_LED_PHASE_BASE = 0.6
_LED_PHASE_BRIGHT = 0.9
_LED_ROTATE_BASE = 0.14
_LED_ROTATE_BRIGHT = 0.32
_LED_OFF_EPS = 0.02
# Touch panels often deliver touch + emulated mouse as duplicate on_press events.
_LED_TOGGLE_DEBOUNCE_S = 0.35


def _led_effective_on(state: MockState) -> bool:
    """Light is visibly on (button label, status copy, icons)."""
    return state.led_on and state.led_brightness > _LED_OFF_EPS


def _led_slider_locked(state: MockState) -> bool:
    """OFF via power button — brightness stored, slider not draggable."""
    return not state.led_on and state.led_brightness > _LED_OFF_EPS


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
    """h in [0, 1], s/v in [0, 1]."""
    if s <= 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    return v, p, q


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        int(_clamp_byte(r)),
        int(_clamp_byte(g)),
        int(_clamp_byte(b)),
    )


def _clamp_byte(c: float) -> int:
    return max(0, min(255, int(round(c * 255))))


def _rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if d < 1e-6:
        return 0.0, 0.0, mx
    s = d / mx
    if mx == r:
        h = (g - b) / d % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h / 6.0, s, mx


def _build_hsv_wheel_texture(size: int) -> Texture:
    """Smooth HSV disk: hue on angle, saturation from center to edge (Kivy bottom-up rows)."""
    size = max(64, min(384, int(size)))
    half = size / 2.0
    buf = bytearray(size * size * 4)
    idx = 0
    for ty in range(size):
        for tx in range(size):
            dx = (tx + 0.5 - half) / half
            dy = (ty + 0.5 - half) / half
            dist = math.hypot(dx, dy)
            if dist > 1.05:
                buf[idx : idx + 4] = (0, 0, 0, 0)
            else:
                angle = math.atan2(dy, dx)
                hue = (math.degrees(angle) + 360.0) % 360.0 / 360.0
                sat = min(1.0, dist)
                r, g, b = _hsv_to_rgb(hue, sat, 1.0)
                alpha = 255
                if dist > 1.0:
                    alpha = int(255 * (1.05 - dist) / 0.05)
                buf[idx] = _clamp_byte(r)
                buf[idx + 1] = _clamp_byte(g)
                buf[idx + 2] = _clamp_byte(b)
                buf[idx + 3] = alpha
            idx += 4
    tex = Texture.create(size=(size, size), colorfmt="rgba")
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    return tex


# ---------------------------------------------------------------------------
# Study bank (same ideas as legacy Tkinter kiosk)
# ---------------------------------------------------------------------------

STUDY_MCQ: list[dict[str, object]] = [
    {
        "q": "What gas do plants take in for photosynthesis?",
        "options": ["Oxygen", "Carbon dioxide", "Nitrogen", "Hydrogen"],
        "correct": 1,
        "explain": "Plants use CO₂ with light to make sugars and release O₂.",
    },
    {
        "q": "Newton's first law is about…",
        "options": ["Gravity", "Inertia", "Friction", "Mass × acceleration"],
        "correct": 1,
        "explain": "An object stays at rest or in uniform motion unless a net force acts.",
    },
    {
        "q": "In Python, what starts a function definition?",
        "options": ["func", "def", "function", "fn"],
        "correct": 1,
        "explain": "Use def name(args): to define a function.",
    },
]


# ---------------------------------------------------------------------------
# Themed widgets
# ---------------------------------------------------------------------------


def make_button(
    text: str,
    on_press: Callable[..., None],
    *,
    accent: bool = False,
    width: float = dp(190),
    height: float = dp(44),
) -> Button:
    bg = Theme.CYAN if accent else Theme.PANEL_HI
    fg = Theme.BLACK if accent else Theme.TEXT
    btn = Button(
        text=text,
        size_hint=(None, None),
        width=width,
        height=height,
        bold=True,
        font_size=Theme.CAPTION,
        color=fg,
        background_normal="",
        background_down="",
        background_color=bg,
    )
    btn.bind(on_press=lambda *_: on_press())
    return btn


class GlowPanel(BoxLayout):
    """Dark glass card with violet neon frame glow + cyan hairline."""

    def __init__(self, *, fill=None, **kwargs):
        self.padding = kwargs.pop("padding", Theme.PAD)
        self.spacing = kwargs.pop("spacing", Theme.GAP)
        super().__init__(**kwargs)
        self._fill = fill or Theme.PANEL
        self._glow_lines: list[Line] = []
        with self.canvas.before:
            self._fill_color = Color(*self._fill)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=Theme.RADIUS)
            for alpha, width_mult in Theme.CARD_GLOW_LAYERS:
                Color(Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
                ln = Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS),
                    width=dp(2.2) * width_mult,
                    cap="round",
                )
                self._glow_lines.append(ln)
            self._border_accent = Color(*Theme.BORDER_CYAN_SOFT)
            self._hairline = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS),
                width=dp(1.15),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        rr = (self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS)
        for ln in self._glow_lines:
            ln.rounded_rectangle = rr
        self._hairline.rounded_rectangle = rr


class StatCard(GlowPanel):
    def __init__(self, title: str, accent, *, pulse: bool = False, **kwargs):
        super().__init__(orientation="vertical", padding=dp(14), spacing=dp(6), **kwargs)
        self.accent = accent
        self._pulse = pulse
        self._pulse_phase = random.uniform(0, math.tau)
        self._pulse_ev = None
        self.title = Label(
            text=title.upper(),
            size_hint_y=None,
            height=dp(20),
            font_size=Theme.CAPTION,
            bold=True,
            color=Theme.MUTED,
            halign="left",
        )
        self.value = Label(
            text="--",
            size_hint_y=None,
            height=dp(40),
            font_size=Theme.STAT,
            bold=True,
            color=accent,
            halign="left",
        )
        self.sub = Label(text="", font_size=Theme.CAPTION, color=Theme.MUTED, halign="left")
        for lab in (self.title, self.value, self.sub):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            self.add_widget(lab)
        if self._pulse:
            self._pulse_ev = Clock.schedule_interval(self._pulse_tick, 1 / 22.0)

    def set_value(self, value: str, sub: str) -> None:
        self.value.text = value
        self.sub.text = sub

    def _pulse_tick(self, dt: float) -> None:
        self._pulse_phase += dt * 2.4
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse_phase))
        self.value.color = (self.accent[0], self.accent[1], self.accent[2], pulse)


class DeviceViz(Widget):
    """PNG device icons from UIUX2/icons with level-based animation."""

    def __init__(self, kind: str, state: MockState, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.state = state
        self.phase = 0.0
        self._texture = _device_icon_texture(kind)
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_interval(self._tick, 1 / 30)

    def _tick(self, dt: float) -> None:
        if self.kind == "fan":
            if self.state.fan_level > 0:
                spd = _FAN_PHASE_L1 if self.state.fan_level == 1 else _FAN_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "humidifier":
            if self.state.humidifier_level > 0:
                spd = _HUM_PHASE_L1 if self.state.humidifier_level == 1 else _HUM_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "led" and self.state.led_on and self.state.led_brightness > 0:
            br = self.state.led_brightness
            self.phase = (self.phase + dt * (_LED_PHASE_BASE + _LED_PHASE_BRIGHT * br)) % 10
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
            rotate_deg = math.degrees(self.phase * _FAN_ROTATE) if active else 0.0
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
            pulse = 0.85 + 0.15 * math.sin(self.phase * _HUM_PULSE) if lvl > 0 else 1.0
            bubbles = 3 if lvl == 1 else (5 if lvl == 2 else 0)
            rise_mul = _HUM_RISE_L1 if lvl == 1 else (_HUM_RISE_L2 if lvl == 2 else 0)
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
                math.degrees(self.phase * (_LED_ROTATE_BASE + _LED_ROTATE_BRIGHT * br)) if br > 0 else 0.0
            )
            with self.canvas:
                Color(lc[0], lc[1], lc[2], glow_a)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(lc[0], lc[1], lc[2], alpha)
                PushMatrix()
                Rotate(angle=rotate_deg, origin=(cx, cy))
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                PopMatrix()


class IconSlot(AnchorLayout):
    """Keeps fixed-size animated icons centered like the reference cards."""

    def __init__(self, kind: str, state: MockState, *, icon_size=CONTROL_ICON, width=CONTROL_ICON_SLOT, **kwargs):
        super().__init__(
            anchor_x="center",
            anchor_y="center",
            size_hint=(None, 1),
            width=width,
            **kwargs,
        )
        self.viz = DeviceViz(kind, state, size_hint=(None, None), size=(icon_size, icon_size))
        self.add_widget(self.viz)


class SegmentedLevelControl(BoxLayout):
    """OFF / 1 / 2 pill segmented control."""

    def __init__(self, on_select: Callable[[int], None], **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(2), size_hint_y=None, height=dp(48), **kwargs)
        self._on_select = on_select
        self._buttons: list[Button] = []
        for label in ("OFF", "1", "2"):
            btn = Button(
                text=label,
                font_size=CONTROL_BUTTON_TEXT,
                bold=True,
                background_normal="",
                background_color=Theme.PANEL_HI,
                color=Theme.MUTED,
            )
            btn.bind(on_press=lambda _b, lv=label: self._pick(lv))
            self._buttons.append(btn)
            self.add_widget(btn)

    def _pick(self, label: str) -> None:
        level = 0 if label == "OFF" else int(label)
        self._on_select(level)

    def set_level(self, level: int) -> None:
        for i, btn in enumerate(self._buttons):
            active = (level == 0 and i == 0) or (level == i and i > 0)
            if active:
                btn.background_color = Theme.CYAN
                btn.color = Theme.BLACK
            else:
                btn.background_color = Theme.PANEL_HI
                btn.color = Theme.MUTED if i == 0 and level != 0 else Theme.TEXT


class ColorWheel(Widget):
    """HSV color wheel — smooth texture disk, touch to pick custom light color."""

    def __init__(self, state: MockState, on_change: Callable[[], None] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.on_change = on_change
        self._wheel_tex: Texture | None = None
        self._wheel_tex_px = 0
        self.bind(pos=self._redraw, size=self._redraw)

    def _wheel_radius(self) -> float:
        return min(self.width, self.height) * 0.44

    def _wheel_texture(self, diameter: float) -> Texture:
        px = max(96, min(384, int(diameter)))
        if self._wheel_tex is None or self._wheel_tex_px != px:
            self._wheel_tex = _build_hsv_wheel_texture(px)
            self._wheel_tex_px = px
        return self._wheel_tex

    def _pick_at(self, x: float, y: float) -> bool:
        cx, cy = self.center
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        r = self._wheel_radius()
        if dist < dp(8) or dist > r:
            return False
        angle = math.atan2(dy, dx)
        hue = (math.degrees(angle) + 360.0) % 360.0 / 360.0
        sat = min(1.0, dist / r)
        rgb = _hsv_to_rgb(hue, sat, 1.0)
        self.state.set_led_color(rgb)
        if self.on_change:
            self.on_change()
        self._redraw()
        return True

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self._pick_at(touch.x, touch.y):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._pick_at(touch.x, touch.y)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 20 or self.height < 20:
            return
        cx, cy = self.center
        r = self._wheel_radius()
        diameter = r * 2.0
        tex = self._wheel_texture(diameter)
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(
                texture=tex,
                pos=(cx - r, cy - r),
                size=(diameter, diameter),
            )
            Color(*Theme.BORDER_DIM)
            Line(circle=(cx, cy, r), width=dp(1.2))

        h, s, _v = _rgb_to_hsv(*self.state.led_color)
        ang = h * 2 * math.pi
        sr = s * r
        sx = cx + math.cos(ang) * sr
        sy = cy + math.sin(ang) * sr
        with self.canvas:
            Color(*self.state.led_color, 0.35)
            Line(circle=(sx, sy, dp(14)), width=dp(3))
            Color(1, 1, 1, 0.9)
            Line(circle=(sx, sy, dp(9)), width=dp(1.5))


class LevelDeviceCard(GlowPanel):
    """Fan / humidifier card — icon, title, status, segmented levels."""

    def __init__(
        self,
        title: str,
        kind: str,
        state: MockState,
        *,
        speed_label: str,
        output_label: str,
        **kwargs,
    ):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", CONTROL_CARD_H)
        super().__init__(orientation="horizontal", padding=(dp(18), dp(14)), spacing=dp(14), **kwargs)
        self.kind = kind
        self.state = state
        self._speed_label = speed_label
        self._output_label = output_label

        icon_slot = IconSlot(kind, state)
        text_col = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_x=1,
            padding=(0, dp(24), dp(8), dp(10)),
        )
        self.title_label = Label(
            text=title,
            font_size=CONTROL_TITLE,
            bold=True,
            color=Theme.TEXT,
            halign="left",
            size_hint_y=None,
            height=dp(34),
        )
        self.status = Label(
            text="",
            font_size=CONTROL_STATUS,
            color=Theme.MUTED,
            halign="left",
            size_hint_y=None,
            height=dp(30),
        )
        for lab in (self.title_label, self.status):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            text_col.add_widget(lab)
        text_col.add_widget(Widget())
        self.segment = SegmentedLevelControl(on_select=self._set_level, size_hint_x=None, width=dp(240))
        text_col.add_widget(self.segment)

        self.add_widget(icon_slot)
        self.add_widget(text_col)
        self.refresh()

    def _set_level(self, level: int) -> None:
        if self.kind == "fan":
            self.state.set_fan_level(level)
        else:
            self.state.set_humidifier_level(level)
        self.refresh()
        cb = getattr(self, "_refresh_peers", None)
        if cb:
            cb()

    def refresh(self) -> None:
        lv = self.state.fan_level if self.kind == "fan" else self.state.humidifier_level
        if self.kind == "fan":
            label = self._speed_label
        else:
            label = self._output_label
        self.status.text = f"{label}: Level {lv}" if lv else f"{label}: OFF"
        self.segment.set_level(lv)


class LightBasicCard(GlowPanel):
    """Ambient light — icon, OFF toggle, brightness summary."""

    def __init__(self, state: MockState, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", CONTROL_CARD_H)
        super().__init__(orientation="horizontal", padding=(dp(18), dp(14)), spacing=dp(14), **kwargs)
        self.state = state

        icon_slot = IconSlot("led", state, icon_size=dp(96))
        text_col = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_x=1,
            padding=(0, dp(28), dp(8), dp(12)),
        )
        self.title_label = Label(
            text="Ambient Light",
            font_size=CONTROL_TITLE,
            bold=True,
            color=Theme.TEXT,
            halign="left",
            size_hint_y=None,
            height=dp(34),
        )
        self.status = Label(
            text="",
            font_size=CONTROL_STATUS,
            color=Theme.MUTED,
            halign="left",
            size_hint_y=None,
            height=dp(30),
        )
        for lab in (self.title_label, self.status):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            text_col.add_widget(lab)
        text_col.add_widget(Widget())
        bottom = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(18))
        self._led_btn = Button(
            text="OFF",
            size_hint=(None, None),
            size=(dp(124), dp(46)),
            bold=True,
            font_size=CONTROL_BUTTON_TEXT,
            background_normal="",
            background_color=Theme.OFF,
            color=Theme.MUTED,
        )
        self._led_toggle_ev = None
        self._last_led_toggle_at = -1.0
        self._led_btn.bind(on_press=self._on_led_press)
        bottom.add_widget(self._led_btn)
        bottom.add_widget(Label(text="Bright", font_size=CONTROL_STATUS, color=Theme.MUTED, halign="left"))
        text_col.add_widget(bottom)

        self.add_widget(icon_slot)
        self.add_widget(text_col)
        self.refresh()

    def _on_led_press(self, *_args) -> None:
        """Coalesce duplicate touch+mouse presses into one toggle."""
        if self._led_toggle_ev is not None:
            return
        now = Clock.get_time()
        if now - self._last_led_toggle_at < _LED_TOGGLE_DEBOUNCE_S:
            return
        self._led_toggle_ev = Clock.schedule_once(self._run_led_toggle, 0)

    def _run_led_toggle(self, _dt: float) -> None:
        self._led_toggle_ev = None
        self._last_led_toggle_at = Clock.get_time()
        self._toggle()

    def _toggle(self) -> None:
        if _led_effective_on(self.state):
            self.state.set_led(on=False)
        else:
            if self.state.led_brightness <= _LED_OFF_EPS:
                self.state.set_led(on=True, brightness=0.65)
            else:
                self.state.set_led(on=True)
        self.refresh()
        cb = getattr(self, "_refresh_peers", None)
        if cb:
            cb()

    def refresh(self) -> None:
        on = _led_effective_on(self.state)
        pct = int(round(self.state.led_brightness * 100))
        self._led_btn.text = "ON" if on else "OFF"
        self._led_btn.background_color = Theme.CYAN if on else Theme.OFF
        self._led_btn.color = Theme.BLACK if on else Theme.MUTED
        off_note = " (Currently OFF)" if not on else ""
        self.status.text = f"Brightness: {pct}%{off_note}"


class LightColorCard(GlowPanel):
    """Ambient light — intensity slider, color wheel, hex swatch."""

    def __init__(self, state: MockState, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", CONTROL_CARD_H)
        super().__init__(orientation="horizontal", padding=(dp(16), dp(12)), spacing=dp(10), **kwargs)
        self.state = state

        left = BoxLayout(orientation="vertical", size_hint_x=0.58, spacing=dp(8))
        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(74), spacing=dp(10))
        icon_slot = IconSlot("led", state, icon_size=CONTROL_SMALL_ICON, width=dp(82))
        info = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_x=1, padding=(0, dp(8), 0, 0))
        self.title_label = Label(
            text="Ambient Light",
            font_size=CONTROL_TITLE,
            bold=True,
            color=Theme.TEXT,
            halign="left",
            size_hint_y=None,
            height=dp(32),
        )
        self.status = Label(
            text="",
            font_size=CONTROL_STATUS,
            color=Theme.MUTED,
            halign="left",
            size_hint_y=None,
            height=dp(26),
        )
        info.add_widget(self.title_label)
        info.add_widget(self.status)
        top.add_widget(icon_slot)
        top.add_widget(info)

        slider_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54), spacing=dp(8))
        slider_row.add_widget(Label(text="0%", font_size=sp(13), color=Theme.MUTED, size_hint_x=None, width=dp(34)))
        self.slider = Slider(min=0.0, max=1.0, value=state.led_brightness, size_hint_x=1)
        self.slider.cursor_size = (dp(30), dp(30))
        self.slider.bind(value=self._on_brightness)
        slider_row.add_widget(self.slider)
        slider_row.add_widget(Label(text="100%", font_size=sp(13), color=Theme.MUTED, size_hint_x=None, width=dp(46)))

        meta = BoxLayout(orientation="vertical", size_hint_y=1, spacing=dp(8), padding=(dp(84), 0, 0, 0))
        meta.add_widget(Label(text="Select Color", font_size=sp(14), color=Theme.MUTED, size_hint_y=None, height=dp(22), halign="left"))
        swatch_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        self._swatch = Widget(size_hint=(None, None), size=(dp(32), dp(32)))
        self._hex_lbl = Label(text="", font_size=sp(14), bold=True, color=Theme.ACCENT_SOFT, halign="left")
        swatch_row.add_widget(self._swatch)
        swatch_row.add_widget(self._hex_lbl)
        meta.add_widget(swatch_row)
        meta.add_widget(Widget())

        wheel_holder = AnchorLayout(anchor_x="center", anchor_y="center", size_hint_x=0.42)
        self.wheel = ColorWheel(state, on_change=self.refresh, size_hint=(None, None), size=(dp(164), dp(164)))
        wheel_holder.add_widget(self.wheel)

        left.add_widget(top)
        left.add_widget(slider_row)
        left.add_widget(meta)

        self.add_widget(left)
        self.add_widget(wheel_holder)
        self._bind_swatch()
        self.refresh()

    def _bind_swatch(self) -> None:
        def _sync_swatch(*_a):
            self._swatch.canvas.clear()
            with self._swatch.canvas:
                Color(*self.state.led_color)
                RoundedRectangle(pos=self._swatch.pos, size=self._swatch.size, radius=[dp(6)])

        self._swatch.bind(pos=_sync_swatch, size=_sync_swatch)
        _sync_swatch()

    def _on_brightness(self, _inst, value: float) -> None:
        if self.slider.disabled:
            return
        v = float(value)
        self.state.set_led(brightness=v)
        if v > _LED_OFF_EPS and not self.state.led_on:
            self.state.set_led(on=True)
        elif v <= _LED_OFF_EPS and self.state.led_on:
            self.state.set_led(on=False)
        self.refresh()
        cb = getattr(self, "_refresh_peers", None)
        if cb:
            cb()

    def refresh(self) -> None:
        pct = int(round(self.state.led_brightness * 100))
        on = _led_effective_on(self.state)
        off_note = " (Currently OFF)" if not on else ""
        self.status.text = f"Intensity: {pct}%{off_note}"
        self.slider.disabled = _led_slider_locked(self.state)
        self.slider.unbind(value=self._on_brightness)
        self.slider.value = self.state.led_brightness
        self.slider.bind(value=self._on_brightness)
        self._hex_lbl.text = _rgb_to_hex(*self.state.led_color)
        self.wheel._redraw()
        if hasattr(self, "_swatch"):
            self._swatch.canvas.clear()
            with self._swatch.canvas:
                Color(*self.state.led_color)
                RoundedRectangle(pos=self._swatch.pos, size=self._swatch.size, radius=[dp(6)])


# ---------------------------------------------------------------------------
# Sensors dashboard
# ---------------------------------------------------------------------------


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


class SensorIcon(Widget):
    """Sensor card icon from UIUX2/icons."""

    def __init__(self, icon_file: str, tint, **kwargs):
        super().__init__(**kwargs)
        self._texture = _sensor_icon_texture(icon_file)
        self.tint = tint
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 4 or self.height < 4:
            return
        badge_side = min(self.width, self.height)
        badge_x = self.center_x - badge_side / 2
        badge_y = self.center_y - badge_side / 2
        side = badge_side * 0.72
        ix = self.center_x - side / 2
        iy = self.center_y - side / 2
        with self.canvas:
            Color(self.tint[0], self.tint[1], self.tint[2], 0.18)
            Ellipse(
                pos=(badge_x - badge_side * 0.08, badge_y - badge_side * 0.08),
                size=(badge_side * 1.16, badge_side * 1.16),
            )
            Color(0.86, 0.93, 1.0, 0.96)
            RoundedRectangle(
                pos=(badge_x, badge_y),
                size=(badge_side, badge_side),
                radius=[badge_side * 0.28],
            )
            Color(self.tint[0], self.tint[1], self.tint[2], 0.68)
            Line(
                rounded_rectangle=(badge_x, badge_y, badge_side, badge_side, badge_side * 0.28),
                width=dp(1.6),
            )
            Color(self.tint[0], self.tint[1], self.tint[2], 1)
            Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))


class SensorDashboardCard(GlowPanel):
    """Neon sensor tile — icon left, title / value / subtitle right."""

    def __init__(self, title: str, icon_file: str, accent, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", SENSOR_CARD_H)
        super().__init__(
            orientation="horizontal",
            padding=(dp(12), dp(10)),
            spacing=dp(8),
            **kwargs,
        )
        self.accent = accent

        icon_holder = AnchorLayout(
            anchor_x="center",
            anchor_y="center",
            size_hint=(None, 1),
            width=SENSOR_ICON_SLOT,
        )
        icon_holder.add_widget(
            SensorIcon(icon_file, accent, size_hint=(None, None), size=(SENSOR_ICON, SENSOR_ICON))
        )

        text_col = BoxLayout(
            orientation="vertical",
            spacing=dp(2),
            size_hint_x=1,
            padding=(0, dp(6), dp(4), 0),
        )
        self.title_label = Label(
            text=title,
            font_size=CONTROL_TITLE,
            bold=True,
            color=Theme.TEXT,
            halign="left",
            valign="bottom",
            size_hint_y=None,
            height=dp(34),
        )
        self.value_label = Label(
            text="--",
            font_size=Theme.STAT,
            bold=True,
            color=accent,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(44),
        )
        self.sub_label = Label(
            text="",
            font_size=CONTROL_STATUS,
            color=Theme.MUTED,
            halign="left",
            valign="top",
            size_hint_y=1,
        )
        for lab in (self.title_label, self.value_label, self.sub_label):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            text_col.add_widget(lab)

        self.add_widget(icon_holder)
        self.add_widget(text_col)

    def set_value(self, value: str, subtitle: str) -> None:
        self.value_label.text = value
        self.sub_label.text = subtitle


def _status_footer_label(prefix: str, status: str) -> Label:
    full = f"{prefix} [color=00ff00]{status}[/color]"
    lbl = Label(
        text=full,
        markup=True,
        font_size=SENSOR_STATUS,
        color=Theme.MUTED,
        halign="center",
        valign="middle",
    )
    lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    return lbl


# ---------------------------------------------------------------------------
# Refs + builders
# ---------------------------------------------------------------------------


@dataclass
class SensorsRefs:
    temp: SensorDashboardCard
    humidity: SensorDashboardCard
    lux: SensorDashboardCard
    heart: SensorDashboardCard
    body_temp: SensorDashboardCard
    spo2: SensorDashboardCard


def build_study_screen() -> Screen:
    screen = Screen(name="study")
    root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)

    def sync_root_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size

    root.bind(pos=sync_root_bg, size=sync_root_bg)

    header = Label(
        text="Study",
        font_size=Theme.TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        size_hint_y=None,
        height=dp(40),
        halign="left",
    )
    header.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    root.add_widget(header)

    card = GlowPanel(orientation="vertical", padding=dp(16), spacing=dp(12), size_hint_y=1)
    q_label = Label(text="", font_size=Theme.BODY, color=Theme.TEXT, halign="left", valign="top")
    q_label.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width - dp(8), None)))

    feedback = Label(text="", font_size=Theme.CAPTION, color=Theme.MUTED, halign="left")
    feedback.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))

    grid = GridLayout(cols=1, spacing=dp(8), size_hint_y=None)
    grid.bind(minimum_height=grid.setter("height"))
    option_buttons: list[Button] = []

    class StudyCtrl:
        idx = 0
        selected: int | None = None

    ctrl = StudyCtrl()

    def load_item():
        ctrl.selected = None
        item = STUDY_MCQ[ctrl.idx % len(STUDY_MCQ)]
        q_label.text = str(item["q"])
        opts = list(item["options"])
        feedback.text = ""
        grid.clear_widgets()
        option_buttons.clear()
        for i, opt in enumerate(opts):
            btn = Button(
                text=opt,
                size_hint_y=None,
                height=dp(44),
                background_normal="",
                background_color=Theme.PANEL_HI,
                color=Theme.TEXT,
                font_size=Theme.CAPTION,
            )

            def mk_handler(ii: int):
                def _pick(*_a):
                    ctrl.selected = ii
                    for j, b in enumerate(option_buttons):
                        b.background_color = Theme.CYAN if j == ii else Theme.PANEL_HI
                        b.color = Theme.BLACK if j == ii else Theme.TEXT

                return _pick

            btn.bind(on_press=mk_handler(i))
            grid.add_widget(btn)
            option_buttons.append(btn)

    def check_answer(*_):
        item = STUDY_MCQ[ctrl.idx % len(STUDY_MCQ)]
        cor = int(item["correct"])
        if ctrl.selected is None:
            feedback.text = "Pick an answer first."
            feedback.color = Theme.WARN
            return
        if ctrl.selected == cor:
            feedback.text = "Correct — " + str(item["explain"])
            feedback.color = Theme.OK
        else:
            feedback.text = "Not quite — " + str(item["explain"])
            feedback.color = Theme.DANGER

    def next_q(*_):
        ctrl.idx += 1
        load_item()

    card.add_widget(q_label)
    card.add_widget(feedback)
    scroll_opts = ScrollView(do_scroll_x=False, size_hint_y=1, bar_width=dp(4))
    scroll_opts.add_widget(grid)
    card.add_widget(scroll_opts)

    actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
    actions.add_widget(make_button("Check", check_answer, accent=False, width=dp(120)))
    actions.add_widget(make_button("Next", next_q, accent=True, width=dp(120)))
    card.add_widget(actions)

    root.add_widget(card)

    load_item()
    screen.add_widget(root)
    return screen


def build_sensors_screen(state: MockState) -> tuple[Screen, SensorsRefs]:
    screen = Screen(name="sensors")
    root = FloatLayout()

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)

    def sync_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size

    root.bind(pos=sync_bg, size=sync_bg)

    backdrop = CircuitBackdrop(size_hint=(1, 1))
    root.add_widget(backdrop)

    content = BoxLayout(
        orientation="vertical",
        spacing=dp(8),
        size_hint=(1, 1),
        pos_hint={"x": 0, "y": 0},
        padding=SENSOR_PAD,
    )

    header = GridLayout(cols=3, size_hint_y=None, height=SENSOR_HEADER_H, spacing=dp(4))
    title = Label(
        text="SENSOR DASHBOARD",
        font_size=Theme.TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        halign="center",
        valign="middle",
    )
    title.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    clock_lbl = Label(
        text="",
        font_size=SENSOR_CLOCK,
        color=Theme.TEXT,
        halign="right",
        valign="middle",
    )
    clock_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    header.add_widget(Widget())
    header.add_widget(title)
    header.add_widget(clock_lbl)

    def _update_clock(_dt: float = 0) -> None:
        now = datetime.now()
        clock_lbl.text = now.strftime("%H:%M | %b %d, %Y").upper()

    _update_clock()
    Clock.schedule_interval(_update_clock, 30.0)

    grid = GridLayout(cols=2, spacing=SENSOR_GRID_GAP, size_hint_y=1)
    grid.row_force_default = True
    grid.row_default_height = SENSOR_CARD_H

    temp = SensorDashboardCard(
        "Room Temperature",
        "thermometer.png",
        Theme.ACCENT_SOFT,
    )
    humidity = SensorDashboardCard(
        "Humidity",
        "humidity.png",
        Theme.OK,
    )
    lux = SensorDashboardCard(
        "Ambient Light",
        "sun.png",
        Theme.WARN,
    )
    heart = SensorDashboardCard(
        "User Heart Rate",
        "heart-rate.png",
        Theme.DANGER,
    )
    body_temp = SensorDashboardCard(
        "User Body Temp",
        "temperature.png",
        Theme.TEXT,
    )
    spo2 = SensorDashboardCard(
        "Blood Oxygen",
        "oxygen.png",
        Theme.DANGER,
    )
    for card in (temp, humidity, lux, heart, body_temp, spo2):
        grid.add_widget(card)

    content.add_widget(header)
    content.add_widget(grid)
    root.add_widget(content)

    # Initial values from mock state
    temp.set_value(f"{state.room_temp_c:.1f} °C", "Avg. Main Room")
    humidity.set_value(f"{state.humidity_pct:.0f}%", "Main Room")
    lux.set_value(f"{state.lux:.0f} lx", "Lux Intensity")
    heart.set_value(f"{state.heart_bpm} bpm", "Real-time, Last 5 mins")
    body_temp.set_value(f"{state.body_temp_c:.1f} °C", "Status: Normal")
    spo2.set_value(f"{state.spo2_pct:.0f}%", "Status: Optimal")

    screen.add_widget(root)
    refs = SensorsRefs(
        temp=temp,
        humidity=humidity,
        lux=lux,
        heart=heart,
        body_temp=body_temp,
        spo2=spo2,
    )
    return screen, refs


def build_controls_screen(state: MockState) -> Screen:
    screen = Screen(name="controls")
    root = BoxLayout(orientation="vertical", padding=CONTROL_PAD, spacing=dp(8))

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)

    def sync_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size

    root.bind(pos=sync_bg, size=sync_bg)

    header = Label(
        text="Controls",
        size_hint_y=None,
        height=dp(40),
        font_size=Theme.TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        halign="left",
    )
    header.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))

    grid = GridLayout(cols=2, spacing=CONTROL_GRID_GAP, size_hint_y=1)
    grid.row_force_default = True
    grid.row_default_height = CONTROL_CARD_H

    fan = LevelDeviceCard("Ceiling Fan", "fan", state, speed_label="Speed", output_label="Output")
    hum = LevelDeviceCard("Humidifier", "humidifier", state, speed_label="Speed", output_label="Output")
    light_basic = LightBasicCard(state)
    light_color = LightColorCard(state)

    def _refresh_all() -> None:
        fan.refresh()
        hum.refresh()
        light_basic.refresh()
        light_color.refresh()

    for card in (fan, hum, light_basic, light_color):
        card._refresh_peers = _refresh_all
    light_color.wheel.on_change = _refresh_all

    grid.add_widget(fan)
    grid.add_widget(hum)
    grid.add_widget(light_basic)
    grid.add_widget(light_color)

    root.add_widget(header)
    root.add_widget(grid)
    screen.add_widget(root)
    return screen
