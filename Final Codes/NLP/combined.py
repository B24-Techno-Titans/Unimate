import os
import sys
import speech_recognition as sr
from google import genai
import tempfile
import subprocess
import time
import requests
import humidifier
from humidifier import set_humidifier

PIPER_EXE = "/home/unimate/unimate_tts/piper/piper"
VOICE_MODEL = "/home/unimate/unimate_tts/en_US-hfc_female-medium.onnx"
AUDIO_OUTPUT = "plughw:1,0"
# LED URLs
LED_ON_URL  = "http://led-controller.local/set-colour?rgb=%23ff00ff&brightness=70"
LED_OFF_URL = "http://led-controller.local/set-colour?rgb=%23000000&brightness=0"

# FAN URL (HTTP API placeholder)
FAN_ON_URL = "http://smart-fan.local/set-speed?speed=2"
FAN_OFF_URL = "http://smart-fan.local/set-speed?speed=0"


# -------------------------------
# Redirect low-level C stderr (ALSA, JACK) to null
# -------------------------------
sys.stderr.flush()
devnull = os.open(os.devnull, os.O_WRONLY)
os.dup2(devnull, sys.stderr.fileno())

# -------------------------------
# Gemini API setup
# -------------------------------
API_KEY = "AIzaSyB5wy_dooNDVwV9hAj-myU8d1d3rIH5U48"
os.environ["GEMINI_API_KEY"] = API_KEY
client = genai.Client()

# -------------------------------
# Speech recognition setup
# -------------------------------
recognizer = sr.Recognizer()
mic_index = None  # change if multiple mics
WAKE_WORD = "wake up"
recognizer.pause_threshold = 1.5  # seconds of pause to detect end of speech

# -------------------------------
# Text-to-Speech (TTS) function
# -------------------------------
AUDIO_OUTPUT = "plughw:0,0"
# AUDIO_OUTPUT = "hw:1,0"  # 3.5mm headphone jack
TTS_FILE = "tts_output.mp3"  # persistent file for TTS


def speak(text):
    clean_text = text.replace('"', '').replace("'", "")
    command = (
        f'echo "{clean_text}" | '
        f'{PIPER_EXE} --model {VOICE_MODEL} --output_raw | '
        f'aplay -r 22050 -f S16_LE -t raw -D {AUDIO_OUTPUT}'
    )
    subprocess.run(command, shell=True)


# -------------------------------
# Wake word detection
# -------------------------------
def listen_for_wake_word():
    with sr.Microphone(device_index=mic_index) as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Say 'Bunny' to start...")
        while True:
            try:
                audio = recognizer.listen(source, phrase_time_limit=3)
                text = recognizer.recognize_google(audio).lower()
                if WAKE_WORD in text:
                    print("Wake word detected!")
                    speak("Yes?")
                    return
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                print(f"Google API error: {e}")

# -------------------------------
# Command recognition
# -------------------------------
def listen_for_command():
    with sr.Microphone(device_index=mic_index) as source:
        print("Listening for command...")
        audio = recognizer.listen(source, phrase_time_limit=5)
        recognizer.pause_threshold = 1
    try:
        text = recognizer.recognize_google(audio).lower()
        print("Heard:", text)
        return text
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"Google API error: {e}")
        return ""

def handle_command(text):
    # LED control
    if "on" in text and ("led" in text or "light" in text):
        print("Turning LED ON")
        try:
            requests.get(LED_ON_URL, timeout=3)
        except requests.RequestException as e:
            print("LED ON request failed:", e)
        return

    if "off" in text and ("led" in text or "light" in text):
        print("Turning LED OFF")
        try:
            requests.get(LED_OFF_URL, timeout=3)
        except requests.RequestException as e:
            print("LED OFF request failed:", e)
        return
    if "fan" in text:
        if "on" in text:
            print("Turning FAN ON")
            try:
                requests.get(FAN_ON_URL, timeout=3)
            except requests.RequestException as e:
                print("FAN ON request failed:", e)
        elif "off" in text:
            print("Turning FAN OFF")
            try:
                requests.get(FAN_OFF_URL, timeout=3)
            except requests.RequestException as e:
                print("FAN OFF request failed:", e)
        return
    if "humidifier" in text:
        if "on" in text:
            print("Turning HUMIDIFIER ON")
            set_humidifier(1)
        elif "off" in text:
            print("Turning HUMIDIFIER OFF")
            set_humidifier(0)
        elif "blink" in text:
            print("Setting HUMIDIFIER to BLINK")
            set_humidifier(2)
        return
    
def gorc(text):
    if "how" in text:
        return True
    if ("on" in text or "off" in text) and ("led" in text or "light" in text or "fan" in text or "humidifier" in text):
        return False
    else:
        return True

# -------------------------------
# Gemini response
# -------------------------------
PERSONALITY_PROMPT = (
    'only respond with english letters and numbers'
    "dont go for long reposes , give short answers if not told to give long"
    "You are UniMate, a friendly and helpful companion robot. "
    "You talk in a warm, polite, and approachable manner. "
    "You try to understand the user's context and provide useful, human-like responses. "
    "Always respond in a friendly, conversational tone. "
    "dont introduce yourself only output the needed answer."
    "your response is going to a texe to speech api so Dont respond with symbols and emojies on any situation"
)
def ask_gemini(command):
    try:
        print("Fetching response from Gemini...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=PERSONALITY_PROMPT + command
        )
        print("UniMate says:", response.text)
        speak(response.text)   # <-- speak the response
    except Exception as e:
        print("Gemini API Error:", e)
# -------------------------------
# Main loop
# -------------------------------
if __name__ == "__main__":
    while True:
        listen_for_wake_word()
        command = listen_for_command()
        if gorc(command):
            ask_gemini(command)
        else:
            handle_command(command)