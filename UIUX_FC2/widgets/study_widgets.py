"""Study screen tile and wheel picker widgets."""

from __future__ import annotations

from typing import Callable

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from theme import Theme
from widgets.common import (
    STUDY_TILE_ICON,
    STUDY_TILE_LABEL,
    STUDY_WHEEL_CENTER_ROW,
    STUDY_WHEEL_ROW_H,
    STUDY_WHEEL_SCROLL_ANIM_S,
    STUDY_WHEEL_SCROLL_SETTLE_S,
    STUDY_WHEEL_VISIBLE_ROWS,
    bind_touch_safe_on_press,
    schedule_touch_safe,
    study_icon_texture,
    touch_is_tap,
)
from widgets.panels import GlowPanel


class StudyTileIcon(Widget):
    """Study tile icon from UIUX2/icons PNG assets."""

    def __init__(self, icon_file: str, **kwargs):
        super().__init__(**kwargs)
        self._texture = study_icon_texture(icon_file)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 4 or self.height < 4:
            return
        side = min(self.width, self.height) * 0.9
        ix = self.center_x - side / 2
        iy = self.center_y - side / 2
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))


class StudyTile(GlowPanel):
    """Neon study feature tile — icon, label, optional tap handler."""

    def __init__(
        self,
        icon_file: str,
        label: str,
        *,
        on_tap: Callable[[], None] | None = None,
        **kwargs,
    ):
        super().__init__(
            orientation="vertical",
            padding=(dp(12), dp(14), dp(12), dp(10)),
            spacing=dp(6),
            **kwargs,
        )
        self.icon_file = icon_file
        self._base_label = label
        self._on_tap = on_tap
        self._alarm_mode = False
        self._tile_pressed = False
        self._tile_glow_restore_ev = None

        icon_holder = AnchorLayout(size_hint_y=1)
        icon_holder.add_widget(
            StudyTileIcon(
                icon_file,
                size_hint=(None, None),
                size=(STUDY_TILE_ICON, STUDY_TILE_ICON),
            )
        )
        self.caption = Label(
            text=label,
            font_size=STUDY_TILE_LABEL,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(44),
        )
        self.caption.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(icon_holder)
        self.add_widget(self.caption)

    def set_caption(self, text: str, *, accent: tuple[float, float, float, float] | None = None) -> None:
        self.caption.text = text
        if accent is not None:
            self.caption.color = accent

    def set_alarm_mode(self, active: bool) -> None:
        self._alarm_mode = active
        if active:
            self.set_caption("TIME'S UP\nTAP TO SILENCE", accent=Theme.WARN)
        else:
            self.set_caption(self._base_label, accent=Theme.ACCENT_SOFT)

    def _set_tile_pressed(self, active: bool) -> None:
        self._tile_pressed = active
        if active:
            self._border_accent.rgba = Theme.CYAN
            self._hairline.width = dp(2.2)
            for ln in self._glow_lines:
                ln.width = dp(3.0)
        else:
            self._border_accent.rgba = Theme.BORDER_CYAN_SOFT
            self._hairline.width = dp(1.15)
            for i, ln in enumerate(self._glow_lines):
                ln.width = dp(2.2) * Theme.CARD_GLOW_LAYERS[i][1]

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self._on_tap is not None:
            touch.ud["study_tile"] = self
            touch.ud["study_tile_x"] = touch.x
            touch.ud["study_tile_y"] = touch.y
            touch.ud["study_tile_id"] = touch.id
            self._set_tile_pressed(True)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self._on_tap is None:
            return super().on_touch_up(touch)
        if touch.ud.get("study_tile") is not self:
            if self._tile_pressed:
                self._set_tile_pressed(False)
            return super().on_touch_up(touch)
        if touch.ud.get("study_tile_id") != touch.id:
            self._set_tile_pressed(False)
            return super().on_touch_up(touch)
        if not self.collide_point(*touch.pos):
            self._set_tile_pressed(False)
            return super().on_touch_up(touch)
        x0 = touch.ud.get("study_tile_x", touch.x)
        y0 = touch.ud.get("study_tile_y", touch.y)
        if not touch_is_tap(touch, down_x=x0, down_y=y0):
            self._set_tile_pressed(False)
            return super().on_touch_up(touch)
        self._set_tile_pressed(True)
        if self._tile_glow_restore_ev is not None:
            self._tile_glow_restore_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._tile_glow_restore_ev = None
            self._set_tile_pressed(False)
            schedule_touch_safe(self, self._on_tap)

        self._tile_glow_restore_ev = Clock.schedule_once(_after_glow, 0.14)
        return True


class WheelRow(Button):
    """Row that allows ScrollView drags; tap only when finger did not scroll."""

    _tap_slop = dp(16)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud["wheel_row"] = self
            touch.ud["wheel_row_y"] = touch.y
        return False

    def on_touch_up(self, touch):
        if touch.ud.get("wheel_row") is not self:
            return False
        if not self.collide_point(*touch.pos):
            return False
        if abs(touch.y - touch.ud.get("wheel_row_y", touch.y)) <= self._tap_slop:
            self.dispatch("on_press")
        return False


