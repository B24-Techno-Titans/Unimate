from adafruit_pca9685 import PCA9685
from adafruit_motor import servo
import busio
import board
import time

# Initialize I2C
i2c = busio.I2C(board.SCL, board.SDA)

# Initialize PCA9685
pca = PCA9685(i2c)
pca.frequency = 50  # 50Hz for servos

# Create servo object (channel 0)
my_servo = servo.Servo(pca.channels[0])

# Move to 0 degrees
print("Moving to 0°")
my_servo.angle = 0
time.sleep(2)

# Move to 180 degrees
print("Moving to 180°")
my_servo.angle = 180
time.sleep(2)

# Cleanup
pca.deinit()