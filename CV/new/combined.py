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
# head_servo = servo.Servo(pca.channels[1])

head_servo = servo.Servo(
    pca.channels[1],
    min_pulse=500,
    max_pulse=2700
)


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
current_y_angle = 120
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

while True:
    frame = picam2.capture_array()
    frame = cv2.resize(frame, (640, 480))

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
                offset_x = face_center_x - center_x
                face_center_y = y + h // 2
                offset_y = face_center_y - center_y

                # Draw face box
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(frame, dominant, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

                # Center line
                cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 0), 2)
                cv2.line(frame, (0, center_y), ( frame_w,center_y), (0, 255, 0), 2)

                # Determine direction
                # if abs(offset_x) <= CENTER_OFFSET:
                #     position_x = "CENTER"
                # elif offset_x < -CENTER_OFFSET:
                #     position_x = "LEFT"
                #     current_x_angle += abs(offset_x) * 0.02  # rotate right (cameraï¿½s left)
                # elif offset_x > CENTER_OFFSET:
                #     position_x = "RIGHT"
                #     current_x_angle -= abs(offset_x) * 0.02  # rotate left (cameraï¿½s right)
                # else:
                #     position_x = "CENTER"

                # if abs(offset_y) <= CENTER_OFFSET:
                #     position_y = "CENTER"
                # elif offset_y < -CENTER_OFFSET:
                #     position_y = "UP"
                #     current_y_angle -= abs(offset_y) * 0.02
                # elif offset_y > CENTER_OFFSET:
                #     position_y = "DOWN"
                #     current_y_angle += abs(offset_y) * 0.02
                # else:
                #     position_y = "CENTER"

                if abs(offset_x) <= CENTER_OFFSET:
                    position_x = "CENTER"
                elif offset_x < -CENTER_OFFSET:
                    position_x = "LEFT"
                    current_x_angle += 2  # rotate right (cameraï¿½s left)
                elif offset_x > CENTER_OFFSET:
                    position_x = "RIGHT"
                    current_x_angle -= 2  # rotate left (cameraï¿½s right)
                else:
                    position_x = "CENTER"

                if abs(offset_y) <= CENTER_OFFSET:
                    position_y = "CENTER"
                elif offset_y < -CENTER_OFFSET:
                    position_y = "UP"
                    current_y_angle -= 2
                elif offset_y > CENTER_OFFSET:
                    position_y = "DOWN"
                    current_y_angle += 2
                else:
                    position_y = "CENTER"


                current_x_angle = max(45, min(135, current_x_angle))  # limit range
                if(current_x_angle):
                  set_servo_angle(current_x_angle)
                
                current_y_angle = max(120, min(200, current_y_angle))  # limit range
                if(current_y_angle):
                  set_h_servo_angle(current_y_angle)
        

                cv2.putText(frame, f"{position_x} (offset={offset_x})", (x, y + h + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                cv2.putText(frame, f"{position_y} (offset={offset_y})", (x + w + 10, y + h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)


                print(f"Face at {position_x},{position_y}, offset={offset_x}, dominant emotion: {dominant}, , servo={current_x_angle}, {current_y_angle}")

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
# servo.stop()
# GPIO.cleanup()
cv2.destroyAllWindows()
print("?? Clean exit")
