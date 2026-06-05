import time

_MIN_INTERVAL = 2.0
_readings = {"r_temp": 0.0, "r_humidity": 0.0}
_last_read = 0.0
_sensor = None


def _get_sensor():
    global _sensor
    if _sensor is None:
        import board
        import adafruit_dht

        _sensor = adafruit_dht.DHT22(board.D4)
    return _sensor


def _refresh():
    global _readings, _last_read
    now = time.monotonic()
    if now - _last_read < _MIN_INTERVAL:
        return
    try:
        sensor = _get_sensor()
        _readings = {
            "r_temp": sensor.temperature or 0,
            "r_humidity": sensor.humidity or 0,
        }
        _last_read = now
    except Exception as e:
        print("Error:", e)


def get_temp():
    _refresh()
    return _readings["r_temp"]


def get_humidity():
    _refresh()
    return _readings["r_humidity"]


if __name__ == "__main__":
    try:
        while True:
            _refresh()
            print(
                f"Temperature: {_readings['r_temp']:.1f} C  "
                f"Humidity: {_readings['r_humidity']:.1f}%"
            )
            time.sleep(_MIN_INTERVAL)
    except KeyboardInterrupt:
        print("\nExiting...")
