# import RPi.GPIO as GPIO
# import time

# GPIO.setmode(GPIO.BOARD)
# GPIO.setup(32, GPIO.OUT)

# p = GPIO.PWM(32, 50)  # PWM frequency is 50Hz
# p.start(2.5)  # Initialization

# try:
#     while True:
#         p.ChangeDutyCycle(5)  # Rotate the servo motor to 90 degrees
#         time.sleep(1)
#         p.ChangeDutyCycle(10)  # Rotate the servo motor to 180 degrees
#         time.sleep(1)
# except KeyboardInterrupt:
#     p.stop()
#     GPIO.cleanup()


import time
from adafruit_servokit import ServoKit

kit = ServoKit(channels=16)

SERVO_CHANNEL = 15

kit.servo[SERVO_CHANNEL].set_pulse_width_range(500, 2500)

try:
    while True:
        print("Moving to 0 degrees")
        kit.servo[SERVO_CHANNEL].angle = 0
        time.sleep(2)
        
        print("Moving to 90 degrees")
        kit.servo[SERVO_CHANNEL].angle = 90
        time.sleep(2)
        
        print("Moving to 180 degrees")
        kit.servo[SERVO_CHANNEL].angle = 180
        time.sleep(2)

except KeyboardInterrupt:
    print("Program stopped by user")
    kit.servo[SERVO_CHANNEL].angle = None