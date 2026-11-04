"""Spotify music control screen — talks to Spotify Soloist over its local WebSocket API.

Screen: ``MusicScreen`` (ScreenManager name ``"music"``). Connects only to
``ws://127.0.0.1:<port>`` (loopback, never exposed); the Soloist process is
started and configured outside this app — we never start/stop/configure it and
the API key never appears here (the local WS API takes no key).

Protocol notes (verified against the Soloist WebSocket API reference):
  * commands used: get_state, get_queue, play, pause, skip_prev, skip_next,
    seek(position_ms), set_volume(volume 0-100), set_shuffle(enabled),
    set_repeat_context(enabled), set_repeat_track(enabled)
  * events used: auth_state, playback_state, track_changed, playback_changed,
    volume_changed, position_sync, options_changed, queue_changed, error
  * ``options_changed`` / ``playback_state.options`` carry shuffle + repeat
    (``off`` / ``context`` / ``track``)
  * ``queue_changed`` carries ``previous`` / ``upcoming`` entry arrays
  * there is no mute command in the WS API; mute is implemented locally by
    sending ``set_volume`` 0 and restoring the previous level (documented field)

Requires: ``pip install websocket-client`` (``import websocket``). If missing,
the screen degrades to "Music player not running" with disabled controls.
"""

from __future__ import annotations

import json
import math
import threading
import time
from io import BytesIO
from typing import Any, Callable

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import (
    Color,
    InstructionGroup,
    Line,
    Rectangle,
    RoundedRectangle,
    Triangle,
)
from kivy.metrics import dp, sp
from kivy.network.urlrequest import UrlRequest
from kivy.properties import BooleanProperty, ObjectProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget

from theme import Theme
from widgets.animations import CircuitBackdrop
from widgets.common import (
    STUDY_GRID_GAP,
    STUDY_HEADER_H,
    STUDY_PAD,
    schedule_touch_safe,
)
from widgets.mcq_widgets import MCQNavButton
from widgets.panels import GlowPanel

try:  # Only third-party dependency of this screen.
    import websocket  # type: ignore[import]  # pip install websocket-client
except ImportError:  # Screen shows "Music player not running"; app never crashes.
    websocket = None

# ---------------------------------------------------------------------------
# Soloist connection config (loopback only; matches soloist --ws 127.0.0.1:9090)
# ---------------------------------------------------------------------------

SOLOIST_WS_HOST = "127.0.0.1"  # bind/discover is done by soloist itself, never here
SOLOIST_WS_PORT = 9090
SOLOIST_WS_URL = f"ws://{SOLOIST_WS_HOST}:{SOLOIST_WS_PORT}"
SOLOIST_RECONNECT_DELAY_S = 2.0
SOLOIST_PING_INTERVAL_S = 20.0

POSITION_TICK_INTERVAL_S = 0.5  # UI interpolation between position_sync anchors

# Optional equalizer bars — animated only while this screen is visible AND
# playback is active. Set to False to hide the bars entirely.
ENABLE_EQUALIZER = True
ANIM_TICK_INTERVAL_S = 0.1  # 10 FPS; deliberately low for the Pi 4

# "Up next" card: show this many queue entries; ask Soloist for one spare.
QUEUE_ROWS = 4
QUEUE_REQUEST_LIMIT = 5

ALBUM_ART_TIMEOUT_S = 8.0
ALBUM_ART_MAX_BYTES = 1_500_000  # request small/default covers; skip huge payloads
_ART_CACHE: dict[str, Any] = {}
_ART_CACHE_MAX = 4  # tiny LRU — only textures for recently seen tracks stay alive

# Cover size preference from the WS docs (sizes: small, default, large, xlarge)
_ART_SIZE_PREF = ("small", "default")

# Playback status values confirmed in the WS API reference
_PLAYING_STATUSES = ("playing", "buffering")

# Repeat modes confirmed in the WS API reference
_REPEAT_MODES = ("off", "context", "track")


# ---------------------------------------------------------------------------
# Payload helpers (verified against the Soloist WebSocket API reference)
# ---------------------------------------------------------------------------


