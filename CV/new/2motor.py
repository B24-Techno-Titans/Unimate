from picamera2 import Picamera2
import cv2
from deepface import DeepFace
import busio
import board
# import RPi.GPIO as GPIO
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo
import time

CENTER_OFFSET = 10

# ------------------------------
# Servo setup (Pin 32 = GPIO 12)
# ------------------------------
# SERVO_PIN = 12
# GPIO.setmode(GPIO.BCM)
# GPIO.setup(SERVO_PIN, GPIO.OUT)
# servo = GPIO.PWM(SERVO_PIN, 50)  # 50Hz PWM
# servo.start(7.5)  # Middle position (~90ï¿½)

# Start Driver
i2c = busio.I2C(board.SCL, board.SDA)

# PCA9685 setup
pca = PCA9685(i2c)
pca.frequency = 50  # Standard servo frequency

base_servo = servo.Servo(pca.channels[0])
head_servo = servo.Servo(pca.channels[1])

# Servo helper
def set_servo_angle(new_angle):
    new_angle = max(0, min(180, new_angle))  # Clamp
    # duty = 2.5 + (new_angle / 18)
    # servo.ChangeDutyCycle(duty)
    base_servo.angle = new_angle
    time.sleep(0.02)

def set_h_servo_angle(new_angle):
    new_angle = max(0, min(180, new_angle))  # Clamp
    head_servo.angle = new_angle
    time.sleep(0.02)

# Start centered
current_x_angle = 90
current_y_angle = 160
set_servo_angle(current_x_angle)
set_h_servo_angle(current_y_angle)

# ------------------------------
# Camera + DeepFace setup
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("? Pi Camera + Face Tracking started ï¿½ press 'q' to quit")

CENTER_TOLERANCE = 40
TARGET_OFFSET = 0  # target center
FRAME_DELAY = 0.15  # reduce servo jitter

head_servo.angle = 90
time.sleep(1)
head_servo.angle = 110
time.sleep(1)
head_servo.angle = 70
