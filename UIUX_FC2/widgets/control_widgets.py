"""Device control card widgets."""

from __future__ import annotations

import math
from typing import Callable

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from mock_state import MockState
from raspi_bridge import apply_led_state, rgb_tuple_to_hex, set_fan, set_humidifier, set_lights
from theme import Theme
from widgets.animations import DeviceViz
from widgets.common import (
    CONTROL_BTN_HEIGHT,
    CONTROL_BTN_WIDTH,
    CONTROL_BUTTON_TEXT,
    CONTROL_CARD_H,
    CONTROL_ICON,
    CONTROL_ICON_SLOT,
    CONTROL_SMALL_ICON,
    CONTROL_STATUS,
    CONTROL_TITLE,
    LED_BRIDGE_DEBOUNCE_S,
    LED_OFF_EPS,
    bridge_worker,
    build_hsv_wheel_texture,
    hsv_to_rgb,
    led_effective_on,
    led_slider_locked,
    make_auto_button,
    rgb_to_hex,
    rgb_to_hsv,
    sync_auto_button,
    bind_touch_safe_on_press,
)
from widgets.panels import GlowPanel

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
            bind_touch_safe_on_press(btn, lambda lv=label: self._pick(lv))
            self._buttons.append(btn)
            self.add_widget(btn)

    def _pick(self, label: str) -> None:
        if self.disabled:
            return
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

    def set_disabled(self, disabled: bool) -> None:
        self.disabled = disabled
        self.opacity = 0.45 if disabled else 1.0
        for btn in self._buttons:
            btn.disabled = disabled
            if disabled:
                btn.background_color = Theme.PANEL_HI
                btn.color = Theme.MUTED


class ColorWheel(Widget):
    """HSV color wheel — smooth texture disk, touch to pick custom light color."""

    def __init__(
        self,
        state: MockState,
        on_change: Callable[[], None] | None = None,
        on_pick: Callable[[tuple[float, float, float]], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.state = state
        self.on_change = on_change
        self.on_pick = on_pick
        self._wheel_tex: Texture | None = None
        self._wheel_tex_px = 0
        self._disabled = False
        self.bind(pos=self._redraw, size=self._redraw)

    def _wheel_radius(self) -> float:
        return min(self.width, self.height) * 0.44

    def _wheel_texture(self, diameter: float) -> Texture:
        px = max(96, min(384, int(diameter)))
        if self._wheel_tex is None or self._wheel_tex_px != px:
            self._wheel_tex = build_hsv_wheel_texture(px)
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
        rgb = hsv_to_rgb(hue, sat, 1.0)
        if self.on_pick is not None:
            self.on_pick(rgb)
        else:
            self.state.set_led_color(rgb)
            if self.on_change:
                self.on_change()
        self._redraw()
        return True

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.opacity = 0.45 if disabled else 1.0

    def on_touch_down(self, touch):
        if self._disabled:
            return super().on_touch_down(touch)
        if self.collide_point(*touch.pos) and self._pick_at(touch.x, touch.y):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._disabled:
            return super().on_touch_move(touch)
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

        h, s, _v = rgb_to_hsv(*self.state.led_color)
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
        self._auto_btn = make_auto_button()
        bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)
        text_col.add_widget(self._auto_btn)
        self.segment = SegmentedLevelControl(
            on_select=self._set_level,
            size_hint_x=None,
            width=CONTROL_BTN_WIDTH,
        )
        text_col.add_widget(self.segment)

        self.add_widget(icon_slot)
        self.add_widget(text_col)
        self.refresh()

    def _auto_enabled(self) -> bool:
        return self.state.auto_fan if self.kind == "fan" else self.state.auto_humidifier

    def _on_auto_press(self, *_args) -> None:
        value = not self._auto_enabled()
        prev = self._auto_enabled()
        if self.kind == "fan":
            self.state.auto_fan = value
        else:
            self.state.auto_humidifier = value
        level = self.state.fan_level if self.kind == "fan" else self.state.humidifier_level

        def _call() -> bool:
            if self.kind == "fan":
                return set_fan(level, auto_fan=value)
            return set_humidifier(level, auto_humid=value)

        def _done(ok: bool) -> None:
            if not ok:
                if self.kind == "fan":
                    self.state.auto_fan = prev
                else:
                    self.state.auto_humidifier = prev
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def _set_level(self, level: int) -> None:
        if self._auto_enabled():
            return
        prev = self.state.fan_level if self.kind == "fan" else self.state.humidifier_level
        if prev == level:
            return

        def _call() -> bool:
            if self.kind == "fan":
                return set_fan(level, auto_fan=False)
            return set_humidifier(level, auto_humid=False)

        def _done(ok: bool) -> None:
            if ok:
                if self.kind == "fan":
                    self.state.set_fan_level(level)
                else:
                    self.state.set_humidifier_level(level)
            else:
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def refresh(self) -> None:
        lv = self.state.fan_level if self.kind == "fan" else self.state.humidifier_level
        if self.kind == "fan":
            label = self._speed_label
        else:
            label = self._output_label
        auto_note = " (Auto)" if self._auto_enabled() else ""
        self.status.text = (
            f"{label}: Level {lv}{auto_note}" if lv else f"{label}: OFF{auto_note}"
        )
        self.segment.set_level(lv)
        self.segment.set_disabled(self._auto_enabled())
        sync_auto_button(self._auto_btn, self._auto_enabled())


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
        self._auto_btn = make_auto_button()
        bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)
        text_col.add_widget(self._auto_btn)
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
        bind_touch_safe_on_press(self._led_btn, self._run_led_toggle)
        bottom.add_widget(self._led_btn)
        bottom.add_widget(Label(text="Bright", font_size=CONTROL_STATUS, color=Theme.MUTED, halign="left"))
        text_col.add_widget(bottom)

        self.add_widget(icon_slot)
        self.add_widget(text_col)
        self.refresh()

    def _on_auto_press(self, *_args) -> None:
        value = not self.state.auto_light
        prev = self.state.auto_light
        self.state.auto_light = value
        brightness = (
            int(round(self.state.led_brightness * 255)) if led_effective_on(self.state) else 0
        )

        def _call() -> bool:
            return set_lights(
                rgb_hex=rgb_tuple_to_hex(self.state.led_color),
                brightness=brightness,
                auto_light=value,
            )

        def _done(ok: bool) -> None:
            if not ok:
                self.state.auto_light = prev
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def _run_led_toggle(self, *_args) -> None:
        """Coalesce duplicate touch+mouse presses into one toggle."""
        if self.state.auto_light:
            return
        self._toggle()

    def _toggle(self) -> None:
        if self.state.auto_light:
            return
        if led_effective_on(self.state):
            target_on = False
            target_brightness = self.state.led_brightness
        else:
            target_on = True
            target_brightness = (
                0.65 if self.state.led_brightness <= LED_OFF_EPS else self.state.led_brightness
            )
        target_color = self.state.led_color

        def _call() -> bool:
            return apply_led_state(
                led_on=target_on,
                led_brightness=target_brightness,
                led_color=target_color,
                auto_light=False,
            )

        def _done(ok: bool) -> None:
            if ok:
                self.state.set_led(on=target_on, brightness=target_brightness)
            else:
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def refresh(self) -> None:
        on = led_effective_on(self.state)
        pct = int(round(self.state.led_brightness * 100))
        self._led_btn.text = "ON" if on else "OFF"
        self._led_btn.background_color = Theme.CYAN if on else Theme.OFF
        self._led_btn.color = Theme.BLACK if on else Theme.MUTED
        self._led_btn.disabled = self.state.auto_light
        self._led_btn.opacity = 0.45 if self.state.auto_light else 1.0
        off_note = " (Currently OFF)" if not on else ""
        auto_note = " (Auto)" if self.state.auto_light else ""
        self.status.text = f"Brightness: {pct}%{off_note}{auto_note}"
        sync_auto_button(self._auto_btn, self.state.auto_light)


