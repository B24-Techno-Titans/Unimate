from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
import cv2

# Load the emotion recognizer
fer = HSEmotionRecognizer(model_name='enet_b0_8_best_afew')

# Load a face image
img = cv2.imread('test_face.jpg')  # your face image path
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

# Predict emotions
emotion, scores = fer.predict_emotions(img_rgb)

print("Detected emotion:", emotion)
print("All scores:", scores)
