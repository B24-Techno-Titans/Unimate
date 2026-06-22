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
servo3 = pca.channels[0]
servo4 = pca.channels[8]

def set_angle(channel, angle):
    min_pulse = 2000
    max_pulse = 8000
    pulse = int(min_pulse + (angle / 180.0) * (max_pulse - min_pulse))
    channel.duty_cycle = pulse


# Continuous sweep
START_ANGLE = 70
END_ANGLE = 110

#try:
#    for i  in range(5):
#        # 0 → 180
#        for angle in range(START_ANGLE, END_ANGLE, 2):
#            set_angle(servo3, angle)
#            time.sleep(0.02)
#
        # 180 → 0
#        for angle in range(END_ANGLE, START_ANGLE , -2):
#            set_angle(servo3, angle)
#            time.sleep(0.02)
#except KeyboardInterrupt:
#    print("Program terminated by user")

#set_angle(servo4, 80)
set_angle(servo3, 60)
time.sleep(1)
set_angle(servo3 , 90)
set_angle(servo4, 120)
#set_angle(servo3, 90)
time.sleep(1)
set_angle(servo3 , 120)
time.sleep(1)
set_angle(servo3 , 90)
