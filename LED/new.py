import time
import board
import busio
import neopixel_spi as neopixel  # use this name in code

# Setup SPI
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)  # SCK=GPIO11, MOSI=GPIO10
pixels = neopixel.NeoPixel_SPI(spi, 30, brightness=0.0, auto_write=True)  # 30 LEDs, reduced brightness

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

# RGB fading loop
try:
    while True:
        for j in range(255):
            for i in range(len(pixels)):
                rc_index = (i * 256 // len(pixels)) + j
                pixels[i] = wheel(rc_index & 255)
                color = wheel(rc_index & 255)
                print(f"LED {i} -> {color}")
            time.sleep(0.005)

except KeyboardInterrupt:
    for i in range(len(pixels)):
        pixels[i] = (0,0,0)
