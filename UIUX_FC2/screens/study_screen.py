"""Study dashboard screen builder and popup handlers."""

from __future__ import annotations

import json
import math
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from kivy.clock import Clock
from kivy.graphics import Color, InstructionGroup, Line, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

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
from widgets.ask_bunny_widgets import (
    AskBunnyIconRow,
    GlowingDotsRow,
    RespondingCaptionBox,
    RespondBunnyIconRow,
    SpeechProgressRow,
)
from widgets.buttons import GlowFlatButton, GlowIconButton, make_button
from widgets.common import (
    MCQ_LETTERS,
    SAVED_MCQ_DIR,
    STUDY_ASK_DOTS_H,
    STUDY_ASK_ICON_ROW_H,
    STUDY_ASK_POPUP_PAD,
    STUDY_ASK_POPUP_SIZE,
    STUDY_ASK_POPUP_TITLE,
    STUDY_GRID_GAP,
    STUDY_HEADER_H,
    STUDY_MCQ_ACTION_DEBOUNCE_S,
    STUDY_MCQ_ANSWER_FONT,
    STUDY_MCQ_ANSWER_H,
    STUDY_MCQ_FILE_LIST_FONT,
    STUDY_MCQ_FILE_SUB_FONT,
    STUDY_MCQ_GRID_GAP,
    STUDY_MCQ_NAV_H,
    STUDY_MCQ_NAV_W,
    STUDY_MCQ_POPUP_PAD,
    STUDY_MCQ_POPUP_SIZE,
    STUDY_MCQ_QUESTION_FONT,
    STUDY_MCQ_QUESTION_H,
    STUDY_MCQ_RESULTS_ROW_FONT,
    STUDY_MCQ_RESULTS_ROW_H,
    STUDY_PAD,
    STUDY_QUIZ_ANSWER_SECTION_PAD,
    STUDY_RESPOND_CAPTION_H,
    STUDY_RESPOND_PROGRESS_H,
    STUDY_SUMMARY_BODY_FONT,
    STUDY_SUMMARY_H3_FONT,
    STUDY_SUMMARY_H4_FONT,
    STUDY_TITLE,
    STUDY_TODO_ADD_H,
    STUDY_TODO_KEYBOARD_H,
    STUDY_TODO_LIST_BOTTOM_PAD,
    STUDY_TODO_POPUP_PAD,
    STUDY_TODO_POPUP_SIZE,
    STUDY_TODO_ROW_RIGHT_PAD,
    STUDY_TODO_TEXT_FONT,
    STUDY_TONE_PATH,
    STUDY_WHEEL_ROW_H,
    STUDY_WHEEL_VISIBLE_ROWS,
    bind_touch_safe_on_press,
    format_timer_seconds,
    list_quiz_files,
    list_saved_mcq_files,
    list_summary_files,
    load_mcqs_from_file,
    load_quiz_questions_from_file,
    load_summary_text_from_file,
    markdown_to_kivy_markup,
    quiz_display_name,
    schedule_touch_safe,
    write_pdf_mode_status,
    write_voice_trigger,
)
from widgets.mcq_widgets import (
    MCQChoiceButton,
    MCQFileListScroll,
    MCQFileRow,
    MCQNavButton,
    QuizDangerNavButton,
    QuizGlowPanel,
)
from widgets.panels import GlowPanel
from widgets.study_widgets import StudyTile, WheelPickerColumn
from widgets.todo_widgets import TodoRow, UniMateKeyboard

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
    todo_popup: Popup | None = None
    todo_add_popup: Popup | None = None
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
    todo_items: list[dict[str, object]] = [
        {"text": "Study SQL data query language", "done": False},
        {"text": "Practice MCQ generator", "done": False},
        {"text": "Use Voice Quiz", "done": False},
        {"text": "Generate SQL querys notes", "done": False},
        {"text": "Practice MCQ generator (voice list)", "done": False},
        {"text": "Use Voice Quiz", "done": False},
    ]
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
        if not STUDY_TONE_PATH.is_file():
            return False
        path = str(STUDY_TONE_PATH)
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
            timer_tile.set_caption(format_timer_seconds(ctrl.remaining_seconds), accent=Theme.CYAN)
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

        bind_touch_safe_on_press(close_btn, _close_thinking)
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

        bind_touch_safe_on_press(close_btn, _close_responding)
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

        bind_touch_safe_on_press(close_btn, _close_ask_popup)
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
                return MCQ_LETTERS[max(0, min(3, idx))]
            return MCQ_LETTERS[idx]

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
                letter = MCQ_LETTERS[i]
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

        bind_touch_safe_on_press(close_btn, _close_mcq)
        _refresh_mcq_view()
        mcq_popup.open()

    def _open_mcq_file_picker() -> None:
        nonlocal mcq_file_picker
        if mcq_file_picker is not None and mcq_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        quiz_files = list_saved_mcq_files()

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
            questions = load_mcqs_from_file(path)
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
                n = len(load_mcqs_from_file(path))
                subtitle = f"{n} question{'s' if n != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        quiz_display_name(path),
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

        bind_touch_safe_on_press(close_btn, _close_picker)
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

        bind_touch_safe_on_press(close_btn, _close_quiz)
        _refresh_quiz_view()
        quiz_popup.open()

    def _open_quiz_file_picker() -> None:
        nonlocal quiz_file_picker
        if quiz_file_picker is not None and quiz_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        quiz_files = list_quiz_files()

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
            questions = load_quiz_questions_from_file(path)
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
                n = len(load_quiz_questions_from_file(path))
                subtitle = f"{n} question{'s' if n != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        quiz_display_name(path),
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

        bind_touch_safe_on_press(close_btn, _close_picker)
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
            text=markdown_to_kivy_markup(summary_text),
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
            write_voice_trigger(True)

        def _close_viewer(*_a) -> None:
            write_voice_trigger(False)
            write_pdf_mode_status(summary_viewer_context, False)
            if summary_viewer_popup is not None:
                summary_viewer_popup.dismiss()

        ask_btn.bind_safe_press(_on_ask_questions)
        bind_touch_safe_on_press(close_btn, _close_viewer)
        _sync_body_layout(body_lbl)
        summary_viewer_popup.open()

    def _open_summary_file_picker() -> None:
        nonlocal summary_file_picker
        if summary_file_picker is not None and summary_file_picker.parent is not None:
            return

        picker_ready_at = Clock.get_time() + STUDY_MCQ_ACTION_DEBOUNCE_S
        summary_files = list_summary_files()

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
            summary_text = load_summary_text_from_file(path)
            if not summary_text:
                status_lbl.text = "No valid summary text in this file."
                status_lbl.color = Theme.DANGER
                return
            status_lbl.text = ""
            write_pdf_mode_status(summary_text, True)
            if summary_file_picker is not None:
                summary_file_picker.dismiss()
            _open_summary_viewer_popup(quiz_display_name(path), summary_text)

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
                text = load_summary_text_from_file(path)
                char_count = len(text)
                subtitle = f"{char_count:,} character{'s' if char_count != 1 else ''}"
                list_inner.add_widget(
                    MCQFileRow(
                        quiz_display_name(path),
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

        bind_touch_safe_on_press(close_btn, _close_picker)
        summary_file_picker.open()

    def _open_todo_add_popup(*, refresh_main: Callable[[], None]) -> None:
        nonlocal todo_add_popup
        if todo_add_popup is not None and todo_add_popup.parent is not None:
            return

        sheet_pad = (dp(20), dp(14), dp(20), dp(10))
        sheet_spacing = dp(10)
        sheet_body_h = dp(36) + dp(48) + STUDY_TODO_ADD_H + sheet_pad[1] + sheet_pad[3] + sheet_spacing * 2
        sheet_h = sheet_body_h + STUDY_TODO_KEYBOARD_H

        panel = GlowPanel(
            orientation="vertical",
            padding=sheet_pad,
            spacing=sheet_spacing,
            size_hint=(1, 1),
        )
        panel.add_widget(
            Label(
                text="ADD TO-DO ITEM",
                font_size=STUDY_MCQ_FILE_LIST_FONT,
                bold=True,
                color=Theme.ACCENT_SOFT,
                halign="center",
                valign="middle",
                size_hint_y=None,
                height=dp(36),
            )
        )
        text_input = TextInput(
            hint_text="Enter a new task…",
            multiline=False,
            font_size=STUDY_TODO_TEXT_FONT,
            foreground_color=Theme.ACCENT_SOFT,
            background_color=(*Theme.PANEL_HI[:3], 1),
            cursor_color=Theme.CYAN,
            padding=(dp(12), dp(10), dp(12), dp(10)),
            size_hint_y=None,
            height=dp(48),
            keyboard_mode="managed",
        )
        panel.add_widget(text_input)

        actions = BoxLayout(size_hint_y=None, height=STUDY_TODO_ADD_H, spacing=dp(10))
        cancel_btn = MCQNavButton("CANCEL", size_hint_x=1)
        add_btn = MCQNavButton("ADD", size_hint_x=1)
        actions.add_widget(cancel_btn)
        actions.add_widget(add_btn)
        panel.add_widget(actions)
        panel.add_widget(UniMateKeyboard(text_input))

        todo_add_popup = Popup(
            title="",
            content=panel,
            size_hint=(1, None),
            height=sheet_h,
            pos_hint={"x": 0, "y": 0},
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_add(*_a) -> None:
            if todo_add_popup is not None:
                todo_add_popup.dismiss()

        def _confirm_add(*_a) -> None:
            text = text_input.text.strip()
            if not text:
                return
            todo_items.append({"text": text, "done": False})
            _close_add()
            refresh_main()

        cancel_btn.bind_safe_press(_close_add)
        add_btn.bind_safe_press(_confirm_add)
        todo_add_popup.open()
        Clock.schedule_once(lambda _dt: setattr(text_input, "focus", True), 0.1)

    def _open_todo_popup() -> None:
        nonlocal todo_popup
        if todo_popup is not None and todo_popup.parent is not None:
            return

        panel = GlowPanel(
            orientation="vertical",
            padding=STUDY_TODO_POPUP_PAD,
            spacing=dp(8),
            size_hint=(1, 1),
        )

        title_row = BoxLayout(
            size_hint_y=None,
            height=dp(48),
            spacing=dp(10),
            padding=(0, 0, STUDY_TODO_ROW_RIGHT_PAD, 0),
        )
        close_btn = GlowIconButton(
            text="X",
            size_hint=(None, None),
            width=dp(40),
            height=dp(40),
            font_size=sp(22),
        )
        title_lbl = Label(
            text="TO-DO LIST",
            font_size=STUDY_ASK_POPUP_TITLE,
            bold=True,
            color=Theme.ACCENT_SOFT,
            halign="left",
            valign="middle",
            size_hint_x=1,
        )
        title_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
        title_row.add_widget(close_btn)
        title_row.add_widget(title_lbl)
        panel.add_widget(title_row)

        list_scroll = MCQFileListScroll(
            size_hint_y=1,
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        list_inner = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None,
            padding=(0, 0, 0, STUDY_TODO_LIST_BOTTOM_PAD),
        )
        list_inner.bind(minimum_height=list_inner.setter("height"))
        list_scroll.add_widget(list_inner)
        panel.add_widget(list_scroll)

        add_row = BoxLayout(size_hint_y=None, height=STUDY_TODO_ADD_H, padding=(0, dp(4), 0, 0))
        add_btn = MCQNavButton(
            "ADD ITEM",
            size_hint=(1, 1),
        )
        add_row.add_widget(add_btn)
        panel.add_widget(add_row)

        def _refresh_todo_list() -> None:
            list_inner.clear_widgets()
            if not todo_items:
                empty_lbl = Label(
                    text="No items yet. Tap ADD ITEM to create one.",
                    font_size=STUDY_TODO_TEXT_FONT,
                    color=Theme.MUTED,
                    halign="center",
                    valign="middle",
                    size_hint_y=None,
                    height=dp(80),
                )
                empty_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
                list_inner.add_widget(empty_lbl)
                return
            for idx, item in enumerate(todo_items, start=1):
                text = str(item.get("text", ""))
                done = bool(item.get("done", False))
                item_index = idx - 1

                def _make_toggle(i: int = item_index) -> Callable[[], None]:
                    def _toggle_done() -> None:
                        todo_items[i]["done"] = not bool(todo_items[i].get("done", False))
                        _refresh_todo_list()

                    return _toggle_done

                def _make_delete(i: int = item_index) -> Callable[[], None]:
                    def _delete_item() -> None:
                        if 0 <= i < len(todo_items):
                            todo_items.pop(i)
                            _refresh_todo_list()

                    return _delete_item

                list_inner.add_widget(
                    TodoRow(
                        idx,
                        text,
                        done=done,
                        on_toggle=_make_toggle(),
                        on_delete=_make_delete(),
                    )
                )

        todo_popup = Popup(
            title="",
            content=panel,
            size_hint=STUDY_TODO_POPUP_SIZE,
            auto_dismiss=False,
            separator_height=0,
            background="",
            background_color=Theme.PANEL,
        )

        def _close_todo(*_a) -> None:
            if todo_popup is not None:
                todo_popup.dismiss()

        def _open_add(*_a) -> None:
            _open_todo_add_popup(refresh_main=_refresh_todo_list)

        bind_touch_safe_on_press(close_btn, _close_todo)
        add_btn.bind_safe_press(_open_add)
        _refresh_todo_list()
        todo_popup.open()

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

    def _on_todo_tile_tap() -> None:
        Clock.schedule_once(lambda _dt: _open_todo_popup(), 0)

    tile_defs: list[tuple[str, str, Callable[[], None] | None]] = [
        ("question.png", "ASK FROM BUNNY", _on_ask_bunny_tile_tap),
        ("timer.png", "STUDY TIMER", _on_timer_tile_tap),
        ("open-book.png", "SUMMARIZE NOTES", _on_summarize_notes_tile_tap),
        ("to-do.png", "TO-DO LIST", _on_todo_tile_tap),
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
