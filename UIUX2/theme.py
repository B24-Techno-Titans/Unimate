"""Design tokens for the Kivy UniMate UI (neon kawaii robot face palette)."""

from __future__ import annotations

from kivy.metrics import dp, sp


class Theme:
    # Core screen — deep navy (reference face backdrop)
    BLACK = (0.0, 0.0, 0.0, 1.0)
    BG = (0.04, 0.06, 0.14, 1.0)
    FACE_BG = (0.04, 0.06, 0.14, 1.0)
    # Legacy alias — face screen fills with FACE_BG
    EYES_BG = FACE_BG

    # Neon accents
    CYAN = (0.15, 0.92, 1.0, 1.0)
    CYAN_DIM = (0.15, 0.92, 1.0, 0.55)
    VIOLET = (0.52, 0.28, 0.95, 1.0)
    VIOLET_DIM = (0.52, 0.28, 0.95, 0.38)

    # Cards / typography
    PANEL = (0.06, 0.07, 0.12, 0.94)
    PANEL_HI = (0.09, 0.11, 0.17, 0.96)
    BORDER_CYAN_SOFT = (0.15, 0.92, 1.0, 0.35)
    BORDER_VIOLET_SOFT = (0.52, 0.28, 0.95, 0.45)
    BORDER_DIM = (0.15, 0.92, 1.0, 0.2)
    TEXT = (0.92, 0.96, 1.0, 1.0)
    MUTED = (0.5, 0.58, 0.72, 1.0)
    ACCENT = CYAN
    ACCENT_SOFT = (0.45, 0.95, 1.0, 1.0)
    BORDER = BORDER_CYAN_SOFT
    OK = (0.38, 0.95, 0.72, 1.0)
    WARN = (1.0, 0.75, 0.35, 1.0)
    DANGER = (1.0, 0.4, 0.42, 1.0)
    OFF = (0.08, 0.1, 0.14, 1.0)

    # Multi-layer glow for rounded frames (alpha, width multiplier)
    FRAME_GLOW_LAYERS_VIOLET = [
        (0.08, 3.8),
        (0.14, 2.8),
        (0.22, 2.0),
        (0.38, 1.35),
        (0.65, 0.9),
        (1.0, 0.55),
    ]
    CARD_GLOW_LAYERS = [
        (0.06, 2.8),
        (0.12, 2.0),
        (0.24, 1.35),
        (0.45, 0.95),
    ]

    NAV_DOT_ACTIVE = CYAN
    NAV_DOT_DIM = BORDER_DIM

    RADIUS = [dp(22), dp(22), dp(22), dp(22)]
    CARD_CORNER_RADIUS = dp(22)
    PAD = dp(18)
    GAP = dp(14)

    TITLE = sp(24)
    SUBTITLE = sp(13)
    BODY = sp(15)
    CAPTION = sp(11)
    STAT = sp(30)
