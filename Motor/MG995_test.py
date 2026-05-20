import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BOARD)
GPIO.setup(32, GPIO.OUT)

p = GPIO.PWM(32, 50)  # PWM frequency is 50Hz
p.start(2.5)  # Initialization

try:
    while True:
        p.ChangeDutyCycle(5)  # Rotate the servo motor to 90 degrees
        time.sleep(1)
        p.ChangeDutyCycle(10)  # Rotate the servo motor to 180 degrees
        time.sleep(1)
except KeyboardInterrupt:
    p.stop()
    GPIO.cleanup()