class LightColorCard(GlowPanel):
    """Ambient light — intensity slider, color wheel, hex swatch."""

    def __init__(self, state: MockState, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", CONTROL_CARD_H)
        super().__init__(orientation="horizontal", padding=(dp(16), dp(12)), spacing=dp(10), **kwargs)
        self.state = state
        self._led_bridge_ev = None
        self._slider_sync = False
        self._pending_led_on: bool | None = None
        self._pending_led_brightness: float | None = None
        self._pending_led_color: tuple[float, float, float] | None = None

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

        self._auto_btn = make_auto_button()
        self._auto_btn.size_hint = (1, None)
        self._auto_btn.size = (0, CONTROL_BTN_HEIGHT)
        bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)

        slider_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54), spacing=dp(8))
        slider_row.add_widget(Label(text="0%", font_size=sp(13), color=Theme.MUTED, size_hint_x=None, width=dp(34)))
        self.slider = Slider(min=0.0, max=1.0, value=state.led_brightness, size_hint_x=1)
        self.slider.cursor_size = (dp(30), dp(30))
        self.slider.bind(value=self._on_brightness)
        slider_row.add_widget(self.slider)
        slider_row.add_widget(Label(text="100%", font_size=sp(13), color=Theme.MUTED, size_hint_x=None, width=dp(46)))

        meta = BoxLayout(orientation="vertical", size_hint_y=1, spacing=dp(8), padding=(dp(84), 0, 0, 0))
        swatch_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        self._swatch = Widget(size_hint=(None, None), size=(dp(32), dp(32)))
        self._hex_lbl = Label(text="", font_size=sp(14), bold=True, color=Theme.ACCENT_SOFT, halign="left")
        swatch_row.add_widget(self._swatch)
        swatch_row.add_widget(self._hex_lbl)
        meta.add_widget(swatch_row)
        meta.add_widget(Widget())

        wheel_holder = AnchorLayout(anchor_x="center", anchor_y="center", size_hint_x=0.42)
        self.wheel = ColorWheel(
            state,
            on_change=self.refresh,
            on_pick=self._on_color_pick,
            size_hint=(None, None),
            size=(dp(164), dp(164)),
        )
        wheel_holder.add_widget(self.wheel)

        left.add_widget(top)
        left.add_widget(self._auto_btn)
        left.add_widget(slider_row)
        left.add_widget(meta)

        self.add_widget(left)
        self.add_widget(wheel_holder)
        self._bind_swatch()
        self.refresh()

    def _on_auto_press(self, *_args) -> None:
        value = not self.state.auto_light
        prev = self.state.auto_light
        self.state.auto_light = value
        brightness = (
            int(round(self.state.led_brightness * 255)) if led_effective_on(self.state) else 0
        )

        def _call() -> bool:
            return set_lights(
                rgb_hex=rgb_tuple_to_hex(self.state.led_color),
                brightness=brightness,
                auto_light=value,
            )

        def _done(ok: bool) -> None:
            if not ok:
                self.state.auto_light = prev
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def _bind_swatch(self) -> None:
        def _sync_swatch(*_a):
            self._swatch.canvas.clear()
            with self._swatch.canvas:
                Color(*self.state.led_color)
                RoundedRectangle(pos=self._swatch.pos, size=self._swatch.size, radius=[dp(6)])

        self._swatch.bind(pos=_sync_swatch, size=_sync_swatch)
        _sync_swatch()

    def _cancel_led_bridge(self) -> None:
        if self._led_bridge_ev is not None:
            self._led_bridge_ev.cancel()
            self._led_bridge_ev = None

    def _queue_led_bridge(
        self,
        *,
        led_on: bool,
        brightness: float,
        color: tuple[float, float, float],
    ) -> None:
        self._pending_led_on = led_on
        self._pending_led_brightness = brightness
        self._pending_led_color = color
        self._cancel_led_bridge()
        self._led_bridge_ev = Clock.schedule_once(self._flush_led_bridge, LED_BRIDGE_DEBOUNCE_S)

    def _flush_led_bridge(self, _dt: float) -> None:
        self._led_bridge_ev = None
        if (
            self._pending_led_on is None
            or self._pending_led_brightness is None
            or self._pending_led_color is None
        ):
            return
        target_on = self._pending_led_on
        target_brightness = self._pending_led_brightness
        target_color = self._pending_led_color

        def _call() -> bool:
            return apply_led_state(
                led_on=target_on,
                led_brightness=target_brightness,
                led_color=target_color,
                auto_light=False,
            )

        def _done(ok: bool) -> None:
            self._pending_led_on = None
            self._pending_led_brightness = None
            self._pending_led_color = None
            if ok:
                self.state.set_led(on=target_on, brightness=target_brightness)
                self.state.set_led_color(target_color)
            else:
                self.pulse_control_error()
            self.refresh()
            cb = getattr(self, "_refresh_peers", None)
            if cb:
                cb()

        bridge_worker(_call, _done)

    def _on_color_pick(self, rgb: tuple[float, float, float]) -> None:
        if self.state.auto_light:
            return
        led_on = led_effective_on(self.state)
        brightness = self.state.led_brightness
        self._queue_led_bridge(led_on=led_on, brightness=brightness, color=rgb)

    def _on_brightness(self, _inst, value: float) -> None:
        if self.state.auto_light:
            return
        if self.slider.disabled or self._slider_sync:
            return
        v = float(value)
        desired_on = v > LED_OFF_EPS
        self._queue_led_bridge(
            led_on=desired_on,
            brightness=v,
            color=self.state.led_color,
        )

    def refresh(self) -> None:
        pct = int(round(self.state.led_brightness * 100))
        on = led_effective_on(self.state)
        off_note = " (Currently OFF)" if not on else ""
        auto_note = " (Auto)" if self.state.auto_light else ""
        self.status.text = f"Intensity: {pct}%{off_note}{auto_note}"
        manual_locked = led_slider_locked(self.state)
        self.slider.disabled = manual_locked or self.state.auto_light
        self.slider.opacity = 0.45 if self.state.auto_light else 1.0
        self.wheel.set_disabled(self.state.auto_light)
        self._slider_sync = True
        try:
            self.slider.unbind(value=self._on_brightness)
            self.slider.value = self.state.led_brightness
            self.slider.bind(value=self._on_brightness)
        finally:
            self._slider_sync = False
        self._hex_lbl.text = rgb_to_hex(*self.state.led_color)
        self.wheel._redraw()
        sync_auto_button(self._auto_btn, self.state.auto_light)
        if hasattr(self, "_swatch"):
            self._swatch.canvas.clear()
            with self._swatch.canvas:
                Color(*self.state.led_color)
                RoundedRectangle(pos=self._swatch.pos, size=self._swatch.size, radius=[dp(6)])

