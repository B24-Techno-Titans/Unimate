"""To-do list widget components."""

from __future__ import annotations

from typing import Callable

from kivy.graphics import Color, Line, RoundedRectangle
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from theme import Theme
from widgets.common import (
    STUDY_MCQ_ANSWER_BORDER_SEL,
    STUDY_TODO_CHECK_SIZE,
    STUDY_TODO_DELETE_SIZE,
    STUDY_TODO_KEY_FONT,
    STUDY_TODO_KEY_GAP,
    STUDY_TODO_KEY_H,
    STUDY_TODO_KEYBOARD_H,
    STUDY_TODO_ROW_H,
    STUDY_TODO_ROW_RIGHT_PAD,
    STUDY_TODO_TEXT_FONT,
    TODO_KEYBOARD_ROWS,
    schedule_touch_safe,
)

class TodoCheckButton(Button):
    """Square check toggle for to-do rows."""

    _RADIUS = dp(8)

    def __init__(
        self,
        checked: bool = False,
        on_toggle: Callable[[], None] | None = None,
        **kwargs,
    ):
        self._checked = checked
        self._on_toggle = on_toggle
        self._pressed = False
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("width", STUDY_TODO_CHECK_SIZE)
        kwargs.setdefault("height", STUDY_TODO_CHECK_SIZE)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.ACCENT_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.6),
            )
            self._tick_color = Color(*Theme.ACCENT_SOFT)
            self._tick = Line(points=[], width=dp(2.4), cap="round")
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self._sync_canvas()

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._checked:
            self._fill_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.18)
            self._border_color.rgba = Theme.CYAN
            cx = self.x + self.width * 0.5
            cy = self.y + self.height * 0.5
            w = self.width * 0.22
            h = self.height * 0.12
            self._tick.points = [
                cx - w,
                cy,
                cx - w * 0.15,
                cy - h,
                cx + w,
                cy + h,
            ]
            self._tick_color.rgba = Theme.CYAN
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.ACCENT_SOFT if not self._pressed else Theme.CYAN
            self._tick.points = []
            self._tick_color.rgba = (0, 0, 0, 0)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._pressed = True
            self._sync_canvas()
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed:
            self._pressed = False
            self._sync_canvas()
            if self.collide_point(*touch.pos) and self._on_toggle is not None:
                schedule_touch_safe(self, self._on_toggle)
        return result


class TodoDeleteButton(Button):
    """Red circular delete button for to-do rows."""

    def __init__(self, on_delete: Callable[[], None] | None = None, **kwargs):
        self._on_delete = on_delete
        self._pressed = False
        kwargs.setdefault("text", "X")
        kwargs.setdefault("font_size", sp(20))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", Theme.TEXT)
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("width", STUDY_TODO_DELETE_SIZE)
        kwargs.setdefault("height", STUDY_TODO_DELETE_SIZE)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._fill_color = Color(Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.88)
            self._fill = Ellipse(pos=self.pos, size=self.size)
            self._border_color = Color(*Theme.DANGER)
            self._border = Line(circle=(self.center_x, self.center_y, self.width * 0.5), width=dp(1.2))
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_args) -> None:
        self._fill.pos = self.pos
        self._fill.size = self.size
        r = min(self.width, self.height) * 0.5
        self._border.circle = (self.center_x, self.center_y, r)
        if self._pressed:
            self._fill_color.rgba = Theme.DANGER
        else:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.88)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._pressed = True
            self._sync_canvas()
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed:
            self._pressed = False
            self._sync_canvas()
            if self.collide_point(*touch.pos) and self._on_delete is not None:
                schedule_touch_safe(self, self._on_delete)
        return result


