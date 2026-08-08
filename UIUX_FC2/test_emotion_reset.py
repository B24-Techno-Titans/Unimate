#!/usr/bin/env python3
"""Quick test script to verify emotion auto-reset timer functionality."""

import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from emotions.morph import RoboMorphWidget, EMOTION_RESET_TIMEOUT_SECONDS


class EmotionResetTestApp(App):
    def build(self):
        self.title = "Emotion Auto-Reset Timer Test"
        
        root = BoxLayout(orientation="vertical", padding=10, spacing=10)
        
        # Status label
        self.status_label = Label(
            text=f"[b]Emotion Auto-Reset Timer Test[/b]\n\n"
            f"[i]Timeout: {EMOTION_RESET_TIMEOUT_SECONDS}s[/i]\n\n"
            f"Instructions:\n"
            f"1. Click a non-normal emotion (Sad, Angry, Happy)\n"
            f"2. Wait ~10 seconds\n"
            f"3. Emotion should auto-reset to Normal\n"
            f"4. Click another emotion during countdown\n"
            f"5. Timer should restart\n\n"
            f"Current emotion: Normal",
            markup=True,
            size_hint_y=0.3,
        )
        root.add_widget(self.status_label)
        
        # Morph widget
        self.morph_widget = RoboMorphWidget()
        root.add_widget(self.morph_widget)
        
        # Setup periodic status update
        from kivy.clock import Clock
        Clock.schedule_interval(self._update_status, 0.2)
        
        return root
    
    def _update_status(self, _dt):
        settled = self.morph_widget.settled_expression
        anim = self.morph_widget.is_animating
        timer_active = self.morph_widget._reset_timer is not None
        
        status = (
            f"[b]Emotion Auto-Reset Timer Test[/b]\n\n"
            f"[i]Timeout: {EMOTION_RESET_TIMEOUT_SECONDS}s[/i]\n\n"
            f"[b]Status:[/b]\n"
            f"Current: {settled.upper()}\n"
            f"Animating: {anim}\n"
            f"Timer Active: {timer_active}"
        )
        self.status_label.text = status


if __name__ == "__main__":
    app = EmotionResetTestApp()
    app.run()
