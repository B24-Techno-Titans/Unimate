import math
import esp_led as led
import LuxSensor

def lux_to_brightness(lux, Lmax=500):
    """
    Convert ambient light in lux to brightness (0-255).
    
    Parameters:
        lux (float): Current lux reading from sensor
        Lmax (float): Maximum expected lux value (default = 1000 for indoor use)
    
    Returns:
        int: Brightness value between 0 and 255
    """
    # Prevent division by zero or negative lux
    lux = max(lux, 0)
    
    # Logarithmic mapping
    # brightness = 255 * (math.log(1 + lux) / math.log(1 + Lmax))
    brightness = 255 * (1 - (math.log(1 + lux) / math.log(1 + Lmax)))
    
    # Limit to 0–255 range
    return int(min(255, max(0, brightness)))

def updateBrightness():
    lux = LuxSensor.get_lux()
    b = lux_to_brightness(lux)
    # print(f"Lux : {lux} lx\t b = {b}")
    led.changeLedState(brightness=b)

if __name__ == '__main__':
    
    try:
        led.changeLedState(colour=(255,255,255), brightness=255) # Remove later
        while(True): updateBrightness()
    except:
        led.changeLedState(brightness=0) # Remove ??
        print("Exiting...")


