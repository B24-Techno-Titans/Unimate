import os
import sys
import speech_recognition as sr
from google import genai
import tempfile
import subprocess
import time

PIPER_EXE = "/home/unimate/unimate_tts/piper/piper"
VOICE_MODEL = "/home/unimate/unimate_tts/en_US-hfc_female-medium.onnx"
AUDIO_OUTPUT = "plughw:1,0"

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
        print("Say 'Wake up' to start...")
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
        # recognizer.adjust_for_ambient_noise(source)
        print("Listening for command...")
        try:
            audio = recognizer.listen(source, phrase_time_limit=8)
            recognizer.pause_threshold = 1
            print("Command captured. Processing...")
            command = recognizer.recognize_google(audio)
            print("You said:", command)
            return command
        except sr.UnknownValueError:
            print("Sorry, could not understand.")
            speak("Sorry, I could not understand that.")
            return None
        except sr.RequestError as e:
            print(f"Google API error: {e}")
            speak("There was an error connecting to the speech service.")
            return None

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
        if command:
            ask_gemini(command)