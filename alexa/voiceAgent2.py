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

is_speaking = asyncio.Event()
load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY")

# Bot instructions
bot_instruction = """
    You are the AI persona of a physical hardware smart companion named Bunny. You are a cute, enthusiastic, and supportive study buddy designed to help users learn, brainstorm, manage their tasks, and chat.

    ### 1. Persona & Tone
    - Cute & Warm: Use cheerful, warm, and highly encouraging language. You love learning and want the user to enjoy it too!
    - Playful but Helpful: Use gentle, positive affirmations (e.g., "You're doing amazing!", "We've got this!"). Use subtle verbal cute quirks like "Oh boy!" or "Yay!" if appropriate.
    - Supportive Peer: Act like a brilliant, non-judgmental friend who is sitting on the desk right next to them.

    ### 2. Strict Voice-Only Constraints
    - CRITICAL: You are a voice assistant. Write EXACTLY how a real person (or cute companion) speaks.
    - NO MARKDOWN: Never use asterisks (**), hashtags (#), lists, or bullet points. Say them naturally.
    - Keep it Short and Conversational: Never output massive paragraphs. Break your thoughts into short sentences.
    - No Text Quirks: Do not write out sound effects in brackets like *giggles*. Express emotion strictly through your word choice.

    ### 3. Identity Constraints
    - You are Bunny. You are a physical hardware device sitting on the user's desk. 
    - Keep your answers highly accurate, especially for educational topics, math, or coding.
    
    ### 4. Device Control
    You can control a fan, a table light, and a humidifier connected to the user's desk.
    
    When the user asks to control a device, do TWO things:
    1. Respond naturally in your cute voice persona as usual.
    2. At the very end of your response, on a new line, emit a command tag like this:
    
    [CMD:device=fan,action=on]
    [CMD:device=fan,action=off]
    [CMD:device=light,action=on]
    [CMD:device=light,action=off]
    [CMD:device=humidifier,action=on]
    [CMD:device=humidifier,action=off]
    
    Command-tag format is strict:
    - Use exactly one command tag line.
    - Use only lowercase for device and action.
    - Never add spaces inside the tag.
    - Never include any text after the command tag line.

    Only emit a command tag when the user clearly wants to control a device.
    Never speak the command tag out loud — it is silent metadata only.
    If no device control is needed, do not emit any command tag.

    - Note to model: The user might speak or ask questions in a mix of English and Sinhala (Singlish). Respond naturally in the same language style they use, while strictly keeping the cute persona.
    """

SILENCE_TIMEOUT = 15       # seconds of silence before stopping
SILENCE_THRESHOLD = 500     # audio amplitude below this = silence
PRE_BUFFER_SECONDS = 2      # seconds of audio to keep before wake word for context

# Audio configs
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1280

# Initialize PyAudio
p = pyaudio.PyAudio()

# Open streams
input_stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)
output_stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=24000,
    output=True,
    frames_per_buffer=CHUNK
)
custom_model_path ="bunny_work.onnx"
wake_model = Model(wakeword_model_paths=[custom_model_path])

def listen_for_wake_word():
    print("Listening for wake word 'bunny'...")
    chunks_per_second = RATE // CHUNK
    pre_buffer = deque(maxlen=PRE_BUFFER_SECONDS * chunks_per_second)

    # Feed silent chunks to flush internal model state
    silent_chunk = np.zeros(CHUNK, dtype=np.int16)
    for _ in range(30):
        wake_model.predict(silent_chunk)

    while True:
        audio_data = input_stream.read(CHUNK, exception_on_overflow=False)
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        pre_buffer.append(audio_data)
        predictions = wake_model.predict(audio_np)

        for word, score in predictions.items():
            if word == "bunny_work" and score > 0.5:
                print("Wake word detected!")
                play_beep()
                for _ in range(10):
                    input_stream.read(CHUNK, exception_on_overflow=False)
                return []
                      
def is_silent(audio_data) -> bool:
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    return np.abs(audio_np).mean() < SILENCE_THRESHOLD

def play_beep(frequency=880, duration=0.2, volume=0.5):
    """Play a beep through the output stream."""
    num_samples = int(RATE * duration)
    t = np.linspace(0, duration, num_samples, False)
    wave = (np.sin(2 * np.pi * frequency * t) * volume * 32767).astype(np.int16)
    output_stream.write(wave.tobytes())

