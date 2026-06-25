"""MCQ and quiz widget components."""

from __future__ import annotations

import time
import math
from typing import Callable

from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from theme import Theme
from widgets.common import (
    STUDY_MCQ_ANSWER_BORDER,
    STUDY_MCQ_ANSWER_BORDER_SEL,
    STUDY_MCQ_ANSWER_FONT,
    STUDY_MCQ_ANSWER_RADIUS,
    STUDY_MCQ_FILE_LIST_FONT,
    STUDY_MCQ_FILE_ROW_H,
    STUDY_MCQ_FILE_SUB_FONT,
    STUDY_MCQ_NAV_FONT,
    STUDY_MCQ_SCROLL_SLOP,
    schedule_touch_safe,
    touch_is_tap,
)

class MCQChoiceButton(Button):
    """Touchable rounded MCQ answer tile with selection and check feedback glow."""

    def __init__(
        self,
        option_index: int,
        *,
        on_select: Callable[[int], None],
        **kwargs,
    ):
        super().__init__(
            font_size=STUDY_MCQ_ANSWER_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            padding=(dp(14), dp(10)),
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._option_index = option_index
        self._on_select = on_select
        self._selected = False
        self._feedback: str | None = None  # None | "correct" | "wrong"
        self._feedback_phase = 0.0
        self._feedback_tick = None
        self._feedback_boost_until = 0.0
        self.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width - dp(24), None)))
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL_HI)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[STUDY_MCQ_ANSWER_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER,
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self._touch_down_pos: tuple[float, float] | None = None
        self._touch_id = None
        self._pressed = False
        self._select_glow_ev = None

    def _emit_select(self) -> None:
        if self.disabled:
            return
        schedule_touch_safe(self, lambda: self._on_select(self._option_index))

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._touch_id = touch.id
        self._touch_down_pos = (touch.x, touch.y)
        self._pressed = True
        self._sync_canvas()
        touch.grab(self)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        if self._touch_id != touch.id or self._touch_down_pos is None:
            self._pressed = False
            self._sync_canvas()
            return True
        x0, y0 = self._touch_down_pos
        self._touch_down_pos = None
        self._touch_id = None
        if not self.collide_point(*touch.pos):
            self._pressed = False
            self._sync_canvas()
            return True
        if not touch_is_tap(touch, down_x=x0, down_y=y0):
            self._pressed = False
            self._sync_canvas()
            return True
        self._pressed = True
        self._sync_canvas()
        if self._select_glow_ev is not None:
            self._select_glow_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._select_glow_ev = None
            self._pressed = False
            self._sync_canvas()
            self._emit_select()

        self._select_glow_ev = Clock.schedule_once(_after_glow, 0.14)
        return True

    def set_label(self, text: str) -> None:
        self.text = text

    def set_visual(self, *, selected: bool = False, feedback: str | None = None) -> None:
        self._selected = selected
        next_feedback = feedback if feedback in ("correct", "wrong") else None
        if self._feedback != next_feedback:
            self._feedback_phase = 0.0
        self._feedback = next_feedback
        if self._feedback is not None:
            self._start_feedback_tick()
        else:
            self._stop_feedback_tick()
        self._sync_canvas()

    def pulse_feedback(self, feedback: str) -> None:
        if feedback not in ("correct", "wrong"):
            return
        self._feedback_boost_until = time.monotonic() + 0.42
        self._start_feedback_tick()
        self._apply_feedback_glow()

    def _start_feedback_tick(self) -> None:
        if self._feedback_tick is None:
            self._feedback_tick = Clock.schedule_interval(self._tick_feedback_glow, 1 / 30.0)

    def _stop_feedback_tick(self) -> None:
        if self._feedback_tick is not None:
            self._feedback_tick.cancel()
            self._feedback_tick = None

    def _tick_feedback_glow(self, dt: float) -> None:
        if self._feedback is None:
            self._stop_feedback_tick()
            return
        self._feedback_phase += dt
        self._apply_feedback_glow()

    def _apply_feedback_glow(self) -> None:
        if self._feedback == "correct":
            glow = Theme.OK
            outer_alpha = 0.30
            inner_alpha = 0.52
        elif self._feedback == "wrong":
            glow = Theme.DANGER
            outer_alpha = 0.32
            inner_alpha = 0.55
        else:
            return

        # Match the robot eyes' breathing feel: bigger/smaller glow, not fixed width.
        pulse = 0.88 + 0.12 * math.sin(self._feedback_phase * 2.0)
        boost = 1.0
        if time.monotonic() < self._feedback_boost_until:
            boost = 1.22
        self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4 * pulse * boost
        self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5 * pulse * boost
        alpha_boost = 1.25 if boost > 1.0 else 1.0
        self._outer_glow_color.rgba = (
            glow[0],
            glow[1],
            glow[2],
            min(0.72, outer_alpha * alpha_boost),
        )
        self._inner_glow_color.rgba = (
            glow[0],
            glow[1],
            glow[2],
            min(0.85, inner_alpha * alpha_boost),
        )

    def _sync_canvas(self, *_args) -> None:
        if (
            self._pressed
            and self._feedback is None
            and not self._selected
        ):
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
            self._fill.pos = self.pos
            self._fill.size = self.size
            rr = (
                self.x,
                self.y,
                self.width,
                self.height,
                STUDY_MCQ_ANSWER_RADIUS,
            )
            self._outer_glow.rounded_rectangle = rr
            self._inner_glow.rounded_rectangle = rr
            self._border.rounded_rectangle = (
                self.x,
                self.y,
                self.width,
                self.height,
                STUDY_MCQ_ANSWER_RADIUS,
            )
            self._border.width = border_w
            return

        if self._feedback == "correct":
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.OK
            self._apply_feedback_glow()
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._feedback == "wrong":
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.DANGER
            self._apply_feedback_glow()
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._selected:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4
            self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4
            self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER
        self._fill.pos = self.pos
        self._fill.size = self.size
        rr = (
            self.x,
            self.y,
            self.width,
            self.height,
            STUDY_MCQ_ANSWER_RADIUS,
        )
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            STUDY_MCQ_ANSWER_RADIUS,
        )
        self._border.width = border_w


