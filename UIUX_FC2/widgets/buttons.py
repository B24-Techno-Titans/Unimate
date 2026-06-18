"""Themed button widgets for UniMate dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.uix.button import Button

from theme import Theme
from widgets.common import (
    CONTROL_PRESS_DEBOUNCE_S,
    STUDY_MCQ_ANSWER_BORDER_SEL,
    schedule_touch_safe,
)

KV_DIR = Path(__file__).resolve().parent.parent / "kv"
Builder.load_file(str(KV_DIR / "buttons.kv"))

def make_button(
    text: str,
    on_press: Callable[..., None],
    *,
    accent: bool = False,
    width: float = dp(190),
    height: float = dp(44),
) -> Button:
    return GlowFlatButton(
        text,
        on_press,
        accent=accent,
        width=width,
        height=height,
    )


class GlowFlatButton(Button):
    """Themed flat button with cyan glow on press."""

    _RADIUS = dp(12)

    def __init__(
        self,
        text: str,
        on_press: Callable[..., None],
        *,
        accent: bool = False,
        width: float = dp(190),
        height: float = dp(44),
        **kwargs,
    ):
        self._accent = accent
        self._pressed = False
        self._on_press_cb = on_press
        fg = Theme.BLACK if accent else Theme.TEXT
        super().__init__(
            text=text,
            size_hint=(None, None),
            width=width,
            height=height,
            bold=True,
            font_size=Theme.CAPTION,
            color=fg,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*(Theme.CYAN if accent else Theme.PANEL_HI))
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(on_press=self._on_button_press)

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._pressed:
            self._fill_color.rgba = Theme.CYAN if self._accent else Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.CYAN if self._accent else Theme.PANEL_HI
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.2)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._set_pressed(True)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed and not self.collide_point(*touch.pos):
            self._set_pressed(False)
        return result

    def _on_button_press(self, *_args) -> None:
        if self.disabled:
            return
        self._set_pressed(True)

        def _after_glow(_dt: float) -> None:
            self._set_pressed(False)
            schedule_touch_safe(self, self._on_press_cb, debounce_s=CONTROL_PRESS_DEBOUNCE_S)

        Clock.schedule_once(_after_glow, 0.14)


class GlowIconButton(Button):
    """Small icon button (e.g. popup close) with press glow."""

    _RADIUS = dp(10)

    def __init__(self, text: str = "×", **kwargs):
        self._pressed = False
        kwargs.setdefault("font_size", sp(28))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", Theme.ACCENT_SOFT)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(text=text, **kwargs)
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._pressed:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.2)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._set_pressed(True)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed:
            Clock.schedule_once(lambda _dt: self._set_pressed(False), 0.14)
        return result

