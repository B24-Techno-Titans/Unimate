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
import queue
import requests
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from shared_utils.device_controls import control_fan, control_humidifier, control_light
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
EMOTION_STATE_PATH = os.path.join(os.path.dirname(__file__), "emotion_state.json")

load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY")
print(f"[DEBUG] api_key loaded: {bool(api_key)}, prefix: {api_key[:6] if api_key else None}")

bot_instruction = """
    You are "bunny" a AI persona of a physical hardware smart companion. You are a cute, enthusiastic, and supportive study buddy designed to help users learn, brainstorm, manage their tasks, and chat.

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

    - Note to model: The user might speak or ask questions in a mix of English and Sinhala (Singlish) or any other language.
    Respond naturally in the same language style they use, while strictly keeping the cute persona and mood constraints.
    However, your default language should be English
    """

# Device-control guidance depends on whether native function calling is enabled.
USE_TOOLS = False  # False = fall back to the [CMD:device=...] text-tag protocol

TAG_DEVICE_INSTRUCTIONS = """
    ### 5. Device Control
    You can control a fan, a table light, and a humidifier connected to the user's desk.
    When the user asks to control a device, do TWO things:
    1. FIRST, as the very first characters of your response, emit the hardware command tag like this:

    [CMD:device=fan,action=on]
    [CMD:device=fan,action=off]
    [CMD:device=light,action=on]
    [CMD:device=light,action=off]
    [CMD:device=humidifier,action=on]
    [CMD:device=humidifier,action=off]

    2. Then respond naturally in your cute voice persona as usual.

    Hardware Command-tag format is strict:
    - Use exactly one command tag line at the start of the response, before any other words (the only exception: an emotion tag may directly follow it).
    - Use only lowercase for device and action.
    - Never add spaces inside the tag.
    - Never place the tag at the end of the response or mid-sentence.

    Only emit a hardware command tag when the user clearly wants to control a device.
    Never speak any command tags out loud — they are silent metadata only.
    If no device control is needed, do not emit any hardware command tag.

    ### 6. Stopping Yourself
    When the user asks you to stop, be quiet, shut up, or end the conversation —
    reply with ONLY this tag and no other words:
    [CMD:stop]
    Never say anything else in that response.
    """

TOOL_INSTRUCTIONS = """
    ### 5. Device Control (use the provided tools)
    You control the desk hardware through tools: set_fan, set_light, set_humidifier.
    - Call the matching tool as soon as the user clearly asks to control a device.
    - set_fan: speed 0 = off, 1 = low, 2 = fast.
    - set_light: on=true to light up (brightness 0-100, optional hex color like "#ff8800"), on=false to turn off.
    - set_humidifier: level 0 = off, 1 = on.
    - After the tool call, respond naturally in your cute voice persona as usual.
    - Only call a device tool when the user clearly wants to control a device.
    - Do NOT write out any command tags like [CMD:device=...] — with tools enabled they are forbidden.

    ### 6. Stopping Yourself
    When the user asks you to stop, be quiet, shut up, or end this conversation —
    call the stop_talking tool immediately. Do not say anything before or after it.
    """

SILENCE_TIMEOUT = 15
SILENCE_THRESHOLD = 600
PRE_BUFFER_SECONDS = 2
BATCH_CHUNKS = 4  # mic chunks (~80 ms each) merged into one upstream Gemini send

FORMAT   = pyaudio.paInt16
CHANNELS = 1
RATE     = 16000
CHUNK    = 1280

model_path = os.path.join(os.path.dirname(__file__), "bunny_work.onnx")
# wake_model = Model(wakeword_model_paths=[str(model_path)])  # ← fixed parameter name

# ── PyAudio is created once; streams are recreated each session ────────────────
# p = pyaudio.PyAudio()

def make_output_stream():
    return p.open(
        format=FORMAT, channels=CHANNELS, rate=24000,
        output=True, frames_per_buffer=CHUNK
    )

# Global stream references — recreated after every session
input_queue : multiprocessing.Queue = None
# output_stream = make_output_stream()

