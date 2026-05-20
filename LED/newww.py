import board
import busio
import time
import neopixel_spi as neopixel  # SPI version

# -------------------- SETUP --------------------
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)  # SCK=GPIO11, MOSI=GPIO10
num_leds = 14
pixels = neopixel.NeoPixel_SPI(spi, num_leds, brightness=0.4, auto_write=True)

# -------------------- FUNCTION --------------------
def set_color(r, g, b):
    for i in range(len(pixels)):
        pixels[i] = (r, g, b)
        print(f"LED {i}")

# -------------------- MAIN LOOP --------------------
try:
    while True:
        # Example: set all LEDs to red
        set_color(255, 0, 0)  # Change to (0,255,0) for green, (0,0,255) for blue
        time.sleep(1)  # Keep color for 1 second
        

except KeyboardInterrupt:
    # Turn off all LEDs when exiting
    set_color(0, 0, 0)
