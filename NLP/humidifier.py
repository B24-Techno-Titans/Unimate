import requests
import time

humidifier_url = "http://humidifier.local/press"

def press_once():
    try:
        response = requests.get(humidifier_url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data.get("state")
    except requests.RequestException as e:
        print("Request failed:", e)
    return None


def set_humidifier(target_state):
    """
    target_state:
        0 = OFF
        1 = CONTINUOUS (ON)
        2 = BLINK
    """

    print("Reading current state...")
    current_state = press_once()  # This press changes state!

    if current_state is None:
        print("Could not read state")
        return

    print("Current state after press:", current_state)

    # Because press_once() already changed state,
    # we calculate how many more presses needed

    while current_state != target_state:
        time.sleep(0.5)
        current_state = press_once()
        print("Pressed again. New state:", current_state)

    print("Humidifier set to state:", target_state)


