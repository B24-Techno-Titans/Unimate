import requests

ESP_URL = "http://led-controller.local"
TIMEOUT = 5  # seconds

def rgb_to_hex(colour):
    r, g, b = colour
    return f"%23{r:02X}{g:02X}{b:02X}"

def changeLedState(**kwargs): # colour -> (r, g, b) tuple
    params = {}
    colour = kwargs.get("colour", None)
    brightness = kwargs.get("brightness", None)

    if(colour != None): params["rgb"] = rgb_to_hex(colour)
    if(brightness != None): params["brightness"] = brightness

    try:
        response = requests.get(f"{ESP_URL}/set-colour", params=params, timeout=5)
        
        if response.status_code == 200:
            # print("Colour change requested successfully")
            # print("ESP32 says:", response.text)
            pass
        else:
            print(f"Failed with status code: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Connection Error: {e}")

def main():
    from time import sleep
    print("!!! Import to use\nFor testing:")
    try:
        while(True):
            print("---------------------------------------------------------------------------------------")
            print("Red = ", end="")
            r = input()
            print("Green = ", end="")
            g = input()
            print("Blue = ", end="")
            b = input()
            print("Brightness (0-255) = ", end="")
            brightness = input()
            changeLedState(colour=(int(r), int(g), int(b)), brightness=int(brightness))
            sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")

def test():
    try:
        # requests.get(f"{ESP_URL}/ping")
        changeLedState(colour=(0,0,255), brightness=20)
    except requests.exceptions.RequestException as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    main()
    # test()
