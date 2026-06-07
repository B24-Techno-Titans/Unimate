"""Smart Home & Health: study, sensor, and control screens for UniMate Kivy UI."""

from __future__ import annotations

import json
import math
import random
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, InstructionGroup, Line, PopMatrix, PushMatrix, Rectangle, Rotate, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.graphics.vertex_instructions import Ellipse
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from mock_state import MockState
from raspi_bridge import apply_led_state, rgb_tuple_to_hex, set_fan, set_humidifier, set_lights
from nlp_functions import (
    AskBunnyHandlers,
    CAPTION_AUDIO_LAG_S,
    QUIZ_ANSWER_TIME_LIMIT_S,
    QuizEvaluation,
    caption_target_index,
    cleanup_wav,
    evaluate_quiz_answer,
    format_mmss,
    listen_for_quiz_answer,
    run_ask_bunny_session,
    stop_playback,
    words_window,
)
from theme import Theme

_ICONS_DIR = Path(__file__).resolve().parent / "icons"
_DEVICE_ICON_FILES = {
    "fan": "fan_mask.png",
    "humidifier": "drop_mask.png",
    "led": "sun_mask.png",
}
_icon_texture_cache: dict[str, object] = {}
_sensor_icon_cache: dict[str, object] = {}
_study_icon_cache: dict[str, object] = {}

# Sensors dashboard — sized for 1024×600 kiosk
SENSOR_PAD = dp(14)
SENSOR_HEADER_H = dp(52)
SENSOR_FOOTER_H = dp(36)
SENSOR_GRID_GAP = dp(10)
SENSOR_CARD_H = dp(160)
SENSOR_ICON = dp(84)
SENSOR_ICON_SLOT = dp(112)
# Typography aligned with Controls tab (CONTROL_* / Theme.TITLE)
SENSOR_STATUS = sp(12)


def _device_icon_texture(kind: str):
    if kind not in _icon_texture_cache:
        fname = _DEVICE_ICON_FILES[kind]
        path = _ICONS_DIR / fname
        if not path.is_file():
            raise FileNotFoundError(f"Device icon not found: {path}")
        _icon_texture_cache[kind] = CoreImage(str(path)).texture
    return _icon_texture_cache[kind]


def _sensor_icon_texture(filename: str):
    if filename not in _sensor_icon_cache:
        path = _ICONS_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Sensor icon not found: {path}")
        _sensor_icon_cache[filename] = CoreImage(str(path)).texture
    return _sensor_icon_cache[filename]


def _study_icon_texture(filename: str):
    if filename not in _study_icon_cache:
        path = _ICONS_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Study icon not found: {path}")
        _study_icon_cache[filename] = CoreImage(str(path)).texture
    return _study_icon_cache[filename]


# Controls grid — sized for 1024×600 windowed / fullscreen kiosk
CONTROL_CARD_H = dp(248)
CONTROL_ICON = dp(112)
CONTROL_ICON_SLOT = dp(148)
CONTROL_SMALL_ICON = dp(70)
CONTROL_GRID_GAP = dp(12)
CONTROL_PAD = dp(12)
CONTROL_TITLE = sp(25)
CONTROL_STATUS = sp(17)
SENSOR_CLOCK = sp(22)
CONTROL_BUTTON_TEXT = sp(14)

# Controls device icon animation — per-effect rates (lower = slower)
_FAN_PHASE_L1 = 2.4
_FAN_PHASE_L2 = 4.8
_FAN_ROTATE = 3.6
_HUM_PHASE_L1 = 8.8
_HUM_PHASE_L2 = 16.0
_HUM_PULSE = 0.95
_HUM_RISE_L1 = 13.5
_HUM_RISE_L2 = 21.0
_LED_PHASE_BASE = 0.6
_LED_PHASE_BRIGHT = 0.9
_LED_ROTATE_BASE = 0.14
_LED_ROTATE_BRIGHT = 0.32
_LED_OFF_EPS = 0.02
# Touch panels often deliver touch + emulated mouse as duplicate on_press events.
_CONTROL_PRESS_DEBOUNCE_S = 0.35
_LED_TOGGLE_DEBOUNCE_S = _CONTROL_PRESS_DEBOUNCE_S
_LED_BRIDGE_DEBOUNCE_S = 0.35
_CONTROL_BTN_WIDTH = dp(240)
_CONTROL_BTN_HEIGHT = dp(48)


def _make_auto_button() -> Button:
    return Button(
        text="AUTO",
        size_hint=(None, None),
        size=(_CONTROL_BTN_WIDTH, _CONTROL_BTN_HEIGHT),
        bold=True,
        font_size=CONTROL_BUTTON_TEXT,
        background_normal="",
        background_color=Theme.PANEL_HI,
        color=Theme.TEXT,
    )


def _sync_auto_button(btn: Button, enabled: bool) -> None:
    if enabled:
        btn.text = "AUTO ON"
        btn.background_color = Theme.CYAN
        btn.color = Theme.BLACK
    else:
        btn.text = "AUTO"
        btn.background_color = Theme.PANEL_HI
        btn.color = Theme.TEXT


def _bridge_worker(call: Callable[[], bool], callback: Callable[[bool], None]) -> None:
    """Run a bridge HTTP call off the UI thread; invoke callback on the main thread."""

    def _run() -> None:
        ok = False
        try:
            ok = call()
        except Exception as exc:
            print(f"[dashboard] bridge call error: {exc}")
        Clock.schedule_once(lambda _dt: callback(ok), 0)

    threading.Thread(target=_run, daemon=True).start()


def _led_effective_on(state: MockState) -> bool:
    """Light is visibly on (button label, status copy, icons)."""
    return state.led_on and state.led_brightness > _LED_OFF_EPS


def _led_slider_locked(state: MockState) -> bool:
    """OFF via power button — brightness stored, slider not draggable."""
    return not state.led_on and state.led_brightness > _LED_OFF_EPS


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
    """h in [0, 1], s/v in [0, 1]."""
    if s <= 0.0:
        return v, v, v
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0:
        return v, t, p
    if i == 1:
        return q, v, p
    if i == 2:
        return p, v, t
    if i == 3:
        return p, q, v
    if i == 4:
        return t, p, v
    return v, p, q


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        int(_clamp_byte(r)),
        int(_clamp_byte(g)),
        int(_clamp_byte(b)),
    )


def _clamp_byte(c: float) -> int:
    return max(0, min(255, int(round(c * 255))))


def _rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if d < 1e-6:
        return 0.0, 0.0, mx
    s = d / mx
    if mx == r:
        h = (g - b) / d % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h / 6.0, s, mx


def _build_hsv_wheel_texture(size: int) -> Texture:
    """Smooth HSV disk: hue on angle, saturation from center to edge (Kivy bottom-up rows)."""
    size = max(64, min(384, int(size)))
    half = size / 2.0
    buf = bytearray(size * size * 4)
    idx = 0
    for ty in range(size):
        for tx in range(size):
            dx = (tx + 0.5 - half) / half
            dy = (ty + 0.5 - half) / half
            dist = math.hypot(dx, dy)
            if dist > 1.05:
                buf[idx : idx + 4] = (0, 0, 0, 0)
            else:
                angle = math.atan2(dy, dx)
                hue = (math.degrees(angle) + 360.0) % 360.0 / 360.0
                sat = min(1.0, dist)
                r, g, b = _hsv_to_rgb(hue, sat, 1.0)
                alpha = 255
                if dist > 1.0:
                    alpha = int(255 * (1.05 - dist) / 0.05)
                buf[idx] = _clamp_byte(r)
                buf[idx + 1] = _clamp_byte(g)
                buf[idx + 2] = _clamp_byte(b)
                buf[idx + 3] = alpha
            idx += 4
    tex = Texture.create(size=(size, size), colorfmt="rgba")
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    return tex


# ---------------------------------------------------------------------------
# Study dashboard
# ---------------------------------------------------------------------------

_STUDY_TONE_PATH = Path(__file__).resolve().parent / "tone.mp3"
STUDY_PAD = dp(16)
STUDY_HEADER_H = dp(56)
STUDY_GRID_GAP = dp(12)
STUDY_TILE_LABEL = sp(15)
STUDY_TILE_ICON = dp(108)
STUDY_TITLE = sp(40)
STUDY_ASK_POPUP_TITLE = sp(38)
STUDY_ASK_ICON_ROW_H = dp(150)
STUDY_ASK_DOTS_H = dp(56)
STUDY_ASK_DOT_SPACING = dp(40)
STUDY_ASK_POPUP_SIZE = (0.92, 0.86)
STUDY_ASK_POPUP_PAD = (dp(40), dp(36), dp(40), dp(36))
STUDY_RESPOND_CAPTION_H = dp(120)
STUDY_RESPOND_PROGRESS_H = dp(32)
STUDY_WHEEL_ROW_H = dp(44)
STUDY_WHEEL_VISIBLE_ROWS = 5
STUDY_WHEEL_SCROLL_ANIM_S = 0.22
STUDY_WHEEL_SCROLL_SETTLE_S = 0.08
STUDY_WHEEL_CENTER_ROW = (STUDY_WHEEL_VISIBLE_ROWS - 1) // 2

# MCQ popup — same footprint as Ask From Bunny
STUDY_MCQ_POPUP_SIZE = STUDY_ASK_POPUP_SIZE
STUDY_MCQ_POPUP_PAD = (dp(40), dp(14), dp(40), dp(36))
STUDY_MCQ_QUESTION_H = dp(118)
STUDY_MCQ_ANSWER_H = dp(78)
STUDY_MCQ_ANSWER_RADIUS = dp(18)
STUDY_MCQ_GRID_GAP = dp(14)
STUDY_MCQ_NAV_H = dp(50)
STUDY_MCQ_NAV_W = dp(150)
STUDY_MCQ_QUESTION_FONT = sp(28)
STUDY_MCQ_ANSWER_FONT = sp(24)
STUDY_MCQ_NAV_FONT = sp(20)
STUDY_MCQ_ANSWER_BORDER = dp(0.9)
STUDY_MCQ_ANSWER_BORDER_SEL = dp(1.2)
# Touch displays can emit touch + emulated mouse presses for one finger tap.
STUDY_MCQ_ACTION_DEBOUNCE_S = 0.4
STUDY_MCQ_TOUCH_SLOP = dp(22)
STUDY_MCQ_SCROLL_SLOP = dp(14)
STUDY_MCQ_FILE_ROW_H = dp(72)
STUDY_MCQ_FILE_LIST_FONT = sp(22)
STUDY_MCQ_FILE_SUB_FONT = sp(22)
STUDY_MCQ_RESULTS_ROW_FONT = sp(20)
STUDY_MCQ_RESULTS_ROW_H = dp(44)
STUDY_QUIZ_ANSWER_SECTION_PAD = dp(14)
STUDY_SUMMARY_BODY_FONT = sp(22)
STUDY_SUMMARY_H3_FONT = sp(26)
STUDY_SUMMARY_H4_FONT = sp(24)

_SAVED_MCQ_DIR = Path(__file__).resolve().parent.parent / "saved"
_SAVED_MCQ_MAX_FILES = 10

_QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "questions"
_QUESTIONS_MAX_FILES = 10

_SUMMARIES_DIR = Path(__file__).resolve().parent.parent / "summaries"
_SUMMARIES_MAX_FILES = 10
_PDF_MODE_STATUS_PATH = Path(__file__).resolve().parent.parent / "pdf_mode" / "pdf_mode_status.json"
_VOICE_TRIGGER_PATH = Path(__file__).resolve().parent.parent / "alexa" / "voice_trigger.json"

_MCQ_LETTERS = ("A", "B", "C", "D")


def _schedule_touch_safe(
    owner: object,
    callback: Callable[[], None],
    *,
    debounce_s: float = STUDY_MCQ_ACTION_DEBOUNCE_S,
) -> None:
    """Coalesce duplicate touch+mouse releases into one callback."""
    last_at = getattr(owner, "_touch_safe_last_at", -1.0)
    now = Clock.get_time()
    if now - last_at < debounce_s:
        return
    ev = getattr(owner, "_touch_safe_ev", None)
    if ev is not None:
        return

    def _run(_dt: float) -> None:
        owner._touch_safe_ev = None
        owner._touch_safe_last_at = Clock.get_time()
        callback()

    owner._touch_safe_ev = Clock.schedule_once(_run, 0)


def _bind_touch_safe_on_press(
    btn: Button,
    callback: Callable[[], None],
    *,
    debounce_s: float = _CONTROL_PRESS_DEBOUNCE_S,
) -> None:
    """Bind on_press while coalescing duplicate touch + emulated mouse events."""

    def _handler(*_args) -> None:
        if btn.disabled:
            return
        _schedule_touch_safe(btn, callback, debounce_s=debounce_s)

    btn.bind(on_press=_handler)


def _touch_is_tap(
    touch,
    *,
    down_x: float,
    down_y: float,
    slop: float = STUDY_MCQ_TOUCH_SLOP,
) -> bool:
    if not touch:
        return False
    return abs(touch.x - down_x) <= slop and abs(touch.y - down_y) <= slop


