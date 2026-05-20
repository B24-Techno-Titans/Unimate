from picamera2 import Picamera2
import cv2
import numpy as np
import time

# Load Haarcascade
face_cascade = cv2.CascadeClassifier(
    "/home/unimate/Unimate/CV/haarcascades/haarcascade_frontalface_default.xml"
)

# Initialize PiCamera
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
picam2.configure(config)
picam2.start()
time.sleep(0.2)

print("Haarcascade face detection started. Press 'q' to quit.")

try:
    while True:
        frame = picam2.capture_array()  # RGB
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        frame_h, frame_w = frame.shape[:2]
        center_x = frame_w // 2
        center_y = frame_h // 2

        # Draw vertical and horizontal center lines
        cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 255), 2)  # vertical
        cv2.line(frame, (0, center_y), (frame_w, center_y), (0, 255, 255), 2)  # horizontal

        # Detect faces
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )

        for (x, y, w, h) in faces:
            # Draw face rectangle
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Draw center of face
            face_center_x = x + w // 2
            face_center_y = y + h // 2
            cv2.circle(frame, (face_center_x, face_center_y), 5, (255, 0, 0), -1)
            
            # Print coordinates and offset from center
            offset_x = face_center_x - center_x
            offset_y = face_center_y - center_y
            print(f"Face at x={x}, y={y}, w={w}, h={h} | OffsetX={offset_x}, OffsetY={offset_y}")

        # Show frame
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imshow("Haarcascade Face Detection", frame_bgr)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print("Error:", e)
finally:
    picam2.close()
    cv2.destroyAllWindows()
    print("Clean exit")
