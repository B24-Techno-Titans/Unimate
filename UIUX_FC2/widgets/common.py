"""Shared constants and helpers for UniMate dashboard widgets."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Callable

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.uix.button import Button

from mock_state import MockState
from theme import Theme

_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"
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


def device_icon_texture(kind: str):
    if kind not in _icon_texture_cache:
        fname = _DEVICE_ICON_FILES[kind]
        path = _ICONS_DIR / fname
        if not path.is_file():
            raise FileNotFoundError(f"Device icon not found: {path}")
        _icon_texture_cache[kind] = CoreImage(str(path)).texture
    return _icon_texture_cache[kind]


def sensor_icon_texture(filename: str):
    if filename not in _sensor_icon_cache:
        path = _ICONS_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"Sensor icon not found: {path}")
        _sensor_icon_cache[filename] = CoreImage(str(path)).texture
    return _sensor_icon_cache[filename]


def study_icon_texture(filename: str):
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
FAN_PHASE_L1 = 2.4
FAN_PHASE_L2 = 4.8
FAN_ROTATE = 3.6
HUM_PHASE_L1 = 8.8
HUM_PHASE_L2 = 16.0
HUM_PULSE = 0.95
HUM_RISE_L1 = 13.5
HUM_RISE_L2 = 21.0
LED_PHASE_BASE = 0.6
LED_PHASE_BRIGHT = 0.9
LED_ROTATE_BASE = 0.14
LED_ROTATE_BRIGHT = 0.32
LED_OFF_EPS = 0.02
# Touch panels often deliver touch + emulated mouse as duplicate on_press events.
CONTROL_PRESS_DEBOUNCE_S = 0.35
_LED_TOGGLE_DEBOUNCE_S = CONTROL_PRESS_DEBOUNCE_S
LED_BRIDGE_DEBOUNCE_S = 0.35
CONTROL_BTN_WIDTH = dp(240)
CONTROL_BTN_HEIGHT = dp(48)
CONTROL_ERROR_PULSE_S = 0.75


def make_auto_button() -> Button:
    return Button(
        text="AUTO",
        size_hint=(None, None),
        size=(CONTROL_BTN_WIDTH, CONTROL_BTN_HEIGHT),
        bold=True,
        font_size=CONTROL_BUTTON_TEXT,
        background_normal="",
        background_color=Theme.PANEL_HI,
        color=Theme.TEXT,
    )


def sync_auto_button(btn: Button, enabled: bool) -> None:
    if enabled:
        btn.text = "AUTO ON"
        btn.background_color = Theme.CYAN
        btn.color = Theme.BLACK
    else:
        btn.text = "AUTO"
        btn.background_color = Theme.PANEL_HI
        btn.color = Theme.TEXT


def bridge_worker(call: Callable[[], bool], callback: Callable[[bool], None]) -> None:
    """Run a bridge HTTP call off the UI thread; invoke callback on the main thread."""

    def _run() -> None:
        ok = False
        try:
            ok = call()
        except Exception as exc:
            print(f"[dashboard] bridge call error: {exc}")
        Clock.schedule_once(lambda _dt: callback(ok), 0)

    threading.Thread(target=_run, daemon=True).start()


def led_effective_on(state: MockState) -> bool:
    """Light is visibly on (button label, status copy, icons)."""
    return state.led_on and state.led_brightness > LED_OFF_EPS


def led_slider_locked(state: MockState) -> bool:
    """OFF via power button — brightness stored, slider not draggable."""
    return not state.led_on and state.led_brightness > LED_OFF_EPS


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[float, float, float]:
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


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        int(clamp_byte(r)),
        int(clamp_byte(g)),
        int(clamp_byte(b)),
    )


def clamp_byte(c: float) -> int:
    return max(0, min(255, int(round(c * 255))))


def rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
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


def build_hsv_wheel_texture(size: int) -> Texture:
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
                r, g, b = hsv_to_rgb(hue, sat, 1.0)
                alpha = 255
                if dist > 1.0:
                    alpha = int(255 * (1.05 - dist) / 0.05)
                buf[idx] = clamp_byte(r)
                buf[idx + 1] = clamp_byte(g)
                buf[idx + 2] = clamp_byte(b)
                buf[idx + 3] = alpha
            idx += 4
    tex = Texture.create(size=(size, size), colorfmt="rgba")
    tex.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
    return tex


# ---------------------------------------------------------------------------
# Study dashboard
# ---------------------------------------------------------------------------

STUDY_TONE_PATH = Path(__file__).resolve().parent.parent / "tone.mp3"
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

# To-do popup — same footprint as MCQ / summary pickers
STUDY_TODO_POPUP_SIZE = STUDY_MCQ_POPUP_SIZE
STUDY_TODO_POPUP_PAD = STUDY_MCQ_POPUP_PAD
STUDY_TODO_ROW_H = dp(52)
STUDY_TODO_CHECK_SIZE = dp(34)
STUDY_TODO_DELETE_SIZE = dp(34)
STUDY_TODO_TEXT_FONT = sp(22)
STUDY_TODO_ADD_H = STUDY_MCQ_NAV_H
STUDY_TODO_ROW_RIGHT_PAD = dp(56)
STUDY_TODO_LIST_BOTTOM_PAD = dp(56)
STUDY_TODO_KEY_H = dp(40)
STUDY_TODO_KEY_FONT = sp(17)
STUDY_TODO_KEY_GAP = dp(5)
STUDY_TODO_KEYBOARD_ROWS = 4
STUDY_TODO_KEYBOARD_H = (
    STUDY_TODO_KEY_H * STUDY_TODO_KEYBOARD_ROWS
    + STUDY_TODO_KEY_GAP * (STUDY_TODO_KEYBOARD_ROWS - 1)
    + dp(8)
)

SAVED_MCQ_DIR = Path("/home/unimate/Unimate/saved")
_SAVED_MCQ_MAX_FILES = 10

QUESTIONS_DIR = Path("/home/unimate/Unimate/questions")
QUESTIONS_MAX_FILES = 10

SUMMARIES_DIR = Path("/home/unimate/Unimate/summaries")
SUMMARIES_MAX_FILES = 10
PDF_MODE_STATUS_PATH = Path("/home/unimate/Unimate/pdf_mode/pdf_mode_status.json")
VOICE_TRIGGER_PATH = Path("/home/unimate/Unimate/alexa/voice_trigger.json")
MIC_IN_USE_PATH = Path("/home/unimate/Unimate/shared_mic/mic_in_use.json")

MCQ_LETTERS = ("A", "B", "C", "D")
TODO_KEYBOARD_ROWS = (
    list("QWERTYUIOP"),
    list("ASDFGHJKL") + ["DEL"],
    ["SHIFT"] + list("ZXCVBNM") + [",", "."],
    ["SPACE"],
)


def schedule_touch_safe(
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


def bind_touch_safe_on_press(
    btn: Button,
    callback: Callable[[], None],
    *,
    debounce_s: float = CONTROL_PRESS_DEBOUNCE_S,
) -> None:
    """Bind on_press while coalescing duplicate touch + emulated mouse events."""

    def _handler(*_args) -> None:
        if btn.disabled:
            return
        schedule_touch_safe(btn, callback, debounce_s=debounce_s)

    btn.bind(on_press=_handler)


def touch_is_tap(
    touch,
    *,
    down_x: float,
    down_y: float,
    slop: float = STUDY_MCQ_TOUCH_SLOP,
) -> bool:
    if not touch:
        return False
    return abs(touch.x - down_x) <= slop and abs(touch.y - down_y) <= slop


def quiz_display_name(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"\s+copy\s+(\d+)$", r" (Set \1)", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+copy$", " (Set 1)", stem, flags=re.IGNORECASE)
    return stem.replace("-", " — ")


def list_saved_mcq_files() -> list[Path]:
    if not SAVED_MCQ_DIR.is_dir():
        return []
    files = [p for p in SAVED_MCQ_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:_SAVED_MCQ_MAX_FILES]


def answer_index(options: list[str], answer_raw: object) -> int | None:
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


def normalize_mcq_item(raw: object) -> dict[str, object] | None:
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
    answer_idx = answer_index(options, raw.get("answer"))
    if answer_idx is None:
        return None
    return {"question": question.strip(), "options": options, "answer": answer_idx}


def load_mcqs_from_file(path: Path) -> list[dict[str, object]]:
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
        norm = normalize_mcq_item(item)
        if norm is not None:
            out.append(norm)
    return out


def list_quiz_files() -> list[Path]:
    if not QUESTIONS_DIR.is_dir():
        return []
    files = [p for p in QUESTIONS_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:QUESTIONS_MAX_FILES]


def essay_questions_from_payload(data: object) -> list | None:
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


def normalize_quiz_item(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    answer_raw = raw.get("answer")
    answer = answer_raw.strip() if isinstance(answer_raw, str) else ""
    return {"question": question.strip(), "answer": answer}


def load_quiz_questions_from_file(path: Path) -> list[dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dashboard] Quiz load error ({path.name}): {exc}")
        return []
    essay_list = essay_questions_from_payload(data)
    if not isinstance(essay_list, list):
        return []
    out: list[dict[str, object]] = []
    for item in essay_list:
        norm = normalize_quiz_item(item)
        if norm is not None:
            out.append(norm)
    return out


def list_summary_files() -> list[Path]:
    if not SUMMARIES_DIR.is_dir():
        return []
    files = [p for p in SUMMARIES_DIR.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:SUMMARIES_MAX_FILES]


def summary_text_from_payload(data: object) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("summary", "context", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def load_summary_text_from_file(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dashboard] Summary load error ({path.name}): {exc}")
        return ""
    return summary_text_from_payload(data)


def write_pdf_mode_status(context: str, active: bool) -> None:
    payload = {"pdf_mode_active": active, "context": context}
    try:
        PDF_MODE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PDF_MODE_STATUS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[dashboard] pdf_mode status write error: {exc}")


def write_voice_trigger(trigger: bool) -> None:
    payload = {"trigger": trigger, "requested_at": time.time() if trigger else None}
    try:
        VOICE_TRIGGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOICE_TRIGGER_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[dashboard] voice trigger write error: {exc}")


def write_mic_in_use(is_ui_using: bool) -> None:
    payload = {"is_ui_using": is_ui_using}
    try:
        MIC_IN_USE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MIC_IN_USE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[dashboard] mic_in_use write error: {exc}")


def rgba_to_markup_color(rgba: tuple[float, float, float, float]) -> str:
    r, g, b, _ = rgba
    return f"{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def escape_kivy_plain_text(text: str) -> str:
    """Keep user-authored brackets from being parsed as Kivy markup tags."""
    return text.replace("[", "(").replace("]", ")")


def markdown_inline_to_kivy(text: str) -> str:
    accent = rgba_to_markup_color(Theme.ACCENT_SOFT)
    pattern = re.compile(
        r"`([^`\n]+)`"  # inline code
        r"|\*\*(.+?)\*\*"  # bold
        r"|(?<!\*)\*([^*\n]+?)\*(?!\*)"  # italic
    )
    parts: list[str] = []
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            parts.append(escape_kivy_plain_text(text[pos : match.start()]))
        if match.group(1) is not None:
            inner = escape_kivy_plain_text(match.group(1))
            parts.append(f"[font=DejaVuSansMono][color={accent}]{inner}[/color][/font]")
        elif match.group(2) is not None:
            inner = markdown_inline_to_kivy(match.group(2))
            parts.append(f"[b]{inner}[/b]")
        elif match.group(3) is not None:
            inner = markdown_inline_to_kivy(match.group(3))
            parts.append(f"[i]{inner}[/i]")
        pos = match.end()
    parts.append(escape_kivy_plain_text(text[pos:]))
    return "".join(parts)


def markdown_to_kivy_markup(md: str) -> str:
    accent = rgba_to_markup_color(Theme.ACCENT_SOFT)
    muted = rgba_to_markup_color(Theme.MUTED)
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
            title = markdown_inline_to_kivy(heading.group(2).strip())
            size = int(STUDY_SUMMARY_H3_FONT if level <= 3 else STUDY_SUMMARY_H4_FONT)
            out_lines.append(
                f"[size={size}][b][color={accent}]{title}[/color][/b][/size]"
            )
            continue
        bullet = re.match(r"^(\s*)[*+-]\s+(.+)$", line)
        if bullet:
            indent = "    " * (len(bullet.group(1)) // 2)
            body = markdown_inline_to_kivy(bullet.group(2))
            out_lines.append(f"{indent}• {body}")
            continue
        numbered = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if numbered:
            indent = "    " * (len(numbered.group(1)) // 2)
            body = markdown_inline_to_kivy(numbered.group(3))
            out_lines.append(f"{indent}{numbered.group(2)}. {body}")
            continue
        out_lines.append(markdown_inline_to_kivy(stripped))
    return "\n".join(out_lines)


def format_timer_seconds(total: int) -> str:
    total = max(0, int(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

