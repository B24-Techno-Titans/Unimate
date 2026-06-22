import RPi.GPIO as GPIO

import time
import board
import busio
from adafruit_pca9685 import PCA9685

# I2C setup
i2c = busio.I2C(board.SCL, board.SDA)

# PCA9685 setup
pca = PCA9685(i2c, address=0x40)
pca.frequency = 50

# Channels
servo1 = pca.channels[4]
servo2 = pca.channels[5]

def set_angle(channel, angle):
    min_pulse = 2000
    max_pulse = 8000
    pulse = int(min_pulse + (angle / 180.0) * (max_pulse - min_pulse))
    channel.duty_cycle = pulse


set_angle(servo1, 80)
set_angle(servo2, 65)

# Continuous sweep
START_ANGLE = 55
END_ANGLE = 75

def move_ears() :
    try:
        for i  in range(5):
            # 0 → 180
            for angle in range(START_ANGLE, END_ANGLE, 2):
                set_angle(servo1, angle + 15)
                set_angle(servo2, angle)
                time.sleep(0.02)

            # 180 → 0
            for angle in range(END_ANGLE, START_ANGLE , -2):
                set_angle(servo1, angle + 15)
                set_angle(servo2, angle)
                time.sleep(0.02)
    except KeyboardInterrupt:
        print("Program terminated by user")

    set_angle(servo1, 80)
    set_angle(servo2, 65)



sensor = 17
led = 18

GPIO.setmode(GPIO.BCM)
GPIO.setup(sensor, GPIO.IN)
#GPIO.setup(led, GPIO.OUT)

try:
    while True:
        if GPIO.input(sensor):
            print("Touch Detected")
            time.sleep(1)
            move_ears()
            time.sleep(1)
        else:
            pass
            #GPIO.output(led, False)
        time.sleep(0.1)
except KeyboardInterrupt:
    GPIO.cleanup()