def _quiz_display_name(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"\s+copy\s+(\d+)$", r" (Set \1)", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+copy$", " (Set 1)", stem, flags=re.IGNORECASE)
    return stem.replace("-", " — ")


def _list_saved_mcq_files() -> list[Path]:
    if not _SAVED_MCQ_DIR.is_dir():
        return []
    files = [p for p in _SAVED_MCQ_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:_SAVED_MCQ_MAX_FILES]


def _answer_index(options: list[str], answer_raw: object) -> int | None:
    if isinstance(answer_raw, bool):
        return None
    if isinstance(answer_raw, int):
        return max(0, min(3, answer_raw))
    if not isinstance(answer_raw, str):
        return None
    text = answer_raw.strip()
    if not text:
        return None
    try:
        return options.index(text)
    except ValueError:
        pass
    lower = text.casefold()
    for i, opt in enumerate(options):
        if opt.strip().casefold() == lower:
            return i
    return None


def _normalize_mcq_item(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    question = raw.get("question")
    options_raw = raw.get("options")
    if not isinstance(question, str) or not question.strip():
        return None
    if not isinstance(options_raw, list) or len(options_raw) < 2:
        return None
    options = [str(o) for o in options_raw[:4]]
    while len(options) < 4:
        options.append("")
    answer_idx = _answer_index(options, raw.get("answer"))
    if answer_idx is None:
        return None
    return {"question": question.strip(), "options": options, "answer": answer_idx}


def _load_mcqs_from_file(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dashboard] MCQ load error ({path.name}): {exc}")
        return []
    mcqs = data.get("mcqs") if isinstance(data, dict) else None
    if not isinstance(mcqs, list):
        return []
    out: list[dict[str, object]] = []
    for item in mcqs:
        norm = _normalize_mcq_item(item)
        if norm is not None:
            out.append(norm)
    return out


def _list_quiz_files() -> list[Path]:
    if not _QUESTIONS_DIR.is_dir():
        return []
    files = [p for p in _QUESTIONS_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:_QUESTIONS_MAX_FILES]


def _essay_questions_from_payload(data: object) -> list | None:
    if not isinstance(data, dict):
        return None
    essay = data.get("essay_questions")
    if isinstance(essay, list):
        return essay
    nested = data.get("questions")
    if isinstance(nested, dict):
        essay_nested = nested.get("essay_questions")
        if isinstance(essay_nested, list):
            return essay_nested
    return None


def _normalize_quiz_item(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    answer_raw = raw.get("answer")
    answer = answer_raw.strip() if isinstance(answer_raw, str) else ""
    return {"question": question.strip(), "answer": answer}


def _load_quiz_questions_from_file(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dashboard] Quiz load error ({path.name}): {exc}")
        return []
    essay_list = _essay_questions_from_payload(data)
    if not isinstance(essay_list, list):
        return []
    out: list[dict[str, object]] = []
    for item in essay_list:
        norm = _normalize_quiz_item(item)
        if norm is not None:
            out.append(norm)
    return out


def _list_summary_files() -> list[Path]:
    if not _SUMMARIES_DIR.is_dir():
        return []
    files = [p for p in _SUMMARIES_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:_SUMMARIES_MAX_FILES]


def _summary_text_from_payload(data: object) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("summary", "context", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _load_summary_text_from_file(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dashboard] Summary load error ({path.name}): {exc}")
        return ""
    return _summary_text_from_payload(data)


def _write_pdf_mode_status(context: str, active: bool) -> None:
    payload = {"pdf_mode_active": active, "context": context}
    try:
        _PDF_MODE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PDF_MODE_STATUS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[dashboard] pdf_mode status write error: {exc}")


def _write_voice_trigger(trigger: bool) -> None:
    payload = {"trigger": trigger, "requested_at": time.time() if trigger else None}
    try:
        _VOICE_TRIGGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VOICE_TRIGGER_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[dashboard] voice trigger write error: {exc}")


def _rgba_to_markup_color(rgba: tuple[float, float, float, float]) -> str:
    r, g, b, _ = rgba
    return f"{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def _escape_kivy_plain_text(text: str) -> str:
    """Keep user-authored brackets from being parsed as Kivy markup tags."""
    return text.replace("[", "(").replace("]", ")")


def _markdown_inline_to_kivy(text: str) -> str:
    accent = _rgba_to_markup_color(Theme.ACCENT_SOFT)
    pattern = re.compile(
        r"`([^`\n]+)`"  # inline code
        r"|\*\*(.+?)\*\*"  # bold
        r"|(?<!\*)\*([^*\n]+?)\*(?!\*)"  # italic
    )
    parts: list[str] = []
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            parts.append(_escape_kivy_plain_text(text[pos : match.start()]))
        if match.group(1) is not None:
            inner = _escape_kivy_plain_text(match.group(1))
            parts.append(f"[font=DejaVuSansMono][color={accent}]{inner}[/color][/font]")
        elif match.group(2) is not None:
            inner = _markdown_inline_to_kivy(match.group(2))
            parts.append(f"[b]{inner}[/b]")
        elif match.group(3) is not None:
            inner = _markdown_inline_to_kivy(match.group(3))
            parts.append(f"[i]{inner}[/i]")
        pos = match.end()
    parts.append(_escape_kivy_plain_text(text[pos:]))
    return "".join(parts)


def _markdown_to_kivy_markup(md: str) -> str:
    accent = _rgba_to_markup_color(Theme.ACCENT_SOFT)
    muted = _rgba_to_markup_color(Theme.MUTED)
    out_lines: list[str] = []
    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        if re.fullmatch(r"[-*]{3,}", stripped):
            out_lines.append(f"[color={muted}]────────────────────────────────[/color]")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = _markdown_inline_to_kivy(heading.group(2).strip())
            size = int(STUDY_SUMMARY_H3_FONT if level <= 3 else STUDY_SUMMARY_H4_FONT)
            out_lines.append(
                f"[size={size}][b][color={accent}]{title}[/color][/b][/size]"
            )
            continue
        bullet = re.match(r"^(\s*)[*+-]\s+(.+)$", line)
        if bullet:
            indent = "    " * (len(bullet.group(1)) // 2)
            body = _markdown_inline_to_kivy(bullet.group(2))
            out_lines.append(f"{indent}• {body}")
            continue
        numbered = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if numbered:
            indent = "    " * (len(numbered.group(1)) // 2)
            body = _markdown_inline_to_kivy(numbered.group(3))
            out_lines.append(f"{indent}{numbered.group(2)}. {body}")
            continue
        out_lines.append(_markdown_inline_to_kivy(stripped))
    return "\n".join(out_lines)


def _format_timer_seconds(total: int) -> str:
    total = max(0, int(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Themed widgets
# ---------------------------------------------------------------------------


def make_button(
    text: str,
    on_press: Callable[..., None],
    *,
    accent: bool = False,
    width: float = dp(190),
    height: float = dp(44),
) -> Button:
    return GlowFlatButton(
        text,
        on_press,
        accent=accent,
        width=width,
        height=height,
    )


class GlowFlatButton(Button):
    """Themed flat button with cyan glow on press."""

    _RADIUS = dp(12)

    def __init__(
        self,
        text: str,
        on_press: Callable[..., None],
        *,
        accent: bool = False,
        width: float = dp(190),
        height: float = dp(44),
        **kwargs,
    ):
        self._accent = accent
        self._pressed = False
        self._on_press_cb = on_press
        fg = Theme.BLACK if accent else Theme.TEXT
        super().__init__(
            text=text,
            size_hint=(None, None),
            width=width,
            height=height,
            bold=True,
            font_size=Theme.CAPTION,
            color=fg,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*(Theme.CYAN if accent else Theme.PANEL_HI))
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.bind(on_press=self._on_button_press)

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._pressed:
            self._fill_color.rgba = Theme.CYAN if self._accent else Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.CYAN if self._accent else Theme.PANEL_HI
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.2)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._set_pressed(True)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed and not self.collide_point(*touch.pos):
            self._set_pressed(False)
        return result

    def _on_button_press(self, *_args) -> None:
        if self.disabled:
            return
        self._set_pressed(True)

        def _after_glow(_dt: float) -> None:
            self._set_pressed(False)
            _schedule_touch_safe(self, self._on_press_cb, debounce_s=_CONTROL_PRESS_DEBOUNCE_S)

        Clock.schedule_once(_after_glow, 0.14)


class GlowIconButton(Button):
    """Small icon button (e.g. popup close) with press glow."""

    _RADIUS = dp(10)

    def __init__(self, text: str = "×", **kwargs):
        self._pressed = False
        kwargs.setdefault("font_size", sp(28))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", Theme.ACCENT_SOFT)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(text=text, **kwargs)
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._pressed:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.2)

    def on_touch_down(self, touch):
        if not self.disabled and self.collide_point(*touch.pos):
            self._set_pressed(True)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if self._pressed:
            Clock.schedule_once(lambda _dt: self._set_pressed(False), 0.14)
        return result


_CONTROL_ERROR_PULSE_S = 0.75


class GlowPanel(BoxLayout):
    """Dark glass card with violet neon frame glow + cyan hairline."""

    def __init__(self, *, fill=None, **kwargs):
        self.padding = kwargs.pop("padding", Theme.PAD)
        self.spacing = kwargs.pop("spacing", Theme.GAP)
        super().__init__(**kwargs)
        self._fill = fill or Theme.PANEL
        self._glow_lines: list[Line] = []
        self._glow_colors: list[Color] = []
        self._error_pulse_ev = None
        self._error_pulse_start = 0.0
        self._error_pulse_duration = _CONTROL_ERROR_PULSE_S
        self._error_pulse_until = 0.0
        with self.canvas.before:
            self._fill_color = Color(*self._fill)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=Theme.RADIUS)
            for alpha, width_mult in Theme.CARD_GLOW_LAYERS:
                glow_color = Color(Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
                self._glow_colors.append(glow_color)
                ln = Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS),
                    width=dp(2.2) * width_mult,
                    cap="round",
                )
                self._glow_lines.append(ln)
            self._border_accent = Color(*Theme.BORDER_CYAN_SOFT)
            self._hairline = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS),
                width=dp(1.15),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def _sync_canvas(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        rr = (self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS)
        for ln in self._glow_lines:
            ln.rounded_rectangle = rr
        self._hairline.rounded_rectangle = rr

    def pulse_control_error(self, duration: float = _CONTROL_ERROR_PULSE_S) -> None:
        """Brief red pulse on the whole card when a device control call fails."""
        self._error_pulse_start = time.monotonic()
        self._error_pulse_duration = duration
        self._error_pulse_until = self._error_pulse_start + duration
        if self._error_pulse_ev is None:
            self._error_pulse_ev = Clock.schedule_interval(self._tick_control_error_pulse, 1 / 30.0)

    def _tick_control_error_pulse(self, dt: float) -> None:
        if time.monotonic() >= self._error_pulse_until:
            self._stop_control_error_pulse()
            return
        progress = (time.monotonic() - self._error_pulse_start) / self._error_pulse_duration
        progress = max(0.0, min(1.0, progress))
        pulse = math.sin(progress * math.pi)
        strength = 0.22 + 0.18 * pulse
        dr, dg, db, _ = Theme.DANGER
        br, bg, bb, ba = self._fill
        self._fill_color.rgba = (
            br + (dr - br) * strength,
            bg + (dg - bg) * strength,
            bb + (db - bb) * strength,
            ba,
        )
        vr, vg, vb = Theme.VIOLET[:3]
        for glow_color, (base_alpha, _) in zip(self._glow_colors, Theme.CARD_GLOW_LAYERS):
            blend = 0.45 + 0.35 * pulse
            glow_color.rgba = (
                vr + (dr - vr) * blend,
                vg + (dg - vg) * blend,
                vb + (db - vb) * blend,
                base_alpha * (0.75 + 0.35 * pulse),
            )
        hr, hg, hb, _ = Theme.BORDER_CYAN_SOFT
        self._border_accent.rgba = (
            hr + (dr - hr) * strength,
            hg + (dg - hg) * strength,
            hb + (db - hb) * strength,
            0.28 + 0.22 * pulse,
        )

    def _restore_panel_colors(self) -> None:
        self._fill_color.rgba = self._fill
        for glow_color, (alpha, _) in zip(self._glow_colors, Theme.CARD_GLOW_LAYERS):
            glow_color.rgba = (Theme.VIOLET[0], Theme.VIOLET[1], Theme.VIOLET[2], alpha)
        self._border_accent.rgba = Theme.BORDER_CYAN_SOFT

    def _stop_control_error_pulse(self) -> None:
        if self._error_pulse_ev is not None:
            self._error_pulse_ev.cancel()
            self._error_pulse_ev = None
        self._restore_panel_colors()


class MCQChoiceButton(Button):
    """Touchable rounded MCQ answer tile with selection and check feedback glow."""

    def __init__(
        self,
        option_index: int,
        *,
        on_select: Callable[[int], None],
        **kwargs,
    ):
        super().__init__(
            font_size=STUDY_MCQ_ANSWER_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            padding=(dp(14), dp(10)),
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._option_index = option_index
        self._on_select = on_select
        self._selected = False
        self._feedback: str | None = None  # None | "correct" | "wrong"
        self._feedback_phase = 0.0
        self._feedback_tick = None
        self._feedback_boost_until = 0.0
        self.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width - dp(24), None)))
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL_HI)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[STUDY_MCQ_ANSWER_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(
                    self.x,
                    self.y,
                    self.width,
                    self.height,
                    STUDY_MCQ_ANSWER_RADIUS,
                ),
                width=STUDY_MCQ_ANSWER_BORDER,
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self._touch_down_pos: tuple[float, float] | None = None
        self._touch_id = None
        self._pressed = False
        self._select_glow_ev = None

    def _emit_select(self) -> None:
        if self.disabled:
            return
        _schedule_touch_safe(self, lambda: self._on_select(self._option_index))

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._touch_id = touch.id
        self._touch_down_pos = (touch.x, touch.y)
        self._pressed = True
        self._sync_canvas()
        touch.grab(self)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        if self._touch_id != touch.id or self._touch_down_pos is None:
            self._pressed = False
            self._sync_canvas()
            return True
        x0, y0 = self._touch_down_pos
        self._touch_down_pos = None
        self._touch_id = None
        if not self.collide_point(*touch.pos):
            self._pressed = False
            self._sync_canvas()
            return True
        if not _touch_is_tap(touch, down_x=x0, down_y=y0):
            self._pressed = False
            self._sync_canvas()
            return True
        self._pressed = True
        self._sync_canvas()
        if self._select_glow_ev is not None:
            self._select_glow_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._select_glow_ev = None
            self._pressed = False
            self._sync_canvas()
            self._emit_select()

        self._select_glow_ev = Clock.schedule_once(_after_glow, 0.14)
        return True

    def set_label(self, text: str) -> None:
        self.text = text

    def set_visual(self, *, selected: bool = False, feedback: str | None = None) -> None:
        self._selected = selected
        next_feedback = feedback if feedback in ("correct", "wrong") else None
        if self._feedback != next_feedback:
            self._feedback_phase = 0.0
        self._feedback = next_feedback
        if self._feedback is not None:
            self._start_feedback_tick()
        else:
            self._stop_feedback_tick()
        self._sync_canvas()

    def pulse_feedback(self, feedback: str) -> None:
        if feedback not in ("correct", "wrong"):
            return
        self._feedback_boost_until = time.monotonic() + 0.42
        self._start_feedback_tick()
        self._apply_feedback_glow()

    def _start_feedback_tick(self) -> None:
        if self._feedback_tick is None:
            self._feedback_tick = Clock.schedule_interval(self._tick_feedback_glow, 1 / 30.0)

    def _stop_feedback_tick(self) -> None:
        if self._feedback_tick is not None:
            self._feedback_tick.cancel()
            self._feedback_tick = None

    def _tick_feedback_glow(self, dt: float) -> None:
        if self._feedback is None:
            self._stop_feedback_tick()
            return
        self._feedback_phase += dt
        self._apply_feedback_glow()

    def _apply_feedback_glow(self) -> None:
        if self._feedback == "correct":
            glow = Theme.OK
            outer_alpha = 0.30
            inner_alpha = 0.52
        elif self._feedback == "wrong":
            glow = Theme.DANGER
            outer_alpha = 0.32
            inner_alpha = 0.55
        else:
            return

        # Match the robot eyes' breathing feel: bigger/smaller glow, not fixed width.
        pulse = 0.88 + 0.12 * math.sin(self._feedback_phase * 2.0)
        boost = 1.0
        if time.monotonic() < self._feedback_boost_until:
            boost = 1.22
        self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4 * pulse * boost
        self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5 * pulse * boost
        alpha_boost = 1.25 if boost > 1.0 else 1.0
        self._outer_glow_color.rgba = (
            glow[0],
            glow[1],
            glow[2],
            min(0.72, outer_alpha * alpha_boost),
        )
        self._inner_glow_color.rgba = (
            glow[0],
            glow[1],
            glow[2],
            min(0.85, inner_alpha * alpha_boost),
        )

    def _sync_canvas(self, *_args) -> None:
        if (
            self._pressed
            and self._feedback is None
            and not self._selected
        ):
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
            self._fill.pos = self.pos
            self._fill.size = self.size
            rr = (
                self.x,
                self.y,
                self.width,
                self.height,
                STUDY_MCQ_ANSWER_RADIUS,
            )
            self._outer_glow.rounded_rectangle = rr
            self._inner_glow.rounded_rectangle = rr
            self._border.rounded_rectangle = (
                self.x,
                self.y,
                self.width,
                self.height,
                STUDY_MCQ_ANSWER_RADIUS,
            )
            self._border.width = border_w
            return

        if self._feedback == "correct":
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.OK
            self._apply_feedback_glow()
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._feedback == "wrong":
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.DANGER
            self._apply_feedback_glow()
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._selected:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4
            self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 4.4
            self._inner_glow.width = STUDY_MCQ_ANSWER_BORDER_SEL * 2.5
            self.color = Theme.ACCENT_SOFT
            border_w = STUDY_MCQ_ANSWER_BORDER
        self._fill.pos = self.pos
        self._fill.size = self.size
        rr = (
            self.x,
            self.y,
            self.width,
            self.height,
            STUDY_MCQ_ANSWER_RADIUS,
        )
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            STUDY_MCQ_ANSWER_RADIUS,
        )
        self._border.width = border_w


class MCQNavButton(Button):
    """Prev / Check / Next — touch-safe (no duplicate touch+mouse presses)."""

    _BTN_RADIUS = dp(14)

    def __init__(self, label: str, **kwargs):
        self._on_safe_press: Callable[[], None] | None = kwargs.pop("on_safe_press", None)
        super().__init__(
            text=label,
            font_size=STUDY_MCQ_NAV_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            **kwargs,
        )
        self._flash_ev = None
        self._glow_release_ev = None
        self._flash_active = False
        self._pressed = False
        self._touch_down_pos: tuple[float, float] | None = None
        self._touch_id = None
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._BTN_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._BTN_RADIUS),
                width=dp(1.5),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)

    def bind_safe_press(self, callback: Callable[[], None]) -> None:
        self._on_safe_press = callback

    def _set_pressed(self, active: bool) -> None:
        self._pressed = active
        self._sync_canvas()

    def _emit_safe_press(self) -> None:
        if self._on_safe_press is None or self.disabled:
            return
        _schedule_touch_safe(self, self._on_safe_press)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._touch_id = touch.id
        self._touch_down_pos = (touch.x, touch.y)
        self._set_pressed(True)
        touch.grab(self)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        if self._touch_id != touch.id or self._touch_down_pos is None:
            self._set_pressed(False)
            return True
        x0, y0 = self._touch_down_pos
        self._touch_down_pos = None
        self._touch_id = None
        if not self.collide_point(*touch.pos):
            self._set_pressed(False)
            return True
        if not _touch_is_tap(touch, down_x=x0, down_y=y0):
            self._set_pressed(False)
            return True
        self._set_pressed(True)
        if self._glow_release_ev is not None:
            self._glow_release_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._glow_release_ev = None
            self._set_pressed(False)
            self._emit_safe_press()

        self._glow_release_ev = Clock.schedule_once(_after_glow, 0.14)
        return True

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._BTN_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._flash_active:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.22)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.12)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.22)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._pressed:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.5)

    def flash_danger(self, duration: float = 0.35) -> None:
        if self._flash_ev is not None:
            self._flash_ev.cancel()
        self._flash_active = True
        self._sync_canvas()

        def _restore(_dt: float) -> None:
            self._flash_ev = None
            self._flash_active = False
            self._sync_canvas()

        self._flash_ev = Clock.schedule_once(_restore, duration)


