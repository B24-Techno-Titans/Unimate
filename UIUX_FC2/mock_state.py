"""Mock telemetry and actuator state for the Kivy UI."""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


_STRESS_SEVERITY = {"Normal": 0, "Moderate": 1, "Stressed": 2}


@dataclass
class VitalSnapshot:
    heart_bpm: int
    body_temp_c: float
    spo2_pct: float


class VitalsBuffer:
    MAXLEN = 30

    def __init__(self) -> None:
        self._snapshots: deque[VitalSnapshot] = deque(maxlen=self.MAXLEN)

    def push(
        self,
        heart_bpm: int | None,
        body_temp_c: float | None,
        spo2_pct: float | None,
    ) -> None:
        if heart_bpm is None or body_temp_c is None or spo2_pct is None:
            return
        if heart_bpm <= 0 or body_temp_c <= 0 or spo2_pct <= 0:
            return
        self._snapshots.append(
            VitalSnapshot(
                heart_bpm=int(heart_bpm),
                body_temp_c=float(body_temp_c),
                spo2_pct=float(spo2_pct),
            )
        )

    def snapshots(self) -> list[VitalSnapshot]:
        return list(self._snapshots)

    def averages(self) -> tuple[int | None, float | None, float | None]:
        if not self._snapshots:
            return None, None, None
        n = len(self._snapshots)
        heart = round(sum(s.heart_bpm for s in self._snapshots) / n)
        body_temp = sum(s.body_temp_c for s in self._snapshots) / n
        spo2 = sum(s.spo2_pct for s in self._snapshots) / n
        return heart, body_temp, spo2

    def stress_level_majority(
        self,
        score_fn: Callable[[int, float, float], tuple[str, tuple[float, float, float, float]]],
    ) -> tuple[str | None, tuple[float, float, float, float] | None]:
        if not self._snapshots:
            return None, None
        counts: Counter[str] = Counter()
        colors: dict[str, tuple[float, float, float, float]] = {}
        for snap in self._snapshots:
            level, color = score_fn(snap.heart_bpm, snap.body_temp_c, snap.spo2_pct)
            counts[level] += 1
            colors[level] = color
        level = max(counts, key=lambda name: (counts[name], _STRESS_SEVERITY[name]))
        return level, colors[level]


@dataclass
class MockState:
    room_temp_c: float = 24.0
    humidity_pct: float = 58.0
    lux: float = 320.0
    heart_bpm: int = 72
    body_temp_c: float = 36.8
    spo2_pct: float = 98.0

    fan_level: int = 0  # 0 off, 1 low, 2 high
    humidifier_level: int = 0
    led_on: bool = False
    led_brightness: float = 0.0
    led_color: tuple[float, float, float] = (0.15, 0.92, 1.0)  # face cyan #00E5FF
    auto_fan: bool = False
    auto_humidifier: bool = False
    auto_light: bool = False
    vitals_buffer: VitalsBuffer = field(default_factory=VitalsBuffer)

    def set_fan_off(self) -> None:
        self.fan_level = 0

    def set_fan_level(self, level: int) -> None:
        self.fan_level = _clamp_int(level, 0, 2)

    def cycle_fan(self) -> None:
        self.fan_level = (self.fan_level + 1) % 3

    def set_humidifier_off(self) -> None:
        self.humidifier_level = 0

    def set_humidifier_level(self, level: int) -> None:
        self.humidifier_level = _clamp_int(level, 0, 2)

    def cycle_humidifier(self) -> None:
        self.humidifier_level = (self.humidifier_level + 1) % 3

    def set_led(self, *, on: bool | None = None, brightness: float | None = None) -> None:
        if on is not None:
            self.led_on = bool(on)
        if brightness is not None:
            self.led_brightness = _clamp(float(brightness), 0.0, 1.0)
        if self.led_brightness <= 0.0:
            self.led_on = False

    def set_led_color(self, rgb: tuple[float, float, float]) -> None:
        r, g, b = rgb
        self.led_color = (
            _clamp(float(r), 0.0, 1.0),
            _clamp(float(g), 0.0, 1.0),
            _clamp(float(b), 0.0, 1.0),
        )

    @property
    def fan_on(self) -> bool:
        return self.fan_level > 0

    @property
    def humidifier_on(self) -> bool:
        return self.humidifier_level > 0

    def tick(self) -> None:
        """Small bounded random walk, matching the old mock dashboard behavior."""
        self.room_temp_c = _clamp(self.room_temp_c + random.uniform(-0.16, 0.16), 20.0, 30.0)
        self.humidity_pct = _clamp(self.humidity_pct + random.uniform(-0.55, 0.55), 38.0, 76.0)
        self.lux = _clamp(self.lux + random.uniform(-16.0, 16.0), 80.0, 760.0)
        self.body_temp_c = _clamp(self.body_temp_c + random.uniform(-0.04, 0.04), 36.1, 37.6)
        self.heart_bpm = int(_clamp(self.heart_bpm + random.choice([-1, 0, 0, 1]), 58, 104))
        self.spo2_pct = _clamp(self.spo2_pct + random.uniform(-0.35, 0.35), 94.0, 100.0)
