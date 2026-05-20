from picamera2 import Picamera2
import cv2
from deepface import DeepFace
import RPi.GPIO as GPIO
import time

# ------------------------------
# Servo setup (Pin 32 = GPIO 12)
# ------------------------------
SERVO_PIN = 12
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
servo = GPIO.PWM(SERVO_PIN, 50)  # 50Hz PWM
servo.start(7.5)  # Middle position (~90�)

# Servo helper
def set_servo_angle(angle):
    angle = max(0, min(180, angle))  # Clamp
    duty = 2.5 + (angle / 18)
    servo.ChangeDutyCycle(duty)
    time.sleep(0.03)

# Start centered
current_angle = 90
set_servo_angle(current_angle)

# ------------------------------
# Camera + DeepFace setup
# ------------------------------
picam2 = Picamera2()
picam2.start()

print("? Pi Camera + Face Tracking started � press 'q' to quit")

CENTER_TOLERANCE = 40
TARGET_OFFSET = 0  # target center
FRAME_DELAY = 0.1  # reduce servo jitter

while True:
    frame = picam2.capture_array()
    frame_h, frame_w = frame.shape[:2]
    center_x = frame_w // 2

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
                offset = face_center_x - center_x

                # Draw face box
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(frame, dominant, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

                # Center line
                cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 0), 2)

                # Determine direction
                if abs(offset) <= 50:
                    position = "CENTER"
                elif offset < -50:
                    position = "LEFT"
                    current_angle += 2  # rotate right (camera�s left)
                elif offset > 50:
                    position = "RIGHT"
                    current_angle -= 2  # rotate left (camera�s right)
                else:
                    position = "CENTER"

                current_angle = max(45, min(135, current_angle))  # limit range
                set_servo_angle(current_angle)

                cv2.putText(frame, f"{position} (offset={offset})", (x, y + h + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

                print(f"Face at {position}, offset={offset}, emotion={dominant}, servo={current_angle}�")

                time.sleep(FRAME_DELAY)

    except Exception as e:
        print("?? Frame error:", e)

    cv2.imshow("PiCam Face Tracking", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ------------------------------
# Cleanup
# ------------------------------
picam2.close()
servo.stop()
GPIO.cleanup()
cv2.destroyAllWindows()
print("?? Clean exit")
