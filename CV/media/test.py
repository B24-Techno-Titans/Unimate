from picamera2 import Picamera2
import cv2
import numpy as np
import onnxruntime as ort
import time
import os

# -----------------------
# Load Haarcascade
# -----------------------
face_cascade = cv2.CascadeClassifier(
    "/home/unimate/Unimate/CV/haarcascades/haarcascade_frontalface_default.xml"
)

# -----------------------
# Load FER+ ONNX
# -----------------------
onnx_model_path = os.path.join(os.path.dirname(__file__), "emotion-ferplus-8.onnx")
session = ort.InferenceSession(onnx_model_path)

emotion_labels = ['neutral', 'happiness', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt']

def preprocess_face(face_img):
    # Convert to grayscale and resize to 64x64
    face_gray = cv2.cvtColor(face_img, cv2.COLOR_RGB2GRAY)
    face_resized = cv2.resize(face_gray, (64,64))

    # Zero-center normalization for FER+
    face_norm = (face_resized.astype(np.float32) - 128.0) / 128.0  # [-1,1]

    # ONNX expects [1,1,64,64]
    face_input = face_norm[np.newaxis, np.newaxis, :, :]
    return face_input


def predict_emotion(face_img):
    inp = preprocess_face(face_img)
    outputs = session.run(None, {session.get_inputs()[0].name: inp})
    emotion_idx = int(np.argmax(outputs[0]))
    return emotion_labels[emotion_idx]

# -----------------------
# Initialize Camera
# -----------------------
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
picam2.configure(config)
picam2.start()
time.sleep(0.2)

print("Face + Emotion Detection started. Press 'q' to quit.")

# -----------------------
# Main loop
# -----------------------
try:
    while True:
        frame = picam2.capture_array()
        frame_h, frame_w = frame.shape[:2]
        center_x, center_y = frame_w // 2, frame_h // 2

        # Draw center lines
        cv2.line(frame, (center_x, 0), (center_x, frame_h), (0, 255, 255), 2)
        cv2.line(frame, (0, center_y), (frame_w, center_y), (0, 255, 255), 2)

        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60,60))

        for (x, y, w, h) in faces:
            # Draw face rectangle
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

            # Crop face
            face_img = frame[y:y+h, x:x+w]

            # Predict emotion
            emotion = predict_emotion(face_img)

            # Draw face center
            face_center_x, face_center_y = x + w//2, y + h//2
            cv2.circle(frame, (face_center_x, face_center_y), 5, (255,0,0), -1)

            # Show emotion label
            cv2.putText(frame, emotion, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)

            # Print info
            offset_x, offset_y = face_center_x - center_x, face_center_y - center_y
            print(f"Face at x={x}, y={y}, w={w}, h={h} | OffsetX={offset_x}, OffsetY={offset_y} | Emotion={emotion}")



        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imshow("Face + Emotion Detection", frame_bgr)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print("Error:", e)
finally:
    picam2.close()
    cv2.destroyAllWindows()
    print("Clean exit")
