"""Backward-compatible re-exports for UniMate dashboard screens and widgets."""

from screens.controls_screen import build_controls_screen
from screens.sensors_screen import SensorsRefs, build_sensors_screen
from screens.study_screen import build_study_screen
from widgets.buttons import make_button

__all__ = [
    "SensorsRefs",
    "build_controls_screen",
    "build_sensors_screen",
    "build_study_screen",
    "make_button",
]
