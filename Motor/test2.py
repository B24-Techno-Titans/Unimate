from picamera2 import Picamera2
import cv2
from deepface import DeepFace
import busio
import board
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo
import time
# ------------------------------
# SERVO + PCA9685 INITIALIZATION
# ------------------------------
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50  # typical for servos

base_servo = servo.Servo(pca.channels[0])
head_servo = servo.Servo(
    pca.channels[1],
    min_pulse=500,
    max_pulse=2700
)
stand_servo = servo.Servo(
    pca.channels[2],
    min_pulse=500,
    max_pulse=2500
)

current_stand_angle = 90  # start center
stand_servo.angle = current_stand_angle

# Start centered
current_x_angle = 110   # base servo (left-right)
current_y_angle = 100  # head servo (up-down)
base_servo.angle = current_x_angle
head_servo.angle = current_y_angle

# ------------------------------
# CAMERA INITIALIZATION
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("? Pi Camera + Face Tracking started � press 'q' to quit")

# ------------------------------
# CONSTANTS
# ------------------------------
CENTER_TOLERANCE = 40
FRAME_DELAY = 0.1
SMOOTH_FACTOR_X = 0.05  # lower = smoother
SMOOTH_FACTOR_Y = 0.05
MAX_STEP = 3            # limit servo speed per update
STAND_THRESHOLD = 80    # when X offset beyond this, use stand servo

# ------------------------------
# MAIN LOOP
# ------------------------------
while True:
    frame = picam2.capture_array()
    frame = cv2.resize(frame, (640, 480))  # resize for performance

    # Convert BGRA ? BGR if needed
    if frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    frame_h, frame_w = frame.shape[:2]
    center_x = frame_w // 2
    center_y = frame_h // 2

    try:
        results = DeepFace.analyze(
            frame,
            actions=['emotion'],
            detector_backend='opencv',
            enforce_detection=False
        )

        results = results if isinstance(results, list) else [results]

        for res in results:
            region = res.get('region', None)
            dominant = res.get('dominant_emotion', 'unknown')

            if region and all(k in region for k in ('x', 'y', 'w', 'h')):
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                face_center_x = x + w // 2
                face_center_y = y + h // 2
                offset_x = face_center_x - center_x
                offset_y = face_center_y - center_y

                # Draw visuals
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(frame, dominant, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 0), 2)
                cv2.line(frame, (0, center_y), (frame_w, center_y), (0, 255, 0), 2)

                # ------------------------------
                # SERVO MOVEMENT LOGIC
                # ------------------------------
                # Small movement = base servo, large = stand servo

                if abs(offset_x) > STAND_THRESHOLD:
                    # Big movement ? rotate stand
                    if offset_x > 0:
                        current_stand_angle = max(45, current_stand_angle - 3)
                        print("? Rotating stand RIGHT")
                    else:
                        current_stand_angle = min(135, current_stand_angle + 3)
                        print("? Rotating stand LEFT")
                    stand_servo.angle = current_stand_angle

                else:
                    # Small movement ? fine tune base
                    target_x_angle = current_x_angle - (offset_x * SMOOTH_FACTOR_X)
                    target_y_angle = current_y_angle + (offset_y * SMOOTH_FACTOR_Y)

                    # Clamp servo range
                    target_x_angle = max(45, min(135, target_x_angle))
                    target_y_angle = max(50, min(180, target_y_angle))

                    # Compute step deltas
                    delta_x = target_x_angle - current_x_angle
                    delta_y = target_y_angle - current_y_angle

                    # Limit how much to move per frame
                    delta_x = max(-MAX_STEP, min(MAX_STEP, delta_x))
                    delta_y = max(-MAX_STEP, min(MAX_STEP, delta_y))

                    # Apply changes
                    current_x_angle += delta_x
                    current_y_angle += delta_y

                    base_servo.angle = current_x_angle
                    head_servo.angle = current_y_angle

                # Display info
                cv2.putText(frame, f"X: {offset_x:+d} ({current_x_angle:.1f})", (x, y + h + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.putText(frame, f"Y: {offset_y:+d} ({current_y_angle:.1f})", (x + w + 10, y + h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                print(f"OffsetX={offset_x}, OffsetY={offset_y}, Stand={current_stand_angle:.1f}, "
                      f"Base={current_x_angle:.1f}, Head={current_y_angle:.1f}, Emotion={dominant}")

                time.sleep(FRAME_DELAY)

    except Exception as e:
        print("?? Frame error:", e)

    cv2.imshow("PiCam Face Tracking", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ------------------------------
# CLEANUP
# ------------------------------
picam2.close()
pca.deinit()
cv2.destroyAllWindows()
print("?? Clean exit")
