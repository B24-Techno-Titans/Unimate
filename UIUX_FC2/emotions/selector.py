"""Emotion picker screen: morphing face + Normal / Sad / Angry / Happy buttons."""

from __future__ import annotations

from typing import Callable

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from widgets.buttons import make_button
from emotions.morph import Expression, RoboMorphWidget
from theme import Theme


def build_emotion_screen(
    morph_widget: RoboMorphWidget,
    *,
    on_expression_changed: Callable[[Expression], None] | None = None,
) -> Screen:
    screen = Screen(name="face")
    root = BoxLayout(orientation="vertical", padding=0, spacing=0)

    with root.canvas.before:
        Color(*Theme.FACE_BG)
        bg = Rectangle(pos=root.pos, size=root.size)

    def _sync_bg(*_a):
        bg.pos = root.pos
        bg.size = root.size

    root.bind(pos=_sync_bg, size=_sync_bg)

    morph_widget.size_hint_y = 1
    root.add_widget(morph_widget)

    btn_row = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(58),
        padding=(dp(10), dp(8)),
        spacing=dp(8),
    )

    buttons: dict[Expression, object] = {}

    def _refresh_buttons(_dt: float = 0) -> None:
        settled = morph_widget.settled_expression
        anim = morph_widget.is_animating
        for name, btn in buttons.items():
            active = name == settled and not anim
            btn._accent = active  # noqa: SLF001
            btn._set_pressed(active)  # noqa: SLF001
            btn.disabled = anim

    def _pick(name: Expression):
        def _handler(*_a):
            if morph_widget.is_animating:
                return
            morph_widget.set_expression(name)
            if on_expression_changed:
                on_expression_changed(name)
            _refresh_buttons()

        return _handler

    for label, name in (
        ("Normal", "normal"),
        ("Sad", "sad"),
        ("Angry", "angry"),
        ("Happy", "happy"),
    ):
        btn = make_button(
            label,
            _pick(name),
            accent=(name == "normal"),
            width=dp(92),
            height=dp(42),
        )
        buttons[name] = btn
        btn_row.add_widget(btn)

    # root.add_widget(btn_row)
    screen.add_widget(root)

    def _on_anim_tick(_dt: float) -> None:
        _refresh_buttons()

    from kivy.clock import Clock

    Clock.schedule_interval(_on_anim_tick, 1 / 30.0)
    _refresh_buttons()
    return screen
