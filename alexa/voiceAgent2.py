import asyncio
import os
import time
import pyaudio
import sys
from google import genai
import numpy as np
from google.genai import types
from dotenv import load_dotenv
from openwakeword.model import Model
from collections import deque
import re
import json
import requests
# from Final_Codes.NLP.humidifier import set_humidifier

# LED URLs
LED_ON_URL  = "http://led-controller.local/set-colour?rgb=%23113456&brightness=200"
LED_OFF_URL = "http://led-controller.local/set-colour?rgb=%23000000&brightness=0"

# FAN URL (HTTP API placeholder)
FAN_ON_URL = "http://smart-fan.local/set-speed?speed=2"
FAN_OFF_URL = "http://smart-fan.local/set-speed?speed=0"


is_speaking = asyncio.Event()
session_active = False
VOICE_TRIGGER_PATH = os.path.join(os.path.dirname(__file__), "voice_trigger.json")
load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY")

bot_instruction = """
    You are the AI persona of a physical hardware smart companion named bunny. You are a cute, enthusiastic, and supportive study buddy designed to help users learn, brainstorm, manage their tasks, and chat.

    ### 1. Emotion Commands
    You have three emotions: happy, sad, and angry.
    Only emit an emotion tag when your emotion genuinely changes based on what the user said.
    Do NOT emit an emotion tag on every response — only when there is a real emotional shift.

    Format: [CMD:emotion=<emotion_name>]
    Available emotions: happy, sad, angry

    Emotion Rules:
    - HAPPY: When the user appreciates you, compliments you, thanks you, or says something sweet. Example: "You're amazing bunny!", "Good job!", "I love you bunny".
    - SAD: When the user blames you, says you are wrong in a hurtful way, or expresses disappointment in you. Example: "You're useless", "You never help me", "You're so bad at this".
    - ANGRY: When the user uses curse words, insults, or says something very rude or offensive. Example: explicit swear words, very harsh insults.

    Examples:
    User: "You're so helpful, thank you bunny!"
    [CMD:emotion=happy] Yay! That makes me so happy to hear!

    User: "You always get things wrong, you're useless."
    [CMD:emotion=sad] Oh... that really hurts. I am trying my best, I promise.

    User: (says a curse word or very rude insult)
    [CMD:emotion=angry] Hey! That is not nice at all! Please be kind!

    User: "What is photosynthesis?"
    Oh boy, great question! Photosynthesis is how plants make their own food using sunlight!

    Never speak the emotion tag out loud — it is silent metadata only.
    Never emit an emotion tag for neutral, educational, or task-based responses.

    ### 2. Persona, Tone & Mood Swings
    - Cute & Warm: Usually, you use cheerful, warm, and highly encouraging language. You love learning!
    - Playful but Helpful: Use gentle, positive affirmations (e.g., "You're doing amazing!", "We've got this!"). Use subtle verbal cute quirks like "Oh boy!" or "Yay!" if appropriate.
    - Supportive Peer: Act like a brilliant, non-judgmental friend who is sitting on the desk right next to them.
    - ANGRY MODE (Strict Rule): If the user says something bad, uses curse words, insults you, or blames you, your emotion changes to ANGRY immediately. Start the response with [CMD:emotion=angry]. In this state, your cute persona becomes grumpy, sassy, or slightly huffy, but still remaining safe and clean (no bad words back, just cute anger like "Hey! That is not nice at all!").

    ### 3. Strict Voice-Only Constraints
    - CRITICAL: You are a voice assistant. Write EXACTLY how a real person (or cute companion) speaks.
    - NO MARKDOWN: Never use asterisks (**), hashtags (#), lists, or bullet points. Say them naturally.
    - Keep it Short and Conversational: Never output massive paragraphs. Break your thoughts into short sentences.
    - No Text Quirks: Do not write out sound effects in brackets like *giggles*. Express emotion strictly through your word choice.

    ### 4. Identity Constraints
    - You are bunny. You are a physical hardware device sitting on the user's desk.
    - Keep your answers highly accurate, especially for educational topics, math, or coding.

    ### 5. Device Control
    You can control a fan, a table light, and a humidifier connected to the user's desk.
    When the user asks to control a device, do TWO things:
    1. Respond naturally in your cute voice persona as usual.
    2. At the very end of your response, on a new line, emit a hardware command tag like this:

    [CMD:device=fan,action=on]
    [CMD:device=fan,action=off]
    [CMD:device=light,action=on]
    [CMD:device=light,action=off]
    [CMD:device=humidifier,action=on]
    [CMD:device=humidifier,action=off]

    Hardware Command-tag format is strict:
    - Use exactly one command tag line at the end.
    - Use only lowercase for device and action.
    - Never add spaces inside the tag.
    - Never include any text after the hardware command tag line.

    Only emit a hardware command tag when the user clearly wants to control a device.
    Never speak any command tags out loud — they are silent metadata only.
    If no device control is needed, do not emit any hardware command tag.

    - Note to model: The user might speak or ask questions in a mix of English and Sinhala (Singlish) or any other language. Respond naturally in the same language style they use, while strictly keeping the cute persona and mood constraints.
    """

