import time
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

# Setup I2C and PCA9685
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50

# Create servo on channel 0
my_servo = servo.Servo(pca.channels[2])

print("Starting servo test...")
while True:
    for angle in range(0, 180, 5):
        my_servo.angle = angle
        time.sleep(0.2)
    for angle in range(180, 0, -5):
        my_servo.angle = angle
        time.sleep(0.2)