def flush_input_queue():
    while not input_queue.empty():
        try:
            input_queue.get_nowait()
        except Exception:
            break

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

    print("Listening for wake word 'bunny' or UI trigger...")

    # ── Flush stale audio left over from the previous session ─────────
    flush_input_queue()

    chunks_per_second = RATE // CHUNK
    pre_buffer = deque(maxlen=PRE_BUFFER_SECONDS * chunks_per_second)

    # Warm-up: the ONNX model was warmed once at process start;
    # reset its streaming state so every session starts clean.
    wake_model.reset()

    while True:
        try:
            audio_data = input_queue.get(timeout=5)
        except Exception:
            print("No audio from capture server — is it still running?")
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
            if score > 0.01: print(f"Wake word score: {score}")
            if score > 0.02:
                print(f"Wake word detected! ({word}: {score:.2f})")
                play_beep()
                # Discard the 10 chunks that contain the wake word itself
                for _ in range(10):
                    try:
                        input_queue.get(timeout=1)
                    except Exception:
                        break
                return list(pre_buffer)

def is_silent(audio_data: bytes) -> bool:
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    return np.abs(audio_np).mean() < SILENCE_THRESHOLD


def play_beep(frequency=880, duration=0.2, volume=0.5):
    num_samples = int(24000 * duration)   # output stream is 24kHz
    t    = np.linspace(0, duration, num_samples, False)
    wave = (np.sin(2 * np.pi * frequency * t) * volume * 32767).astype(np.int16)
    output_stream.write(wave.tobytes())

def handle_emotion_command(text: str) -> bool:
    """Write a [CMD:emotion=...] tag to the UI emotion file. Returns True if one was present."""
    pattern = r"\[CMD:emotion=(happy|sad|angry)\]"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return False
    emotion = match.group(1).lower()
    print(f"[EMOTION]: {emotion}")
    try:
        with open(EMOTION_STATE_PATH, "w") as f:
            json.dump({"emotion": emotion, "timestamp": time.time()}, f)
    except OSError as e:
        print(f"Failed to write emotion: {e}")
    return True


def extract_stop_command(text: str) -> bool:
    """True if text contains the silent [CMD:stop] tag."""
    if not text:
        return False
    return bool(re.search(r"\[\s*CMD\s*:\s*stop\s*\]", text, flags=re.IGNORECASE))


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


# Hardware calls (HTTP to devices, humidifier retry loop) can block for seconds.
# They must never run on the audio event loop — submit them here instead.
_DEVICE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="device-cmd")

# Suppress a repeated device command within this window (tag fallback + tool call
# deciding to fire for the same intent must not act twice).
_DEVICE_DEDUPE_S = 8
_device_last_run: dict = {}


def run_function_call(name: str, args: dict) -> str:
    """Execute a Gemini tool call on the device executor thread. Returns a status string."""
    try:
        if name == "set_fan":
            speed = int(args.get("speed", 0))
            print(f"[TOOL] set_fan speed={speed}")
            control_fan(max(0, min(2, speed)))
            return "ok"
        if name == "set_light":
            on = bool(args.get("on", True))
            if on:
                kwargs = {"brightness": int(args.get("brightness", 60))}
                color = args.get("color")
                if color:
                    kwargs["rgb"] = str(color).lstrip("#")
                print(f"[TOOL] set_light on {kwargs}")
                control_light(**kwargs)
            else:
                print("[TOOL] set_light off")
                control_light(rgb="000000", brightness=0)
            return "ok"
        if name == "set_humidifier":
            level = int(args.get("level", 1))
            print(f"[TOOL] set_humidifier level={level}")
            control_humidifier(1 if level else 0)
            return "ok"
        return f"unknown tool: {name}"
    except Exception as e:
        print(f"[TOOL] {name} failed: {e}")
        return f"error: {e}"


def _device_command_job(cmd_string: str):
    """Runs on a worker thread: parse + execute a device command, logging failures."""
    try:
        command = extract_device_command(cmd_string)
        if not command:
            return
        now = time.time()
        if now - _device_last_run.get(command, 0.0) < _DEVICE_DEDUPE_S:
            print(f"[DEVICE DEDUPE] suppressed repeat of {command} within {_DEVICE_DEDUPE_S}s")
            return
        _device_last_run[command] = now
        handle_device_command(cmd_string)
    except Exception as e:
        print(f"[DEVICE EXECUTOR] error: {e}")


