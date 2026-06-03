import board
import busio
import adafruit_bh1750

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_bh1750.BH1750(i2c)

def get_lux():
    try:
        return round(sensor.lux, 2)
    except Exception as e:
        print("Error: ", e)
        return 0

if __name__ == '__main__':
    import time
    try:
        while True:
            lux = sensor.lux
            print(f"Light Level: {lux:.2f} lx")
            time.sleep(1)
    except:
        print("\nExiting...")