class MCQFileListScroll(ScrollView):
    """Marks touches that moved enough to count as scrolling (not a row tap)."""

    def on_touch_down(self, touch):
        touch.ud["mcq_list_scrolled"] = False
        touch.ud["mcq_list_down_x"] = touch.x
        touch.ud["mcq_list_down_y"] = touch.y
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if abs(touch.y - touch.ud.get("mcq_list_down_y", touch.y)) > STUDY_MCQ_SCROLL_SLOP:
            touch.ud["mcq_list_scrolled"] = True
        if abs(touch.x - touch.ud.get("mcq_list_down_x", touch.x)) > STUDY_MCQ_SCROLL_SLOP:
            touch.ud["mcq_list_scrolled"] = True
        return super().on_touch_move(touch)


class MCQFileRow(BoxLayout):
    """Scroll-friendly quiz file row — tap only when the finger did not scroll."""

    _ROW_RADIUS = dp(14)

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        on_pick: Callable[[], None],
        **kwargs,
    ):
        super().__init__(
            orientation="vertical",
            padding=(dp(14), dp(10)),
            spacing=dp(2),
            size_hint_y=None,
            height=STUDY_MCQ_FILE_ROW_H,
            **kwargs,
        )
        self._on_pick = on_pick
        self._touched = False
        self._pick_delay_ev = None
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._ROW_RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._ROW_RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        title_lbl = Label(
            text=title,
            font_size=STUDY_MCQ_FILE_LIST_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_y=0.62,
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        sub_lbl = Label(
            text=subtitle,
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.MUTED,
            halign="left",
            valign="middle",
            size_hint_y=0.38,
        )
        sub_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(title_lbl)
        self.add_widget(sub_lbl)

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._ROW_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._touched:
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.CYAN
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = Theme.PANEL
            self._border_color.rgba = Theme.BORDER_VIOLET_SOFT
            self._outer_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow_color.rgba = (Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._border.width = dp(1.2)

    def _set_touched(self, active: bool) -> None:
        self._touched = active
        self._sync_canvas()

    def _emit_pick(self) -> None:
        self._set_touched(True)
        if self._pick_delay_ev is not None:
            self._pick_delay_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._pick_delay_ev = None
            self._set_touched(False)
            self._on_pick()

        self._pick_delay_ev = Clock.schedule_once(_after_glow, 0.14)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud["mcq_file_row"] = self
            touch.ud["mcq_file_row_x"] = touch.x
            touch.ud["mcq_file_row_y"] = touch.y
            touch.ud["mcq_file_row_id"] = touch.id
            self._set_touched(True)
        return False

    def on_touch_up(self, touch):
        if touch.ud.get("mcq_file_row") is not self:
            return False
        if touch.ud.get("mcq_file_row_id") != touch.id:
            return False
        if touch.ud.get("mcq_list_scrolled"):
            self._set_touched(False)
            return False
        if not self.collide_point(*touch.pos):
            self._set_touched(False)
            return False
        x0 = touch.ud.get("mcq_file_row_x", touch.x)
        y0 = touch.ud.get("mcq_file_row_y", touch.y)
        if _touch_is_tap(touch, down_x=x0, down_y=y0):
            _schedule_touch_safe(self, self._emit_pick)
        else:
            self._set_touched(False)
        return False


class QuizDangerNavButton(MCQNavButton):
    """Red-accent nav button for quiz Answer."""

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._BTN_RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._flash_active:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.35)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.16)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.28)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        elif self._pressed:
            self._fill_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.38)
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.18)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0.32)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            self._fill_color.rgba = (
                Theme.DANGER[0],
                Theme.DANGER[1],
                Theme.DANGER[2],
                0.28,
            )
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0)
            self._inner_glow_color.rgba = (Theme.DANGER[0], Theme.DANGER[1], Theme.DANGER[2], 0)
            self._border.width = dp(1.5)


class QuizGlowPanel(BoxLayout):
    """Rounded panel with green/red glow for transcript or answer blocks."""

    _RADIUS = dp(14)

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=(dp(12), dp(14), dp(12), dp(10)),
            size_hint_y=None,
            **kwargs,
        )
        self._passing = False
        with self.canvas.before:
            self._outer_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 4.4,
                cap="round",
            )
            self._inner_glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner_glow = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=STUDY_MCQ_ANSWER_BORDER_SEL * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[self._RADIUS] * 4,
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.body_lbl = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="top",
            size_hint_y=None,
            height=dp(48),
        )
        self.body_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.body_lbl.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(dp(48), ts[1] + dp(8)))
        )
        self.bind(minimum_height=self._sync_height)
        self.add_widget(self.body_lbl)

    def _sync_height(self, *_args) -> None:
        self.height = self.body_lbl.height + dp(20)

    def set_text(self, text: str) -> None:
        self.body_lbl.text = text

    def set_passing(self, passing: bool) -> None:
        self._passing = passing
        self._sync_canvas()

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer_glow.rounded_rectangle = rr
        self._inner_glow.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr
        if self._passing:
            glow = Theme.OK
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.OK
            self._outer_glow_color.rgba = (glow[0], glow[1], glow[2], 0.14)
            self._inner_glow_color.rgba = (glow[0], glow[1], glow[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        else:
            glow = Theme.DANGER
            self._fill_color.rgba = Theme.PANEL_HI
            self._border_color.rgba = Theme.DANGER
            self._outer_glow_color.rgba = (glow[0], glow[1], glow[2], 0.14)
            self._inner_glow_color.rgba = (glow[0], glow[1], glow[2], 0.25)
            self._border.width = STUDY_MCQ_ANSWER_BORDER_SEL
        self._sync_height()


# Study dashboard widgets (require GlowPanel)
# ---------------------------------------------------------------------------

class StudyTileIcon(Widget):
    """Study tile icon from UIUX2/icons PNG assets."""

    def __init__(self, icon_file: str, **kwargs):
        super().__init__(**kwargs)
        self._texture = _study_icon_texture(icon_file)
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


class AskBunnyIconRow(BoxLayout):
    """Bunny + question icons for the Ask From Bunny popup."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=-dp(400),
            padding=(0, 0),
            **kwargs,
        )
        for icon_file, weight in (("animal.png", 0.54), ("question.png", 0.46)):
            img = Image(
                texture=_study_icon_texture(icon_file),
                fit_mode="contain",
                size_hint_x=weight,
            )
            self.add_widget(img)


class RespondBunnyIconRow(BoxLayout):
    """Bunny + response icons for the Responding popup."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=-dp(400),
            padding=(0, 0),
            **kwargs,
        )
        for icon_file, weight in (("animal.png", 0.54), ("response.png", 0.46)):
            img = Image(
                texture=_study_icon_texture(icon_file),
                fit_mode="contain",
                size_hint_x=weight,
            )
            self.add_widget(img)


class RespondingCaptionBox(BoxLayout):
    """Inner cyan frame — shows a sliding window of spoken words (combined.py answer)."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            padding=(dp(14), dp(12)),
            size_hint_y=None,
            height=STUDY_RESPOND_CAPTION_H,
            **kwargs,
        )
        self.caption = Label(
            text="",
            font_size=sp(22),
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
        )
        self.caption.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        self.add_widget(self.caption)
        with self.canvas.before:
            Color(*Theme.BORDER_CYAN_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(14)),
                width=dp(1.4),
            )
        self.bind(pos=self._sync_border, size=self._sync_border)

    def _sync_border(self, *_args) -> None:
        self._border.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            dp(14),
        )


class SpeechProgressRow(BoxLayout):
    """Playback progress bar and elapsed / total timestamps."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=STUDY_RESPOND_PROGRESS_H,
            **kwargs,
        )
        self._track = Widget(size_hint_x=1)
        self._time_lbl = Label(
            text="0:00 / 0:00",
            font_size=sp(14),
            color=Theme.CYAN_DIM,
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(88),
        )
        self._progress = 0.0
        self.add_widget(self._track)
        self.add_widget(self._time_lbl)
        self._track.bind(pos=self._draw, size=self._draw)

    def set_progress(self, elapsed: float, duration: float) -> None:
        duration = max(duration, 0.01)
        self._progress = min(1.0, max(0.0, elapsed / duration))
        self._time_lbl.text = f"{format_mmss(elapsed)} / {format_mmss(duration)}"
        self._draw()

    def _draw(self, *_args) -> None:
        self._track.canvas.clear()
        if self._track.width < 4:
            return
        x, y, w, h = self._track.x, self._track.y, self._track.width, self._track.height
        cy = y + h / 2
        with self._track.canvas:
            Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.2)
            Line(points=[x, cy, x + w, cy], width=dp(2))
            if self._progress > 0:
                Color(*Theme.ACCENT_SOFT)
                Line(points=[x, cy, x + w * self._progress, cy], width=dp(3))


