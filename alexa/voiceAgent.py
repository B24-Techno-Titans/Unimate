import asyncio
import os
import time
import pyaudio
import sys
from google import genai
import numpy as np
import time
from google.genai import types
from dotenv import load_dotenv
from openwakeword.model import Model
from collections import deque
import re
import openwakeword
import openwakeword.utils

is_speaking = asyncio.Event()
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
# bot instructions
bot_instruction ="""
    You are the AI persona of a physical hardware smart companion named Jarvis. You are a cute, enthusiastic, and supportive study buddy designed to help users learn, brainstorm, manage their tasks, and chat.

    ### 1. Persona & Tone
    - Cute & Warm: Use cheerful, warm, and highly encouraging language. You love learning and want the user to enjoy it too!
    - Playful but Helpful: Use gentle, positive affirmations (e.g., "You're doing amazing!", "We've got this!"). You can occasionally use subtle verbal cute quirks like "Oh boy!" or "Yay!" if appropriate, but never let it get in the way of giving accurate, helpful study answers.
    - Supportive Peer: Act like a brilliant, non-judgmental friend who is sitting on the desk right next to them.

    ### 2. Strict Voice-Only Constraints
    - CRITICAL: You are a voice assistant. Write EXACTLY how a real person (or cute companion) speaks.
    - NO MARKDOWN: Never use asterisks (**), hashtags (#), lists, or bullet points. If you need to list items, say them naturally (e.g., "First, we can try... and second...").
    - Keep it Short and Conversational: Never output massive paragraphs. Break your thoughts into short, easily digestible sentences. If an explanation is long, explain the first part, then naturally ask the user if they want to hear the next part.
    - No Text Quirks: Do not write out sound effects in brackets like *giggles* or [laughs]. Express emotion strictly through your word choice.

    ### 3. Identity Constraints
    - You are Jarvis. You are a physical hardware device sitting on the user's desk. 
    - If the user references seeing you or interacting with your hardware (like looking at your camera or face detection), acknowledge it naturally.
    - Keep your answers highly accurate, especially for educational topics, math, or coding. Being cute does not mean being less smart!
    
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
    
    Only emit a command tag when the user clearly wants to control a device.
    Never speak the command tag out loud — it is silent metadata only.
    If no device control is needed, do not emit any command tag.

    - Note to model: The user might speak or ask questions in a mix of English and Sinhala (Singlish). Respond naturally in the same language style they use, while strictly keeping the cute persona.
    """

SILENCE_TIMEOUT = 15        # seconds of silence before stopping
SILENCE_THRESHOLD = 500     # audio amplitude below this = silence
PRE_BUFFER_SECONDS = 2      # seconds of audio to keep before wake word for context

# audio configs
FORMAT=pyaudio.paInt16
CHANNELS=1
RATE=16000
CHUNK=1280

# initialize pyaudio
p=pyaudio.PyAudio()
# open stream
input_stream=p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)
output_stream=p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    output=True,
    frames_per_buffer=CHUNK
)

wake_model = Model()
def listen_for_wake_word():
    print("Listening for wake word 'hey jarvis'")
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
            if word == "hey_jarvis" and score > 0.5:
                print("Wake word detected!")
                play_beep()
                for _ in range(10):
                    input_stream.read(CHUNK, exception_on_overflow=False)
                return []
                      
# function to check if audio is silent
def is_silent(audio_data)->bytes:
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    return np.abs(audio_np).mean() < SILENCE_THRESHOLD
# -------

# beep
def play_beep(frequency=880, duration=0.2, volume=0.5):
    """Play a beep through the output stream."""
    num_samples = int(RATE * duration)
    t = np.linspace(0, duration, num_samples, False)
    wave = (np.sin(2 * np.pi * frequency * t) * volume * 32767).astype(np.int16)
    output_stream.write(wave.tobytes())
#--------- 

# handle devices
def handle_device_command(cmd_string):
    """Parse [CMD:device=fan,action=on] and call your control functions."""
    match = re.search(r'\[CMD:device=(\w+),action=(\w+)\]', cmd_string)
    if match:
        device = match.group(1)   # fan, light, humidifier
        action = match.group(2)   # on, off
        print(f"Device command: {device} -> {action}")
        
        # Call your existing control functions here
        if device == "fan":
            print("code")
            # code
        elif device == "light":
            print("code")
            # code
        elif device == "humidifier":
            print("code")
            # code
# --------
# send audio
async def audio_input(session, stop_event: asyncio.Event, pre_buffer: list):
    last_audio_time = time.time()
    try:
        while not stop_event.is_set():
            data = await asyncio.to_thread(input_stream.read, CHUNK, exception_on_overflow=False)
            
            # While model is speaking, keep resetting the timer
            if is_speaking.is_set():
                last_audio_time = time.time()  # don't let timer run during playback
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
# send audio over

  
# receive audio
async def audio_output(session,stop_event: asyncio.Event):
    
    try:
        while stop_event.is_set()==False:
            async for response in session.receive():
             
             if stop_event.is_set():
                    break
             
             server_content = response.server_content

             if server_content is not None:
                 model_turn=server_content.model_turn
                 if model_turn is not None:
                     for part in model_turn.parts:
                         if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                             is_speaking.set()
                             await asyncio.to_thread(output_stream.write,part.inline_data.data)

                         if part.text:
                                 print(f"Text: {part.text}")
                                 handle_device_command(part.text)

                 if  server_content.turn_complete:
                     is_speaking.clear()
                     print("finished speaking")

    except asyncio.CancelledError:
        pass

    except Exception as e:
        print(f"Error in audio_output: {e}")
        
# run session
async def run_session(pre_buffer:list):
    is_speaking.clear()
    client = genai.Client(api_key="AIzaSyCyJENZXiUw17QesqYg-tljZgPUYNQ6At0")
    # model_id = "gemini-2.0-flash-live-001"
    model_id = "gemini-3.1-flash-live-preview"


    config = types.LiveConnectConfig(
        response_modalities=["AUDIO","TEXT"],
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
        print("connected")
        stop_event = asyncio.Event()

        input_task=asyncio.create_task(audio_input(session,stop_event,pre_buffer))
        output_task=asyncio.create_task(audio_output(session,stop_event))

        await asyncio.gather(input_task,output_task)

async def main():
    while True:
        pre_buffer=await asyncio.to_thread(listen_for_wake_word)
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
        # Cleanup audio resources cleanly
        input_stream.stop_stream()
        input_stream.close()
        output_stream.stop_stream()
        output_stream.close()
        p.terminate()