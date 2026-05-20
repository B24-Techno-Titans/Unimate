from picamera2 import Picamera2
import cv2
import mediapipe as mp
import time

# Servo imports
import busio
import board
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

# ------------------------------
# SERVO + PCA9685 SETUP
# ------------------------------
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50

base_servo = servo.Servo(pca.channels[0])
head_servo = servo.Servo(pca.channels[1], min_pulse=500, max_pulse=2700)
stand_servo = servo.Servo(pca.channels[2], min_pulse=500, max_pulse=2500)

current_x_angle = 90
current_y_angle = 140
current_stand_angle = 90

base_servo.angle = current_x_angle
head_servo.angle = current_y_angle
stand_servo.angle = current_stand_angle

# ------------------------------
# MEDIAPIPE INITIALIZATION
# ------------------------------
mp_face = mp.solutions.face_detection
mp_draw = mp.solutions.drawing_utils

face_detection = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5)

# ------------------------------
# CAMERA INITIALIZATION
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("? MediaPipe Face Tracking started")

CENTER_TOLERANCE = 40
FRAME_DELAY = 0.1
SMOOTH_FACTOR = 0.05
MAX_STEP = 3
STAND_THRESHOLD = 80

while True:
    frame = picam2.capture_array()
    frame = cv2.resize(frame, (640, 480))

    # Convert for MediaPipe
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    results = face_detection.process(rgb)

    h, w, _ = frame.shape
    center_x = w // 2
    center_y = h // 2

    if results.detections:
        for det in results.detections:
            box = det.location_data.relative_bounding_box
            x = int(box.xmin * w)
            y = int(box.ymin * h)
            w_box = int(box.width * w)
            h_box = int(box.height * h)

            face_cx = x + w_box // 2
            face_cy = y + h_box // 2

            offset_x = face_cx - center_x
            offset_y = face_cy - center_y

            cv2.rectangle(frame, (x, y), (x + w_box, y + h_box), (0, 255, 0), 2)

            # ----------------------------
            # SERVO CONTROL LOGIC
            # ----------------------------
            if abs(offset_x) > STAND_THRESHOLD:
                # Use stand servo for big rotations
                if offset_x > 0:
                    current_stand_angle -= 3
                else:
                    current_stand_angle += 3

                current_stand_angle = max(45, min(135, current_stand_angle))
                stand_servo.angle = current_stand_angle

            else:
                # Fine control
                target_x = current_x_angle - offset_x * SMOOTH_FACTOR
                target_y = current_y_angle + offset_y * SMOOTH_FACTOR

                target_x = max(45, min(135, target_x))
                target_y = max(90, min(200, target_y))

                dx = max(-MAX_STEP, min(MAX_STEP, target_x - current_x_angle))
                dy = max(-MAX_STEP, min(MAX_STEP, target_y - current_y_angle))

                current_x_angle += dx
                current_y_angle += dy

                base_servo.angle = current_x_angle
                head_servo.angle = current_y_angle

            cv2.putText(frame, f"X:{offset_x:+d}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,0), 2)
            cv2.putText(frame, f"Y:{offset_y:+d}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,0), 2)

    cv2.imshow("MediaPipe Face Tracking", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

picam2.close()
pca.deinit()
cv2.destroyAllWindows()
print("? Clean Exit")
