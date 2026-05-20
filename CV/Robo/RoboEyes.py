# ----------------------------------------------------------------------------
# robo_eye_display.py
# ----------------------------------------------------------------------------
# This script runs the dual OLED display loop. It periodically checks 
# 'eye_command.txt' to dynamically load and play the correct pre-rendered 
# frame sequences (LEFT, RIGHT, or CENTER).
# ----------------------------------------------------------------------------

import time
import threading
import sys
import os
from PIL import Image

# --- Luma.OLED Driver Imports ---
from luma.core.interface.serial import i2c
# Assuming SH1106 is the correct driver for your OLEDs
from luma.oled.device import sh1106, ssd1306 
# --------------------------------

# --- Global Constants ---
BGCOLOR = 0
VIDEO_FPS = 60 
EYE_COMMAND_FILE = "eye_command.txt"
READ_INTERVAL_MS = 200 # Check the command file every 200ms
# Time between displaying frames in ms
FRAME_TIME_INTERVAL = 1000 // VIDEO_FPS 

# --- Time Utilities (Mocking MicroPython for compatibility) ---
def ticks_ms():
    """Returns the current time in milliseconds."""
    return int(time.monotonic() * 1000)

def ticks_diff(ticks1, ticks2):
    """Calculates the time difference (ticks1 - ticks2)."""
    return ticks1 - ticks2

def ticks_add(ticks, delta):
    """Adds a delta time (ms) to a tick value."""
    return ticks + delta

# --- Frame Directory Mappings ---
FRAME_MAP = {
    "LEFT": {
        "left": "left_frames_goLeft", 
        "right": "right_frames_goLeft"
    },
    "RIGHT": {
        "left": "left_frames_goRight", 
        "right": "right_frames_goRight"
    },
    "CENTER": {
        "left": "left_framesG", # Idle/No-face frames
        "right": "right_framesG"
    }
}

# -----------------------------
# FramePlayer Class 
# -----------------------------

class FramePlayer():
    """Manages loading and playback for a single eye display."""
    
    def __init__(self, fb, device, eye_side):
        self.fb = fb # The PIL Image buffer
        self.device = device # The luma device
        self.eye_side = eye_side
        
        self.my_frames = [] # Storage for loaded PIL images
        self._current_frame_index = 0
        self._frame_time_interval = FRAME_TIME_INTERVAL 
        self._next_frame_display_time = 0
        
    def load_frames(self, frame_dir):
        """Loads all frames from the specific eye directory."""
        print(f"[{self.eye_side.upper()}] Loading frames from '{frame_dir}'...")
        if not os.path.isdir(frame_dir):
            print(f"[{self.eye_side.upper()}] Error: Directory '{frame_dir}' not found. Check path.")
            return False

        files = sorted([f for f in os.listdir(frame_dir) if f.endswith('.png')])
        
        # Clear existing frames and load new ones
        self.my_frames = [] 
        for file in files:
            path = os.path.join(frame_dir, file)
            try:
                # Load the 128x64 image directly. Use the device's mode for speed.
                frame_img = Image.open(path).convert(self.fb.mode)
                self.my_frames.append(frame_img)
            except Exception as e:
                print(f"[{self.eye_side.upper()}] Error loading {file}: {e}")
                
        print(f"[{self.eye_side.upper()}] Loaded {len(self.my_frames)} frames.")
        
        if len(self.my_frames) > 0:
            self._current_frame_index = 0 # Reset animation when new frames are loaded
            self._next_frame_display_time = ticks_ms()
            return True
        return False
        
    def update_and_draw(self):
        """
        Checks if it's time for the next frame, draws it to the buffer, and 
        returns True if drawn. The sequence loops continuously.
        """
        now = ticks_ms()
        
        if not self.my_frames:
            return False # No frames loaded

        # Check if it's time to display the next frame
        if ticks_diff(now, self._next_frame_display_time) >= 0:
            
            # 1. Get the pre-rendered image for this screen
            frame_img = self.my_frames[self._current_frame_index]
            
            # 2. Paste the image directly onto the buffer
            self.fb.paste(frame_img, (0, 0))
                
            # 3. Advance to the next frame
            # The original code advanced by 4, I'm keeping it if it's intentional
            self._current_frame_index += 1
            if self._current_frame_index >= len(self.my_frames):
                self._current_frame_index = 0 # Loop back to the start
            
            # 4. Schedule next display time
            # Ensure the next frame time is always relative to now, not the last scheduled time
            self._next_frame_display_time = ticks_add(now, self._frame_time_interval)
            
            return True # A video frame was drawn
            
        return False # Waiting for next video frame time


# -----------------------------
# Display Control Functions
# -----------------------------

