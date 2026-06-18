"""Ask From Bunny popup widget components."""

from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from nlp_functions import format_mmss
from theme import Theme
from widgets.common import (
    STUDY_ASK_DOT_SPACING,
    STUDY_RESPOND_CAPTION_H,
    STUDY_RESPOND_PROGRESS_H,
    study_icon_texture,
)


class AskBunnyIconRow(BoxLayout):
    """Bunny + question icons for the Ask From Bunny popup."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=-dp(400),
            padding=(0, 0),
            **kwargs,
        )
        for icon_file, weight in (("animal.png", 0.54), ("question.png", 0.46)):
            img = Image(
                texture=study_icon_texture(icon_file),
                fit_mode="contain",
                size_hint_x=weight,
            )
            self.add_widget(img)


class RespondBunnyIconRow(BoxLayout):
    """Bunny + response icons for the Responding popup."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=-dp(400),
            padding=(0, 0),
            **kwargs,
        )
        for icon_file, weight in (("animal.png", 0.54), ("response.png", 0.46)):
            img = Image(
                texture=study_icon_texture(icon_file),
                fit_mode="contain",
                size_hint_x=weight,
            )
            self.add_widget(img)


class RespondingCaptionBox(BoxLayout):
    """Inner cyan frame — shows a sliding window of spoken words (combined.py answer)."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=(dp(14), dp(12)),
            size_hint_y=None,
            height=STUDY_RESPOND_CAPTION_H,
            **kwargs,
        )
        self.caption = Label(
            text="",
            font_size=sp(22),
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
        )
        self.caption.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(self.caption)
        with self.canvas.before:
            Color(*Theme.BORDER_CYAN_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(14)),
                width=dp(1.4),
            )
        self.bind(pos=self._sync_border, size=self._sync_border)

    def _sync_border(self, *_args) -> None:
        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(14),
        )


class SpeechProgressRow(BoxLayout):
    """Playback progress bar and elapsed / total timestamps."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=STUDY_RESPOND_PROGRESS_H,
            **kwargs,
        )
        self._track = Widget(size_hint_x=1)
        self._time_lbl = Label(
            text="0:00 / 0:00",
            font_size=sp(14),
            color=Theme.CYAN_DIM,
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(88),
        )
        self._progress = 0.0
        self.add_widget(self._track)
        self.add_widget(self._time_lbl)
        self._track.bind(pos=self._draw, size=self._draw)

    def set_progress(self, elapsed: float, duration: float) -> None:
        duration = max(duration, 0.01)
        self._progress = min(1.0, max(0.0, elapsed / duration))
        self._time_lbl.text = f"{format_mmss(elapsed)} / {format_mmss(duration)}"
        self._draw()

    def _draw(self, *_args) -> None:
        self._track.canvas.clear()
        if self._track.width < 4:
            return
        x, y, w, h = self._track.x, self._track.y, self._track.width, self._track.height
        cy = y + h / 2
        with self._track.canvas:
            Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.2)
            Line(points=[x, cy, x + w, cy], width=dp(2))
            if self._progress > 0:
                Color(*Theme.ACCENT_SOFT)
                Line(points=[x, cy, x + w * self._progress, cy], width=dp(3))


class GlowingDotsRow(Widget):
    """Sequential pulsing cyan dots below the Ask From Bunny title."""

    DOT_COUNT = 4

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._phase = 0.0
        self._pulse_ev = None
        self.bind(pos=self._draw, size=self._draw)

    def on_parent(self, widget, parent):
        if parent is not None and self._pulse_ev is None:
            self._pulse_ev = Clock.schedule_interval(self._tick, 1 / 30.0)
        elif parent is None and self._pulse_ev is not None:
            self._pulse_ev.cancel()
            self._pulse_ev = None

    def _tick(self, dt: float) -> None:
        self._phase += dt * 2.2
        self._draw()

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 4 or self.height < 4:
            return
        # Canvas instructions use parent coordinates (see StudyTileIcon).
        n = self.DOT_COUNT
        spacing = STUDY_ASK_DOT_SPACING * 0.82
        mid = (n - 1) / 2.0
        cx_mid = self.center_x
        cy = self.center_y
        dot_r = min(dp(7), self.height * 0.14)
        glow_r_extra = sp(2)
        for i in range(n):
            cx = cx_mid + (i - mid) * spacing
            cycle = (self._phase - i * 0.42) % n
            pulse = max(0.0, 1.0 - abs(cycle) * 1.5)
            glow_a = 0.015 + 0.16 * pulse
            core_a = 0.12 + 0.42 * pulse
            with self.canvas:
                for mult, alpha in ((2.6, glow_a * 0.3), (1.85, glow_a * 0.55), (1.35, glow_a)):
                    glow_r = dot_r * mult + glow_r_extra
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    Ellipse(
                        pos=(cx - glow_r, cy - glow_r),
                        size=(glow_r * 2, glow_r * 2),
                    )
                Color(Theme.ACCENT_SOFT[0], Theme.ACCENT_SOFT[1], Theme.ACCENT_SOFT[2], core_a)
                Ellipse(pos=(cx - dot_r, cy - dot_r), size=(dot_r * 2, dot_r * 2))