class MCQNavButton(Button):
    """Prev / Check / Next — touch-safe (no duplicate touch+mouse presses)."""

    _BTN_RADIUS = dp(14)

    def __init__(self, label: str, **kwargs):
        self._on_safe_press: Callable[[], None] | None = kwargs.pop("on_safe_press", None)
        super().__init__(
            text=label,
            font_size=STUDY_MCQ_NAV_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._flash_ev = None
        self._glow_release_ev = None
        self._flash_active = False
        self._pressed = False
        self._touch_down_pos: tuple[float, float] | None = None
        self._touch_id = None
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._BTN_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=dp(1.5),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def bind_safe_press(self, callback: Callable[[], None]) -> None:
        self._on_safe_press = callback

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _emit_safe_press(self) -> None:
        if self._on_safe_press is None or self.disabled:
            return
        schedule_touch_safe(self, self._on_safe_press)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._touch_id = touch.id
        self._touch_down_pos = (touch.x, touch.y)
        self._set_pressed(True)
        touch.grab(self)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        if self._touch_id != touch.id or self._touch_down_pos is None:
            self._set_pressed(False)
            return True
        x0, y0 = self._touch_down_pos
        self._touch_down_pos = None
        self._touch_id = None
        if not self.collide_point(*touch.pos):
            self._set_pressed(False)
            return True
        if not touch_is_tap(touch, down_x=x0, down_y=y0):
            self._set_pressed(False)
            return True
        self._set_pressed(True)
        if self._glow_release_ev is not None:
            self._glow_release_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._glow_release_ev = None
            self._set_pressed(False)
            self._emit_safe_press()

        self._glow_release_ev = Clock.schedule_once(_after_glow, 0.14)
        return True

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._BTN_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._flash_active:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.22)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.12)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.22)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._pressed:
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
            self._border.width = dp(1.5)

    def flash_danger(self, duration: float = 0.35) -> None:
        if self._flash_ev is not None:
            self._flash_ev.cancel()
        self._flash_active = True
        self._sync_canvas()

        def _restore(_dt: float) -> None:
            self._flash_ev = None
            self._flash_active = False
            self._sync_canvas()

        self._flash_ev = Clock.schedule_once(_restore, duration)


