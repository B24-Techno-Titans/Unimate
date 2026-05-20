import time
from rpi_ws281x import PixelStrip, Color

LED_COUNT = 60
LED_PIN = 13
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 64 
LED_INVERT = False
LED_CHANNEL = 1    # Channel 0 for GPIO12

strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA,
                   LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
strip.begin()

def wheel(pos):
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

def rainbow_cycle(wait):
    n = strip.numPixels()
    j = 0
    while True:  # run forever until Ctrl+C
        for i in range(n):
            strip.setPixelColor(i, wheel((i * 256 // n + j) & 255))
        strip.show()
        time.sleep(wait / 1000.0)
        j = (j + 1) % 256  # wrap around smoothly

def clear_strip():
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()

if __name__ == '__main__':
    try:
        rainbow_cycle(20)
    except KeyboardInterrupt:
        print("\tExiting...")
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()