class GlowingDotsRow(Widget):
    """Sequential pulsing cyan dots below the Ask From Bunny title."""

    DOT_COUNT = 4

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._phase = 0.0
        self._pulse_ev = None
        self.bind(pos=self._draw, size=self._draw)

    def on_parent(self, widget, parent):
        if parent is not None and self._pulse_ev is None:
            self._pulse_ev = Clock.schedule_interval(self._tick, 1 / 30.0)
        elif parent is None and self._pulse_ev is not None:
            self._pulse_ev.cancel()
            self._pulse_ev = None

    def _tick(self, dt: float) -> None:
        self._phase += dt * 2.2
        self._draw()

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 4 or self.height < 4:
            return
        # Canvas instructions use parent coordinates (see StudyTileIcon).
        n = self.DOT_COUNT
        spacing = STUDY_ASK_DOT_SPACING * 0.82
        mid = (n - 1) / 2.0
        cx_mid = self.center_x
        cy = self.center_y
        dot_r = min(dp(7), self.height * 0.14)
        glow_r_extra = sp(2)
        for i in range(n):
            cx = cx_mid + (i - mid) * spacing
            cycle = (self._phase - i * 0.42) % n
            pulse = max(0.0, 1.0 - abs(cycle) * 1.5)
            glow_a = 0.015 + 0.16 * pulse
            core_a = 0.12 + 0.42 * pulse
            with self.canvas:
                for mult, alpha in ((2.6, glow_a * 0.3), (1.85, glow_a * 0.55), (1.35, glow_a)):
                    glow_r = dot_r * mult + glow_r_extra
                    Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], alpha)
                    Ellipse(
                        pos=(cx - glow_r, cy - glow_r),
                        size=(glow_r * 2, glow_r * 2),
                    )
                Color(Theme.ACCENT_SOFT[0], Theme.ACCENT_SOFT[1], Theme.ACCENT_SOFT[2], core_a)
                Ellipse(pos=(cx - dot_r, cy - dot_r), size=(dot_r * 2, dot_r * 2))


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
        if not _touch_is_tap(touch, down_x=x0, down_y=y0):
            self._set_tile_pressed(False)
            return super().on_touch_up(touch)
        self._set_tile_pressed(True)
        if self._tile_glow_restore_ev is not None:
            self._tile_glow_restore_ev.cancel()

        def _after_glow(_dt: float) -> None:
            self._tile_glow_restore_ev = None
            self._set_tile_pressed(False)
            _schedule_touch_safe(self, self._on_tap)

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
            _bind_touch_safe_on_press(btn, lambda v=val: self.set_value(v, scroll=True, animate=True))
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


# ---------------------------------------------------------------------------



class StatCard(GlowPanel):
    def __init__(self, title: str, accent, *, pulse: bool = False, **kwargs):
        super().__init__(orientation="vertical", padding=dp(14), spacing=dp(6), **kwargs)
        self.accent = accent
        self._pulse = pulse
        self._pulse_phase = random.uniform(0, math.tau)
        self._pulse_ev = None
        self.title = Label(
            text=title.upper(),
            size_hint_y=None,
            height=dp(20),
            font_size=Theme.CAPTION,
            bold=True,
            color=Theme.MUTED,
            halign="left",
        )
        self.value = Label(
            text="--",
            size_hint_y=None,
            height=dp(40),
            font_size=Theme.STAT,
            bold=True,
            color=accent,
            halign="left",
        )
        self.sub = Label(text="", font_size=Theme.CAPTION, color=Theme.MUTED, halign="left")
        for lab in (self.title, self.value, self.sub):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            self.add_widget(lab)
        if self._pulse:
            self._pulse_ev = Clock.schedule_interval(self._pulse_tick, 1 / 22.0)

    def set_value(self, value: str, sub: str) -> None:
        self.value.text = value
        self.sub.text = sub

    def _pulse_tick(self, dt: float) -> None:
        self._pulse_phase += dt * 2.4
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse_phase))
        self.value.color = (self.accent[0], self.accent[1], self.accent[2], pulse)


