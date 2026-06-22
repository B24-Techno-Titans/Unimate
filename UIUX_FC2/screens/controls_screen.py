"""Controls dashboard screen builder."""

from __future__ import annotations

from kivy.graphics import Color, Rectangle
from kivy.uix.screenmanager import Screen

from mock_state import MockState
from theme import Theme
from widgets.common import CONTROL_CARD_H, CONTROL_GRID_GAP, CONTROL_PAD
from widgets.control_widgets import LevelDeviceCard, LightBasicCard, LightColorCard
from widgets.screen_shells import ControlsScreenShell


def build_controls_screen(state: MockState) -> Screen:
    screen = Screen(name="controls")
    root = ControlsScreenShell(
        padding=CONTROL_PAD,
        grid_gap=CONTROL_GRID_GAP,
        card_height=CONTROL_CARD_H,
    )

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)

    def sync_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size

    root.bind(pos=sync_bg, size=sync_bg)

    grid = root.device_grid

    fan = LevelDeviceCard("Desk Fan", "fan", state, speed_label="Speed", output_label="Output")
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

    screen.add_widget(root)
    return screen
