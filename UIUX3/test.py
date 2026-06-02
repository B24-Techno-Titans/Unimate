from kivy.app import App
from kivy.uix.label import Label
from kivy.config import Config

Config.set('graphics', 'fullscreen', 'auto')

class TouchApp(App):
    def build(self):
        lbl = Label(text="Touch me!", font_size=48)

        def on_touch(widget, touch):
            widget.text = f"Tapped: {int(touch.x)}, {int(touch.y)}"

        lbl.bind(on_touch_down=on_touch)
        return lbl

TouchApp().run()