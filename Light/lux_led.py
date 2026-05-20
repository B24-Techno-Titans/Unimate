import LuxSensor as lux
import LED_Strip as led
import time

range_id = 0

def adjust_brightness(r, g, b, precentage):
    r = int(r * precentage)
    g = int(g * precentage)
    b = int(b * precentage)
    return (r, g, b)

led.set_color(255,0,0)

while True:
    light = lux.get_lux()
    r, g, b = led.get_current_color()

    if light > 200:
        if(not range_id == 1):
            range_id = 1
            r, g, b = adjust_brightness(r, g, b, 0.4)
    elif light>125:
        if(not range_id == 2):
            range_id = 2
            r, g, b = adjust_brightness(r, g, b, 0.6)
    elif light>80:
        if(not range_id == 3):
            range_id = 3
            r, g, b = adjust_brightness(r, g, b, 0.8)
    else:
        if(not range_id == 4):
            range_id = 4
            r, g, b = adjust_brightness(r, g, b, 1)
    
    led.set_color(r, g, b)
    time.sleep(2)
