FAN_URL = "http://smart-fan.local/set-speed"
LED_URL = "http://led-controller.local/set-colour"
HUMIDIFIER_URL = "http://humidifier.local/press"

import asyncio
import requests
import math
import time
from . import LuxSensor, TempSensor

auto_light_on = False
auto_fan_on = False
_current_fan_speed = -1
auto_humid_on = False
_current_humid_level = -1

# -------------- Basic Device Controls --------------
def control_fan(speed: int):
    try:
        requests.get(f"{FAN_URL}?speed={speed}", timeout=4)
    except Exception as e:
        print(f"Error controlling fan: {e}")

def control_humidifier(state: int):
    if not hasattr(control_humidifier, "current_state"):
        control_humidifier.current_state = 0

    try:
        call_count = 0
        while control_humidifier.current_state != state and call_count < 6:
            call_count += 1
            time.sleep(0.5)
            response = requests.get(HUMIDIFIER_URL, timeout=4)
            if response.status_code == 200:
                control_humidifier.current_state = response.json().get("state")
            else:
                print(f"Failed with status code: {response.status_code}")
    except Exception as e:
        print(f"Error controlling humidifier: {e}")

def control_light(**kwargs):
    params = {}
    colour = kwargs.get("rgb", None)
    brightness = kwargs.get("brightness", None)

    if(colour != None): params["rgb"] = "#" + colour
    print("Colour: ", params["rgb"])
    if(brightness != None): params["brightness"] = min(brightness, 100) # limit to 100 for low power usage

    try:
        response = requests.get(LED_URL, params=params, timeout=5)
        print("Request: ", response.request.url)
        
        if response.status_code == 200:
            print("Colour change requested successfully")
            print("ESP32 says:", response.text)
            pass
        else:
            print(f"Failed with status code: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Connection Error: {e}")

# -------------- Auto Brightness --------------
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
    return int(min(150, max(0, brightness)))

# Test Values
# lux_values = [0, 10, 100, 500, 1000]
# for lux in lux_values:
#     print(f"Lux: {lux} -> Brightness: {lux_to_brightness(lux)}")

async def autoBrightness():
    global auto_light_on
    while(auto_light_on):
        lux = LuxSensor.get_lux()
        b = lux_to_brightness(lux)
        # print(f"Lux : {lux} lx\t b = {b}")
        control_light(brightness=b)

        await asyncio.sleep(0.1)

def stopAutoBrightness():
    global auto_light_on
    auto_light_on = False

# -------------- Auto Fan Speed --------------
def temp_to_fan_speed(temp_c: float) -> int:
    if temp_c < 26:
        return 0
    if temp_c <= 30:
        return 1
    return 2

async def autoFanSpeed():
    global auto_fan_on, _current_fan_speed
    auto_fan_on = True
    while auto_fan_on:
        temp_c = TempSensor.get_temp()
        speed = temp_to_fan_speed(temp_c)
        if speed != _current_fan_speed:
            control_fan(speed)
            _current_fan_speed = speed

        print("Current fan speed: ", _current_fan_speed)
        await asyncio.sleep(2)

def stopAutoFanSpeed():
    global auto_fan_on, _current_fan_speed
    auto_fan_on = False
    _current_fan_speed = 0

# -------------- Auto Humidifier --------------
def humid_to_humid_level(humid: float) -> int:
    if humid < 80:
        return 2
    if humid <= 90:
        return 1
    return 0

async def autoHumidifier():
    global auto_humid_on
    auto_humid_on = True
    while auto_humid_on:
        humid = TempSensor.get_humidity()
        level = humid_to_humid_level(humid)
        if level != _current_humid_level:
            control_humidifier(level)
            _current_humid_level = level

        print("Current humidifier level: ", _current_humid_level)
        await asyncio.sleep(0.1)

def stopAutoHumidifier():
    global auto_humid_on
    auto_humid_on = False