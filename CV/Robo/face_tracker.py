# ----------------------------------------------------------------------------
# face_tracker_writer.py
# ----------------------------------------------------------------------------
# This script continuously analyzes the camera feed for a face and determines 
# if the face is to the LEFT, RIGHT, or CENTER of the frame.
# It writes the resulting command ('LEFT', 'RIGHT', or 'CENTER') to 
# 'eye_command.txt' for the display script to read.
# ----------------------------------------------------------------------------

from picamera2 import Picamera2
import cv2
from deepface import DeepFace
import time
import os

# --- Configuration ---
CENTER_TOLERANCE = 40  # Pixels from center to consider "CENTERED"
EYE_COMMAND_FILE = "eye_command.txt"
WRITE_INTERVAL = 0.1 # Write the file 10 times per second (100ms interval)
WINDOW_NAME = "Face Tracker Output (Press 'q' to quit)" # OpenCV Window Title

# --- State Helpers ---
def write_command(command):
    """Writes the current command string to the command file."""
    try:
        # Use 'w' to overwrite the file contents completely
        with open(EYE_COMMAND_FILE, 'w') as f:
            f.write(command.strip().upper())
    except IOError as e:
        print(f"Error writing to command file: {e}")

def determine_new_state(offset_x, tolerance):
    """Determines the eye position based on face tracker's x-offset."""
    if abs(offset_x) <= tolerance:
        # The face is near the center
        return "CENTER"
    elif offset_x < 0:
        # Face is to the LEFT of the screen center -> Robot looks LEFT
        return "LEFT"
    else:
        # Face is to the RIGHT of the screen center -> Robot looks RIGHT
        return "RIGHT"

def run_face_tracker():
    """Main loop for face detection and command writing."""
    print(f"Initializing Pi Camera...")
    
    # Initialize Pi Camera
    picam2 = Picamera2()
    # Configure the camera for fast frame capture (e.g., lower resolution)
    # Adjust this based on your RPi performance needs
    config = picam2.create_video_configuration(main={"size": (320, 240)})
    picam2.configure(config)
    picam2.start()
    
    print(f"Pi Camera ready. Writing commands to '{EYE_COMMAND_FILE}'. Press 'q' in the CV window to stop.")
    
    last_write_time = time.time()
    current_command = "CENTER" # Default to CENTER (idle)

    try:
        while True:
            frame = picam2.capture_array()
            # Convert frame from RGB (Picamera2 default) to BGR (OpenCV default)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            frame_h, frame_w = frame.shape[:2]
            center_x = frame_w // 2
            
            face_detected = False
            
            try:
                # --- DeepFace Analysis (can be CPU intensive) ---
                # Note: We enforce_detection=False to avoid crashing if no face is found
                results = DeepFace.analyze(
                    frame, actions=['emotion'], detector_backend='opencv', enforce_detection=False
                )
                
                results = results if isinstance(results, list) else [results]

                if results:
                    # Focus on the first detected face
                    region = results[0].get('region', {}) 
                    if 'x' in region and region['w'] > 0:
                        face_detected = True
                        x, y, w, h = region['x'], region['y'], region['w'], region['h']
                        face_center_x = x + w // 2
                        offset_x = face_center_x - center_x
                        
                        # Determine the new desired state
                        new_state = determine_new_state(offset_x, CENTER_TOLERANCE)
                        current_command = new_state
                        
                        # --- Visualization ---
                        color = (0, 255, 0) if new_state == "CENTER" else (0, 0, 255)
                        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                        cv2.putText(frame, new_state, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                        
                        # Optional: Print tracking status
                        # print(f"Detected: {current_command} (offset={offset_x})")
                            
            except Exception as e:
                # This often happens when DeepFace fails detection
                # print(f"No face detected or CV error: {e}")
                pass 
                
            # If no face was detected in this cycle, default to CENTER
            if not face_detected:
                current_command = "CENTER"
                
            # Draw the center zone boundaries on the frame for reference
            cv2.line(frame, (center_x - CENTER_TOLERANCE, 0), (center_x - CENTER_TOLERANCE, frame_h), (255, 255, 0), 1)
            cv2.line(frame, (center_x + CENTER_TOLERANCE, 0), (center_x + CENTER_TOLERANCE, frame_h), (255, 255, 0), 1)
            
            # Show the frame
            cv2.imshow(WINDOW_NAME, frame)
            
            # Check for 'q' key press to quit the loop
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # --- Command File Writing (throttled) ---
            now = time.time()
            if now - last_write_time >= WRITE_INTERVAL:
                write_command(current_command)
                last_write_time = now
            
            # Small sleep to prevent 100% CPU usage on the main loop
            time.sleep(0.005) 
            
    except KeyboardInterrupt:
        print("\nExiting face tracker (Keyboard Interrupt).")
    except Exception as e:
        print(f"\nCritical error in face tracker: {e}")
    finally:
        picam2.close()
        cv2.destroyAllWindows() # Close the OpenCV window
        # Ensure the last command is CENTER before exiting
        write_command("CENTER") 
        print("Camera cleaned up, OpenCV windows closed, and command file reset to CENTER.")

if __name__ == '__main__':
    run_face_tracker()