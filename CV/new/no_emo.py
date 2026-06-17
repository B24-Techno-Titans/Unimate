from picamera2 import Picamera2
import cv2
import busio
import board
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo
import time
from pathlib import Path

# ------------------------------
# SERVO + PCA9685 INITIALIZATION
# ------------------------------
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50

base_servo = servo.Servo(pca.channels[0])
head_servo = servo.Servo(pca.channels[1], min_pulse=500, max_pulse=2700)
stand_servo = servo.Servo(pca.channels[2], min_pulse=500, max_pulse=2500)

current_stand_angle = 90
stand_servo.angle = current_stand_angle

current_x_angle = 110
current_y_angle = 100
base_servo.angle = current_x_angle
head_servo.angle = current_y_angle

# ------------------------------
# CAMERA INITIALIZATION
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("Pi Camera Face Tracking started – press 'q' to quit")

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
SMOOTH_FACTOR_Y = 0.05
MAX_STEP = 3
STAND_THRESHOLD = 120

# ------------------------------
# MAIN LOOP
# ------------------------------
while True:
    frame = picam2.capture_array()
    frame = cv2.resize(frame, (640, 480))

    if frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    frame_h, frame_w = frame.shape[:2]
    center_x = frame_w // 2
    center_y = frame_h // 2

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(60, 60)
    )

    for (x, y, w, h) in faces[:1]:  # track only first face
        face_center_x = x + w // 2
        face_center_y = y + h // 2

        offset_x = face_center_x - center_x
        offset_y = face_center_y - center_y

        # Draw visuals
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
        cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 0), 2)
        cv2.line(frame, (0, center_y), (frame_w, center_y), (0, 255, 0), 2)

        # ------------------------------
        # SERVO MOVEMENT LOGIC
        # ------------------------------
        if abs(offset_x) > STAND_THRESHOLD:
            if offset_x > 0:
                current_stand_angle = max(45, current_stand_angle - 3)
            else:
                current_stand_angle = min(135, current_stand_angle + 3)
            stand_servo.angle = current_stand_angle

        else:
            target_x = current_x_angle - (offset_x * SMOOTH_FACTOR_X)
            target_y = current_y_angle + (offset_y * SMOOTH_FACTOR_Y)

            target_x = max(45, min(135, target_x))
            target_y = max(50, min(180, target_y))

            dx = max(-MAX_STEP, min(MAX_STEP, target_x - current_x_angle))
            dy = max(-MAX_STEP, min(MAX_STEP, target_y - current_y_angle))

            current_x_angle += dx
            current_y_angle += dy

            base_servo.angle = current_x_angle
            head_servo.angle = current_y_angle

        cv2.putText(
            frame,
            f"X:{offset_x:+d} Y:{offset_y:+d}",
            (x, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        time.sleep(FRAME_DELAY)

    cv2.imshow("PiCam Face Tracking", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ------------------------------
# CLEANUP
# ------------------------------
picam2.close()
pca.deinit()
cv2.destroyAllWindows()
print("Clean exit")
