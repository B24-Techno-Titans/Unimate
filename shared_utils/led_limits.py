"""Shared LED brightness limit — single source of truth.

The strip's power circuit is unstable at full brightness, so every sender
(bridge, UI, voice agent) caps the 0-255 firmware brightness at
LED_MAX_BRIGHTNESS before/requesting hardware. Raise only in small steps and
re-test on the hardware afterwards.
"""

LED_MAX_BRIGHTNESS = 100
