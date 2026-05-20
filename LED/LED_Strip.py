import board
import busio
import time
import threading
import neopixel_spi as neopixel  # SPI version

RGB_path = "/home/unimate/Unimate/LED/rgb.data"
flow_on = False

# -------------------- SETUP --------------------
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)  # SCK=GPIO11, MOSI=GPIO10
num_leds = 14 
pixels = neopixel.NeoPixel_SPI(spi, num_leds, brightness=0.4, auto_write=True)

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

def start_rgb_flow():
    if not flow_on:
        flow_thread = threading.Thread(target=rgb_flow)
        flow_thread.daemon = True # Daemon ensures thread dies if main program dies
        flow_thread.start()

def rgb_flow():
    global flow_on
    flow_on = True
    while flow_on:
        for j in range(255):
            if not flow_on:
                return  # Exit the function immediately
            for i in range(len(pixels)):
                rc_index = (i * 256 // len(pixels)) + j
                color = wheel(rc_index & 255)
                pixels[i] = color
                print(f"LED {i}: {color}", end="")
                # time.sleep(0.004) # prints RGB values for each LED
            time.sleep(0.02)

def set_color(r, g, b):
    global flow_on
    if flow_on:
        flow_on = False
        time.sleep(0.1) 

    #save_current_color(r, g, b)
    for i in range(len(pixels)):
        pixels[i] = (r, g, b)
        # print(f"LED {i}: {(r,g,b)} ", end="")

def save_current_color(r, g, b):
    with open(RGB_path, "w") as f:
        f.write(f"{r} {g} {b}")

def get_current_color():    #as a List
    rgb = []
    with open(RGB_path, "r") as f:
        line = f.readline()
        for n in line.split():
            rgb.append(int(n))
    return rgb

# -------------------- MAIN LOOP --------------------
# For Testing
if __name__ == "__main__":
    import time

    start_rgb_flow()
    try:
        while True:
    #        # Example: set all LEDs to red
    #        set_color(255, 0, 0)  # Change to (0,255,0) for green, (0,0,255) for blue
    #        time.sleep(1)  # Keep color for 1 second
            pass

    except KeyboardInterrupt:
        # Turn off all LEDs when exiting
        set_color(0, 0, 0)