class DeviceViz(Widget):
    """PNG device icons from UIUX2/icons with level-based animation."""

    def __init__(self, kind: str, state: MockState, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.state = state
        self.phase = 0.0
        self._texture = _device_icon_texture(kind)
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_interval(self._tick, 1 / 30)

    def _tick(self, dt: float) -> None:
        if self.kind == "fan":
            if self.state.fan_level > 0:
                spd = _FAN_PHASE_L1 if self.state.fan_level == 1 else _FAN_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "humidifier":
            if self.state.humidifier_level > 0:
                spd = _HUM_PHASE_L1 if self.state.humidifier_level == 1 else _HUM_PHASE_L2
                self.phase = (self.phase + dt * spd) % 10
        elif self.kind == "led" and self.state.led_on and self.state.led_brightness > 0:
            br = self.state.led_brightness
            self.phase = (self.phase + dt * (_LED_PHASE_BASE + _LED_PHASE_BRIGHT * br)) % 10
        self._draw()

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 10 or self.height < 10:
            return
        cx, cy = self.center
        r = min(self.width, self.height) * 0.42
        side = r * 1.65
        ix = cx - side / 2
        iy = cy - side / 2
        c_c = Theme.CYAN
        rotate_deg = 0.0
        alpha = 1.0
        tint = c_c

        if self.kind == "fan":
            active = self.state.fan_level > 0
            alpha = 1.0 if active else 0.28
            glow_a = 0.12 if active else 0.03
            rotate_deg = math.degrees(self.phase * _FAN_ROTATE) if active else 0.0
            with self.canvas:
                Color(c_c[0], c_c[1], c_c[2], glow_a)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(*tint, alpha)
                PushMatrix()
                Rotate(angle=rotate_deg, origin=(cx, cy))
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                PopMatrix()

        elif self.kind == "humidifier":
            lvl = self.state.humidifier_level
            alpha = 1.0 if lvl > 0 else 0.28
            pulse = 0.85 + 0.15 * math.sin(self.phase * _HUM_PULSE) if lvl > 0 else 1.0
            bubbles = 3 if lvl == 1 else (5 if lvl == 2 else 0)
            rise_mul = _HUM_RISE_L1 if lvl == 1 else (_HUM_RISE_L2 if lvl == 2 else 0)
            with self.canvas:
                Color(c_c[0], c_c[1], c_c[2], 0.1 if lvl > 0 else 0.03)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(*tint, alpha * pulse)
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                if bubbles:
                    for i in range(bubbles):
                        ox = (i - (bubbles - 1) / 2) * r * 0.28 + r * 0.38
                        rise = (self.phase * rise_mul + i * 17) % (r * 1.0)
                        br = r * (0.09 if lvl == 1 else 0.12)
                        Color(c_c[0], c_c[1], c_c[2], 0.55 * pulse)
                        Line(circle=(cx + ox, cy - r * 0.1 + rise, br), width=max(dp(1.5), r * 0.035))

        else:  # LED — tint with selected color
            lc = self.state.led_color
            br = self.state.led_brightness if self.state.led_on else 0.0
            alpha = 0.35 + 0.65 * br
            glow_a = 0.14 * alpha
            rotate_deg = (
                math.degrees(self.phase * (_LED_ROTATE_BASE + _LED_ROTATE_BRIGHT * br)) if br > 0 else 0.0
            )
            with self.canvas:
                Color(lc[0], lc[1], lc[2], glow_a)
                Ellipse(pos=(cx - r * 1.15, cy - r * 1.15), size=(r * 2.3, r * 2.3))
                Color(lc[0], lc[1], lc[2], alpha)
                PushMatrix()
                Rotate(angle=rotate_deg, origin=(cx, cy))
                Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))
                PopMatrix()


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
            _bind_touch_safe_on_press(btn, lambda lv=label: self._pick(lv))
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
            self._wheel_tex = _build_hsv_wheel_texture(px)
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
        rgb = _hsv_to_rgb(hue, sat, 1.0)
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

        h, s, _v = _rgb_to_hsv(*self.state.led_color)
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
        self._auto_btn = _make_auto_button()
        _bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)
        text_col.add_widget(self._auto_btn)
        self.segment = SegmentedLevelControl(
            on_select=self._set_level,
            size_hint_x=None,
            width=_CONTROL_BTN_WIDTH,
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

        _bridge_worker(_call, _done)

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

        _bridge_worker(_call, _done)

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
        _sync_auto_button(self._auto_btn, self._auto_enabled())


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
        self._auto_btn = _make_auto_button()
        _bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)
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
        _bind_touch_safe_on_press(self._led_btn, self._run_led_toggle)
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
            int(round(self.state.led_brightness * 255)) if _led_effective_on(self.state) else 0
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

        _bridge_worker(_call, _done)

    def _run_led_toggle(self, *_args) -> None:
        """Coalesce duplicate touch+mouse presses into one toggle."""
        if self.state.auto_light:
            return
        self._toggle()

    def _toggle(self) -> None:
        if self.state.auto_light:
            return
        if _led_effective_on(self.state):
            target_on = False
            target_brightness = self.state.led_brightness
        else:
            target_on = True
            target_brightness = (
                0.65 if self.state.led_brightness <= _LED_OFF_EPS else self.state.led_brightness
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

        _bridge_worker(_call, _done)

    def refresh(self) -> None:
        on = _led_effective_on(self.state)
        pct = int(round(self.state.led_brightness * 100))
        self._led_btn.text = "ON" if on else "OFF"
        self._led_btn.background_color = Theme.CYAN if on else Theme.OFF
        self._led_btn.color = Theme.BLACK if on else Theme.MUTED
        self._led_btn.disabled = self.state.auto_light
        self._led_btn.opacity = 0.45 if self.state.auto_light else 1.0
        off_note = " (Currently OFF)" if not on else ""
        auto_note = " (Auto)" if self.state.auto_light else ""
        self.status.text = f"Brightness: {pct}%{off_note}{auto_note}"
        _sync_auto_button(self._auto_btn, self.state.auto_light)


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

        self._auto_btn = _make_auto_button()
        self._auto_btn.size_hint = (1, None)
        self._auto_btn.size = (0, _CONTROL_BTN_HEIGHT)
        _bind_touch_safe_on_press(self._auto_btn, self._on_auto_press)

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
            int(round(self.state.led_brightness * 255)) if _led_effective_on(self.state) else 0
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

        _bridge_worker(_call, _done)

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
        self._led_bridge_ev = Clock.schedule_once(self._flush_led_bridge, _LED_BRIDGE_DEBOUNCE_S)

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

        _bridge_worker(_call, _done)

    def _on_color_pick(self, rgb: tuple[float, float, float]) -> None:
        if self.state.auto_light:
            return
        led_on = _led_effective_on(self.state)
        brightness = self.state.led_brightness
        self._queue_led_bridge(led_on=led_on, brightness=brightness, color=rgb)

    def _on_brightness(self, _inst, value: float) -> None:
        if self.state.auto_light:
            return
        if self.slider.disabled or self._slider_sync:
            return
        v = float(value)
        desired_on = v > _LED_OFF_EPS
        self._queue_led_bridge(
            led_on=desired_on,
            brightness=v,
            color=self.state.led_color,
        )

    def refresh(self) -> None:
        pct = int(round(self.state.led_brightness * 100))
        on = _led_effective_on(self.state)
        off_note = " (Currently OFF)" if not on else ""
        auto_note = " (Auto)" if self.state.auto_light else ""
        self.status.text = f"Intensity: {pct}%{off_note}{auto_note}"
        manual_locked = _led_slider_locked(self.state)
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
        self._hex_lbl.text = _rgb_to_hex(*self.state.led_color)
        self.wheel._redraw()
        _sync_auto_button(self._auto_btn, self.state.auto_light)
        if hasattr(self, "_swatch"):
            self._swatch.canvas.clear()
            with self._swatch.canvas:
                Color(*self.state.led_color)
                RoundedRectangle(pos=self._swatch.pos, size=self._swatch.size, radius=[dp(6)])


# ---------------------------------------------------------------------------
# Sensors dashboard
# ---------------------------------------------------------------------------


class CircuitBackdrop(Widget):
    """Faint circuit-board lines behind the sensor dashboard."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 20 or self.height < 20:
            return
        w, h = self.width, self.height
        x0, y0 = self.x, self.y
        lines = [
            (0.08, 0.22, 0.42, 0.22),
            (0.42, 0.22, 0.42, 0.55),
            (0.42, 0.55, 0.78, 0.55),
            (0.78, 0.55, 0.78, 0.82),
            (0.15, 0.68, 0.55, 0.68),
            (0.55, 0.68, 0.55, 0.38),
            (0.55, 0.38, 0.92, 0.38),
            (0.25, 0.88, 0.65, 0.88),
            (0.65, 0.88, 0.65, 0.48),
        ]
        with self.canvas:
            Color(0.12, 0.28, 0.48, 0.22)
            for x1r, y1r, x2r, y2r in lines:
                Line(
                    points=[x0 + x1r * w, y0 + y1r * h, x0 + x2r * w, y0 + y2r * h],
                    width=dp(1.2),
                )
            for xr, yr in ((0.42, 0.22), (0.42, 0.55), (0.55, 0.68), (0.65, 0.88)):
                Line(circle=(x0 + xr * w, y0 + yr * h, dp(3)), width=dp(1))


class SensorIcon(Widget):
    """Sensor card icon from UIUX2/icons."""

    def __init__(self, icon_file: str, tint, **kwargs):
        super().__init__(**kwargs)
        self._texture = _sensor_icon_texture(icon_file)
        self.tint = tint
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_args) -> None:
        self.canvas.clear()
        if self.width < 4 or self.height < 4:
            return
        badge_side = min(self.width, self.height)
        badge_x = self.center_x - badge_side / 2
        badge_y = self.center_y - badge_side / 2
        side = badge_side * 0.72
        ix = self.center_x - side / 2
        iy = self.center_y - side / 2
        with self.canvas:
            Color(self.tint[0], self.tint[1], self.tint[2], 0.18)
            Ellipse(
                pos=(badge_x - badge_side * 0.08, badge_y - badge_side * 0.08),
                size=(badge_side * 1.16, badge_side * 1.16),
            )
            Color(0.86, 0.93, 1.0, 0.96)
            RoundedRectangle(
                pos=(badge_x, badge_y),
                size=(badge_side, badge_side),
                radius=[badge_side * 0.28],
            )
            Color(self.tint[0], self.tint[1], self.tint[2], 0.68)
            Line(
                rounded_rectangle=(badge_x, badge_y, badge_side, badge_side, badge_side * 0.28),
                width=dp(1.6),
            )
            Color(self.tint[0], self.tint[1], self.tint[2], 1)
            Rectangle(texture=self._texture, pos=(ix, iy), size=(side, side))


class SensorDashboardCard(GlowPanel):
    """Neon sensor tile — icon left, title / value / subtitle right."""

    def __init__(self, title: str, icon_file: str, accent, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", SENSOR_CARD_H)
        super().__init__(
            orientation="horizontal",
            padding=(dp(12), dp(10)),
            spacing=dp(8),
            **kwargs,
        )
        self.accent = accent

        icon_holder = AnchorLayout(
            anchor_x="center",
            anchor_y="center",
            size_hint=(None, 1),
            width=SENSOR_ICON_SLOT,
        )
        icon_holder.add_widget(
            SensorIcon(icon_file, accent, size_hint=(None, None), size=(SENSOR_ICON, SENSOR_ICON))
        )

        text_col = BoxLayout(
            orientation="vertical",
            spacing=dp(2),
            size_hint_x=1,
            padding=(0, dp(6), dp(4), 0),
        )
        self.title_label = Label(
            text=title,
            font_size=CONTROL_TITLE,
            bold=True,
            color=Theme.TEXT,
            halign="left",
            valign="bottom",
            size_hint_y=None,
            height=dp(34),
        )
        self.value_label = Label(
            text="--",
            font_size=Theme.STAT,
            bold=True,
            color=accent,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(44),
        )
        self.sub_label = Label(
            text="",
            font_size=CONTROL_STATUS,
            color=Theme.MUTED,
            halign="left",
            valign="top",
            size_hint_y=1,
        )
        for lab in (self.title_label, self.value_label, self.sub_label):
            lab.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            text_col.add_widget(lab)

        self.add_widget(icon_holder)
        self.add_widget(text_col)

    def set_value(self, value: str, subtitle: str) -> None:
        self.value_label.text = value
        self.sub_label.text = subtitle


def _status_footer_label(prefix: str, status: str) -> Label:
    full = f"{prefix} [color=00ff00]{status}[/color]"
    lbl = Label(
        text=full,
        markup=True,
        font_size=SENSOR_STATUS,
        color=Theme.MUTED,
        halign="center",
        valign="middle",
    )
    lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    return lbl


# ---------------------------------------------------------------------------
# Refs + builders
# ---------------------------------------------------------------------------


@dataclass
class SensorsRefs:
    temp: SensorDashboardCard
    humidity: SensorDashboardCard
    lux: SensorDashboardCard
    heart: SensorDashboardCard
    body_temp: SensorDashboardCard
    spo2: SensorDashboardCard


def build_study_screen() -> Screen:
    screen = Screen(name="study")
    root = FloatLayout()

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)
    root._grid_group = InstructionGroup()
    root.canvas.before.add(root._grid_group)

    def _sync_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size
        root._grid_group.clear()
        step = dp(48)
        x0, y0 = root.pos
        w, h = root.size
        root._grid_group.add(Color(0.15, 0.92, 1.0, 0.04))
        x = x0
        while x <= x0 + w:
            root._grid_group.add(Line(points=[x, y0, x, y0 + h], width=1))
            x += step
        y = y0
        while y <= y0 + h:
            root._grid_group.add(Line(points=[x0, y, x0 + w, y], width=1))
            y += step

    root.bind(pos=_sync_bg, size=_sync_bg)

    content = BoxLayout(
        orientation="vertical",
        padding=STUDY_PAD,
        spacing=STUDY_GRID_GAP,
        size_hint=(1, 1),
    )

    header_row = BoxLayout(size_hint_y=None, height=STUDY_HEADER_H, spacing=dp(12))
    title = Label(
        text="STUDY",
        font_size=STUDY_TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        halign="left",
        valign="middle",
        size_hint_x=1,
    )
    title.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    header_row.add_widget(title)

    tile_grid = GridLayout(cols=3, spacing=STUDY_GRID_GAP, size_hint_y=1)

    class TimerCtrl:
        remaining_seconds: int = 0
        alarm_active: bool = False
        tick_ev = None
        alarm_ev = None

    ctrl = TimerCtrl()
    timer_tile: StudyTile | None = None
    timer_popup: Popup | None = None
    mcq_popup: Popup | None = None
    mcq_file_picker: Popup | None = None
    quiz_popup: Popup | None = None
    quiz_file_picker: Popup | None = None
    summary_file_picker: Popup | None = None
    summary_viewer_popup: Popup | None = None
    summary_viewer_context: str = ""
    ask_bunny_popup: Popup | None = None
    thinking_popup: Popup | None = None
    responding_popup: Popup | None = None
    ask_bunny_cancel = threading.Event()
    ask_bunny_session_thread: threading.Thread | None = None
    ask_bunny_aplay_proc: subprocess.Popen | None = None
    ask_bunny_wav_path: str | None = None
    ask_bunny_speech_tick = None
    ask_bunny_speech_start = 0.0
    ask_bunny_speech_duration = 0.0
    ask_bunny_speech_words: list[str] = []
    ask_bunny_caption_last_idx = -1
    responding_caption_box: RespondingCaptionBox | None = None
    responding_progress_row: SpeechProgressRow | None = None
    hour_picker: WheelPickerColumn | None = None
    minute_picker: WheelPickerColumn | None = None
    _alarm_proc: subprocess.Popen | None = None

    def _stop_alarm_player() -> None:
        nonlocal _alarm_proc
        if _alarm_proc is None:
            return
        if _alarm_proc.poll() is None:
            _alarm_proc.terminate()
            try:
                _alarm_proc.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                _alarm_proc.kill()
        _alarm_proc = None

    def _spawn_alarm_player() -> bool:
        nonlocal _alarm_proc
        _stop_alarm_player()
        if not _STUDY_TONE_PATH.is_file():
            return False
        path = str(_STUDY_TONE_PATH)
        candidates = [
            ["mpg123", "-q", "--loop", "-1", path],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-loop", "0", path],
            ["mpv", "--no-video", "--really-quiet", "--loop=inf", path],
            ["paplay", path],
            ["cvlc", "-I", "dummy", "--loop", path],
        ]
        for cmd in candidates:
            try:
                _alarm_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except (FileNotFoundError, OSError):
                continue
        return False

    def _begin_alarm_audio(_dt: float) -> None:
        if not ctrl.alarm_active:
            return
        _spawn_alarm_player()

    def _stop_alarm() -> None:
        ctrl.alarm_active = False
        if ctrl.alarm_ev is not None:
            ctrl.alarm_ev.cancel()
            ctrl.alarm_ev = None
        _stop_alarm_player()

    def _refresh_timer_tile() -> None:
        if timer_tile is None:
            return
        if ctrl.alarm_active:
            timer_tile.set_alarm_mode(True)
            return
        timer_tile.set_alarm_mode(False)
        if ctrl.remaining_seconds > 0:
            timer_tile.set_caption(_format_timer_seconds(ctrl.remaining_seconds), accent=Theme.CYAN)
        else:
            timer_tile.set_caption(timer_tile._base_label, accent=Theme.ACCENT_SOFT)

    def _cancel_tick() -> None:
        if ctrl.tick_ev is not None:
            ctrl.tick_ev.cancel()
            ctrl.tick_ev = None

    def _clear_timer(*, stop_alarm: bool = True) -> None:
        _cancel_tick()
        ctrl.remaining_seconds = 0
        if stop_alarm:
            _stop_alarm()
        _refresh_timer_tile()

    def _start_alarm() -> None:
        ctrl.alarm_active = True
        ctrl.remaining_seconds = 0
        _cancel_tick()
        _refresh_timer_tile()
        Clock.schedule_once(_begin_alarm_audio, 0)

        def _pulse(_dt: float) -> None:
            if not ctrl.alarm_active or timer_tile is None:
                return
            t = timer_tile.caption.color[3]
            timer_tile.caption.color = (
                Theme.WARN[0],
                Theme.WARN[1],
                Theme.WARN[2],
                0.45 if t > 0.7 else 1.0,
            )

        if ctrl.alarm_ev is not None:
            ctrl.alarm_ev.cancel()
        ctrl.alarm_ev = Clock.schedule_interval(_pulse, 0.55)

    def _on_timer_tick(_dt: float) -> None:
        if ctrl.alarm_active or ctrl.remaining_seconds <= 0:
            return
        ctrl.remaining_seconds -= 1
        if ctrl.remaining_seconds <= 0:
            _start_alarm()
        else:
            _refresh_timer_tile()

    def _apply_timer_duration(total_seconds: int) -> None:
        total_seconds = max(0, int(total_seconds))
        _stop_alarm()
        if total_seconds <= 0:
            _clear_timer(stop_alarm=False)
            return
        ctrl.remaining_seconds = total_seconds
        _cancel_tick()
        ctrl.tick_ev = Clock.schedule_interval(_on_timer_tick, 1.0)
        _refresh_timer_tile()

    def _silence_from_tile() -> None:
        _stop_alarm()
        _refresh_timer_tile()

    def _open_timer_popup() -> None:
        nonlocal timer_popup, hour_picker, minute_picker
        if ctrl.alarm_active:
            return
        if timer_popup is not None and timer_popup.parent is not None:
            return

        if ctrl.remaining_seconds > 0:
            h, rem = divmod(ctrl.remaining_seconds, 3600)
            m, _s = divmod(rem, 60)
        else:
            h, m = 0, 25

        panel = GlowPanel(orientation="vertical", padding=dp(16), spacing=dp(12))
        panel.add_widget(
            Label(
                text="Set study timer",
                font_size=Theme.BODY,
                bold=True,
                color=Theme.TEXT,
                size_hint_y=None,
                height=dp(28),
            )
        )

        wheels = BoxLayout(spacing=dp(16), size_hint_y=1)
        hour_picker = WheelPickerColumn(
            "HOURS",
            list(range(24)),
            initial=h,
            size_hint_x=0.5,
        )
        minute_picker = WheelPickerColumn(
            "MINUTES",
            list(range(60)),
            initial=m,
            size_hint_x=0.5,
        )
        wheels.size_hint_y = None
        wheels.height = STUDY_WHEEL_ROW_H * STUDY_WHEEL_VISIBLE_ROWS + dp(30)
        wheels.add_widget(hour_picker)
        wheels.add_widget(minute_picker)
        panel.add_widget(wheels)

        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))

        def _close_popup(*_a):
            if timer_popup is not None:
                timer_popup.dismiss()

        def _set_timer(*_a):
            total = hour_picker.value * 3600 + minute_picker.value * 60
            if total <= 0:
                return
            _apply_timer_duration(total)
            _close_popup()

        def _cancel_timer(*_a):
            _clear_timer()
            _close_popup()

        actions.add_widget(make_button("Close", _close_popup, width=dp(100)))
        if ctrl.remaining_seconds > 0:
            actions.add_widget(make_button("Cancel Timer", _cancel_timer, width=dp(140)))
        actions.add_widget(make_button("Set Timer", _set_timer, accent=True, width=dp(120)))
        panel.add_widget(actions)

        timer_popup = Popup(
            title="",
            content=panel,
            size_hint=(0.78, 0.62),
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )
        timer_popup.open()

    def _run_on_main(fn: Callable[[], None]) -> None:
        Clock.schedule_once(lambda _dt: fn(), 0)

    def _stop_ask_bunny_speech_tick() -> None:
        nonlocal ask_bunny_speech_tick
        if ask_bunny_speech_tick is not None:
            ask_bunny_speech_tick.cancel()
            ask_bunny_speech_tick = None

    def _cancel_ask_bunny_session() -> None:
        nonlocal ask_bunny_aplay_proc, ask_bunny_wav_path
        ask_bunny_cancel.set()
        stop_playback(ask_bunny_aplay_proc)
        ask_bunny_aplay_proc = None
        cleanup_wav(ask_bunny_wav_path)
        ask_bunny_wav_path = None
        _stop_ask_bunny_speech_tick()

    def _dismiss_ask_bunny_popups() -> None:
        if ask_bunny_popup is not None and ask_bunny_popup.parent is not None:
            ask_bunny_popup.dismiss()
        if thinking_popup is not None and thinking_popup.parent is not None:
            thinking_popup.dismiss()
        if responding_popup is not None and responding_popup.parent is not None:
            responding_popup.dismiss()

    def _close_thinking_popup() -> None:
        if thinking_popup is not None and thinking_popup.parent is not None:
            thinking_popup.dismiss()

    def _close_responding_popup() -> None:
        if responding_popup is not None and responding_popup.parent is not None:
            responding_popup.dismiss()

    def _reset_ask_bunny_session() -> None:
        nonlocal ask_bunny_aplay_proc, ask_bunny_wav_path, ask_bunny_caption_last_idx
        ask_bunny_caption_last_idx = -1
        _stop_ask_bunny_speech_tick()
        stop_playback(ask_bunny_aplay_proc)
        ask_bunny_aplay_proc = None
        cleanup_wav(ask_bunny_wav_path)
        ask_bunny_wav_path = None
        ask_bunny_cancel.clear()

    def _on_speech_tick(_dt: float) -> None:
        nonlocal ask_bunny_caption_last_idx
        if responding_caption_box is None or responding_progress_row is None:
            return
        elapsed = time.monotonic() - ask_bunny_speech_start
        words = ask_bunny_speech_words
        if words and ask_bunny_speech_duration > 0 and responding_caption_box.caption is not None:
            idx = caption_target_index(elapsed, ask_bunny_speech_duration, len(words), CAPTION_AUDIO_LAG_S)
            if idx >= 0 and idx != ask_bunny_caption_last_idx:
                ask_bunny_caption_last_idx = idx
                responding_caption_box.caption.text = words_window(words, idx)
        responding_progress_row.set_progress(elapsed, ask_bunny_speech_duration)
        playback_done = ask_bunny_aplay_proc is not None and ask_bunny_aplay_proc.poll() is not None
        if playback_done or elapsed >= ask_bunny_speech_duration:
            _stop_ask_bunny_speech_tick()
            _close_responding_popup()
            _reset_ask_bunny_session()

    def _open_thinking_popup() -> None:
        nonlocal thinking_popup
        if thinking_popup is not None and thinking_popup.parent is not None:
            return

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_ASK_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(40))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        stack_h = STUDY_ASK_ICON_ROW_H + dp(50) + STUDY_ASK_DOTS_H + 2 * dp(12)
        body = FloatLayout(size_hint=(1, 1))
        stack = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint=(0.88, None),
            height=stack_h,
            pos_hint={"center_x": 0.5, "top": 0.92},
        )
        icon_holder = RelativeLayout(size_hint=(1, None), height=STUDY_ASK_ICON_ROW_H)
        icon_holder.add_widget(
            RespondBunnyIconRow(
                size_hint=(1, None),
                height=STUDY_ASK_ICON_ROW_H,
                pos=(0, sp(8)),
            )
        )
        stack.add_widget(icon_holder)
        title_lbl = Label(
            text="THINKING",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(50),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        stack.add_widget(title_lbl)

        thinking_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint=(None, None),
            width=dp(270),
            height=STUDY_ASK_DOTS_H,
            pos_hint={"center_x": 0.5},
        )
        thinking_row.add_widget(
            Label(
                text="Thinking",
                font_size=sp(24),
                bold=True,
                color=Theme.ACCENT_SOFT,
                halign="right",
                valign="middle",
                size_hint=(None, 1),
                width=dp(110),
            )
        )
        thinking_row.add_widget(GlowingDotsRow(size_hint=(None, 1), width=dp(150)))
        stack.add_widget(thinking_row)
        body.add_widget(stack)
        panel.add_widget(body)

        thinking_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_ASK_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_thinking(*_a) -> None:
            _cancel_ask_bunny_session()
            _dismiss_ask_bunny_popups()
            _reset_ask_bunny_session()

        _bind_touch_safe_on_press(close_btn, _close_thinking)
        thinking_popup.open()

    def _open_responding_popup(initial_text: str = "") -> None:
        nonlocal responding_popup, responding_caption_box, responding_progress_row
        if responding_popup is not None and responding_popup.parent is not None:
            if responding_caption_box is not None and initial_text:
                responding_caption_box.caption.text = initial_text
            return

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_ASK_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(40))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        stack_h = (
            STUDY_ASK_ICON_ROW_H
            + dp(50)
            + STUDY_RESPOND_CAPTION_H
            + STUDY_RESPOND_PROGRESS_H
            + 3 * dp(12)
        )
        body = FloatLayout(size_hint=(1, 1))
        stack = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint=(0.88, None),
            height=stack_h,
            pos_hint={"center_x": 0.5, "top": 0.92},
        )
        icon_holder = RelativeLayout(size_hint=(1, None), height=STUDY_ASK_ICON_ROW_H)
        icon_holder.add_widget(
            RespondBunnyIconRow(
                size_hint=(1, None),
                height=STUDY_ASK_ICON_ROW_H,
                pos=(0, sp(8)),
            )
        )
        stack.add_widget(icon_holder)
        title_lbl = Label(
            text="RESPONDING",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(50),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        stack.add_widget(title_lbl)

        responding_caption_box = RespondingCaptionBox()
        responding_caption_box.caption.text = initial_text
        stack.add_widget(responding_caption_box)

        responding_progress_row = SpeechProgressRow(
            size_hint_x=1,
            pos_hint={"center_x": 0.5},
        )
        responding_progress_row.set_progress(0.0, 1.0)
        stack.add_widget(responding_progress_row)
        body.add_widget(stack)
        panel.add_widget(body)

        responding_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_ASK_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_responding(*_a) -> None:
            _cancel_ask_bunny_session()
            _dismiss_ask_bunny_popups()
            _reset_ask_bunny_session()

        _bind_touch_safe_on_press(close_btn, _close_responding)
        responding_popup.open()

    def _start_ask_bunny_session() -> None:
        nonlocal ask_bunny_session_thread
        nonlocal ask_bunny_aplay_proc
        nonlocal ask_bunny_wav_path
        nonlocal ask_bunny_speech_tick
        nonlocal ask_bunny_speech_start
        nonlocal ask_bunny_speech_duration
        nonlocal ask_bunny_speech_words

        def _on_empty_stt() -> None:
            _dismiss_ask_bunny_popups()
            _reset_ask_bunny_session()

        def _on_stt_complete(_command: str, use_gemini: bool) -> None:
            if ask_bunny_popup is not None and ask_bunny_popup.parent is not None:
                ask_bunny_popup.dismiss()
            if use_gemini:
                _open_thinking_popup()

        def _on_device_handled() -> None:
            _dismiss_ask_bunny_popups()
            _reset_ask_bunny_session()

        def _on_answer_ready(_answer: str, words: list[str]) -> None:
            nonlocal ask_bunny_speech_words
            ask_bunny_speech_words = words
            _close_thinking_popup()
            _open_responding_popup()

        def _on_speech_start(
            duration: float,
            words: list[str],
            proc: subprocess.Popen | None,
            wav_path: str | None,
        ) -> None:
            nonlocal ask_bunny_aplay_proc, ask_bunny_wav_path, ask_bunny_speech_tick
            nonlocal ask_bunny_speech_start, ask_bunny_speech_duration, ask_bunny_speech_words
            nonlocal ask_bunny_caption_last_idx
            ask_bunny_aplay_proc = proc
            ask_bunny_wav_path = wav_path
            ask_bunny_speech_duration = duration
            ask_bunny_speech_words = words
            ask_bunny_speech_start = time.monotonic()
            ask_bunny_caption_last_idx = -1
            if responding_caption_box is not None:
                responding_caption_box.caption.text = ""
            _stop_ask_bunny_speech_tick()
            ask_bunny_speech_tick = Clock.schedule_interval(_on_speech_tick, 1 / 30.0)

        def _on_error(message: str) -> None:
            _close_thinking_popup()
            _open_responding_popup(message[:120])
            Clock.schedule_once(
                lambda _dt: (_close_responding_popup(), _reset_ask_bunny_session()),
                3.5,
            )

        def _on_finished() -> None:
            if ask_bunny_speech_tick is None:
                _close_responding_popup()
                _reset_ask_bunny_session()

        handlers = AskBunnyHandlers(
            on_empty_stt=_on_empty_stt,
            on_stt_complete=_on_stt_complete,
            on_device_handled=_on_device_handled,
            on_answer_ready=_on_answer_ready,
            on_speech_start=_on_speech_start,
            on_error=_on_error,
            on_finished=_on_finished,
        )
        ask_bunny_session_thread = run_ask_bunny_session(_run_on_main, ask_bunny_cancel, handlers)

    def _open_ask_bunny_popup() -> None:
        nonlocal ask_bunny_popup
        if ask_bunny_popup is not None and ask_bunny_popup.parent is not None:
            return

        _reset_ask_bunny_session()

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_ASK_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(40))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        stack_h = STUDY_ASK_ICON_ROW_H + dp(50) + STUDY_ASK_DOTS_H + 2 * dp(12)
        body = FloatLayout(size_hint=(1, 1))
        stack = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint=(0.88, None),
            height=stack_h,
            pos_hint={"center_x": 0.5, "top": 0.92},
        )
        icon_holder = RelativeLayout(
            size_hint=(1, None),
            height=STUDY_ASK_ICON_ROW_H,
        )
        icon_holder.add_widget(
            AskBunnyIconRow(
                size_hint=(1, None),
                height=STUDY_ASK_ICON_ROW_H,
                pos=(0, sp(8)),
            )
        )
        stack.add_widget(icon_holder)
        title_lbl = Label(
            text="ASK FROM BUNNY",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(50),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        stack.add_widget(title_lbl)
        listening_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint=(None, None),
            width=dp(270),
            height=STUDY_ASK_DOTS_H,
            pos_hint={"center_x": 0.5},
        )
        listening_row.add_widget(
            Label(
                text="Listening",
                font_size=sp(24),
                bold=True,
                color=Theme.ACCENT_SOFT,
                halign="right",
                valign="middle",
                size_hint=(None, 1),
                width=dp(110),
            )
        )
        listening_row.add_widget(
            GlowingDotsRow(
                size_hint=(None, 1),
                width=dp(150),
            )
        )
        stack.add_widget(listening_row)
        body.add_widget(stack)
        panel.add_widget(body)

        ask_bunny_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_ASK_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_ask_popup(*_a) -> None:
            _cancel_ask_bunny_session()
            _dismiss_ask_bunny_popups()
            _reset_ask_bunny_session()

        _bind_touch_safe_on_press(close_btn, _close_ask_popup)
        ask_bunny_popup.open()
        _start_ask_bunny_session()

    def _open_mcq_popup(questions: list[dict[str, object]]) -> None:
        nonlocal mcq_popup
        if not questions:
            return
        if mcq_popup is not None and mcq_popup.parent is not None:
            return
        current_idx = 0
        show_score = False
        selections: dict[int, int] = {}
        checked: set[int] = set()
        answer_buttons: list[MCQChoiceButton] = []

        def _correct_index(q: dict[str, object]) -> int:
            return int(q.get("answer", 0))

        def _score_right() -> int:
            return sum(
                1
                for i in checked
                if selections.get(i) == _correct_index(questions[i])
            )

        def _option_letter(q: dict[str, object], idx: int) -> str:
            opts = q["options"]
            if idx < 0 or idx >= len(opts):
                return _MCQ_LETTERS[max(0, min(3, idx))]
            return _MCQ_LETTERS[idx]

        def _build_results_summary() -> None:
            results_inner.clear_widgets()
            total = len(questions)
            for i in range(total):
                q = questions[i]
                sel = selections.get(i)
                correct_idx = _correct_index(q)
                is_right = sel == correct_idx
                status = "RIGHT" if is_right else "WRONG"
                status_color = Theme.OK if is_right else Theme.DANGER
                if is_right:
                    detail = f"Q{i + 1}: {status} ({_option_letter(q, correct_idx)})"
                else:
                    picked = _option_letter(q, sel) if sel is not None else "—"
                    answer = _option_letter(q, correct_idx)
                    detail = f"Q{i + 1}: {status} — picked {picked}, answer {answer}"
                row = Label(
                    text=detail,
                    font_size=STUDY_MCQ_RESULTS_ROW_FONT,
                    bold=True,
                    color=status_color,
                    halign="left",
                    valign="middle",
                    size_hint_y=None,
                    height=STUDY_MCQ_RESULTS_ROW_H,
                )
                row.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
                results_inner.add_widget(row)

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(4),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        question_lbl = Label(
            text="",
            font_size=STUDY_MCQ_QUESTION_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="top",
            size_hint_y=None,
            height=STUDY_MCQ_QUESTION_H,
        )
        question_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(question_lbl)

        marks_lbl = Label(
            text="",
            font_size=STUDY_MCQ_ANSWER_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(40),
        )
        marks_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(marks_lbl)

        results_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
            opacity=0,
            disabled=True,
        )
        results_inner = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        results_inner.bind(minimum_height=results_inner.setter("height"))
        results_scroll.add_widget(results_inner)
        panel.add_widget(results_scroll)

        answers_grid = GridLayout(
            cols=2,
            spacing=STUDY_MCQ_GRID_GAP,
            size_hint_y=1,
        )

        def _on_answer_pick(option_idx: int) -> None:
            if show_score or current_idx in checked:
                return
            selections[current_idx] = option_idx
            _refresh_mcq_view()

        for i in range(4):
            btn = MCQChoiceButton(
                i,
                on_select=_on_answer_pick,
                size_hint_y=None,
                height=STUDY_MCQ_ANSWER_H,
            )
            answer_buttons.append(btn)
            answers_grid.add_widget(btn)
        panel.add_widget(answers_grid)

        nav_row = BoxLayout(
            size_hint_y=None,
            height=STUDY_MCQ_NAV_H,
            spacing=dp(12),
        )
        prev_btn = MCQNavButton(
            "PREV",
            size_hint=(None, 1),
            width=STUDY_MCQ_NAV_W,
        )
        action_btn = MCQNavButton(
            "CHECK",
            size_hint=(None, 1),
            width=STUDY_MCQ_NAV_W,
        )
        nav_row.add_widget(prev_btn)
        nav_row.add_widget(Widget(size_hint_x=1))
        nav_row.add_widget(action_btn)
        panel.add_widget(nav_row)

        def _refresh_mcq_view() -> None:
            nonlocal show_score
            if show_score:
                total = len(questions)
                right = _score_right()
                pct = int(round(100 * right / total)) if total else 0
                question_lbl.text = f"You got {right} / {total} right"
                question_lbl.halign = "center"
                question_lbl.valign = "middle"
                question_lbl.height = dp(56)
                marks_lbl.text = f"Marks: {pct}%"
                marks_lbl.opacity = 1
                marks_lbl.height = dp(40)
                _build_results_summary()
                results_scroll.opacity = 1
                results_scroll.disabled = False
                results_scroll.size_hint_y = 1
                results_scroll.height = 0
                answers_grid.opacity = 0
                answers_grid.disabled = True
                answers_grid.size_hint_y = None
                answers_grid.height = 0
                prev_btn.text = "PREV"
                prev_btn.disabled = False
                prev_btn.opacity = 1.0
                action_btn.text = "DONE"
                action_btn.disabled = False
                action_btn.opacity = 1.0
                return

            marks_lbl.opacity = 0
            marks_lbl.text = ""
            marks_lbl.height = 0
            results_scroll.opacity = 0
            results_scroll.disabled = True
            results_scroll.size_hint_y = None
            results_scroll.height = 0
            results_inner.clear_widgets()
            answers_grid.opacity = 1
            answers_grid.disabled = False
            answers_grid.size_hint_y = 1
            answers_grid.height = 0
            question_lbl.halign = "left"
            question_lbl.valign = "top"
            question_lbl.height = STUDY_MCQ_QUESTION_H

            q = questions[current_idx]
            opts = q["options"]
            question_lbl.text = f"{current_idx + 1}. {q['question']}"
            sel = selections.get(current_idx)
            is_checked = current_idx in checked
            correct_idx = _correct_index(q)

            for i, btn in enumerate(answer_buttons):
                letter = _MCQ_LETTERS[i]
                opt_text = str(opts[i]) if i < len(opts) else ""
                has_option = bool(opt_text.strip())
                btn.set_label(f"{letter}. {opt_text}" if has_option else "")
                btn.disabled = is_checked or not has_option
                if not has_option:
                    btn.set_visual(selected=False, feedback=None)
                    continue
                if is_checked:
                    if i == correct_idx:
                        btn.set_visual(selected=(sel == i), feedback="correct")
                    elif sel is not None and i == sel and sel != correct_idx:
                        btn.set_visual(selected=True, feedback="wrong")
                    else:
                        btn.set_visual(selected=False, feedback=None)
                else:
                    btn.set_visual(selected=(sel == i), feedback=None)

            if current_idx == 0:
                prev_btn.text = "BACK"
                if 0 in checked:
                    prev_btn.disabled = True
                    prev_btn.opacity = 0.45
                else:
                    prev_btn.disabled = False
                    prev_btn.opacity = 1.0
            else:
                prev_btn.text = "PREV"
                prev_btn.disabled = False
                prev_btn.opacity = 1.0
            if is_checked:
                action_btn.text = "NEXT"
            else:
                action_btn.text = "CHECK"
            action_btn.disabled = False
            action_btn.opacity = 1.0

        def _go_prev() -> None:
            nonlocal current_idx, show_score
            if show_score:
                show_score = False
                current_idx = len(questions) - 1
                _refresh_mcq_view()
                return
            if current_idx == 0 and 0 not in checked:
                if mcq_popup is not None:
                    mcq_popup.dismiss()
                Clock.schedule_once(lambda _dt: _open_mcq_file_picker(), 0)
                return
            if current_idx > 0:
                current_idx -= 1
                _refresh_mcq_view()

        def _on_check() -> None:
            selected_idx = selections.get(current_idx)
            if selected_idx is None:
                action_btn.flash_danger()
                return
            checked.add(current_idx)
            _refresh_mcq_view()
            q = questions[current_idx]
            answer_buttons[selected_idx].pulse_feedback(
                "correct" if selected_idx == _correct_index(q) else "wrong"
            )

        def _on_action() -> None:
            nonlocal current_idx, show_score
            if show_score:
                if mcq_popup is not None:
                    mcq_popup.dismiss()
                return
            if current_idx in checked:
                if current_idx < len(questions) - 1:
                    current_idx += 1
                    _refresh_mcq_view()
                else:
                    show_score = True
                    _refresh_mcq_view()
            else:
                _on_check()

        prev_btn.bind_safe_press(_go_prev)
        action_btn.bind_safe_press(_on_action)

        mcq_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_mcq(*_a) -> None:
            if mcq_popup is not None:
                mcq_popup.dismiss()

        _bind_touch_safe_on_press(close_btn, _close_mcq)
        _refresh_mcq_view()
        mcq_popup.open()

    def _open_mcq_file_picker() -> None:
        nonlocal mcq_file_picker
        if mcq_file_picker is not None and mcq_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        quiz_files = _list_saved_mcq_files()

        def _pick_file_guarded(path: Path) -> None:
            now = Clock.get_time()
            if now < picker_ready_at:
                return
            _pick_file(path)

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        title_lbl = Label(
            text="CHOOSE MCQ",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(48),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(title_lbl)

        status_lbl = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.DANGER,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(28),
        )
        status_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(status_lbl)

        list_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        list_inner = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        list_inner.bind(minimum_height=list_inner.setter("height"))

        def _pick_file(path: Path) -> None:
            questions = _load_mcqs_from_file(path)
            if not questions:
                status_lbl.text = "No valid questions in this file."
                status_lbl.color = Theme.DANGER
                return
            status_lbl.text = ""
            if mcq_file_picker is not None:
                mcq_file_picker.dismiss()
            _open_mcq_popup(questions)

        if not quiz_files:
            empty_lbl = Label(
                text="No quiz files found in saved.",
                font_size=STUDY_MCQ_FILE_LIST_FONT,
                color=Theme.MUTED,
                halign="center",
                valign="middle",
                size_hint_y=None,
                height=dp(80),
            )
            empty_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            list_inner.add_widget(empty_lbl)
        else:
            for path in quiz_files:
                n = len(_load_mcqs_from_file(path))
                subtitle = f"{n} question{'s' if n != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        _quiz_display_name(path),
                        subtitle,
                        on_pick=lambda p=path: _pick_file_guarded(p),
                    )
                )

        list_scroll.add_widget(list_inner)
        panel.add_widget(list_scroll)

        mcq_file_picker = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_picker(*_a) -> None:
            if mcq_file_picker is not None:
                mcq_file_picker.dismiss()

        _bind_touch_safe_on_press(close_btn, _close_picker)
        mcq_file_picker.open()

    def _open_quiz_popup(questions: list[dict[str, object]]) -> None:
        nonlocal quiz_popup
        if not questions:
            return
        if quiz_popup is not None and quiz_popup.parent is not None:
            return

        current_idx = 0
        show_score = False
        phase = "question"  # question | recording | evaluating | evaluated
        transcripts: dict[int, str] = {}
        scores: dict[int, int] = {}
        feedback_map: dict[int, str] = {}
        evaluated: set[int] = set()
        quiz_cancel = threading.Event()
        quiz_worker: threading.Thread | None = None
        record_tick = None
        record_deadline = 0.0

        def _stop_record_tick() -> None:
            nonlocal record_tick
            if record_tick is not None:
                record_tick.cancel()
                record_tick = None

        def _cancel_quiz_worker() -> None:
            nonlocal quiz_worker
            quiz_cancel.set()
            if quiz_worker is not None and quiz_worker.is_alive():
                quiz_worker.join(timeout=0.2)
            quiz_worker = None

        def _average_score() -> int:
            if not evaluated:
                return 0
            total = sum(scores.get(i, 0) for i in evaluated)
            return int(round(total / len(evaluated)))

        def _build_results_summary() -> None:
            results_inner.clear_widgets()
            total = len(questions)
            for i in range(total):
                sc = scores.get(i, 0) if i in evaluated else 0
                status_color = Theme.OK if sc > 50 else Theme.DANGER
                if i in evaluated:
                    detail = f"Q{i + 1}: {sc}%"
                else:
                    detail = f"Q{i + 1}: —"
                    status_color = Theme.MUTED
                row = Label(
                    text=detail,
                    font_size=STUDY_MCQ_RESULTS_ROW_FONT,
                    bold=True,
                    color=status_color,
                    halign="left",
                    valign="middle",
                    size_hint_y=None,
                    height=STUDY_MCQ_RESULTS_ROW_H,
                )
                row.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
                results_inner.add_widget(row)

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(4),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        status_banner = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            bold=True,
            color=Theme.CYAN,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        status_banner.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(status_banner)

        summary_lbl = Label(
            text="",
            font_size=STUDY_MCQ_QUESTION_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=STUDY_MCQ_QUESTION_H,
            opacity=0,
            disabled=True,
        )
        summary_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(summary_lbl)

        content_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        content_inner = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        content_inner.bind(minimum_height=content_inner.setter("height"))

        question_lbl = Label(
            text="",
            font_size=STUDY_MCQ_QUESTION_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="top",
            size_hint_y=None,
            height=STUDY_MCQ_QUESTION_H,
        )
        question_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        question_lbl.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(STUDY_MCQ_QUESTION_H, ts[1] + dp(8)))
        )
        content_inner.add_widget(question_lbl)

        answer_row = AnchorLayout(size_hint_y=None, height=STUDY_MCQ_NAV_H)
        answer_btn = QuizDangerNavButton(
            "ANSWER",
            size_hint=(None, None),
            width=STUDY_MCQ_NAV_W * 1.2,
            height=STUDY_MCQ_NAV_H - dp(4),
        )
        answer_row.add_widget(answer_btn)
        content_inner.add_widget(answer_row)

        score_lbl = Label(
            text="",
            font_size=STUDY_MCQ_ANSWER_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        score_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        content_inner.add_widget(score_lbl)

        transcript_top_pad = Widget(size_hint_y=None, height=0)
        content_inner.add_widget(transcript_top_pad)

        transcript_heading = Label(
            text="Your answer:",
            font_size=sp(26),
            bold=True,
            color=Theme.MUTED,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        transcript_heading.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        content_inner.add_widget(transcript_heading)

        transcript_panel = QuizGlowPanel(opacity=0, disabled=True)
        content_inner.add_widget(transcript_panel)

        expected_top_pad = Widget(size_hint_y=None, height=0)
        content_inner.add_widget(expected_top_pad)

        expected_heading = Label(
            text="Expected answer:",
            font_size=sp(26),
            bold=True,
            color=Theme.MUTED,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        expected_heading.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        content_inner.add_widget(expected_heading)

        expected_panel = QuizGlowPanel(opacity=0, disabled=True)
        content_inner.add_widget(expected_panel)

        content_scroll.add_widget(content_inner)
        panel.add_widget(content_scroll)

        marks_lbl = Label(
            text="",
            font_size=STUDY_MCQ_ANSWER_FONT,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(40),
        )
        marks_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(marks_lbl)

        results_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
            opacity=0,
            disabled=True,
        )
        results_inner = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        results_inner.bind(minimum_height=results_inner.setter("height"))
        results_scroll.add_widget(results_inner)
        panel.add_widget(results_scroll)

        nav_row = BoxLayout(
            size_hint_y=None,
            height=STUDY_MCQ_NAV_H,
            spacing=dp(12),
        )
        prev_btn = MCQNavButton(
            "PREV",
            size_hint=(None, 1),
            width=STUDY_MCQ_NAV_W,
        )
        action_btn = MCQNavButton(
            "NEXT",
            size_hint=(None, 1),
            width=STUDY_MCQ_NAV_W,
        )
        nav_row.add_widget(prev_btn)
        nav_row.add_widget(Widget(size_hint_x=1))
        nav_row.add_widget(action_btn)
        panel.add_widget(nav_row)

        def _set_status(text: str, *, visible: bool, color=Theme.CYAN) -> None:
            if visible and text:
                status_banner.text = text
                status_banner.color = color
                status_banner.opacity = 1
                status_banner.height = dp(28)
            else:
                status_banner.text = ""
                status_banner.opacity = 0
                status_banner.height = 0

        def _show_evaluated_sections(show: bool) -> None:
            for widget in (
                score_lbl,
                transcript_top_pad,
                transcript_heading,
                transcript_panel,
                expected_top_pad,
                expected_heading,
                expected_panel,
            ):
                widget.opacity = 1 if show else 0
                widget.disabled = not show
            answer_row.opacity = 0 if show else 1
            answer_row.disabled = show
            if show:
                score_lbl.height = dp(36)
                transcript_top_pad.height = STUDY_QUIZ_ANSWER_SECTION_PAD
                transcript_heading.height = dp(24)
                expected_top_pad.height = STUDY_QUIZ_ANSWER_SECTION_PAD
                expected_heading.height = dp(24)
            else:
                score_lbl.height = 0
                transcript_top_pad.height = 0
                transcript_heading.height = 0
                expected_top_pad.height = 0
                expected_heading.height = 0
                transcript_panel.set_text("")
                expected_panel.set_text("")

        def _on_record_tick(_dt: float) -> None:
            if phase != "recording":
                return
            remaining = int(math.ceil(record_deadline - time.monotonic()))
            remaining = max(0, remaining)
            _set_status(f"Recording... {remaining}s", visible=True)
            if remaining <= 0:
                quiz_cancel.set()
                _enter_evaluating_ui()

        def _enter_evaluating_ui() -> None:
            nonlocal phase
            if phase == "evaluating":
                return
            phase = "evaluating"
            _stop_record_tick()
            _set_status("Your answer is evaluating", visible=True)
            prev_btn.disabled = True
            prev_btn.opacity = 0.45
            action_btn.disabled = True
            action_btn.opacity = 0.45
            answer_btn.disabled = True
            answer_row.opacity = 0

        def _begin_evaluating(transcript: str) -> None:
            nonlocal phase, quiz_worker
            _enter_evaluating_ui()

            q = questions[current_idx]
            expected = str(q.get("answer", ""))

            def _eval_work() -> None:
                try:
                    evaluation = evaluate_quiz_answer(
                        str(q["question"]),
                        expected,
                        transcript,
                    )
                except Exception as exc:
                    evaluation = QuizEvaluation(
                        score=0,
                        feedback=str(exc) or "Evaluation failed.",
                        raw_response="",
                    )

                def _done(_dt: float) -> None:
                    _on_evaluation_complete(transcript, evaluation)

                Clock.schedule_once(_done, 0)

            quiz_worker = threading.Thread(target=_eval_work, daemon=True)
            quiz_worker.start()

        def _on_record_complete(transcript: str) -> None:
            nonlocal phase, quiz_worker
            quiz_worker = None
            _begin_evaluating(transcript)

        def _on_record_error(message: str) -> None:
            nonlocal phase, quiz_worker
            phase = "question"
            quiz_worker = None
            _stop_record_tick()
            _set_status(message, visible=True, color=Theme.DANGER)
            prev_btn.disabled = False
            prev_btn.opacity = 1.0
            action_btn.disabled = True
            action_btn.opacity = 0.45
            answer_btn.disabled = False
            answer_row.opacity = 1

        def _on_evaluation_complete(transcript: str, evaluation: QuizEvaluation) -> None:
            nonlocal phase, quiz_worker
            quiz_worker = None
            phase = "evaluated"
            evaluated.add(current_idx)
            transcripts[current_idx] = transcript
            scores[current_idx] = evaluation.score
            feedback_map[current_idx] = evaluation.feedback
            _refresh_quiz_view()

        def _start_recording() -> None:
            nonlocal phase, quiz_worker, record_deadline, record_tick
            if phase in ("recording", "evaluating"):
                return
            _cancel_quiz_worker()
            quiz_cancel.clear()
            phase = "recording"
            record_deadline = time.monotonic() + QUIZ_ANSWER_TIME_LIMIT_S
            _refresh_quiz_view()
            _stop_record_tick()
            record_tick = Clock.schedule_interval(_on_record_tick, 0.25)

            def _record_work() -> None:
                try:
                    transcript = listen_for_quiz_answer(
                        quiz_cancel,
                        time_limit_s=QUIZ_ANSWER_TIME_LIMIT_S,
                    )

                    def _ok(_dt: float) -> None:
                        _on_record_complete(transcript)

                    Clock.schedule_once(_ok, 0)
                except Exception as exc:
                    msg = str(exc) or "Recording failed"

                    def _err(_dt: float) -> None:
                        _on_record_error(msg)

                    Clock.schedule_once(_err, 0)

            quiz_worker = threading.Thread(target=_record_work, daemon=True)
            quiz_worker.start()

        def _stop_recording() -> None:
            if phase != "recording":
                return
            quiz_cancel.set()
            _enter_evaluating_ui()

        def _refresh_quiz_view() -> None:
            nonlocal show_score, phase
            if show_score:
                _stop_record_tick()
                _set_status("", visible=False)
                summary_lbl.text = "Quiz completed"
                summary_lbl.opacity = 1
                summary_lbl.disabled = False
                summary_lbl.height = dp(56)
                avg = _average_score()
                marks_lbl.text = f"Marks: {avg}%"
                marks_lbl.opacity = 1
                marks_lbl.height = dp(40)
                _build_results_summary()
                results_scroll.opacity = 1
                results_scroll.disabled = False
                results_scroll.size_hint_y = 1
                results_scroll.height = 0
                content_scroll.opacity = 0
                content_scroll.disabled = True
                content_scroll.size_hint_y = None
                content_scroll.height = 0
                prev_btn.text = "PREV"
                prev_btn.disabled = False
                prev_btn.opacity = 1.0
                action_btn.text = "DONE"
                action_btn.disabled = False
                action_btn.opacity = 1.0
                return

            summary_lbl.opacity = 0
            summary_lbl.disabled = True
            summary_lbl.text = ""
            summary_lbl.height = 0
            marks_lbl.opacity = 0
            marks_lbl.text = ""
            marks_lbl.height = 0
            results_scroll.opacity = 0
            results_scroll.disabled = True
            results_scroll.size_hint_y = None
            results_scroll.height = 0
            results_inner.clear_widgets()
            content_scroll.opacity = 1
            content_scroll.disabled = False
            content_scroll.size_hint_y = 1
            content_scroll.height = 0

            q = questions[current_idx]
            question_lbl.text = f"{current_idx + 1}. {q['question']}"
            content_scroll.scroll_y = 1

            if phase == "recording":
                _show_evaluated_sections(False)
                score_lbl.text = ""
                action_btn.text = "DONE"
                action_btn.disabled = False
                action_btn.opacity = 1.0
                prev_btn.disabled = True
                prev_btn.opacity = 0.45
                answer_btn.disabled = True
                answer_row.opacity = 0
                return

            if phase == "evaluating":
                _show_evaluated_sections(False)
                _set_status("Your answer is evaluating", visible=True)
                action_btn.text = "DONE"
                action_btn.disabled = True
                action_btn.opacity = 0.45
                prev_btn.disabled = True
                prev_btn.opacity = 0.45
                answer_btn.disabled = True
                answer_row.opacity = 0
                return

            if current_idx in evaluated or phase == "evaluated":
                phase = "evaluated"
                _set_status("", visible=False)
                sc = scores.get(current_idx, 0)
                passing = sc > 50
                _show_evaluated_sections(True)
                score_color = Theme.OK if passing else Theme.DANGER
                score_lbl.color = score_color
                score_lbl.text = f"Score: {sc}% — {feedback_map.get(current_idx, '')}"
                transcript_panel.set_text(
                    transcripts.get(current_idx, "(no transcript)")
                )
                transcript_panel.set_passing(passing)
                expected_heading.height = dp(24)
                expected_panel.set_text(str(q.get("answer", "")))
                expected_panel.set_passing(True)
                if current_idx < len(questions) - 1:
                    action_btn.text = "NEXT"
                else:
                    action_btn.text = "NEXT"
                action_btn.disabled = False
                action_btn.opacity = 1.0
            else:
                phase = "question"
                _set_status("", visible=False)
                _show_evaluated_sections(False)
                score_lbl.text = ""
                answer_btn.disabled = False
                answer_row.opacity = 1
                action_btn.text = "NEXT"
                action_btn.disabled = True
                action_btn.opacity = 0.45

            if current_idx == 0:
                prev_btn.text = "BACK"
                if phase in ("recording", "evaluating") or 0 in evaluated:
                    prev_btn.disabled = True
                    prev_btn.opacity = 0.45
                else:
                    prev_btn.disabled = False
                    prev_btn.opacity = 1.0
            else:
                prev_btn.text = "PREV"
                if phase in ("recording", "evaluating"):
                    prev_btn.disabled = True
                    prev_btn.opacity = 0.45
                else:
                    prev_btn.disabled = False
                    prev_btn.opacity = 1.0

        def _go_prev() -> None:
            nonlocal current_idx, show_score, phase
            if phase in ("recording", "evaluating"):
                return
            if show_score:
                show_score = False
                current_idx = len(questions) - 1
                phase = "evaluated"
                _refresh_quiz_view()
                return
            if current_idx == 0 and 0 not in evaluated:
                _cancel_quiz_worker()
                _stop_record_tick()
                if quiz_popup is not None:
                    quiz_popup.dismiss()
                Clock.schedule_once(lambda _dt: _open_quiz_file_picker(), 0)
                return
            current_idx -= 1
            phase = "evaluated" if current_idx in evaluated else "question"
            _refresh_quiz_view()

        def _on_answer() -> None:
            _start_recording()

        def _on_action() -> None:
            nonlocal current_idx, show_score, phase
            if show_score:
                if quiz_popup is not None:
                    quiz_popup.dismiss()
                return
            if phase == "recording":
                _stop_recording()
                return
            if current_idx not in evaluated:
                return
            if current_idx < len(questions) - 1:
                current_idx += 1
                phase = "evaluated" if current_idx in evaluated else "question"
                _refresh_quiz_view()
            else:
                show_score = True
                _refresh_quiz_view()

        answer_btn.bind_safe_press(_on_answer)
        prev_btn.bind_safe_press(_go_prev)
        action_btn.bind_safe_press(_on_action)

        quiz_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_quiz(*_a) -> None:
            _cancel_quiz_worker()
            _stop_record_tick()
            if quiz_popup is not None:
                quiz_popup.dismiss()

        _bind_touch_safe_on_press(close_btn, _close_quiz)
        _refresh_quiz_view()
        quiz_popup.open()

    def _open_quiz_file_picker() -> None:
        nonlocal quiz_file_picker
        if quiz_file_picker is not None and quiz_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        quiz_files = _list_quiz_files()

        def _pick_file_guarded(path: Path) -> None:
            now = Clock.get_time()
            if now < picker_ready_at:
                return
            _pick_file(path)

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        title_lbl = Label(
            text="CHOOSE QUIZ",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(48),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(title_lbl)

        status_lbl = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.DANGER,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(28),
        )
        status_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(status_lbl)

        list_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        list_inner = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        list_inner.bind(minimum_height=list_inner.setter("height"))

        def _pick_file(path: Path) -> None:
            questions = _load_quiz_questions_from_file(path)
            if not questions:
                status_lbl.text = "No valid questions in this file."
                status_lbl.color = Theme.DANGER
                return
            status_lbl.text = ""
            if quiz_file_picker is not None:
                quiz_file_picker.dismiss()
            _open_quiz_popup(questions)

        if not quiz_files:
            empty_lbl = Label(
                text="No quiz files found in questions.",
                font_size=STUDY_MCQ_FILE_LIST_FONT,
                color=Theme.MUTED,
                halign="center",
                valign="middle",
                size_hint_y=None,
                height=dp(80),
            )
            empty_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            list_inner.add_widget(empty_lbl)
        else:
            for path in quiz_files:
                n = len(_load_quiz_questions_from_file(path))
                subtitle = f"{n} question{'s' if n != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        _quiz_display_name(path),
                        subtitle,
                        on_pick=lambda p=path: _pick_file_guarded(p),
                    )
                )

        list_scroll.add_widget(list_inner)
        panel.add_widget(list_scroll)

        quiz_file_picker = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_picker(*_a) -> None:
            if quiz_file_picker is not None:
                quiz_file_picker.dismiss()

        _bind_touch_safe_on_press(close_btn, _close_picker)
        quiz_file_picker.open()

    def _open_summary_viewer_popup(title: str, summary_text: str) -> None:
        nonlocal summary_viewer_popup, summary_viewer_context
        if not summary_text.strip():
            return
        if summary_viewer_popup is not None and summary_viewer_popup.parent is not None:
            return

        summary_viewer_context = summary_text

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        title_lbl = Label(
            text=title.upper(),
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(48),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(title_lbl)

        text_scroll = ScrollView(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        body_lbl = Label(
            text=_markdown_to_kivy_markup(summary_text),
            markup=True,
            font_size=STUDY_SUMMARY_BODY_FONT,
            color=Theme.TEXT,
            halign="left",
            valign="top",
            size_hint_y=None,
        )

        def _sync_body_layout(inst, *_args) -> None:
            inst.text_size = (inst.width, None)
            inst.texture_update()
            inst.height = max(inst.texture_size[1], dp(40))

        body_lbl.bind(width=_sync_body_layout, text=_sync_body_layout)
        text_scroll.add_widget(body_lbl)
        panel.add_widget(text_scroll)

        nav_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=STUDY_MCQ_NAV_H,
            spacing=dp(12),
        )
        nav_row.add_widget(Widget(size_hint_x=1))
        ask_btn = MCQNavButton(
            "ASK QUESTIONS",
            size_hint=(None, None),
            width=STUDY_MCQ_NAV_W + dp(40),
            height=STUDY_MCQ_NAV_H,
        )
        nav_row.add_widget(ask_btn)
        panel.add_widget(nav_row)

        summary_viewer_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _on_ask_questions(*_a) -> None:
            _write_voice_trigger(True)

        def _close_viewer(*_a) -> None:
            _write_voice_trigger(False)
            _write_pdf_mode_status(summary_viewer_context, False)
            if summary_viewer_popup is not None:
                summary_viewer_popup.dismiss()

        ask_btn.bind_safe_press(_on_ask_questions)
        _bind_touch_safe_on_press(close_btn, _close_viewer)
        _sync_body_layout(body_lbl)
        summary_viewer_popup.open()

    def _open_summary_file_picker() -> None:
        nonlocal summary_file_picker
        if summary_file_picker is not None and summary_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        summary_files = _list_summary_files()

        def _pick_file_guarded(path: Path) -> None:
            now = Clock.get_time()
            if now < picker_ready_at:
                return
            _pick_file(path)

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_MCQ_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        top_bar = BoxLayout(size_hint_y=None, height=dp(32))
        top_bar.add_widget(Widget())
        close_btn = GlowIconButton(
            text="×",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
        )
        top_bar.add_widget(close_btn)
        panel.add_widget(top_bar)

        title_lbl = Label(
            text="CHOOSE SUMMARY",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(48),
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(title_lbl)

        status_lbl = Label(
            text="",
            font_size=STUDY_MCQ_FILE_SUB_FONT,
            color=Theme.DANGER,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(28),
        )
        status_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        panel.add_widget(status_lbl)

        list_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        list_inner = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        list_inner.bind(minimum_height=list_inner.setter("height"))

        def _pick_file(path: Path) -> None:
            summary_text = _load_summary_text_from_file(path)
            if not summary_text:
                status_lbl.text = "No valid summary text in this file."
                status_lbl.color = Theme.DANGER
                return
            status_lbl.text = ""
            _write_pdf_mode_status(summary_text, True)
            if summary_file_picker is not None:
                summary_file_picker.dismiss()
            _open_summary_viewer_popup(_quiz_display_name(path), summary_text)

        if not summary_files:
            empty_lbl = Label(
                text="No summary files found in summaries.",
                font_size=STUDY_MCQ_FILE_LIST_FONT,
                color=Theme.MUTED,
                halign="center",
                valign="middle",
                size_hint_y=None,
                height=dp(80),
            )
            empty_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            list_inner.add_widget(empty_lbl)
        else:
            for path in summary_files:
                text = _load_summary_text_from_file(path)
                char_count = len(text)
                subtitle = f"{char_count:,} character{'s' if char_count != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        _quiz_display_name(path),
                        subtitle,
                        on_pick=lambda p=path: _pick_file_guarded(p),
                    )
                )

        list_scroll.add_widget(list_inner)
        panel.add_widget(list_scroll)

        summary_file_picker = Popup(
            title="",
            content=panel,
            size_hint=STUDY_MCQ_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_picker(*_a) -> None:
            if summary_file_picker is not None:
                summary_file_picker.dismiss()

        _bind_touch_safe_on_press(close_btn, _close_picker)
        summary_file_picker.open()

    def _on_timer_tile_tap() -> None:
        if ctrl.alarm_active:
            _silence_from_tile()
            return
        _open_timer_popup()

    def _on_ask_bunny_tile_tap() -> None:
        _open_ask_bunny_popup()

    def _on_generate_mcq_tile_tap() -> None:
        # Defer so the tile touch-up cannot land on the first file row in the new popup.
        Clock.schedule_once(lambda _dt: _open_mcq_file_picker(), 0)

    def _on_generate_quiz_tile_tap() -> None:
        Clock.schedule_once(lambda _dt: _open_quiz_file_picker(), 0)

    def _on_summarize_notes_tile_tap() -> None:
        # Defer so the tile touch-up cannot land on the first file row in the new popup.
        Clock.schedule_once(lambda _dt: _open_summary_file_picker(), 0)

    tile_defs: list[tuple[str, str, Callable[[], None] | None]] = [
        ("question.png", "ASK FROM BUNNY", _on_ask_bunny_tile_tap),
        ("timer.png", "STUDY TIMER", _on_timer_tile_tap),
        ("open-book.png", "SUMMARIZE NOTES", _on_summarize_notes_tile_tap),
        ("to-do.png", "TO-DO LIST", None),
        ("ballot.png", "GENERATE MCQ", _on_generate_mcq_tile_tap),
        ("speech-to-text.png", "GENERATE QUIZ\n(VOICE QUIZ)", _on_generate_quiz_tile_tap),
    ]

    for icon_file, label, handler in tile_defs:
        tile = StudyTile(icon_file, label, on_tap=handler, size_hint_y=1)
        if icon_file == "timer.png":
            timer_tile = tile
        tile_grid.add_widget(tile)

    content.add_widget(header_row)
    content.add_widget(tile_grid)
    root.add_widget(content)
    screen.add_widget(root)

    def _on_enter(*_args):
        _refresh_timer_tile()

    screen.bind(on_enter=_on_enter)

    _refresh_timer_tile()
    Clock.schedule_once(_sync_bg, 0)
    return screen


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

    content = BoxLayout(
        orientation="vertical",
        spacing=dp(8),
        size_hint=(1, 1),
        pos_hint={"x": 0, "y": 0},
        padding=SENSOR_PAD,
    )

    header = GridLayout(cols=3, size_hint_y=None, height=SENSOR_HEADER_H, spacing=dp(4))
    title = Label(
        text="SENSOR DASHBOARD",
        font_size=Theme.TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        halign="center",
        valign="middle",
    )
    title.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    clock_lbl = Label(
        text="",
        font_size=SENSOR_CLOCK,
        color=Theme.TEXT,
        halign="right",
        valign="middle",
    )
    clock_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
    header.add_widget(Widget())
    header.add_widget(title)
    header.add_widget(clock_lbl)

    def _update_clock(_dt: float = 0) -> None:
        now = datetime.now()
        clock_lbl.text = now.strftime("%H:%M | %b %d, %Y").upper()

    _update_clock()
    Clock.schedule_interval(_update_clock, 30.0)

    grid = GridLayout(cols=2, spacing=SENSOR_GRID_GAP, size_hint_y=1)
    grid.row_force_default = True
    grid.row_default_height = SENSOR_CARD_H

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

    content.add_widget(header)
    content.add_widget(grid)
    root.add_widget(content)

    # Initial values from mock state
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


def build_controls_screen(state: MockState) -> Screen:
    screen = Screen(name="controls")
    root = BoxLayout(orientation="vertical", padding=CONTROL_PAD, spacing=dp(8))

    with root.canvas.before:
        Color(*Theme.BG)
        root._bg_rect = Rectangle(pos=root.pos, size=root.size)

    def sync_bg(*_):
        root._bg_rect.pos = root.pos
        root._bg_rect.size = root.size

    root.bind(pos=sync_bg, size=sync_bg)

    header = Label(
        text="Controls",
        size_hint_y=None,
        height=dp(40),
        font_size=Theme.TITLE,
        bold=True,
        color=Theme.ACCENT_SOFT,
        halign="left",
    )
    header.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))

    grid = GridLayout(cols=2, spacing=CONTROL_GRID_GAP, size_hint_y=1)
    grid.row_force_default = True
    grid.row_default_height = CONTROL_CARD_H

    fan = LevelDeviceCard("Ceiling Fan", "fan", state, speed_label="Speed", output_label="Output")
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

    root.add_widget(header)
    root.add_widget(grid)
    screen.add_widget(root)
    return screen