class MCQFileListScroll(ScrollView):
    """Marks touches that moved enough to count as scrolling (not a row tap)."""

    def on_touch_down(self, touch):
        touch.ud["mcq_list_scrolled"] = False
        touch.ud["mcq_list_down_x"] = touch.x
        touch.ud["mcq_list_down_y"] = touch.y
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if abs(touch.y - touch.ud.get("mcq_list_down_y", touch.y)) > STUDY_MCQ_SCROLL_SLOP:
            touch.ud["mcq_list_scrolled"] = True
        if abs(touch.x - touch.ud.get("mcq_list_down_x", touch.x)) > STUDY_MCQ_SCROLL_SLOP:
            touch.ud["mcq_list_scrolled"] = True
        return super().on_touch_move(touch)


class MCQFileRow(BoxLayout):
    """Scroll-friendly quiz file row — tap only when the finger did not scroll."""

    _ROW_RADIUS = dp(14)

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        on_pick: Callable[[], None],
        **kwargs,
    ):
        super().__init__(
            orientation="vertical",
            padding=(dp(14), dp(10)),
            spacing=dp(2),
            size_hint_y=None,
            height=STUDY_MCQ_FILE_ROW_H,
            **kwargs,
        )
        self._on_pick = on_pick
        self._touched = False
        self._pick_delay_ev = None
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._ROW_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        title_lbl = Label(
            text=title,
            font_size=STUDY_MCQ_FILE_LIST_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_y=0.62,
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        sub_lbl = Label(
            text=subtitle,
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.MUTED,
            halign="left",
            valign="middle",
            size_hint_y=0.38,
        )
        sub_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(title_lbl)
        self.add_widget(sub_lbl)

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._ROW_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._touched:
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

    def _set_touched(self, active: bool) -> None:
        self._touched = active
        self._sync_canvas()

    def _emit_pick(self) -> None:
        self._set_touched(True)
        if self._pick_delay_ev is not None:
            self._pick_delay_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._pick_delay_ev = None
            self._set_touched(False)
            self._on_pick()

        self._pick_delay_ev = Clock.schedule_once(_after_glow, 0.14)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud["mcq_file_row"] = self
            touch.ud["mcq_file_row_x"] = touch.x
            touch.ud["mcq_file_row_y"] = touch.y
            touch.ud["mcq_file_row_id"] = touch.id
            self._set_touched(True)
        return False

    def on_touch_up(self, touch):
        if touch.ud.get("mcq_file_row") is not self:
            return False
        if touch.ud.get("mcq_file_row_id") != touch.id:
            return False
        if touch.ud.get("mcq_list_scrolled"):
            self._set_touched(False)
            return False
        if not self.collide_point(*touch.pos):
            self._set_touched(False)
            return False
        x0 = touch.ud.get("mcq_file_row_x", touch.x)
        y0 = touch.ud.get("mcq_file_row_y", touch.y)
        if touch_is_tap(touch, down_x=x0, down_y=y0):
            schedule_touch_safe(self, self._emit_pick)
        else:
            self._set_touched(False)
        return False


class QuizDangerNavButton(MCQNavButton):
    """Red-accent nav button for quiz Answer."""

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._BTN_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._flash_active:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.35)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.16)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.28)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._pressed:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.38)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.18)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.32)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = (
                Theme.DANGER[0],
                Theme.DANGER[1],
                Theme.DANGER[2],
                0.28,
            )
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0)
            self._border.width = dp(1.5)


class QuizGlowPanel(BoxLayout):
    """Rounded panel with green/red glow for transcript or answer blocks."""

    _RADIUS = dp(14)

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=(dp(12), dp(14), dp(12), dp(10)),
            size_hint_y=None,
            **kwargs,
        )
        self._passing = False
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
        self.body_lbl = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="top",
            size_hint_y=None,
            height=dp(48),
        )
        self.body_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.body_lbl.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(dp(48), ts[1] + dp(8)))
        )
        self.bind(minimum_height=self._sync_height)
        self.add_widget(self.body_lbl)

    def _sync_height(self, *_args) -> None:
        self.height = self.body_lbl.height + dp(20)

    def set_text(self, text: str) -> None:
        self.body_lbl.text = text

    def set_passing(self, passing: bool) -> None:
        self._passing = passing
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._passing:
            glow = Theme.OK
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.OK
            self._outer_glow_color.rgba = (glow[0], glow[1], glow[2], 0.14)
            self._inner_glow_color.rgba = (glow[0], glow[1], glow[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            glow = Theme.DANGER
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (glow[0], glow[1], glow[2], 0.14)
            self._inner_glow_color.rgba = (glow[0], glow[1], glow[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        self._sync_height()
