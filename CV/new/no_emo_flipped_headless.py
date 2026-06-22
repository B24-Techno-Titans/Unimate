from picamera2 import Picamera2
import cv2
import busio
import board
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo
import signal
import time
from pathlib import Path

# ------------------------------
# SERVO + PCA9685 INITIALIZATION
# ------------------------------
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50

base_servo = servo.Servo(pca.channels[0])  # Real head
stand_servo = servo.Servo(pca.channels[8], min_pulse=500, max_pulse=2500)  # Real base

current_stand_angle = 120
stand_servo.angle = current_stand_angle

current_x_angle = 90
base_servo.angle = current_x_angle

# ------------------------------
# CAMERA INITIALIZATION
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("Pi Camera Face Tracking started (flipped, headless) – Ctrl+C to quit")

# ------------------------------
# FACE DETECTOR
# ------------------------------
CASCADE_PATH = Path(__file__).resolve().parent / "haarcascades" / "haarcascade_frontalface_default.xml"
face_cascade = cv2.CascadeClassifier(str(CASCADE_PATH))

# ------------------------------
# CONSTANTS
# ------------------------------
FRAME_DELAY = 0.05
SMOOTH_FACTOR_X = 0.05
MAX_STEP = 3
STAND_THRESHOLD = 120
STATUS_INTERVAL = 5.0

running = True


def request_stop(signum=None, frame=None):
    global running
    running = False


signal.signal(signal.SIGINT, request_stop)
signal.signal(signal.SIGTERM, request_stop)

# ------------------------------
# MAIN LOOP
# ------------------------------
last_status_time = time.time()

try:
    while running:
        frame = picam2.capture_array()

        # Camera mounted upside down and mirrored left-right
        frame = cv2.rotate(frame, cv2.ROTATE_180)
        frame = cv2.resize(frame, (640, 480))

        if frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        frame_h, frame_w = frame.shape[:2]
        center_x = frame_w // 2

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(60, 60),
        )

        face_found = False
        for (x, y, w, h) in faces[:1]:  # track only first face
            face_found = True
            face_center_x = x + w // 2
            offset_x = face_center_x - center_x

            if abs(offset_x) > STAND_THRESHOLD:
                if offset_x > 0:
                    current_stand_angle = max(75, current_stand_angle - 3)
                else:
                    current_stand_angle = min(165, current_stand_angle + 3)
                stand_servo.angle = current_stand_angle
            else:
                target_x = current_x_angle - (offset_x * SMOOTH_FACTOR_X)
                target_x = max(45, min(135, target_x))

                dx = max(-MAX_STEP, min(MAX_STEP, target_x - current_x_angle))
                current_x_angle += dx
                base_servo.angle = current_x_angle

        now = time.time()
        if now - last_status_time >= STATUS_INTERVAL:
            status = "tracking" if face_found else "no face"
            print(
                f"[{status}] base={current_x_angle:.0f}° stand={current_stand_angle:.0f}°",
                flush=True,
            )
            last_status_time = now

        time.sleep(FRAME_DELAY)

except KeyboardInterrupt:
    request_stop()
finally:
    picam2.close()
    pca.deinit()
    print("Clean exit")
