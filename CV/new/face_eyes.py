import time
from random import uniform, choice
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas
from PIL import ImageDraw

from picamera2 import Picamera2
import cv2
from deepface import DeepFace

# ----------------- OLED / Eyes Setup -----------------
SERIAL_PORT = 1
I2C_ADDRESS_LEFT = 0x3C
I2C_ADDRESS_RIGHT = 0x3D
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64

BLINK_FRAMES = 3
FRAME_DELAY = 0.006
EYE_W = 65 
EYE_H = 40

# Initialize OLED displays
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306

SERIAL_PORT = 1
I2C_ADDRESS_LEFT = 0x3C
I2C_ADDRESS_RIGHT = 0x3D

# Correct way:
serial_left = i2c(port=SERIAL_PORT, address=I2C_ADDRESS_LEFT)
left_eye = ssd1306(serial_left, width=128, height=64)

serial_right = i2c(port=SERIAL_PORT, address=I2C_ADDRESS_RIGHT)
right_eye = ssd1306(serial_right, width=128, height=64)

devices = [left_eye, right_eye]

# ----------------- Pi Camera Setup -----------------
picam2 = Picamera2()
picam2.start()

CENTER_TOLERANCE = 40  # pixels from center to consider "CENTERED"
MAX_EYE_OFFSET = 15    # max pixel movement for the eye

# ----------------- Eye Drawing -----------------
def draw_eye(draw, blink_frame=0, open=True, x_offset=0):
    """
    draw: ImageDraw object
    blink_frame: 0..BLINK_FRAMES
    x_offset: horizontal pupil offset (-MAX_EYE_OFFSET .. MAX_EYE_OFFSET)
    """
    # Eye position
    cx = DISPLAY_WIDTH // 2 + x_offset
    cy = DISPLAY_HEIGHT // 2
    inset = 0
    radius = 20

    # Clear background
    draw.rectangle((0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT), fill=0)

    if open:
        draw.rounded_rectangle(
            (cx - EYE_W//2 + inset, cy - EYE_H//2 + inset,
             cx + EYE_W//2 - inset, cy + EYE_H//2 - inset),
            radius=radius//2, outline=1, fill=1
        )
    else:
        lid_fraction = blink_frame / BLINK_FRAMES
        lid_h = lid_fraction * EYE_H
        draw.rectangle(
            (cx - EYE_W//2 + inset, cy - lid_h,
             cx + EYE_W//2 - inset, cy + lid_h),
            outline=0, fill=0
        )

def update_eyes(blink_frame=0, open=True, x_offset=0):
    for dev in devices:
        with canvas(dev) as draw:
            draw_eye(draw, blink_frame=blink_frame, open=open, x_offset=x_offset)

# ----------------- Blink Animation -----------------
def blink_animation(x_offset=0):
    frames = list(range(1, BLINK_FRAMES + 1)) + list(range(BLINK_FRAMES - 1, 0, -1))
    for f in frames:
        update_eyes(open=False, blink_frame=f, x_offset=x_offset)
        time.sleep(FRAME_DELAY)
    update_eyes(open=True, x_offset=x_offset)

# ----------------- Main Loop -----------------
try:
    while True:
        # Capture frame from Pi Camera
        frame = picam2.capture_array()
        frame_h, frame_w = frame.shape[:2]
        center_x = frame_w // 2

        # Default eye offset
        eye_offset = 0

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
                dominant_emotion = res.get('dominant_emotion', 'unknown')

                if region and all(k in region for k in ('x','w')):
                    face_center_x = region['x'] + region['w'] // 2
                    offset_x = face_center_x - center_x

                    # Map camera offset to eye movement
                    if abs(offset_x) <= CENTER_TOLERANCE:
                        eye_offset = 0
                    else:
                        eye_offset = int(MAX_EYE_OFFSET * offset_x / (frame_w // 2))
                        eye_offset = max(-MAX_EYE_OFFSET, min(MAX_EYE_OFFSET, eye_offset))

                    # Draw rectangle and emotion on frame
                    cv2.rectangle(frame, (region['x'], region['y']),
                                  (region['x']+region['w'], region['y']+region['h']),
                                  (255,0,0), 2)
                    cv2.putText(frame, dominant_emotion,
                                (region['x'], region['y']-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

        except Exception as e:
            print("Face detection error:", e)

        # Update OLED eyes
        if uniform(0, 1) < 0.02:
            blink_animation(x_offset=eye_offset)
        else:
            update_eyes(open=True, x_offset=eye_offset)

        # Show live camera feed
        cv2.imshow("Pi Camera Feed", frame)

        # Quit with 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    pass

finally:
    print("Exiting...")
    for d in devices:
        d.clear()
    picam2.close()
    cv2.destroyAllWindows()
