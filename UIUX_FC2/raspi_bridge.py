"""HTTP client for the UniMate FastAPI bridge (Wifi/raspi2.py on port 5000)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:5000"
REQUEST_TIMEOUT_S = 5.0


def _base_url() -> str:
    return os.environ.get("UNIMATE_RASPI_BRIDGE_URL", DEFAULT_BASE_URL).rstrip("/")


def _log(msg: str) -> None:
    print(f"[raspi_bridge] {msg}")


def _post(path: str, payload: dict[str, Any]) -> bool:
    url = f"{_base_url()}{path}"
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_S)
        if response.status_code >= 400:
            _log(f"POST {path} failed: HTTP {response.status_code} — {response.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        _log(f"POST {path} error: {exc}")
        return False


def _get(path: str) -> dict[str, Any] | None:
    url = f"{_base_url()}{path}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        if response.status_code >= 400:
            _log(f"GET {path} failed: HTTP {response.status_code}")
            return None
        return response.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        _log(f"GET {path} error: {exc}")
        return None


@dataclass
class SensorReadings:
    room_temp_c: float | None = None
    humidity_pct: float | None = None
    lux: float | None = None
    heart_bpm: int | None = None
    body_temp_c: float | None = None
    spo2_pct: float | None = None


def _valid_vital(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return value


def _first_number(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in data:
            continue
        try:
            return float(data[key])
        except (TypeError, ValueError):
            continue
    return None


def _parse_message_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            _log(f"Could not parse sensor message JSON: {text[:120]!r}")
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_sensor_payload(data: dict[str, Any]) -> SensorReadings:
    """Map bridge /data fields into UI sensor slots."""
    message = data.get("message")
    payload = _parse_message_payload(message)
    if not payload:
        return SensorReadings()

    heart = _valid_vital(_first_number(payload, "heartRate", "heartrate", "heart_rate"))
    spo2 = _valid_vital(_first_number(payload, "spO2", "spo2", "SpO2"))
    body_temp = _valid_vital(_first_number(payload, "temperature", "body_temp", "bodyTemp"))

    heart_bpm = int(heart) if heart is not None else None
    return SensorReadings(
        room_temp_c=_first_number(payload, "r_temp", "room_temp", "roomTemp"),
        humidity_pct=_first_number(payload, "r_humidity", "humidity", "humidity_pct"),
        lux=_first_number(payload, "lux"),
        heart_bpm=heart_bpm,
        body_temp_c=body_temp,
        spo2_pct=spo2,
    )


def fetch_sensors() -> SensorReadings | None:
    data = _get("/data")
    if data is None:
        return None
    return parse_sensor_payload(data)


def set_fan(level: int, *, auto_fan: bool = False) -> bool:
    level = max(0, min(2, int(level)))
    if auto_fan:
        return _post("/set-fan", {"autoFan": True})
    else:
        return _post("/set-fan", {"fanSpeed": level, "autoFan": False})


def set_humidifier(level: int, *, auto_humid: bool = False) -> bool:
    level = max(0, min(2, int(level)))
    return _post("/set-humid", {"level": level, "autoHumid": bool(auto_humid)})


def rgb_tuple_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = rgb
    return "{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


def set_lights(
    *,
    rgb_hex: str,
    brightness: int,
    auto_light: bool = False,
) -> bool:
    brightness = max(0, min(255, int(brightness)))
    rgb_hex = rgb_hex.lstrip("#").lower()
    if len(rgb_hex) != 6:
        rgb_hex = "ffffff"
    return _post(
        "/set-lights",
        {
            "light": rgb_hex,
            "brightness": brightness,
            "autoLight": bool(auto_light),
        },
    )


def set_color_rgb(r: int, g: int, b: int) -> bool:
    return _post("/set-color", {"r": int(r), "g": int(g), "b": int(b)})


def apply_led_state(
    *,
    led_on: bool,
    led_brightness: float,
    led_color: tuple[float, float, float],
    auto_light: bool = False,
) -> bool:
    """Push ambient light state via /set-lights (brightness 0 when off)."""
    brightness = int(round(led_brightness * 255)) if led_on else 0
    return set_lights(
        rgb_hex=rgb_tuple_to_hex(led_color),
        brightness=brightness,
        auto_light=auto_light,
    )


@dataclass
class DeviceState:
    """Desk-device state as reported by the bridge (its values are authoritative).

    Fields are None when the bridge hasn't seen a change for that device yet,
    so the UI should keep its own value instead of clobbering it with a guess.
    """

    fan_speed: int | None = None  # 0 off, 1 low, 2 fast
    fan_auto: bool = False
    humid_level: int | None = None
    humid_auto: bool = False
    light_rgb: str | None = None  # hex without '#', e.g. "ff8800"
    light_brightness: int | None = None  # 0-255 as last requested
    light_auto: bool = False


def fetch_device_state() -> DeviceState | None:
    data = _get("/device-state")
    if data is None:
        return None

    def _opt_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return DeviceState(
        fan_speed=_opt_int(data.get("fan_speed")),
        fan_auto=bool(data.get("fan_auto", False)),
        humid_level=_opt_int(data.get("humid_level")),
        humid_auto=bool(data.get("humid_auto", False)),
        light_rgb=data.get("light_rgb") or None,
        light_brightness=_opt_int(data.get("light_brightness")),
        light_auto=bool(data.get("light_auto", False)),
    )


def hex_str_to_rgb_tuple(hex_str: str) -> tuple[float, float, float]:
    """'#ff8800' / 'ff8800' -> (1.0, 0.53, 0.0); malformed input -> white."""
    hex_str = (hex_str or "").lstrip("#").lower()
    if len(hex_str) != 6:
        return (1.0, 1.0, 1.0)
    try:
        return tuple(int(hex_str[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)