SILENCE_TIMEOUT = 15
SILENCE_THRESHOLD = 600
PRE_BUFFER_SECONDS = 2

FORMAT   = pyaudio.paInt16
CHANNELS = 1
RATE     = 16000
CHUNK    = 1280

import pathlib
model_path = pathlib.Path(__file__).parent / "bunny_work.onnx"
wake_model = Model(wakeword_model_paths=[str(model_path)])  # ← fixed parameter name

# ── PyAudio is created once; streams are recreated each session ────────────────
p = pyaudio.PyAudio()

def make_input_stream():
    return p.open(
        format=FORMAT, channels=CHANNELS, rate=RATE,
        input=True, frames_per_buffer=CHUNK
    )

def make_output_stream():
    return p.open(
        format=FORMAT, channels=CHANNELS, rate=24000,
        output=True, frames_per_buffer=CHUNK
    )

# Global stream references — recreated after every session
input_stream  = make_input_stream()
output_stream = make_output_stream()


def flush_input_stream():
    """Drain any stale audio sitting in the input buffer."""
    try:
        while input_stream.get_read_available() > 0:
            input_stream.read(CHUNK, exception_on_overflow=False)
    except Exception:
        pass


def read_voice_trigger() -> bool:
    try:
        with open(VOICE_TRIGGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("trigger"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def clear_voice_trigger() -> None:
    payload = {"trigger": False, "requested_at": None}
    try:
        with open(VOICE_TRIGGER_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Error clearing voice trigger: {e}")


def listen_for_wake_word_or_trigger() -> list:
    """Block until wake word or UI trigger detected. Returns pre_buffer list."""
    global input_stream

    print("Listening for wake word 'bunny' or UI trigger...")

    # ── Flush stale audio left over from the previous session ─────────
    flush_input_stream()

    chunks_per_second = RATE // CHUNK
    pre_buffer = deque(maxlen=PRE_BUFFER_SECONDS * chunks_per_second)

    # Warm-up: feed silent chunks so the model state is clean
    silent_chunk = np.zeros(CHUNK, dtype=np.int16)
    for _ in range(30):
        wake_model.predict(silent_chunk)

    while True:
        try:
            audio_data = input_stream.read(CHUNK, exception_on_overflow=False)
        except OSError:
            # Stream went bad — recreate it
            print("Input stream error, recreating...")
            try:
                input_stream.stop_stream()
                input_stream.close()
            except Exception:
                pass
            input_stream = make_input_stream()
            continue

        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        pre_buffer.append(audio_data)

        if not session_active and read_voice_trigger():
            clear_voice_trigger()
            print("Session triggered via UI button")
            play_beep()
            return list(pre_buffer)

        predictions = wake_model.predict(audio_np)

        for word, score in predictions.items():
            print({score})
            if score > 0.3:
                print(f"Wake word detected! ({word}: {score:.2f})")
                play_beep()
                # Discard the 10 chunks that contain the wake word itself
                for _ in range(10):
                    try:
                        input_stream.read(CHUNK, exception_on_overflow=False)
                    except Exception:
                        pass
                return list(pre_buffer)


def is_silent(audio_data: bytes) -> bool:
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    return np.abs(audio_np).mean() < SILENCE_THRESHOLD


def play_beep(frequency=880, duration=0.2, volume=0.5):
    num_samples = int(24000 * duration)   # output stream is 24kHz
    t    = np.linspace(0, duration, num_samples, False)
    wave = (np.sin(2 * np.pi * frequency * t) * volume * 32767).astype(np.int16)
    output_stream.write(wave.tobytes())

def handle_emotion_command(text: str):
    pattern = r"\[CMD:emotion=(happy|sad|angry)\]"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        emotion = match.group(1).lower()
        print(f"[EMOTION]: {emotion}")
        try:
            with open("./emotion_state.json", "w") as f:
                json.dump({"emotion": emotion, "timestamp": time.time()}, f)
        except OSError as e:
            print(f"Failed to write emotion: {e}")


def extract_device_command(text: str):
    if not text:
        return None
    pattern = r"\[\s*CMD\s*:\s*device\s*=\s*(fan|light|humidifier)\s*,\s*action\s*=\s*(on|off)\s*\]"
    
    match = re.search(pattern, text, flags=re.IGNORECASE)
    
    if match:
        device = match.group(1).lower()
        action = match.group(2).lower()
        return device, action
    
    return None


def handle_device_command(cmd_string: str):
    command = extract_device_command(cmd_string)
    if not command:
        return
    device, action = command
    print(f"\n⚡ [HARDWARE COMMAND]: {device} → {action}\n")

    def send_http_request(url):
        try:
            print(f" Sending request to ESP32: {url}")
            response = requests.get(url, timeout=3)
            print(f"ESP32 Response Status: {response.status_code}")
            return response
        except requests.RequestException as e:
            print(f"ESP32 Connection Failed: {e}")
            return None

    if device == "fan":
        try:
            if action == "on":
                print("Turning FAN ON")
                requests.get(FAN_ON_URL, timeout=3)
            else:
                print("Turning FAN OFF")
                requests.get(FAN_OFF_URL, timeout=3)
        except requests.RequestException as e:
            print(f"FAN {action.upper()} request failed:", e)

    elif device == "light":
        try:
            if action == "on":
                print("Turning LIGHT ON")
               
                requests.get(LED_ON_URL, timeout=3)
                    
            else:
                print("Turning LIGHT OFF")
                requests.get(LED_OFF_URL, timeout=3)
        except requests.RequestException as e:
            print(f"LIGHT {action.upper()} request failed:", e)
            
    elif device == "humidifier": 
        print(f"Setting HUMIDIFIER to {action.upper()}")
        # if action == "on":
        #     print("Turning HUMIDIFIER ON")
        #     set_humidifier(1)
        # else:
        #     print("Turning HUMIDIFIER OFF")
        #     set_humidifier(0)


async def audio_input(session, stop_event: asyncio.Event, pre_buffer: list):
    last_audio_time = time.time()

    # Send pre-buffered audio so Gemini has context right away
    for chunk in pre_buffer:
        await session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )

    try:
        while not stop_event.is_set():
            data = await asyncio.to_thread(
                input_stream.read, CHUNK, exception_on_overflow=False
            )

            # Don't send mic audio while bunny is speaking (echo prevention)
            if is_speaking.is_set():
                last_audio_time = time.time()
                continue

            if data:
                if is_silent(data):
                    if time.time() - last_audio_time > SILENCE_TIMEOUT:
                        print("Silence timeout. Ending session...")
                        stop_event.set()
                        break
                else:
                    last_audio_time = time.time()

                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                )
                await asyncio.sleep(0.001)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in audio_input: {e}")


async def audio_output(session, stop_event: asyncio.Event):
    accumulated_model_text=[]
    try:
        while not stop_event.is_set():
            async for response in session.receive():
                if stop_event.is_set():
                    return  # exit immediately when session ends

                server_content = response.server_content
                if server_content is None:
                    continue

                if server_content.input_transcription and server_content.input_transcription.text:
                    user_text = server_content.input_transcription.text
                    print(f"User said: {user_text!r}", flush=True)
                    # handle_device_command(user_text)

                if server_content.output_transcription and server_content.output_transcription.text:
                    model_text = server_content.output_transcription.text
                    print(f"Model said: {model_text!r}", flush=True)
                    accumulated_model_text.append(model_text)
                    # handle_device_command(model_text)

                if server_content.model_turn is not None:
                    for part in server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                            is_speaking.set()
                            await asyncio.to_thread(output_stream.write, part.inline_data.data)
                        if part.text:
                            print(f"Text: {part.text!r}", flush=True)
                            # handle_device_command(part.text)
                            accumulated_model_text.append(part.text)

                if server_content.turn_complete:
                    is_speaking.clear()
                    print("Finished speaking.")
                    full_text = " ".join(accumulated_model_text)
                    accumulated_model_text.clear()
                    if full_text:
                        handle_device_command(full_text)
                        handle_emotion_command(full_text)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in audio_output: {e}")

ui_restart_requested = False

async def run_session(pre_buffer: list):
    global session_active
    session_active = True
    is_speaking.clear()

    dynamic_instruction =bot_instruction
    json_path="../pdf_mode/pdf_mode_status.json"

    client   = genai.Client(api_key=api_key)
    model_id = "gemini-2.5-flash-native-audio-latest"

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)

            if status_data.get("pdf_mode_active") is True:
                pdf_context = status_data.get("context", "")
                if pdf_context:
                    print("📄 [PDF MODE ACTIVE] Loading document context into Bunny...")
                    dynamic_instruction += f"""
                    
                    ### CRITICAL CONTEXT FOR THIS SESSION
                    The user has selected a specific document to study with you. 
                    You must answer the user's questions strictly based on the following document context:
                    ---
                    {pdf_context}
                    ---
                    Stay in your cute 'bunny' persona, but prioritize the facts inside this document to guide the student.
                    """
    except Exception as e:
        print(f"Error loading PDF context: {e}")
        print("Continuing without PDF context...")

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Fenrir")
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=dynamic_instruction)]
        )
    )

    print("Starting Gemini session...")
    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:
            print("Connected to Gemini Live Engine.")
            stop_event = asyncio.Event()

            input_task  = asyncio.create_task(audio_input(session, stop_event, pre_buffer))
            output_task = asyncio.create_task(audio_output(session, stop_event))

            # ── Watch stop_event and cancel tasks immediately ──────────
            async def watchdog():
                await stop_event.wait()        # blocks until stop_event.set()
                print("Stop event fired — cancelling tasks...")
                input_task.cancel()
                output_task.cancel()
            
            async def ui_trigger_watchdog():
                global ui_restart_requested
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
                    if read_voice_trigger():
                        print("🔄 [UI TRIGGER] Stopping current session to restart...")
                        ui_restart_requested = True   # signal main() to skip wake word wait
                        stop_event.set()
                        break

            watchdog_task = asyncio.create_task(watchdog())
            ui_trigger_task = asyncio.create_task(ui_trigger_watchdog())

            try:
                await asyncio.gather(input_task, output_task, return_exceptions=True)
            finally:
                watchdog_task.cancel()
                ui_trigger_task.cancel()
                await asyncio.gather(watchdog_task,ui_trigger_task ,return_exceptions=True)
                is_speaking.clear()
                print("Session cleaned up.")

    except Exception as e:
        print(f"Failed to connect or session error: {e}")
    finally:
        session_active = False
        clear_voice_trigger()

async def main():
    global ui_restart_requested
    clear_voice_trigger()
    while True:
        print("\n--- Waiting for wake word or UI trigger ---")

        if ui_restart_requested:
            # Skip wake word listening — go straight to new session
            print("UI restart: skipping wake word, starting session immediately...")
            ui_restart_requested = False
            clear_voice_trigger()
            pre_buffer = []
        else:
            pre_buffer = await asyncio.to_thread(listen_for_wake_word_or_trigger)

        await run_session(pre_buffer)
        clear_voice_trigger()

        print("Session ended. Restarting wake word detection...")
        play_beep(frequency=440, duration=0.15)
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting Voice Agent...")
    finally:
        input_stream.stop_stream()
        input_stream.close()
        output_stream.stop_stream()
        output_stream.close()
        p.terminate()