def _entity_name(entity: Any) -> str | None:
    """entity.decorations.identity.name — display name when known."""
    if not isinstance(entity, dict):
        return None
    deco = entity.get("decorations")
    if not isinstance(deco, dict):
        return None
    identity = deco.get("identity")
    name = identity.get("name") if isinstance(identity, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _entity_artists(entity: Any) -> list[str]:
    """entity.decorations.creators[].entity.decorations.identity.name."""
    if not isinstance(entity, dict):
        return []
    deco = entity.get("decorations")
    creators = deco.get("creators") if isinstance(deco, dict) else None
    if not isinstance(creators, list):
        return []
    names: list[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        name = _entity_name(creator.get("entity"))
        if name:
            names.append(name)
    return names


def _entity_album(entity: Any) -> str | None:
    """entity.decorations.parent.entity — album (or show) parent entity."""
    if not isinstance(entity, dict):
        return None
    deco = entity.get("decorations")
    parent = deco.get("parent") if isinstance(deco, dict) else None
    if not isinstance(parent, dict):
        return None
    return _entity_name(parent.get("entity"))


def _entity_cover_url(entity: Any) -> str | None:
    """entity.decorations.visual_identity.cover[].url — prefer small/default."""
    if not isinstance(entity, dict):
        return None
    deco = entity.get("decorations")
    visual = deco.get("visual_identity") if isinstance(deco, dict) else None
    covers = visual.get("cover") if isinstance(visual, dict) else None
    if not isinstance(covers, list):
        return None
    urls: dict[str, str] = {}
    for cover in covers:
        if not isinstance(cover, dict):
            continue
        url = cover.get("url")
        size = cover.get("size")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls[str(size)] = url
    for size in _ART_SIZE_PREF:
        if size in urls:
            return urls[size]
    return next(iter(urls.values()), None)


def _entity_duration_ms(entity: Any) -> int | None:
    """entity.decorations.playback.duration_ms."""
    if not isinstance(entity, dict):
        return None
    deco = entity.get("decorations")
    playback = deco.get("playback") if isinstance(deco, dict) else None
    value = playback.get("duration_ms") if isinstance(playback, dict) else None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _entity_uri(entity: Any) -> str | None:
    if not isinstance(entity, dict):
        return None
    uri = entity.get("uri")
    return uri if isinstance(uri, str) and uri else None


def _image_ext_from_bytes(data: bytes) -> str:
    """Kivy inline CoreImage needs `ext` — loaders register it WITHOUT a dot."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) > 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF8"):
        return "gif"
    return "jpg"  # Spotify covers are JPEG overwhelmingly


def _format_mmss(ms: int | None) -> str:
    if not isinstance(ms, int) or ms < 0:
        ms = 0
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes}:{seconds:02d}"


# ---------------------------------------------------------------------------
# Background WebSocket client (one daemon thread, auto-reconnect ~2 s)
# ---------------------------------------------------------------------------


class _SoloistClient:
    """Owns the Soloist WebSocket connection; callbacks hop to the UI thread."""

    def __init__(
        self,
        on_connected: Callable[[], None],
        on_disconnected: Callable[[], None],
        on_event: Callable[[dict], None],
    ) -> None:
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_event = on_event
        self._ws = None
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="soloist-ws", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal shutdown and disconnect; never raises."""
        self._stop_event.set()
        self._close_ws()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)

    def send_command(self, command: str, **fields: Any) -> bool:
        """Send one control/query command. Non-blocking-ish and never raises."""
        ws = self._ws
        if ws is None:
            return False
        message = {"type": "command", "command": command}
        message.update(fields)
        try:
            with self._send_lock:
                ws.send(json.dumps(message))
            return True
        except Exception as exc:  # connection raced a drop — reconnect will fix it
            print(f"[music] soloist send error ({command}): {exc}")
            return False

    # -- worker thread ------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if websocket is None:
                self._stop_event.wait(60.0)
                continue
            WebSocketApp = getattr(websocket, "WebSocketApp", None)
            if WebSocketApp is None:
                self._stop_event.wait(60.0)
                continue
            try:
                app = WebSocketApp(
                    SOLOIST_WS_URL,
                    on_open=self._cb_open,
                    on_message=self._cb_message,
                    on_error=self._cb_error,
                    on_close=self._cb_close,
                )
                self._ws = app
                # Server pushes auth_state (+playback_state when logged in) on
                # connect; run_forever keeps the socket alive with pings.
                app.run_forever(
                    ping_interval=SOLOIST_PING_INTERVAL_S, ping_timeout=10.0
                )
            except Exception as exc:
                print(f"[music] soloist ws error: {exc}")
            self._ws = None
            if self._stop_event.is_set():
                break
            self._stop_event.wait(SOLOIST_RECONNECT_DELAY_S)  # responsive sleep

    def _close_ws(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            pass

    # -- WebSocketApp callbacks (worker thread) -----------------------------

    def _cb_open(self, _ws=None) -> None:
        self._dispatch(self._on_connected)

    def _cb_message(self, _ws=None, message: Any = None) -> None:
        # websocket-client delivers text frames as `str` (and data as `bytes`).
        raw: str | None = None
        if isinstance(message, str):
            raw = message
        elif isinstance(message, (bytes, bytearray)):
            raw = bytes(message).decode("utf-8", "replace")
        if not raw:
            return
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            print(f"[music] soloist bad frame: {exc}")
            return
        if isinstance(event, dict):
            self._dispatch(self._on_event, event)

    def _cb_error(self, _ws=None, error: Any = None) -> None:
        print(f"[music] soloist ws error: {error}")

    def _cb_close(self, _ws=None, *_args) -> None:
        self._dispatch(self._on_disconnected)

    def _dispatch(self, callback: Callable, *args: Any) -> None:
        """Hop into the Kivy main thread; never touch widgets from here."""
        try:
            Clock.schedule_once(lambda _dt: callback(*args), 0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Custom widgets (canvas-only — same neon style as the rest of the app)
# ---------------------------------------------------------------------------


class AlbumArt(Widget):
    """Square album art tile; rounded like the app's icon badges."""

    texture = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._fill_color = Color(*Theme.PANEL_HI)
            self._fill = RoundedRectangle(
                pos=self.pos, size=self.size, radius=Theme.RADIUS
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS),
                width=dp(1.2),
            )
            self._art_color = Color(1, 1, 1, 1)
            self._art = RoundedRectangle(radius=[dp(12)] * 4)
        self.bind(pos=self._redraw, size=self._redraw, texture=self._redraw)

    def _redraw(self, *_args) -> None:
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = (
            self.x, self.y, self.width, self.height, Theme.CARD_CORNER_RADIUS
        )
        tex = self.texture
        if tex is not None and self.width > 8 and self.height > 8:
            side = min(self.width, self.height) * 0.94
            self._art.pos = (
                self.center_x - side / 2,
                self.center_y - side / 2,
            )
            self._art.size = (side, side)
            self._art.texture = tex
            self._art_color.rgba = (1, 1, 1, 1)
        else:
            self._art.size = (0, 0)
            self._art.texture = None


class SeekBar(Widget):
    """Tappable progress bar (thick neon line + knob) — swipe-safe.

    Tap or drag to scrub; the release commits ``seek position_ms`` (docs-confirmed).
    """

    disabled = BooleanProperty(False)

    def __init__(
        self,
        on_commit: Callable[[float], None],
        on_scrub: Callable[[float], None] | None = None,
        **kwargs,
    ):
        self._on_commit = on_commit
        self._on_scrub = on_scrub
        self._fraction = 0.0
        self._dragging = False
        super().__init__(**kwargs)
        with self.canvas:
            # bottom-up: pill track, cyan glow, dim base, bright fill, knob
            self._track_color = Color(*Theme.PANEL_HI)
            self._track = RoundedRectangle(radius=[dp(14)] * 4)
            self._glow_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0.14)
            self._glow = RoundedRectangle(radius=[dp(9)] * 4)
            self._bg_color = Color(*Theme.BORDER_DIM)
            self._bg_line = RoundedRectangle(radius=[dp(5)] * 4)
            self._fg_color = Color(*Theme.ACCENT_SOFT)
            self._fg_line = RoundedRectangle(radius=[dp(5)] * 4)
            self._knob_color = Color(*Theme.CYAN)
            self._knob = RoundedRectangle(radius=[dp(12)] * 4)
        self.bind(pos=self._redraw, size=self._redraw, disabled=self._redraw)

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._redraw()

    @property
    def dragging(self) -> bool:
        """True while the user is scrubbing (position ticks must not fight it)."""
        return self._dragging

    def _redraw(self, *_args) -> None:
        w, h = self.width, self.height
        track_h = min(h, dp(30))
        y = self.center_y - track_h / 2
        self._track.pos = (self.x, y)
        self._track.size = (w, track_h)
        bar_radius = [dp(6)] * 4
        self._bg_line.pos = (self.x, self.center_y - dp(4))
        self._bg_line.size = (w, dp(8))
        self._bg_line.radius = bar_radius
        fill_w = max(dp(14), w * self._fraction)
        self._glow.pos = (self.x, self.center_y - dp(9))
        self._glow.size = (fill_w, dp(18))
        self._glow.radius = [dp(9)] * 4
        self._fg_line.pos = (self.x, self.center_y - dp(6))
        self._fg_line.size = (fill_w, dp(12))
        self._fg_line.radius = bar_radius
        knob_side = dp(24)
        knob_x = self.x + w * self._fraction
        knob_x = max(self.x + knob_side / 2, min(self.x + w - knob_side / 2, knob_x))
        self._knob.pos = (
            knob_x - knob_side / 2,
            self.center_y - knob_side / 2,
        )
        self._knob.size = (knob_side, knob_side)
        self._knob.radius = [knob_side / 2] * 4
        # bright blue progress fill (Theme.ACCENT_SOFT is visibly brighter than
        # Theme.CYAN); disabled = dimmed
        self._fg_color.rgba = (
            Theme.ACCENT_SOFT if not self.disabled else Theme.BORDER_DIM
        )
        self._knob_color.rgba = (
            Theme.CYAN if not self.disabled else Theme.BORDER_DIM
        )
        self._glow_color.rgba = (
            Theme.CYAN[0],
            Theme.CYAN[1],
            Theme.CYAN[2],
            0.14 if not self.disabled else 0.0,
        )

    # touches: drag anywhere to scrub, commit on release (docs: `seek`, position_ms)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._dragging = True
        touch.grab(self)
        self._set_from_touch(touch)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._set_from_touch(touch)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            self._dragging = False
            touch.ungrab(self)
            fraction = self._fraction_from_touch(touch)
            if 0.0 <= fraction <= 1.0:
                self._on_commit(fraction)
            self.set_fraction(fraction)
            return True
        return super().on_touch_up(touch)

    def on_touch_cancel(self, touch):
        if touch.grab_current is self:
            self._dragging = False
            touch.ungrab(self)
            return True
        return super().on_touch_cancel(touch)

    def _fraction_from_touch(self, touch) -> float:
        if self.width <= 1:
            return 0.0
        return max(0.0, min(1.0, (touch.x - self.x) / self.width))

    def _set_from_touch(self, touch) -> None:
        fraction = self._fraction_from_touch(touch)
        self.set_fraction(fraction)
        if self._on_scrub is not None:
            self._on_scrub(fraction)


class _IconButton(Button):
    """Neon icon button matching the app's violet frame / cyan glow language.

    The repo's ``icons/`` set has no media glyphs, so icons are drawn on the
    canvas with the same palette (violet frame, cyan glyph, press glow) instead
    of adding new assets.
    """

    _RADIUS = dp(14)

    def __init__(
        self,
        icon: str,
        on_press_cb: Callable[[], None] | None = None,
        *,
        accent: bool = False,
        active: bool = False,
        active_color=Theme.CYAN,
        glow: bool = False,
        toggle: bool = False,
        size=(dp(56), dp(56)),
        **kwargs,
    ):
        self._icon_name = icon
        self._on_press_cb = on_press_cb
        self._accent = accent
        self._active = active
        self._active_color = active_color
        self._always_glow = glow
        self._toggle = toggle
        self._pressed = False
        kwargs.setdefault("text", "")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", size)
        kwargs.setdefault("pos_hint", {"center_y": 0.5})
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        super().__init__(**kwargs)

        self._badge = Label(
            text="",
            font_size=sp(10),
            bold=True,
            color=Theme.CYAN,
            size_hint=(None, None),
            size=(dp(18), dp(18)),
            halign="center",
            valign="middle",
        )
        self._badge.bind(
            size=lambda inst, *_: setattr(inst, "text_size", (inst.width, inst.height))
        )
        self.add_widget(self._badge)

        with self.canvas.before:
            self._outer_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._outer = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(2.2) * 4.4,
                cap="round",
            )
            self._inner_color = Color(Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], 0)
            self._inner = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(2.2) * 2.5,
                cap="round",
            )
            self._fill_color = Color(*Theme.PANEL)
            self._fill = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self._RADIUS] * 4
            )
            self._border_color = Color(*Theme.BORDER_VIOLET_SOFT)
            self._border = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self._RADIUS),
                width=dp(1.2),
            )
        self._icon_group = InstructionGroup()
        self.canvas.after.add(self._icon_group)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas, disabled=self._sync_canvas)
        self.bind(on_press=self._handle_press)
        self._sync_canvas()

    # -- public state -------------------------------------------------------

    def set_icon(self, icon: str) -> None:
        if icon == self._icon_name:
            return
        self._icon_name = icon
        self._sync_canvas()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._sync_canvas()

    def set_badge(self, text: str) -> None:
        self._badge.text = text

    # -- drawing ------------------------------------------------------------

    def _icon_color(self):
        if self.disabled:
            return (Theme.MUTED[0], Theme.MUTED[1], Theme.MUTED[2], 0.45)
        if self._accent:
            return Theme.BLACK
        if self._active:
            return self._active_color
        if self._toggle:
            return Theme.MUTED
        return Theme.ACCENT_SOFT

    def _sync_canvas(self, *_args) -> None:
        rr = (self.x, self.y, self.width, self.height, self._RADIUS)
        self._outer.rounded_rectangle = rr
        self._inner.rounded_rectangle = rr
        self._fill.pos = self.pos
        self._fill.size = self.size
        self._border.rounded_rectangle = rr

        if self.disabled:
            fill = Theme.PANEL
            border = Theme.BORDER_DIM
            border_w = dp(1.2)
            glow = 0.0
        elif self._accent:
            fill = Theme.CYAN
            border = Theme.CYAN
            border_w = dp(1.6)
            glow = 0.25 if self._pressed else (0.14 if self._always_glow else 0.0)
        elif self._active:
            fill = Theme.PANEL_HI
            border = self._active_color
            border_w = dp(1.6)
            glow = 0.20 if self._pressed else 0.12
        else:
            fill = Theme.PANEL
            border = Theme.BORDER_VIOLET_SOFT
            border_w = dp(1.2)
            glow = 0.25 if self._pressed else 0.0

        self._fill_color.rgba = fill
        self._border_color.rgba = border
        self._border.width = border_w
        self._outer_color.rgba = (
            Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], glow * 0.6
        )
        self._inner_color.rgba = (
            Theme.CYAN[0], Theme.CYAN[1], Theme.CYAN[2], glow
        )
        self._badge.pos = (self.right - dp(18), self.top - dp(18))
        self._badge.color = self._icon_color()
        self._draw_icon()

    def _add_line(self, points, width, color, *, close=False) -> None:
        self._icon_group.add(Color(*color))
        self._icon_group.add(Line(points=points, width=width, cap="round", close=close))

    def _add_triangle(self, points, color) -> None:
        self._icon_group.add(Color(*color))
        self._icon_group.add(Triangle(points=points))

    def _add_rect(self, x, y, w, h, radius, color) -> None:
        self._icon_group.add(Color(*color))
        self._icon_group.add(
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[radius] * 4)
        )

    def _add_rounded_outline(self, x, y, w, h, radius, width, color) -> None:
        self._icon_group.add(Color(*color))
        self._icon_group.add(
            Line(rounded_rectangle=(x, y, w, h, radius), width=width, cap="round")
        )

    def _draw_icon(self) -> None:
        self._icon_group.clear()
        if self.width < 8 or self.height < 8:
            return
        s = min(self.width, self.height)
        cx, cy = self.center
        color = self._icon_color()
        line_w = max(dp(2.2), s * 0.05)
        icon = self._icon_name

        if icon == "play":
            self._add_triangle(
                [
                    cx - s * 0.16, cy - s * 0.27,
                    cx - s * 0.16, cy + s * 0.27,
                    cx + s * 0.27, cy,
                ],
                color,
            )
        elif icon == "pause":
            bar_w = s * 0.13
            bar_h = s * 0.46
            self._add_rect(cx - s * 0.23, cy - bar_h / 2, bar_w, bar_h, s * 0.03, color)
            self._add_rect(cx + s * 0.10, cy - bar_h / 2, bar_w, bar_h, s * 0.03, color)
        elif icon == "prev":
            self._add_rect(
                cx - s * 0.28, cy - s * 0.23, s * 0.08, s * 0.46, s * 0.02, color
            )
            self._add_triangle(
                [
                    cx + s * 0.24, cy - s * 0.26,
                    cx + s * 0.24, cy + s * 0.26,
                    cx - s * 0.12, cy,
                ],
                color,
            )
        elif icon == "next":
            self._add_triangle(
                [
                    cx - s * 0.24, cy - s * 0.26,
                    cx - s * 0.24, cy + s * 0.26,
                    cx + s * 0.12, cy,
                ],
                color,
            )
            self._add_rect(
                cx + s * 0.20, cy - s * 0.23, s * 0.08, s * 0.46, s * 0.02, color
            )
        elif icon == "shuffle":
            self._add_line(
                [
                    cx - s * 0.28, cy + s * 0.16,
                    cx - s * 0.12, cy + s * 0.16,
                    cx + s * 0.10, cy - s * 0.16,
                    cx + s * 0.24, cy - s * 0.16,
                ],
                line_w,
                color,
            )
            self._add_line(
                [
                    cx - s * 0.28, cy - s * 0.16,
                    cx - s * 0.12, cy - s * 0.16,
                    cx + s * 0.10, cy + s * 0.16,
                    cx + s * 0.24, cy + s * 0.16,
                ],
                line_w,
                color,
            )
            self._add_triangle(
                [
                    cx + s * 0.15, cy - s * 0.23,
                    cx + s * 0.15, cy - s * 0.09,
                    cx + s * 0.28, cy - s * 0.16,
                ],
                color,
            )
            self._add_triangle(
                [
                    cx + s * 0.15, cy + s * 0.09,
                    cx + s * 0.15, cy + s * 0.23,
                    cx + s * 0.28, cy + s * 0.16,
                ],
                color,
            )
        elif icon == "repeat":
            self._add_rounded_outline(
                cx - s * 0.30, cy - s * 0.18,
                s * 0.60, s * 0.36,
                dp(8), line_w, color,
            )
            self._add_triangle(
                [
                    cx + s * 0.16, cy + s * 0.27,
                    cx + s * 0.16, cy + s * 0.09,
                    cx + s * 0.32, cy + s * 0.18,
                ],
                color,
            )
            self._add_triangle(
                [
                    cx - s * 0.16, cy - s * 0.27,
                    cx - s * 0.16, cy - s * 0.09,
                    cx - s * 0.32, cy - s * 0.18,
                ],
                color,
            )
        elif icon in ("volume", "mute"):
            self._add_line(
                [
                    cx - s * 0.30, cy - s * 0.09,
                    cx - s * 0.16, cy - s * 0.09,
                    cx - s * 0.02, cy - s * 0.24,
                    cx - s * 0.02, cy + s * 0.24,
                    cx - s * 0.16, cy + s * 0.09,
                    cx - s * 0.30, cy + s * 0.09,
                ],
                line_w,
                color,
                close=True,
            )
            if icon == "mute":
                self._add_line(
                    [cx + s * 0.02, cy - s * 0.22, cx + s * 0.28, cy + s * 0.22],
                    line_w,
                    Theme.WARN,
                )
            else:
                self._add_line(
                    [
                        cx + s * 0.08, cy - s * 0.10,
                        cx + s * 0.16, cy,
                        cx + s * 0.08, cy + s * 0.10,
                    ],
                    line_w,
                    color,
                )
                self._add_line(
                    [
                        cx + s * 0.15, cy - s * 0.18,
                        cx + s * 0.27, cy,
                        cx + s * 0.15, cy + s * 0.18,
                    ],
                    line_w,
                    color,
                )

    # -- input --------------------------------------------------------------

    def _handle_press(self, *_args) -> None:
        if self.disabled:
            return
        self._pressed = True
        self._sync_canvas()
        Clock.schedule_once(self._after_press, 0.14)

    def _after_press(self, _dt: float) -> None:
        self._pressed = False
        self._sync_canvas()
        if self._on_press_cb is not None:
            schedule_touch_safe(self, self._on_press_cb)