class TodoRow(BoxLayout):
    """Single to-do item row: check box, numbered label, delete."""

    def __init__(
        self,
        index: int,
        text: str,
        *,
        done: bool = False,
        on_toggle: Callable[[], None] | None = None,
        on_delete: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(
            orientation="horizontal",
            spacing=dp(12),
            size_hint_y=None,
            height=STUDY_TODO_ROW_H,
            padding=(0, dp(4), STUDY_TODO_ROW_RIGHT_PAD, dp(4)),
            **kwargs,
        )
        self._done = done
        self._index = index
        self._text = text
        self.check_btn = TodoCheckButton(checked=done, on_toggle=on_toggle)
        self.add_widget(self.check_btn)
        self.text_lbl = Label(
            text=f"{index}. {text}",
            font_size=STUDY_TODO_TEXT_FONT,
            bold=True,
            color=Theme.MUTED if done else Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_x=1,
        )
        self.text_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(self.text_lbl)
        delete_col = BoxLayout(
            orientation="horizontal",
            size_hint=(None, 1),
            width=STUDY_TODO_DELETE_SIZE,
        )
        delete_col.add_widget(TodoDeleteButton(on_delete=on_delete))
        self.add_widget(delete_col)

    def refresh(self, index: int, text: str, done: bool) -> None:
        self._index = index
        self._text = text
        self._done = done
        self.check_btn.set_checked(done)
        self.text_lbl.text = f"{index}. {text}"
        self.text_lbl.color = Theme.MUTED if done else Theme.ACCENT_SOFT


class UniMateKeyButton(Button):
    """Themed touch key for the UniMate on-screen keyboard."""

    _RADIUS = dp(9)

    def __init__(self, label: str, on_tap: Callable[[], None], *, accent: bool = False, **kwargs):
        self._on_tap = on_tap
        self._accent = accent
        self._pressed = False
        kwargs.setdefault("text", label)
        kwargs.setdefault("font_size", STUDY_TODO_KEY_FONT)
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", Theme.ACCENT_SOFT)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 3.6,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.0,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL_HI)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.1),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._pressed or self._accent:
            self._fill_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.16 if self._accent else 0.22)
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.12)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.22)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.1)

    def set_accent(self, active: bool) -> None:
        self._accent = active
        self._sync_canvas()

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._pressed = True
            self._sync_canvas()
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed:
            self._pressed = False
            self._sync_canvas()
            if self.collide_point(*touch.pos):
                schedule_touch_safe(self, self._on_tap)
        return result


class UniMateKeyboard(BoxLayout):
    """Custom neon-themed keyboard for UniMate text entry."""

    def __init__(self, text_input: TextInput, **kwargs):
        super().__init__(
            orientation="vertical",
            spacing=STUDY_TODO_KEY_GAP,
            size_hint=(1, None),
            height=STUDY_TODO_KEYBOARD_H,
            **kwargs,
        )
        self._text_input = text_input
        self._shift = False
        self._shift_btn: UniMateKeyButton | None = None
        self._key_buttons: list[UniMateKeyButton] = []
        for row_keys in TODO_KEYBOARD_ROWS:
            row = BoxLayout(spacing=STUDY_TODO_KEY_GAP, size_hint_y=None, height=STUDY_TODO_KEY_H)
            for key in row_keys:
                if key == "SPACE":
                    btn = UniMateKeyButton(
                        "SPACE",
                        self._on_space,
                        size_hint_x=1,
                    )
                elif key == "DEL":
                    btn = UniMateKeyButton(
                        "DEL",
                        self._on_backspace,
                        size_hint_x=1.45,
                        font_size=sp(14),
                    )
                elif key == "SHIFT":
                    self._shift_btn = UniMateKeyButton(
                        "SHIFT",
                        self._on_shift,
                        size_hint_x=1.35,
                        font_size=sp(13),
                    )
                    btn = self._shift_btn
                else:
                    btn = UniMateKeyButton(
                        key.lower(),
                        lambda k=key: self._on_char(k),
                        size_hint_x=1,
                    )
                    btn._canon_key = key
                    self._key_buttons.append(btn)
                row.add_widget(btn)
            self.add_widget(row)

    def _on_char(self, key: str) -> None:
        ch = key.upper() if self._shift else key.lower()
        self._text_input.insert_text(ch)
        if self._shift:
            self._toggle_shift(False)

    def _on_space(self) -> None:
        self._text_input.insert_text(" ")

    def _on_backspace(self) -> None:
        self._text_input.do_backspace()

    def _on_shift(self) -> None:
        self._toggle_shift(not self._shift)

    def _toggle_shift(self, active: bool) -> None:
        self._shift = active
        if self._shift_btn is not None:
            self._shift_btn.set_accent(active)
        for btn in self._key_buttons:
            key = getattr(btn, "_canon_key", "")
            if isinstance(key, str) and len(key) == 1 and key.isalpha():
                btn.text = key.upper() if active else key.lower()

