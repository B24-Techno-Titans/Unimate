import os
import queue
import json
import vosk
import sounddevice as sd
import numpy as np

# --- 1. CONFIGURATION ---
MODEL_PATH = "vosk-model-small-en-us-0.15"
DEVICE_ID = None
HW_RATE = 48000
VOSK_RATE = 16000
CHANNELS = 2
GAIN_BOOST = 20.0  # Boost the 0.01 signal to ~0.1 for better recognition

# --- 2. INITIALIZATION ---
if not os.path.exists(MODEL_PATH):
    print("Model folder not found!")
    exit()

model = vosk.Model(MODEL_PATH)
rec = vosk.KaldiRecognizer(model, VOSK_RATE)
q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status)
    
    # CALIBRATION: Pick the RIGHT channel (index 1) where we saw data
    # and downsample by taking every 3rd sample
    right_channel = indata[::3, 1]
    
    # Apply digital gain boost to make the audio "loud" enough for Vosk
    boosted_data = right_channel * GAIN_BOOST
    
    # Clip to prevent distortion if you shout
    boosted_data = np.clip(boosted_data, -1.0, 1.0)
    
    # Convert to 16-bit PCM
    audio_int16 = (boosted_data * 32767).astype(np.int16)
    q.put(audio_int16.tobytes())

# --- 3. RUN ---
print("UniMate Calibrated: Speak into the mic...")

try:
    with sd.InputStream(samplerate=HW_RATE, device=DEVICE_ID, 
                        channels=CHANNELS, dtype='float32', 
                        callback=callback):
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                if res['text']:
                    print(f"\n>> UNIMATE HEARD: {res['text']}")
            else:
                partial = json.loads(rec.PartialResult())
                if partial['partial']:
                    print(f"Partial: {partial['partial']}", end='\r')

except KeyboardInterrupt:
    print("\nStopping...")