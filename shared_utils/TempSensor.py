import time
import json
from pathlib import Path

JSON_path = Path(__file__).resolve().parent / "temp_data.json"
def get_temp():
    try:
        with open(JSON_path) as f:
            line = f.readline()
            f.seek(0)
            if len(line) > 0:
                data = json.loads(line)
                return data["r_temp"]
            else:
                return 0
    except Exception as e:
        print("Read error:", e)

def get_humidity():
    try:
        with open(JSON_path) as f:
            line = f.readline()
            f.seek(0)
            if len(line)>0:
                data = json.load(f)
                return data["r_humidity"]
            else:
                return 0
    except Exception as e:
        print("Read error:", e)

def update_temp_loop():
    import board
    import adafruit_dht

    dhtDevice = adafruit_dht.DHT22(board.D4)

    while True:
        try:
            temp_c = dhtDevice.temperature or 0
            hum = dhtDevice.humidity or 0
            with open(JSON_path, "w") as f:
                json.dump({"r_temp": temp_c, "r_humidity": hum}, f)

            if __name__ == "__main__": print(f"Temperature: {temp_c:.1f} C  Humidity: {hum:.1f}%")
            time.sleep(1)
        except Exception as e:
            print("Error:", e)
            time.sleep(2)

if __name__ == "__main__":
    update_temp_loop()