class WheelPickerColumn(BoxLayout):
    """Scrollable numeric column — drag to scroll, snap on release, or tap a row."""

    def __init__(
        self,
        title: str,
        values: list[int],
        *,
        initial: int = 0,
        on_change: Callable[[int], None] | None = None,
        **kwargs,
    ):
        super().__init__(orientation="vertical", spacing=dp(4), **kwargs)
        self._values = values
        self._selected = initial if initial in values else values[0]
        self._on_change = on_change
        self._row_buttons: list[Button] = []
        self._suppress_snap = False
        self._settle_ev = None
        self._scroll_anim: Animation | None = None
        self._defer_on_change = False

        hdr = Label(
            text=title,
            font_size=Theme.CAPTION,
            bold=True,
            color=Theme.MUTED,
            size_hint_y=None,
            height=dp(22),
        )
        self.add_widget(hdr)

        pad = STUDY_WHEEL_CENTER_ROW * STUDY_WHEEL_ROW_H
        self.scroll = ScrollView(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(3),
            scroll_type=["bars", "content"],
        )
        inner = BoxLayout(orientation="vertical", size_hint_y=None, padding=(0, pad, 0, pad))
        inner.bind(minimum_height=inner.setter("height"))

        for val in values:
            btn = WheelRow(
                text=f"{val:02d}",
                size_hint_y=None,
                height=STUDY_WHEEL_ROW_H,
                font_size=sp(20),
                bold=True,
                background_normal="",
                background_down="",
            )
            btn._wheel_value = val  # type: ignore[attr-defined]
            bind_touch_safe_on_press(btn, lambda v=val: self.set_value(v, scroll=True, animate=True))
            inner.add_widget(btn)
            self._row_buttons.append(btn)

        self.scroll.add_widget(inner)
        self._inner = inner
        self.add_widget(self.scroll)
        self.scroll.bind(scroll_y=self._on_scroll_y, on_scroll_stop=self._on_scroll_stop)
        Clock.schedule_once(
            lambda _dt: self.set_value(self._selected, scroll=True, animate=False),
            0,
        )

    @property
    def value(self) -> int:
        return self._selected

    def _scroll_range(self) -> float:
        return max(1.0, self._inner.height - self.scroll.height)

    def _index_to_scroll_y(self, idx: int) -> float:
        idx = max(0, min(idx, len(self._values) - 1))
        # Top padding already offsets the center row; content offset is idx * row height.
        target_y = idx * STUDY_WHEEL_ROW_H
        return 1.0 - min(1.0, target_y / self._scroll_range())

    def _scroll_y_to_index(self) -> int:
        content_offset = (1.0 - self.scroll.scroll_y) * self._scroll_range()
        idx = round(content_offset / STUDY_WHEEL_ROW_H)
        return max(0, min(idx, len(self._values) - 1))

    def _cancel_settle(self) -> None:
        if self._settle_ev is not None:
            self._settle_ev.cancel()
            self._settle_ev = None

    def _cancel_scroll_anim(self) -> None:
        if self._scroll_anim is not None:
            self._scroll_anim.cancel(self.scroll)
            self._scroll_anim.unbind(on_complete=self._on_scroll_anim_complete)
            self._scroll_anim = None
        self._suppress_snap = False
        self._defer_on_change = False

    def _apply_highlight(self, val: int) -> None:
        for btn in self._row_buttons:
            selected = btn._wheel_value == val  # type: ignore[attr-defined]
            btn.background_color = Theme.CYAN if selected else Theme.PANEL_HI
            btn.color = Theme.BLACK if selected else Theme.TEXT

    def _on_scroll_anim_complete(self, *_args) -> None:
        self._scroll_anim = None
        self._suppress_snap = False
        if self._defer_on_change:
            self._defer_on_change = False
            if self._on_change:
                self._on_change(self._selected)

    def _scroll_to_index(self, idx: int, *, animate: bool) -> None:
        target_y = self._index_to_scroll_y(idx)
        if not animate:
            self.scroll.scroll_y = target_y
            return
        self._suppress_snap = True
        self._cancel_scroll_anim()
        self._scroll_anim = Animation(
            scroll_y=target_y,
            duration=STUDY_WHEEL_SCROLL_ANIM_S,
            transition="out_cubic",
        )
        self._scroll_anim.bind(on_complete=self._on_scroll_anim_complete)
        self._scroll_anim.start(self.scroll)

    def _sync_selection_from_scroll(self) -> None:
        idx = self._scroll_y_to_index()
        val = self._values[idx]
        if val != self._selected:
            self._selected = val
            self._apply_highlight(val)

    def _on_scroll_y(self, *_args) -> None:
        if self._suppress_snap:
            return
        self._sync_selection_from_scroll()
        self._cancel_settle()
        self._settle_ev = Clock.schedule_once(self._snap_to_nearest, STUDY_WHEEL_SCROLL_SETTLE_S)

    def _on_scroll_stop(self, *_args) -> None:
        if self._suppress_snap:
            return
        self._cancel_settle()
        self._snap_to_nearest()

    def _snap_to_nearest(self, *_dt) -> None:
        self._settle_ev = None
        if self._suppress_snap:
            return
        idx = self._scroll_y_to_index()
        val = self._values[idx]
        changed = val != self._selected
        self._selected = val
        self._apply_highlight(val)
        target_y = self._index_to_scroll_y(idx)
        self._cancel_scroll_anim()
        if abs(self.scroll.scroll_y - target_y) < 0.002:
            if changed and self._on_change:
                self._on_change(val)
            return
        if changed:
            self._defer_on_change = True
        self._scroll_to_index(idx, animate=True)

    def set_value(self, val: int, *, scroll: bool = False, animate: bool = True) -> None:
        if val not in self._values:
            val = self._values[0]
        changed = val != self._selected
        self._selected = val
        self._apply_highlight(val)
        if scroll:
            self._cancel_settle()
            self._cancel_scroll_anim()
            idx = self._values.index(val)
            if animate:
                if changed:
                    self._defer_on_change = True
                self._scroll_to_index(idx, animate=True)
            else:
                self._scroll_to_index(idx, animate=False)
        if self._on_change and changed and not (scroll and animate):
            self._on_change(val)