class EqualizerBars(Widget):
    """Tiny 5-bar equalizer. Advanced by the screen only while playing."""

    _BAR_COUNT = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._phase = 0.0
        self._levels = [0.12] * self._BAR_COUNT
        with self.canvas:
            self._colors = []
            self._bars = []
            for _ in range(self._BAR_COUNT):
                self._colors.append(Color(*Theme.ACCENT_SOFT))
                self._bars.append(RoundedRectangle(radius=[dp(2)] * 4))
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def advance(self, dt: float) -> None:
        self._phase += dt
        for i in range(self._BAR_COUNT):
            wave = math.sin(self._phase * (3.4 + i * 0.55) + i * 1.7)
            self._levels[i] = 0.22 + 0.78 * abs(wave)
        self._redraw()

    def reset(self) -> None:
        self._levels = [0.12] * self._BAR_COUNT
        self._redraw()

    def _redraw(self, *_args) -> None:
        w, h = self.width, self.height
        if w < dp(8) or h < dp(4):
            return
        gap = dp(3)
        bar_w = max(dp(2), (w - gap * (self._BAR_COUNT - 1)) / self._BAR_COUNT)
        for i, bar in enumerate(self._bars):
            bar_h = max(dp(2), h * self._levels[i])
            bar.pos = (self.x + i * (bar_w + gap), self.y)
            bar.size = (bar_w, bar_h)