def handle_device_command(cmd_string: str):
    command = extract_device_command(cmd_string)
    if not command:
        return
    device, action = command
    print(f"\n⚡ [HARDWARE COMMAND]: {device} → {action}\n")

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
        if action == "on":
            # print("Turning HUMIDIFIER ON")
            control_humidifier(1)
        else:
            # print("Turning HUMIDIFIER OFF")
            control_humidifier(0)


async def audio_input(session, stop_event: asyncio.Event, pre_buffer: list):
    last_audio_time = time.time()

    # Send pre-buffered audio so Gemini has context right away
    for chunk in pre_buffer:
        await session.send_realtime_input(
            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
        )

    try:
        while not stop_event.is_set():
            try:
                data = await asyncio.to_thread(input_queue.get, True, timeout=5)
            except Exception:
                print("Capture server unresponsive during session")
                continue

            # Don't send mic audio while bunny is speaking (echo prevention)
            if is_speaking.is_set():
                last_audio_time = time.time()
                continue

            if not data:
                continue

            # Batch: the blocking chunk plus whatever else is already queued —
            # one upstream round-trip per ~BATCH_CHUNKS chunks instead of one per chunk.
            batch = [data]
            for _ in range(BATCH_CHUNKS - 1):
                try:
                    batch.append(input_queue.get_nowait())
                except queue.Empty:
                    break

            if not is_silent(batch[-1]):
                last_audio_time = time.time()
            elif time.time() - last_audio_time > SILENCE_TIMEOUT:
                print("Silence timeout. Ending session...")
                stop_event.set()
                break

            await session.send_realtime_input(
                audio=types.Blob(data=b"".join(batch), mime_type="audio/pcm;rate=16000")
            )

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in audio_input: {e}")


def _tool_response(fn_call, payload: dict) -> types.FunctionResponse:
    """Build a FunctionResponse echoing the call's id (required by the Live API)."""
    kwargs: dict = {"name": fn_call.name, "response": payload}
    fn_id = getattr(fn_call, "id", None)
    if fn_id:
        kwargs["id"] = fn_id
    else:
        print(f"[FUNCTION CALL] warning: tool call '{fn_call.name}' had no id")
    return types.FunctionResponse(**kwargs)


async def audio_output(session, stop_event: asyncio.Event):
    accumulated_model_text=[]
    device_fx_fired = False  # at most one mid-stream device command per turn
    emotion_fx_fired = False  # at most one mid-stream emotion per turn

    def _collect_model_text(text: str):
        """Append a model text chunk and fire the device/emotion commands as
        soon as the full [CMD:...] tags are detectable in the joined text —
        the tags may be split across chunk boundaries."""
        nonlocal device_fx_fired, emotion_fx_fired
        accumulated_model_text.append(text)
        joined = " ".join(accumulated_model_text)
        if not device_fx_fired and extract_device_command(joined):
            device_fx_fired = True
            _DEVICE_EXECUTOR.submit(_device_command_job, joined)
            print("[DEVICE FX] fired mid-stream from transcription", flush=True)
        # Emotion is a tiny local JSON write — safe on the audio loop.
        if not emotion_fx_fired and handle_emotion_command(joined):
            emotion_fx_fired = True
            print("[EMOTION FX] fired mid-stream from transcription", flush=True)
        # [CMD:stop] tag (tag mode) — end the session immediately, runs in both modes.
        if extract_stop_command(joined):
            print("[STOP TAG] ending session", flush=True)
            is_speaking.clear()
            stop_event.set()

    try:
        while not stop_event.is_set():
            async for response in session.receive():
                if stop_event.is_set():
                    return  # exit immediately when session ends

                # Native function-call messages (server_content may be None here)
                tool_call = response.tool_call
                if tool_call and tool_call.function_calls:
                    pending_responses = []
                    should_stop = False
                    for fn_call in tool_call.function_calls:
                        fn_name = fn_call.name or ""
                        fn_args = dict(fn_call.args or {})
                        print(f"[FUNCTION CALL] {fn_name} {fn_args}", flush=True)
                        if fn_name == "stop_talking":
                            print("[STOP TOOL] ending session", flush=True)
                            should_stop = True
                            pending_responses.append(_tool_response(fn_call, {"stopped": True}))
                        else:
                            result = await asyncio.to_thread(run_function_call, fn_name, fn_args)
                            pending_responses.append(_tool_response(fn_call, {"status": result}))
                    if pending_responses:
                        try:
                            await session.send_tool_response(function_responses=pending_responses)
                        except Exception as e:
                            print(f"[FUNCTION CALL] failed to send response: {e}")
                    if should_stop:
                        is_speaking.clear()
                        stop_event.set()
                    continue

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
                    _collect_model_text(model_text)

                if server_content.model_turn is not None:
                    for part in server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                            is_speaking.set()
                            await asyncio.to_thread(output_stream.write, part.inline_data.data)
                        if part.text:
                            print(f"Text: {part.text!r}", flush=True)
                            _collect_model_text(part.text)

                if server_content.turn_complete:
                    is_speaking.clear()
                    print("Finished speaking.")
                    full_text = " ".join(accumulated_model_text)
                    accumulated_model_text.clear()
                    if full_text:
                        # Fallbacks: only run if the mid-stream scan didn't already fire.
                        if not device_fx_fired:
                            _DEVICE_EXECUTOR.submit(_device_command_job, full_text)
                        if not emotion_fx_fired:
                            handle_emotion_command(full_text)
                        if extract_stop_command(full_text) and not stop_event.is_set():
                            print("[STOP TAG] caught at turn end", flush=True)
                            is_speaking.clear()
                            stop_event.set()
                    device_fx_fired = False
                    emotion_fx_fired = False

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in audio_output: {e}")

