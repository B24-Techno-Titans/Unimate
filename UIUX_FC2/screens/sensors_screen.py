"""Sensors dashboard screen builder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import Screen

from mock_state import MockState
from theme import Theme
from widgets.animations import CircuitBackdrop
from widgets.common import SENSOR_CARD_H, SENSOR_CLOCK, SENSOR_GRID_GAP, SENSOR_HEADER_H, SENSOR_PAD
from widgets.panels import SensorDashboardCard
from widgets.screen_shells import SensorsScreenShell


@dataclass
class SensorsRefs:
    temp: SensorDashboardCard
    humidity: SensorDashboardCard
    lux: SensorDashboardCard
    heart: SensorDashboardCard
    body_temp: SensorDashboardCard
    spo2: SensorDashboardCard


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

    content = SensorsScreenShell(
        padding=SENSOR_PAD,
        header_height=SENSOR_HEADER_H,
        grid_gap=SENSOR_GRID_GAP,
        card_height=SENSOR_CARD_H,
        clock_font_size=SENSOR_CLOCK,
    )
    grid = content.sensor_grid
    clock_lbl = content.clock_lbl

    def _update_clock(_dt: float = 0) -> None:
        now = datetime.now()
        clock_lbl.text = now.strftime("%H:%M | %b %d, %Y").upper()

    _update_clock()
    Clock.schedule_interval(_update_clock, 30.0)

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

    root.add_widget(content)

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
