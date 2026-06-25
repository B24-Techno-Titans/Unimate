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
    stress: SensorDashboardCard

    def refresh_vitals(self, state: MockState) -> None:
        self.heart.set_value(f"{state.heart_bpm} bpm | {state.spo2_pct:.0f}%", "Heart Rate | SpO2")
        level, color = _stress_level(state.heart_bpm, state.body_temp_c, state.spo2_pct)
        alert_text = "I suggest to take a break" if level == "Stressed" else "HR, Temp, SpO2"
        self.stress.set_value(level, alert_text)
        self.stress.value_label.color = color
        self.stress.sub_label.color = Theme.WARN if level == "Stressed" else Theme.MUTED


def _stress_level(heart_bpm: int, body_temp_c: float, spo2_pct: float) -> tuple[str, tuple[float, float, float, float]]:
    score = 0
    if heart_bpm >= 100:
        score += 45
    elif heart_bpm >= 85:
        score += 25

    if body_temp_c >= 37.8:
        score += 30
    elif body_temp_c >= 37.3:
        score += 15

    if spo2_pct < 95:
        score += 25
    elif spo2_pct < 97:
        score += 10

    if score >= 60:
        return "Stressed", Theme.DANGER
    if score >= 30:
        return "Moderate", Theme.WARN
    return "Normal", Theme.OK


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
        "Heart Rate + O2",
        "heart-rate.png",
        Theme.DANGER,
    )
    body_temp = SensorDashboardCard(
        "User Body Temp",
        "temperature.png",
        Theme.TEXT,
    )
    stress = SensorDashboardCard(
        "Stress Level",
        "oxygen.png",
        Theme.WARN,
    )
    for card in (temp, humidity, lux, heart, body_temp, stress):
        grid.add_widget(card)

    root.add_widget(content)

    temp.set_value(f"{state.room_temp_c:.1f} °C", "Avg. Main Room")
    humidity.set_value(f"{state.humidity_pct:.0f}%", "Main Room")
    lux.set_value(f"{state.lux:.0f} lx", "Lux Intensity")
    body_temp.set_value(f"{state.body_temp_c:.1f} °C", "Status: Normal")

    screen.add_widget(root)
    refs = SensorsRefs(
        temp=temp,
        humidity=humidity,
        lux=lux,
        heart=heart,
        body_temp=body_temp,
        stress=stress,
    )
    refs.refresh_vitals(state)
    return screen, refs
