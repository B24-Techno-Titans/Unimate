import time
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

# I2C setup
i2c = busio.I2C(board.SCL, board.SDA)

# PCA9685 setup
pca = PCA9685(i2c)
pca.frequency = 50  # Standard servo frequency

# Create a servo object on channel 0
my_servo = servo.Servo(pca.channels[4])
# my_servo2 = servo.Servo(pca.channels[2])

# Sweep the servo
while True:
    my_servo.angle = 90

    # for angle in range(0, 180, 5):  # 0° to 180°
    #     my_servo.angle = angle
    #     time.sleep(0.05)
    # for angle in range(180, 0, -5):  # 180° back to 0°
    #     my_servo.angle = angle
    #     time.sleep(0.05)