def send_to_display(player):
    """Function to execute the I/O transfer in a separate thread."""
    if player.device:
        player.device.display(player.fb)

def setup_devices(addr_l, addr_r, driver):
    """Initializes the two OLED devices."""
    ADDRESS_L = addr_l 
    ADDRESS_R = addr_r
    try:
        # Standard I2C bus 1 on RPi
        serial_L = i2c(port=1, address=ADDRESS_L)
        device_L = driver(serial_L, rotate=0)
        serial_R = i2c(port=1, address=ADDRESS_R)
        device_R = driver(serial_R, rotate=0)
    except Exception as e:
        print(f"Error initializing luma devices at 0x{ADDRESS_L:x} and 0x{ADDRESS_R:x}: {e}")
        return None, None, None, None

    # Create the PIL Image buffers
    img_L = Image.new(device_L.mode, device_L.size, color=BGCOLOR)
    img_R = Image.new(device_R.mode, device_R.size, color=BGCOLOR)
    
    return device_L, device_R, img_L, img_R


def read_command():
    """Reads the current command from the external file."""
    try:
        with open(EYE_COMMAND_FILE, 'r') as f:
            command = f.read().strip().upper()
            if command in FRAME_MAP:
                return command
            else:
                return "CENTER" # Default to a safe state if file content is bad
    except FileNotFoundError:
        # File might not exist yet; assume idle
        return "CENTER"
    except IOError:
        # Handle cases where the file might be being written to
        return "CENTER"


def run_eye_display(device_L, device_R, img_L, img_R):
    """Main loop for reading the command file and updating the displays."""
    
    # --- STEP 1: INITIALIZE PLAYERS ---
    player_L = FramePlayer(img_L, device_L, eye_side='left')
    player_R = FramePlayer(img_R, device_R, eye_side='right')

    current_state = ""
    last_read_time = ticks_ms()

    # --- Initial Load ---
    initial_command = read_command()
    player_L.load_frames(FRAME_MAP[initial_command]['left'])
    player_R.load_frames(FRAME_MAP[initial_command]['right'])
    current_state = initial_command
    print(f"\n--- RoboEyes Display Started (Initial State: {initial_command}) ---")
    print(f"Playing at {VIDEO_FPS} FPS. Reading '{EYE_COMMAND_FILE}' every {READ_INTERVAL_MS}ms. Press Ctrl+C to stop.")

    try:
        while True:
            now = ticks_ms()
            
            # --- Command File Reader Loop ---
            if ticks_diff(now, last_read_time) >= 0:
                new_state = read_command()
                
                if new_state != current_state:
                    print(f"State change detected: {current_state} -> {new_state}")
                    
                    # Dynamically load the new frames
                    frame_dirs = FRAME_MAP.get(new_state, FRAME_MAP["CENTER"])
                    
                    if player_L.load_frames(frame_dirs['left']) and \
                       player_R.load_frames(frame_dirs['right']):
                        current_state = new_state
                    else:
                         # Fallback if the requested directory is missing
                        print(f"Warning: Failed to load frames for state {new_state}. Staying in {current_state}.")
                        
                last_read_time = ticks_add(now, READ_INTERVAL_MS)
            
            # --- Display Animation Loop ---
            # 1. Update and Draw to Memory (will draw if time interval has passed)
            frame_ready_L = player_L.update_and_draw()
            frame_ready_R = player_R.update_and_draw()

            # 2. Parallel I/O Transfer (Only if a new frame was drawn)
            if frame_ready_L or frame_ready_R:
                thread_L = threading.Thread(target=send_to_display, args=(player_L,))
                thread_R = threading.Thread(target=send_to_display, args=(player_R,))
                
                thread_L.start()
                thread_R.start()
                
                thread_L.join()
                thread_R.join()
            
            # 3. Micro-sleep to keep CPU usage reasonable when waiting for next frame time
            time.sleep(0.001)
                
    except KeyboardInterrupt:
        print("\nExiting animation loop.")
    except Exception as e:
        print(f"\nCritical error in display loop: {e}")
    finally:
        device_L.clear()
        device_R.clear()
        print("Display stopped and cleared.")


if __name__ == '__main__':
    # Configuration for your dual OLEDs
    ADDRESS_L = 0x3c 
    ADDRESS_R = 0x3d 
    DISPLAY_DRIVER = sh1106 # Set to ssd1306 if that is your correct driver
    
    device_L, device_R, img_L, img_R = setup_devices(
        ADDRESS_L, ADDRESS_R, DISPLAY_DRIVER
    )

    if device_L and device_R:
        run_eye_display(device_L, device_R, img_L, img_R)
    else:
        sys.exit(1)
