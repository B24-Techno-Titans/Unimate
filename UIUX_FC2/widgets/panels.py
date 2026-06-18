"""Panel and card widgets for UniMate dashboard."""

from __future__ import annotations

import math
import random
import time
from pathlib import Path

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from theme import Theme
from widgets.common import (
    CONTROL_ERROR_PULSE_S,
    CONTROL_STATUS,
    CONTROL_TITLE,
    SENSOR_CARD_H,
    SENSOR_ICON,
    SENSOR_ICON_SLOT,
    sensor_icon_texture,
)

KV_DIR = Path(__file__).resolve().parent.parent / "kv"
Builder.load_file(str(KV_DIR / "panels.kv"))

class GlowPanel(BoxLayout):
    """Dark glass card with violet neon frame glow + cyan hairline."""

    def __init__(self, *, fill=None, **kwargs):
        self.padding = kwargs.pop("padding", Theme.PAD)
        self.spacing = kwargs.pop("spacing", Theme.GAP)
        super().__init__(**kwargs)
        self._fill = fill or Theme.PANEL
        self._glow_lines: list[Line] = []
        self._glow_colors: list[Color] = []
        self._error_pulse_ev = None
        self._error_pulse_start = 0.0
        self._error_pulse_duration = CONTROL_ERROR_PULSE_S
        self._error_pulse_until = 0.0
        with self.canvas.before:
            self._fill_color = Color(*self._fill)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=Theme.RADIUS)
            for alpha, width_mult in Theme.CARD_GLOW_LAYERS:
                glow_color = Color(Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
                self._glow_colors.append(glow_color)
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

    def pulse_control_error(self, duration: float = CONTROL_ERROR_PULSE_S) -> None:
        """Brief red pulse on the whole card when a device control call fails."""
        self._error_pulse_start = time.monotonic()
        self._error_pulse_duration = duration
        self._error_pulse_until = self._error_pulse_start + duration
        if self._error_pulse_ev is None:
            self._error_pulse_ev = Clock.schedule_interval(self._tick_control_error_pulse, 1 / 30.0)

    def _tick_control_error_pulse(self, dt: float) -> None:
        if time.monotonic() >= self._error_pulse_until:
            self._stop_control_error_pulse()
            return
        progress = (time.monotonic() - self._error_pulse_start) / self._error_pulse_duration
        progress = max(0.0, min(1.0, progress))
        pulse = math.sin(progress * math.pi)
        strength = 0.22 + 0.18 * pulse
        dr, dg, db, _ = Theme.DANGER
        br, bg, bb, ba = self._fill
        self._fill_color.rgba = (
            br + (dr - br) * strength,
            bg + (dg - bg) * strength,
            bb + (db - bb) * strength,
            ba,
        )
        vr, vg, vb = Theme.VIOLET[:3]
        for glow_color, (base_alpha, _) in zip(self._glow_colors, Theme.CARD_GLOW_LAYERS):
            blend = 0.45 + 0.35 * pulse
            glow_color.rgba = (
                vr + (dr - vr) * blend,
                vg + (dg - vg) * blend,
                vb + (db - vb) * blend,
                base_alpha * (0.75 + 0.35 * pulse),
            )
        hr, hg, hb, _ = Theme.BORDER_CYAN_SOFT
        self._border_accent.rgba = (
            hr + (dr - hr) * strength,
            hg + (dg - hg) * strength,
            hb + (db - hb) * strength,
            0.28 + 0.22 * pulse,
        )

    def _restore_panel_colors(self) -> None:
        self._fill_color.rgba = self._fill
        for glow_color, (alpha, _) in zip(self._glow_colors, Theme.CARD_GLOW_LAYERS):
            glow_color.rgba = (Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
        self._border_accent.rgba = Theme.BORDER_CYAN_SOFT

    def _stop_control_error_pulse(self) -> None:
        if self._error_pulse_ev is not None:
            self._error_pulse_ev.cancel()
            self._error_pulse_ev = None
        self._restore_panel_colors()



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



class SensorIcon(Widget):
    """Sensor card icon from UIUX2/icons."""

    def __init__(self, icon_file: str, tint, **kwargs):
        super().__init__(**kwargs)
        self._texture = sensor_icon_texture(icon_file)
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

