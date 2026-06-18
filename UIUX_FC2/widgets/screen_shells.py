"""KV-backed layout shells for sensors and controls screens."""

from __future__ import annotations

from pathlib import Path

from kivy.lang import Builder
from kivy.properties import NumericProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

KV_DIR = Path(__file__).resolve().parent.parent / "kv"
Builder.load_file(str(KV_DIR / "sensors_screen.kv"))
Builder.load_file(str(KV_DIR / "controls_screen.kv"))


class SensorsScreenShell(BoxLayout):
    """Vertical shell: header row + sensor card grid."""

    sensor_grid = ObjectProperty(None)
    clock_lbl = ObjectProperty(None)
    header_height = NumericProperty(52)
    grid_gap = NumericProperty(10)
    card_height = NumericProperty(160)
    clock_font_size = NumericProperty(22)
    screen_padding = NumericProperty(14)


class ControlsScreenShell(BoxLayout):
    """Vertical shell: title + 2x2 device card grid."""

    device_grid = ObjectProperty(None)
    grid_gap = NumericProperty(12)
    card_height = NumericProperty(248)
    screen_padding = NumericProperty(12)