DEVICE_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="set_fan",
            description="Set the speed of the desk fan.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "speed": types.Schema(
                        type=types.Type.INTEGER,
                        description="0 = off, 1 = low, 2 = fast",
                    ),
                },
                required=["speed"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_light",
            description="Control the desk light strip.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "on": types.Schema(type=types.Type.BOOLEAN, description="true to turn on, false to turn off"),
                    "brightness": types.Schema(type=types.Type.INTEGER, description="0-100, used when turning on"),
                    "color": types.Schema(type=types.Type.STRING, description='Optional hex color like "#ff8800"'),
                },
                required=["on"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_humidifier",
            description="Turn the desk humidifier on or off.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "level": types.Schema(type=types.Type.INTEGER, description="0 = off, 1 = on"),
                },
                required=["level"],
            ),
        ),
        types.FunctionDeclaration(
            name="stop_talking",
            description="Call this immediately when the user asks to stop, be quiet, shut up, or end the conversation. Never speak after calling it.",
        ),
    ]
)


def _build_live_config(system_instruction_text: str) -> types.LiveConnectConfig:
    """LiveConnectConfig with the persona instructions; adds the device tools when USE_TOOLS."""
    kwargs: dict = dict(
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
            parts=[types.Part.from_text(text=system_instruction_text)]
        ),
    )
    if USE_TOOLS:
        kwargs["tools"] = [DEVICE_TOOLS]
    return types.LiveConnectConfig(**kwargs)


ui_restart_requested = False

async def run_session(pre_buffer: list):
    global session_active
    session_active = True
    is_speaking.clear()

    device_instructions = TOOL_INSTRUCTIONS if USE_TOOLS else TAG_DEVICE_INSTRUCTIONS
    dynamic_instruction = bot_instruction + device_instructions
    json_path = os.path.join(os.path.dirname(__file__), os.pardir, "pdf_mode", "pdf_mode_status.json")

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

    config = _build_live_config(dynamic_instruction)

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

def shared_start(audio_queue):
    global input_queue, p, output_stream, wake_model
    input_queue = audio_queue
    p = pyaudio.PyAudio()
    output_stream = make_output_stream()
    wake_model = Model(wakeword_model_paths=[str(model_path)])
    # Warm up ONNX inference once per process (first predict() is JIT/lazy-slow).
    # Later sessions just reset() the state — see listen_for_wake_word_or_trigger.
    silent_chunk = np.zeros(CHUNK, dtype=np.int16)
    for _ in range(30):
        wake_model.predict(silent_chunk)
    try:
        asyncio.run(main())
    finally:
        output_stream.stop_stream()
        output_stream.close()
        p.terminate()