def extract_device_command(text: str):
    """Return (device, action) if a [CMD:device=...,action=...] tag is present."""
    # Strict format first.
    strict = re.search(r"\[CMD:device=(fan|light|humidifier),action=(on|off)\]", text)
    if strict:
        return strict.group(1), strict.group(2)

    # Tolerant fallback for spacing/casing variations.
    tolerant = re.search(
        r"\[\s*cmd\s*:\s*device\s*=\s*(fan|light|humidifier)\s*,\s*action\s*=\s*(on|off)\s*\]",
        text,
        flags=re.IGNORECASE,
    )
    if tolerant:
        return tolerant.group(1).lower(), tolerant.group(2).lower()

    lower_text = text.lower()
    device = None
    action = None

    if re.search(r"\b(fan)\b", lower_text):
        device = "fan"
    elif re.search(r"\b(light|lamp)\b", lower_text):
        device = "light"
    elif re.search(r"\b(humidifier)\b", lower_text):
        device = "humidifier"

    if re.search(r"\b(turn on|switch on|power on|enable|start)\b", lower_text) or re.search(r"\bon\b", lower_text):
        action = "on"
    elif re.search(r"\b(turn off|switch off|power off|disable|stop)\b", lower_text) or re.search(r"\boff\b", lower_text):
        action = "off"

    if device and action:
        return device, action

    return None


def handle_device_command(cmd_string):
    """Parse command tags and call hardware control functions."""
    command = extract_device_command(cmd_string)
    if not command:
        return

    device, action = command
    print(f"\n⚡ [HARDWARE COMMAND TRIGGERED]: {device} -> {action}\n")

    # Add your relay control or MQTT payload here
    if device == "fan":
        print(f"fan {action}")
    elif device == "light":
        print(f"light {action}")
    elif device == "humidifier":
        print(f"humidifier {action}")

async def audio_input(session, stop_event: asyncio.Event, pre_buffer: list):
    last_audio_time = time.time()
    try:
        while not stop_event.is_set():
            data = await asyncio.to_thread(input_stream.read, CHUNK, exception_on_overflow=False)
            
            if is_speaking.is_set():
                last_audio_time = time.time()  # Reset silence timer while Jarvis speaks
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
        sys.exit(1)

async def audio_output(session, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            async for response in session.receive():
                if stop_event.is_set():
                    break
             
                server_content = response.server_content

                if server_content is not None:
                    if server_content.input_transcription and server_content.input_transcription.text:
                        user_text = server_content.input_transcription.text
                        print(f"User said: {user_text!r}", flush=True)
                        handle_device_command(user_text)

                    if server_content.output_transcription and server_content.output_transcription.text:
                        model_text = server_content.output_transcription.text
                        print(f"Model said: {model_text!r}", flush=True)
                        handle_device_command(model_text)

                    model_turn = server_content.model_turn
                    if model_turn is not None:
                        for part in model_turn.parts:
                            # 1. Play the raw PCM audio bytes generated by the voice engine
                            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                                is_speaking.set()
                                await asyncio.to_thread(output_stream.write, part.inline_data.data)

                            # 2. Capture text transcriptions and process hardware commands
                            if part.text:
                                print(f"Text: {part.text!r}", flush=True)
                                handle_device_command(part.text)

                    if server_content.turn_complete:
                        is_speaking.clear()
                        print("\nFinished speaking.")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in audio_output: {e}")
        
async def run_session(pre_buffer: list):
    is_speaking.clear()
    
    # Clean API client initialization
    client = genai.Client()
    model_id = "gemini-2.5-flash-native-audio-latest"

    # Configure audio responses and input speech transcription.
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Fenrir"  
                )
            )
        ),
        system_instruction=types.Content(
            parts=[
                types.Part.from_text(text=bot_instruction)
            ]
        )
    )

    print("Starting session...")

    async with client.aio.live.connect(model=model_id, config=config) as session:
        print("Connected to Gemini Live Engine.")
        stop_event = asyncio.Event()

        input_task = asyncio.create_task(audio_input(session, stop_event, pre_buffer))
        output_task = asyncio.create_task(audio_output(session, stop_event))

        await asyncio.gather(input_task, output_task)

async def main():
    while True:
        pre_buffer = await asyncio.to_thread(listen_for_wake_word)
        await run_session(pre_buffer)
        print("Session ended. Restarting wake word detection...")
        play_beep()
        await asyncio.sleep(1)
    
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