class MarqueeLabel(StencilView):
    """Single-line label that scrolls long titles; static + ellipsized otherwise."""

    def __init__(
        self,
        text: str = "",
        *,
        font_size=sp(30),
        color=Theme.TEXT,
        bold: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._scrolling = False
        self._offset = 0.0
        self._gap = dp(48)
        self._syncing = False
        self._label = Label(
            text=text,
            font_size=font_size,
            bold=bold,
            color=color,
            halign="left",
            valign="middle",
            size_hint=(None, None),
        )
        self.add_widget(self._label)
        self.bind(pos=self._sync_geometry, size=self._sync_geometry)
        self._label.bind(texture_size=self._on_texture)
        Clock.schedule_once(lambda _dt: self._sync_geometry(), 0)

    def set_text(self, text: str) -> None:
        if self._label.text == text:
            return
        self._label.text = text
        self._offset = 0.0
        self._sync_geometry()

    def set_scrolling(self, enabled: bool) -> None:
        if self._scrolling == enabled:
            return
        self._scrolling = enabled
        self._offset = 0.0
        self._sync_geometry()

    def advance(self, dt: float) -> None:
        if not self._scrolling:
            return
        natural_w = self._label.texture_size[0]
        if natural_w <= self.width + dp(2):
            if self._offset:
                self._offset = 0.0
                self._label.x = self.x
            return
        self._offset += dp(22) * dt  # ~22 dp/s — gentle, low FPS
        max_offset = natural_w - self.width + self._gap
        if self._offset >= max_offset:
            self._offset = 0.0
        self._label.x = self.x - self._offset

    def _on_texture(self, *_args) -> None:
        if not self._syncing:
            self._sync_geometry()

    def _sync_geometry(self, *_args) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            label = self._label
            if self._scrolling:
                label.shorten = False
                label.text_size = (None, None)
                natural_w = max(label.texture_size[0], self.width)
                label.size = (natural_w, self.height)
                label.pos = (self.x - self._offset, self.y)
            else:
                label.shorten = True
                label.shorten_from = "right"
                label.text_size = (self.width, self.height)
                label.size = (self.width, self.height)
                label.pos = self.pos
        finally:
            self._syncing = False


class _QueueRow(BoxLayout):
    """One compact "Up next" row: index + title + artist."""

    def __init__(self, index: int, **kwargs):
        super().__init__(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(44),
            **kwargs,
        )
        self._index_label = Label(
            text=str(index),
            font_size=sp(12),
            bold=True,
            color=Theme.CYAN,
            size_hint_x=None,
            width=dp(16),
            halign="left",
            valign="middle",
        )
        self._title_label = Label(
            text="—",
            font_size=sp(13),
            bold=True,
            color=Theme.TEXT,
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        self._artist_label = Label(
            text="",
            font_size=sp(10),
            color=Theme.MUTED,
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
        )
        for lab in (self._index_label, self._title_label, self._artist_label):
            lab.bind(
                size=lambda inst, *_: setattr(inst, "text_size", (inst.width, inst.height))
            )
        col = BoxLayout(orientation="vertical", spacing=0)
        col.add_widget(self._title_label)
        col.add_widget(self._artist_label)
        self.add_widget(self._index_label)
        self.add_widget(col)

    def set_entry(self, title: str, artist: str) -> None:
        self._title_label.text = title or "—"
        self._title_label.color = Theme.TEXT
        self._artist_label.text = artist or ""
        self._index_label.color = Theme.CYAN if title else Theme.BORDER_DIM

    def set_empty(self, text: str) -> None:
        self._title_label.text = text
        self._title_label.color = Theme.MUTED
        self._artist_label.text = ""
        self._index_label.color = Theme.BORDER_DIM

    def clear(self) -> None:
        self.set_empty("")


class _VolumeSlider(Slider):
    """Themed volume slider; drag sends `set_volume` once on release.

    Kivy's default Slider draws a white track/cursor; this subclass replaces the
    canvas with the same neon track/fill/knob used by the seek bar while keeping
    Slider's built-in touch → value mapping.
    """

    def __init__(self, **kwargs):
        self.dragging = False
        self.on_release_cb: Callable[[], None] | None = None
        # Custom canvas draws the full width; padding=0 makes Slider's touch
        # mapping match the drawn track exactly.
        kwargs.setdefault("padding", 0)
        super().__init__(**kwargs)
        self.canvas.clear()
        with self.canvas:
            self._track_color = Color(*Theme.PANEL_HI)
            self._track = RoundedRectangle(radius=[dp(10)] * 4)
            self._bg_color = Color(*Theme.BORDER_DIM)
            self._bg = RoundedRectangle(radius=[dp(4)] * 4)
            self._fill_color = Color(*Theme.ACCENT_SOFT)
            self._fill = RoundedRectangle(radius=[dp(5)] * 4)
            self._knob_color = Color(*Theme.CYAN)
            self._knob = RoundedRectangle(radius=[dp(10)] * 4)
        self.bind(
            pos=self._redraw,
            size=self._redraw,
            value=self._redraw,
            disabled=self._redraw,
        )
        self._redraw()

    def _redraw(self, *_args) -> None:
        w, h = self.width, self.height
        if w < dp(8) or h < dp(4):
            return
        track_h = min(h, dp(20))
        self._track.pos = (self.x, self.center_y - track_h / 2)
        self._track.size = (w, track_h)
        self._bg.pos = (self.x, self.center_y - dp(3))
        self._bg.size = (w, dp(6))
        span = max(1.0, float(self.max) - float(self.min))
        fraction = max(0.0, min(1.0, (float(self.value) - float(self.min)) / span))
        fill_w = max(dp(10), w * fraction)
        self._fill.pos = (self.x, self.center_y - dp(5))
        self._fill.size = (fill_w, dp(10))
        knob_side = dp(20)
        knob_x = self.x + w * fraction
        knob_x = max(self.x + knob_side / 2, min(self.x + w - knob_side / 2, knob_x))
        self._knob.pos = (
            knob_x - knob_side / 2,
            self.center_y - knob_side / 2,
        )
        self._knob.size = (knob_side, knob_side)
        self._knob.radius = [knob_side / 2] * 4
        self._fill_color.rgba = (
            Theme.ACCENT_SOFT if not self.disabled else Theme.BORDER_DIM
        )
        self._knob_color.rgba = (
            Theme.CYAN if not self.disabled else Theme.BORDER_DIM
        )

    def on_touch_down(self, touch):
        if (
            not self.disabled
            and not touch.is_mouse_scrolling
            and self.collide_point(*touch.pos)
        ):
            self.dragging = True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        was_dragging = self.dragging
        result = super().on_touch_up(touch)
        if was_dragging:
            self.dragging = False
            # Consumed here so the touch cannot fall through to the swipe.
            if self.on_release_cb is not None:
                self.on_release_cb()
            return True
        return result

    def on_touch_cancel(self, touch):
        self.dragging = False
        return super().on_touch_cancel(touch)


class MusicScreen(Screen):
    """Now-playing + transport controls for Spotify Soloist (local WS API)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("name", "music")
        super().__init__(**kwargs)

        self._client: _SoloistClient | None = None
        self._active = False
        self._connected = False
        self._logged_in = False
        self._is_playing = False
        self._position_anchor: dict[str, float] = {}
        self._duration_ms: int | None = None
        self._track_uri: str | None = None
        self._art_url: str | None = None
        self._shuffle_on = False
        self._repeat_mode = "off"
        self._queue_items: list[tuple[str, str]] = []
        self._volume_before_mute = 50
        self._last_volume_sent: int | None = None
        self._mute_visual: bool | None = None
        self._anim_ev = None

        root = FloatLayout()
        with root.canvas.before:
            root._bg_color = Color(*Theme.BG)
            root._bg_rect = Rectangle(pos=root.pos, size=root.size)

        def _sync_bg(*_args):
            root._bg_rect.pos = root.pos
            root._bg_rect.size = root.size

        root.bind(pos=_sync_bg, size=_sync_bg)
        root.add_widget(CircuitBackdrop(size_hint=(1, 1)))

        content = BoxLayout(
            orientation="vertical",
            padding=STUDY_PAD,
            spacing=STUDY_GRID_GAP,
            size_hint=(1, 1),
        )

        # -- header: back button + title + status ---------------------------
        header_row = BoxLayout(size_hint_y=None, height=STUDY_HEADER_H, spacing=dp(12))
        header_row.add_widget(
            MCQNavButton(
                "BACK",
                size_hint=(None, None),
                size=(dp(96), dp(46)),
                on_safe_press=self._go_back,
            )
        )
        title = Label(
            text="MUSIC",
            font_size=sp(34),
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
        )
        title.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        header_row.add_widget(title)
        header_row.add_widget(Widget())  # spacer
        self._status_label = Label(
            text="Music player not running",
            font_size=Theme.BODY,
            bold=True,
            color=Theme.WARN,
            halign="right",
            valign="middle",
        )
        self._status_label.bind(
            size=lambda inst, *_: setattr(inst, "text_size", (inst.width, inst.height))
        )
        header_row.add_widget(self._status_label)
        content.add_widget(header_row)

        # -- body: now playing (left) + up next (right) ---------------------
        body_row = BoxLayout(
            orientation="horizontal",
            spacing=STUDY_GRID_GAP,
            size_hint_y=1,
        )

        now_playing = GlowPanel(
            orientation="horizontal",
            spacing=dp(14),
            size_hint_x=0.62,
        )
        art_holder = AnchorLayout(size_hint=(None, 1), width=dp(248))
        self._art = AlbumArt(size_hint=(None, None), size=(dp(232), dp(232)))
        art_holder.add_widget(self._art)
        now_playing.add_widget(art_holder)

        track_col = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            padding=(0, dp(6), 0, dp(2)),
        )
        self._title_marquee = MarqueeLabel(
            "Nothing playing",
            font_size=sp(30),
            bold=True,
            color=Theme.TEXT,
            size_hint_y=None,
            height=dp(54),
        )
        self._artist_label = Label(
            text="",
            font_size=sp(21),
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(32),
            shorten=True,
            shorten_from="right",
        )
        self._album_label = Label(
            text="",
            font_size=sp(14),
            color=Theme.MUTED,
            halign="left",
            valign="top",
            size_hint_y=1,
            shorten=True,
            shorten_from="right",
        )
        for lab in (self._artist_label, self._album_label):
            lab.bind(
                size=lambda inst, *_: setattr(inst, "text_size", (inst.width, inst.height))
            )
        track_col.add_widget(self._title_marquee)
        track_col.add_widget(self._artist_label)
        track_col.add_widget(self._album_label)

        self._eq = EqualizerBars(size_hint=(None, None), size=(dp(76), dp(26)))
        if ENABLE_EQUALIZER:
            eq_row = BoxLayout(size_hint_y=None, height=dp(28))
            eq_row.add_widget(Widget())
            eq_row.add_widget(self._eq)
            track_col.add_widget(eq_row)

        now_playing.add_widget(track_col)
        body_row.add_widget(now_playing)

        up_next = GlowPanel(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(6),
            size_hint_x=0.38,
        )
        up_header = BoxLayout(size_hint_y=None, height=dp(24))
        up_title = Label(
            text="UP NEXT",
            font_size=sp(14),
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
        )
        up_title.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        up_header.add_widget(up_title)
        self._queue_hint = Label(
            text="",
            font_size=sp(10),
            color=Theme.MUTED,
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(52),
        )
        self._queue_hint.bind(
            size=lambda inst, *_: setattr(inst, "text_size", (inst.width, inst.height))
        )
        up_header.add_widget(self._queue_hint)
        up_next.add_widget(up_header)

        self._queue_rows: list[_QueueRow] = []
        for i in range(QUEUE_ROWS):
            row = _QueueRow(i + 1)
            self._queue_rows.append(row)
            up_next.add_widget(row)
        up_next.add_widget(Widget())  # keep rows top-aligned
        body_row.add_widget(up_next)
        content.add_widget(body_row)

        # -- transport card: seek bar + icon controls + volume --------------
        transport = GlowPanel(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(208),
        )

        seek_row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(10))
        self._elapsed_label = Label(
            text="0:00",
            font_size=sp(13),
            color=Theme.MUTED,
            size_hint_x=None,
            width=dp(54),
        )
        self._seek_bar = SeekBar(
            on_commit=self._on_seek_commit,
            on_scrub=self._on_seek_scrub,
            size_hint_x=1,
        )
        self._duration_label = Label(
            text="0:00",
            font_size=sp(13),
            color=Theme.MUTED,
            size_hint_x=None,
            width=dp(54),
        )
        seek_row.add_widget(self._elapsed_label)
        seek_row.add_widget(self._seek_bar)
        seek_row.add_widget(self._duration_label)
        transport.add_widget(seek_row)

        controls_row = BoxLayout(
            size_hint_y=None,
            height=dp(76),
            spacing=dp(14),
            padding=(dp(20), 0, dp(20), 0),
        )
        controls_row.add_widget(Widget())  # spacer
        self._shuffle_btn = _IconButton(
            "shuffle",
            self._on_shuffle_pressed,
            toggle=True,
            size=(dp(52), dp(52)),
        )
        controls_row.add_widget(self._shuffle_btn)
        self._prev_btn = _IconButton(
            "prev",
            lambda: self._send_command("skip_prev"),
            size=(dp(58), dp(58)),
        )
        controls_row.add_widget(self._prev_btn)
        self._play_btn = _IconButton(
            "play",
            self._on_play_pause,
            accent=True,
            glow=True,
            size=(dp(92), dp(66)),
        )
        controls_row.add_widget(self._play_btn)
        self._next_btn = _IconButton(
            "next",
            lambda: self._send_command("skip_next"),
            size=(dp(58), dp(58)),
        )
        controls_row.add_widget(self._next_btn)
        self._repeat_btn = _IconButton(
            "repeat",
            self._on_repeat_pressed,
            toggle=True,
            size=(dp(52), dp(52)),
        )
        controls_row.add_widget(self._repeat_btn)
        controls_row.add_widget(Widget())  # spacer
        transport.add_widget(controls_row)

        volume_row = BoxLayout(
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
            padding=(dp(20), 0, dp(20), 0),
        )
        volume_row.add_widget(
            Label(
                text="VOLUME",
                font_size=Theme.CAPTION,
                bold=True,
                color=Theme.MUTED,
                size_hint_x=None,
                width=dp(70),
            )
        )
        self._mute_btn = _IconButton(
            "volume",
            self._on_mute_pressed,
            active_color=Theme.WARN,
            toggle=True,
            size=(dp(40), dp(40)),
        )
        volume_row.add_widget(self._mute_btn)
        self._volume_slider = _VolumeSlider(
            min=0, max=100, step=1, value=50, cursor_size=(dp(30), dp(30))
        )
        self._volume_slider.on_release_cb = self._on_volume_touch_up
        self._volume_slider.bind(value=self._on_volume_value)
        volume_row.add_widget(self._volume_slider)
        self._volume_label = Label(
            text="50%",
            font_size=Theme.SUBTITLE,
            bold=True,
            color=Theme.TEXT,
            size_hint_x=None,
            width=dp(48),
        )
        volume_row.add_widget(self._volume_label)
        transport.add_widget(volume_row)

        content.add_widget(transport)
        root.add_widget(content)
        self.add_widget(root)

        self._set_controls_enabled(False)
        self._sync_option_buttons()
        self._sync_mute_button(force=True)
        self._set_queue_items([])
        self._sync_play_button()

    # -- lifecycle ----------------------------------------------------------

    def on_enter(self, *args) -> None:
        self._active = True
        self._set_status("Connecting to music player…", Theme.MUTED)
        try:
            self._start_client()
        except Exception as exc:
            print(f"[music] client start error: {exc}")
        Clock.schedule_interval(self._tick_position, POSITION_TICK_INTERVAL_S)

    def on_leave(self, *args) -> None:
        self._active = False
        Clock.unschedule(self._tick_position)
        self._stop_animations()
        try:
            self._stop_client()
        except Exception as exc:
            print(f"[music] client stop error: {exc}")

    def _start_client(self) -> None:
        if websocket is None:
            self._set_ws_state(False)
            return
        if self._client is not None:
            self._stop_client()
        self._client = _SoloistClient(
            on_connected=self._handle_ws_connected,
            on_disconnected=self._handle_ws_disconnected,
            on_event=self._handle_ws_event,
        )
        self._client.start()

    def _stop_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.stop()

    def _go_back(self) -> None:
        try:
            manager = self.manager
            # Home = the robot face screen (same target as the app idle timeout).
            if manager is not None and "face" in manager.screen_names:
                manager.transition.direction = "left"
                manager.current = "face"
        except Exception:
            pass

    # -- WebSocket callbacks (UI thread via Clock) --------------------------

    def _handle_ws_connected(self) -> None:
        if not self._active:
            return
        self._connected = True
        self._logged_in = False
        client = self._client
        if client is not None:
            client.send_command("get_state")  # refresh snapshot after reconnect

    def _handle_ws_disconnected(self) -> None:
        if not self._active:
            return
        self._set_ws_state(False)

    def _handle_ws_event(self, event: dict) -> None:
        if not self._active or not isinstance(event, dict):
            return
        try:
            event_type = event.get("type")
            if event_type == "auth_state":
                self._apply_auth_state(event)
            elif event_type == "playback_state":
                self._apply_playback_state(event)
            elif event_type == "track_changed":
                self._apply_track(event.get("item"))
            elif event_type == "playback_changed":
                self._apply_status(event.get("status"))
            elif event_type == "volume_changed":
                self._apply_volume(event.get("volume"))
            elif event_type == "position_sync":
                self._apply_position_anchor(event.get("position"))
            elif event_type == "options_changed":
                self._apply_options(event.get("options"))
            elif event_type == "queue_changed":
                self._apply_queue(event)
            elif event_type == "error":
                print(f"[music] soloist api error: {event.get('message')}")
        except Exception as exc:
            print(f"[music] event handling error: {exc}")

    # -- state appliers ------------------------------------------------------

    def _apply_auth_state(self, event: dict) -> None:
        self._connected = True
        self._logged_in = bool(event.get("logged_in"))
        device_name = event.get("device_name")
        if not self._logged_in:
            self._clear_now_playing()
            self._set_status("Spotify not logged in", Theme.WARN)
            self._set_controls_enabled(False)
            self._set_queue_items([])
        else:
            suffix = f" ({device_name})" if device_name else ""
            self._set_status(f"Soloist{suffix}", Theme.OK)
            self._set_controls_enabled(True)
            self._request_queue()

    def _apply_playback_state(self, event: dict) -> None:
        # A playback snapshot only arrives when a session is authenticated
        # (docs: get_state requires login; snapshot is sent on connect when logged in).
        self._connected = True
        self._logged_in = True
        device_name = event.get("device_name")
        if device_name:
            self._set_status(f"Soloist ({device_name})", Theme.OK)
        elif self._status_label.text.startswith("Connecting"):
            self._set_status("Soloist", Theme.OK)
        self._set_controls_enabled(True)
        item = event.get("item")
        self._apply_track(item)
        self._apply_options(event.get("options"))
        self._apply_status(event.get("status"))
        self._apply_volume(event.get("volume"))
        self._apply_position_anchor(event.get("position"))
        if not self._queue_items:
            self._request_queue()

    def _apply_track(self, item: Any) -> None:
        uri = _entity_uri(item)
        title = _entity_name(item)
        artist = " · ".join(_entity_artists(item)) if item else None
        album = _entity_album(item)
        duration = _entity_duration_ms(item)

        self._title_marquee.set_text(title or "Nothing playing")
        self._artist_label.text = artist or ""
        self._album_label.text = album or ""
        self._duration_ms = duration
        self._duration_label.text = _format_mmss(duration) if duration else "0:00"

        if uri != self._track_uri:
            self._track_uri = uri
            self._seek_bar.set_fraction(0.0)
            self._elapsed_label.text = "0:00"

        art_url = _entity_cover_url(item)
        if art_url:
            self._load_album_art(art_url)
        else:
            self._set_album_art(None)

    def _apply_status(self, status: Any) -> None:
        self._is_playing = status in _PLAYING_STATUSES
        self._sync_play_button()
        if self._logged_in:
            if status == "playing":
                self._set_status("Now playing", Theme.OK)
            elif status == "paused":
                self._set_status("Paused", Theme.ACCENT_SOFT)
            elif status == "buffering":
                self._set_status("Buffering…", Theme.WARN)
            elif status == "idle":
                self._set_status("Nothing playing", Theme.MUTED)
        self._sync_animations()

    def _apply_options(self, options: Any) -> None:
        if not isinstance(options, dict):
            return
        shuffle = options.get("shuffle")
        if isinstance(shuffle, bool):
            self._shuffle_on = shuffle
        repeat = options.get("repeat")
        if repeat in _REPEAT_MODES:
            self._repeat_mode = repeat
        self._sync_option_buttons()

    def _apply_volume(self, volume: Any) -> None:
        if not isinstance(volume, (int, float)):
            return
        value = int(max(0, min(100, round(volume))))
        self._last_volume_sent = value
        if not self._volume_slider.dragging:
            self._volume_slider.value = value
            self._volume_label.text = f"{value}%"
        self._sync_mute_button()

    def _apply_position_anchor(self, position: Any) -> None:
        if not isinstance(position, dict):
            return
        pos = position.get("position_ms")
        ts = position.get("timestamp_ms")
        speed = position.get("speed")
        if isinstance(pos, (int, float)) and isinstance(ts, (int, float)):
            self._position_anchor = {
                "position_ms": float(pos),
                "timestamp_ms": float(ts),
                "speed": float(speed) if isinstance(speed, (int, float)) else 0.0,
            }
            # The 2 Hz tick only runs while playing; reflect paused seeks now.
            if not self._is_playing:
                self._elapsed_label.text = _format_mmss(int(pos))
                if self._duration_ms:
                    self._seek_bar.set_fraction(
                        max(0.0, min(1.0, float(pos) / self._duration_ms))
                    )

    # -- queue --------------------------------------------------------------

    def _request_queue(self) -> None:
        if not (self._connected and self._logged_in):
            return
        self._send_command("get_queue", limit=QUEUE_REQUEST_LIMIT)

    def _apply_queue(self, event: dict) -> None:
        upcoming = event.get("upcoming")
        entries = upcoming if isinstance(upcoming, list) else []
        items: list[tuple[str, str]] = []
        for entry in entries[:QUEUE_ROWS]:
            item = entry.get("item") if isinstance(entry, dict) else None
            title = _entity_name(item) or "Unknown track"
            artist = " · ".join(_entity_artists(item))
            items.append((title, artist))
        self._set_queue_items(items)

    def _set_queue_items(self, items: list[tuple[str, str]]) -> None:
        self._queue_items = list(items)
        if not items:
            self._queue_rows[0].set_empty("Queue is empty")
            for row in self._queue_rows[1:]:
                row.clear()
            self._queue_hint.text = ""
            return
        for i, row in enumerate(self._queue_rows):
            if i < len(items):
                row.set_entry(*items[i])
            else:
                row.clear()
        self._queue_hint.text = f"{len(items)}"

    # -- derived positions / art ---------------------------------------------

    def _estimated_position_ms(self) -> int | None:
        anchor = self._position_anchor
        if not anchor or self._duration_ms is None:
            return None
        elapsed = (time.time() * 1000.0 - anchor["timestamp_ms"]) * anchor["speed"]
        return int(max(0, min(self._duration_ms, anchor["position_ms"] + elapsed)))

    def _tick_position(self, _dt: float) -> None:
        """Light 2 Hz UI update (docs: interpolate between position_sync anchors)."""
        try:
            if not (self._connected and self._logged_in):
                return
            if not self._is_playing:
                return  # paused: position only changes via position_sync
            elapsed = self._estimated_position_ms()
            if elapsed is None:
                return
            if not self._seek_bar.dragging:
                self._elapsed_label.text = _format_mmss(elapsed)
                if self._duration_ms:
                    self._seek_bar.set_fraction(elapsed / self._duration_ms)
        except Exception as exc:
            print(f"[music] position tick error: {exc}")

    def _load_album_art(self, url: str) -> None:
        if url == self._art_url:
            return
        self._art_url = url
        cached = _ART_CACHE.get(url)
        if cached is not None:
            self._art.texture = cached
            return
        UrlRequest(
            url,
            on_success=self._on_art_loaded,
            on_failure=self._on_art_failed,
            on_error=self._on_art_failed,
            timeout=ALBUM_ART_TIMEOUT_S,
        )

    def _on_art_loaded(self, _request: UrlRequest, result: Any) -> None:
        try:
            url = getattr(_request, "url", None) or self._art_url
            if not isinstance(result, (bytes, bytearray)):
                return
            data = bytes(result)
            if len(data) > ALBUM_ART_MAX_BYTES:
                return  # too big for low-RAM kiosk — skip art
            ext = _image_ext_from_bytes(data)
            texture = CoreImage(BytesIO(data), ext=ext).texture
            _ART_CACHE[url] = texture
            while len(_ART_CACHE) > _ART_CACHE_MAX:
                _ART_CACHE.pop(next(iter(_ART_CACHE)))
            if self._active and url == self._art_url:
                self._art.texture = texture
        except Exception as exc:
            print(f"[music] album art error: {exc}")

    def _on_art_failed(self, _request: UrlRequest, *_args) -> None:
        print("[music] album art load failed — keeping placeholder")

    def _set_album_art(self, texture: Any) -> None:
        self._art_url = None
        self._art.texture = texture

    # -- animation -----------------------------------------------------------

    def _sync_animations(self) -> None:
        """Animations run only while this screen is visible AND playing."""
        should_run = self._active and self._is_playing
        self._title_marquee.set_scrolling(should_run)
        if should_run:
            if self._anim_ev is None:
                self._anim_ev = Clock.schedule_interval(
                    self._tick_animations, ANIM_TICK_INTERVAL_S
                )
        else:
            if self._anim_ev is not None:
                self._anim_ev.cancel()
                self._anim_ev = None
            self._eq.reset()

    def _stop_animations(self) -> None:
        if self._anim_ev is not None:
            self._anim_ev.cancel()
            self._anim_ev = None
        self._title_marquee.set_scrolling(False)
        self._eq.reset()

    def _tick_animations(self, dt: float) -> None:
        if not (self._active and self._is_playing):
            self._stop_animations()
            return
        self._title_marquee.advance(dt)
        if ENABLE_EQUALIZER:
            self._eq.advance(dt)

    # -- control wiring -------------------------------------------------------

    def _sync_play_button(self) -> None:
        self._play_btn.set_icon("pause" if self._is_playing else "play")

    def _sync_option_buttons(self) -> None:
        self._shuffle_btn.set_active(self._shuffle_on)
        self._repeat_btn.set_active(self._repeat_mode != "off")
        self._repeat_btn.set_badge("1" if self._repeat_mode == "track" else "")

    def _sync_mute_button(self, *, force: bool = False) -> None:
        muted = int(round(max(0, min(100, self._volume_slider.value)))) <= 0
        if not force and self._mute_visual == muted:
            return
        self._mute_visual = muted
        self._mute_btn.set_icon("mute" if muted else "volume")
        self._mute_btn.set_active(muted)

    def _set_status(self, text: str, color) -> None:
        self._status_label.text = text
        self._status_label.color = color

    def _clear_now_playing(self) -> None:
        """Reset the Now Playing card (used for disconnect and logout)."""
        self._is_playing = False
        self._position_anchor = {}
        self._duration_ms = None
        self._track_uri = None
        self._title_marquee.set_text("Nothing playing")
        self._artist_label.text = ""
        self._album_label.text = ""
        self._elapsed_label.text = "0:00"
        self._duration_label.text = "0:00"
        self._seek_bar.set_fraction(0.0)
        self._set_album_art(None)
        self._sync_play_button()
        self._sync_animations()

    def _set_ws_state(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._logged_in = False
            self._clear_now_playing()
            self._shuffle_on = False
            self._repeat_mode = "off"
            self._sync_option_buttons()
            self._set_queue_items([])
            self._set_status("Music player not running", Theme.WARN)
            self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for btn in (
            self._prev_btn,
            self._play_btn,
            self._next_btn,
            self._shuffle_btn,
            self._repeat_btn,
            self._mute_btn,
        ):
            try:
                btn.disabled = not enabled
            except Exception:
                pass
        self._volume_slider.disabled = not enabled
        self._seek_bar.disabled = not enabled

    def _send_command(self, command: str, **fields: Any) -> None:
        client = self._client
        if client is not None:
            client.send_command(command, **fields)

    def _on_play_pause(self, *_args) -> None:
        if not (self._connected and self._logged_in):
            return
        try:
            self._send_command("pause" if self._is_playing else "play")
        except Exception as exc:
            print(f"[music] play/pause error: {exc}")

    def _on_seek_scrub(self, fraction: float) -> None:
        """Live time preview while the seek knob is dragged."""
        if not self._duration_ms:
            return
        self._elapsed_label.text = _format_mmss(
            int(max(0, min(self._duration_ms, fraction * self._duration_ms)))
        )

    def _on_seek_commit(self, fraction: float) -> None:
        """SeekBar released → `seek position_ms` (docs-confirmed)."""
        if not (self._connected and self._logged_in) or not self._duration_ms:
            return
        try:
            target = int(max(0, min(self._duration_ms, fraction * self._duration_ms)))
            self._send_command("seek", position_ms=target)
            # Jump the UI instantly; server confirms/overrides via position_sync.
            self._position_anchor = {
                "position_ms": float(target),
                "timestamp_ms": time.time() * 1000.0,
                "speed": 1.0 if self._is_playing else 0.0,
            }
            self._elapsed_label.text = _format_mmss(target)
        except Exception as exc:
            print(f"[music] seek error: {exc}")

    def _on_volume_value(self, slider: Slider, value: float) -> None:
        try:
            self._volume_label.text = f"{int(round(value))}%"
            self._sync_mute_button()
        except Exception:
            pass

    def _on_volume_touch_up(self) -> None:
        """Drag finished → send `set_volume` once (docs: volume field 0–100)."""
        try:
            if not (self._connected and self._logged_in):
                return
            value = int(round(max(0, min(100, self._volume_slider.value))))
            if value > 0:
                self._volume_before_mute = value
            if value != self._last_volume_sent:
                self._send_command("set_volume", volume=value)
                self._last_volume_sent = value
            self._sync_mute_button()
        except Exception as exc:
            print(f"[music] volume error: {exc}")

    def _on_mute_pressed(self) -> None:
        """No mute command exists in the WS API — toggle via `set_volume`."""
        if not (self._connected and self._logged_in):
            return
        try:
            current = int(round(max(0, min(100, self._volume_slider.value))))
            if current > 0:
                self._volume_before_mute = current
                target = 0
            else:
                target = max(1, min(100, self._volume_before_mute or 50))
            self._send_command("set_volume", volume=target)
            self._last_volume_sent = target
            self._volume_slider.value = target
            self._volume_label.text = f"{target}%"
            self._sync_mute_button()
        except Exception as exc:
            print(f"[music] mute error: {exc}")

    def _on_shuffle_pressed(self) -> None:
        if not (self._connected and self._logged_in):
            return
        self._shuffle_on = not self._shuffle_on
        self._send_command("set_shuffle", enabled=self._shuffle_on)
        self._sync_option_buttons()

    def _on_repeat_pressed(self) -> None:
        """Cycle off → context → track using the documented command pairs."""
        if not (self._connected and self._logged_in):
            return
        next_mode = {
            "off": "context",
            "context": "track",
            "track": "off",
        }.get(self._repeat_mode, "off")
        if next_mode == "off":
            self._send_command("set_repeat_track", enabled=False)
            self._send_command("set_repeat_context", enabled=False)
        elif next_mode == "context":
            self._send_command("set_repeat_track", enabled=False)
            self._send_command("set_repeat_context", enabled=True)
        else:
            self._send_command("set_repeat_context", enabled=False)
            self._send_command("set_repeat_track", enabled=True)
        self._repeat_mode = next_mode
        self._sync_option_buttons()


# ---------------------------------------------------------------------------


def build_music_screen() -> Screen:
    """Factory — same style as the other screen builders (``build_*_screen``)."""
    screen = MusicScreen(name="music")
    return screen


# ---------------------------------------------------------------------------
# Standalone test: run this screen alone without touching the main app
# python3 screens/music_screen.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os  # noqa: E402
    from pathlib import Path  # noqa: E402

    def _ensure_display() -> None:
        """Same display fix-up as main.py: attach to the local X desktop (Xwayland).

        Without this, a run over SSH has no DISPLAY and Kivy cannot connect
        to X ("Unable to connect to X server") so nothing shows on the kiosk.
        """
        if os.environ.get("DISPLAY"):
            return
        forced = os.environ.get("UNIMATE_DISPLAY", "").strip()
        if forced:
            os.environ["DISPLAY"] = forced
            return
        xdir = Path("/tmp/.X11-unix")
        if xdir.is_dir():
            for entry in sorted(xdir.glob("X*")):
                name = entry.name
                if name.startswith("X") and name[1:].isdigit():
                    os.environ["DISPLAY"] = f":{name[1:]}"
                    return
        os.environ.setdefault("DISPLAY", ":0")

    _ensure_display()

    # Identical screen-out (Config/window mode) to main.py:
    # borderless fullscreen kiosk by default, 1024x600 windowed under
    # UNIMATE_WINDOWED=1 — so this screen shows exactly like the others.
    _WINDOWED = os.environ.get("UNIMATE_WINDOWED", "").strip().lower() in {"1", "true", "yes"}

    from kivy.config import Config  # noqa: E402

    if _WINDOWED:
        Config.set("graphics", "fullscreen", "0")
        Config.set("graphics", "borderless", "0")
        Config.set("graphics", "resizable", "1")
        Config.set("graphics", "width", "1024")
        Config.set("graphics", "height", "600")
        Config.set("graphics", "minimum_width", "800")
        Config.set("graphics", "minimum_height", "480")
    else:
        Config.set("graphics", "fullscreen", "auto")
        Config.set("graphics", "borderless", "1")

    Config.set("graphics", "multisamples", "4")

    try:
        Config.write()
    except OSError:
        pass

    from kivy.app import App  # noqa: E402
    from kivy.core.window import Window  # noqa: E402
    from kivy.uix.screenmanager import SlideTransition, ScreenManager  # noqa: E402

    from theme import Theme as _Theme  # noqa: E402

    class _MusicDemoApp(App):
        title = "UniMate Music (standalone)"

        def build(self):
            Window.clearcolor = _Theme.BG
            if _WINDOWED:
                Window.fullscreen = False
            manager = ScreenManager(transition=SlideTransition(duration=0.22))
            manager.add_widget(MusicScreen())  # screen name "music"
            manager.current = "music"
            return manager

    _MusicDemoApp().run()
