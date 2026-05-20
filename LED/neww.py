import time
import board
import busio
import neopixel_spi as neopixel  # SPI version

# Setup SPI
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)  # SCK=GPIO11, MOSI=GPIO10
pixels = neopixel.NeoPixel_SPI(spi, 14, brightness=0.4, auto_write=True)  # 30 LEDs

def wheel(pos):
    # Generate rainbow colors
    if pos < 0 or pos > 255:
        return (0, 0, 0)
    if pos < 85:
        return (int(pos*3), int(255 - pos*3), 0)
    elif pos < 170:
        pos -= 85
        return (int(255 - pos*3), 0, int(pos*3))
    else:
        pos -= 170
        return (0, int(pos*3), int(255 - pos*3))

# RGB fading loop with debug print
try:
    while True:
        for j in range(255):
            for i in range(len(pixels)):
                rc_index = (i * 256 // len(pixels)) + j
                color = wheel(rc_index & 255)
                pixels[i] = color
                print(f"LED {i}: {color}", end="")
                # time.sleep(0.004) # prints RGB values for each LED
            time.sleep(0.02)

except KeyboardInterrupt:
    for i in range(len(pixels)):
        pixels[i] = (0,0,0)
