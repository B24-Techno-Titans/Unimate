"""Ask From Bunny UI wrapper backed by the OpenAI voice flow."""

from __future__ import annotations

import os
import logging
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI
import speech_recognition as sr

from raspi_bridge import apply_led_state, set_fan, set_humidifier  # noqa: E402

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path, override=True)

for _logger_name in ("openai", "httpx", "httpcore"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

PIPER_EXE = "/home/unimate/unimate_tts/piper/piper"
VOICE_MODEL = "/home/unimate/unimate_tts/en_US-hfc_female-medium.onnx"
AUDIO_OUTPUT = "default"

_DEFAULT_LED_COLOR = (1.0, 0.0, 1.0)
_DEFAULT_LED_BRIGHTNESS = 150 / 255.0

WAKE_WORD = "wake up"

# Tweak these values to tune listening, AI response length, and UI caption sync.
MIC_INDEX: int | None = None
RECOGNIZER_PAUSE_THRESHOLD_S = 1.5
WAKE_WORD_PHRASE_TIME_LIMIT_S = 3
COMMAND_LISTEN_TIMEOUT_S = 3.0
COMMAND_PHRASE_TIME_LIMIT_S = 8
COMMAND_AMBIENT_CALIBRATION_S = 0.5
RECOGNIZER_NON_SPEAKING_DURATION_S = 0.5
RECOGNIZER_PHRASE_THRESHOLD = 0.25
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.7
OPENAI_HISTORY_REQUESTS = 1
MIN_AUDIO_DURATION_S = 0.01
PLAYBACK_STOP_TIMEOUT_S = 0.5
CAPTION_WORD_WIDTH = 10
CAPTION_AUDIO_LAG_S = 0.4

PERSONALITY_PROMPT = (
    "You are UniMate, a friendly human like assistant. "
    "Be humanly like you talking to a teenager. "
    "Keep answers short and clear. "
    "Do not use emojis or any symbols or * . "
    "no Bold text or italic text or underline text or any other formatting. "
    "Only respond in plain English letters and numbers. "
    "Do not introduce yourself unless asked."
)
conversation: list[dict[str, str]] = [{"role": "system", "content": PERSONALITY_PROMPT}]
client: OpenAI | None = None

recognizer = sr.Recognizer()
recognizer.pause_threshold = RECOGNIZER_PAUSE_THRESHOLD_S
recognizer.non_speaking_duration = RECOGNIZER_NON_SPEAKING_DURATION_S
recognizer.phrase_threshold = RECOGNIZER_PHRASE_THRESHOLD
recognizer.dynamic_energy_threshold = True
mic_index = MIC_INDEX


@contextmanager
def _suppress_native_audio_stderr():
    """Hide ALSA/JACK diagnostics emitted by PortAudio before Python can filter them."""
    old_stderr_fd = os.dup(2)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(old_stderr_fd)


@contextmanager
def _quiet_microphone(device_index: int | None = None):
    microphone: sr.Microphone | None = None
    source = None
    exc_info: tuple[type[BaseException] | None, BaseException | None, TracebackType | None] = (
        None,
        None,
        None,
    )
    try:
        with _suppress_native_audio_stderr():
            microphone = sr.Microphone(device_index=device_index)
            source = microphone.__enter__()
        yield source
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        if microphone is not None:
            with _suppress_native_audio_stderr():
                microphone.__exit__(*exc_info)


def _openai_client() -> OpenAI:
    global client
    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return client


def speak(text: str) -> None:
    clean_text = text.replace('"', "").replace("'", "")
    command = (
        f'echo "{clean_text}" | '
        f"{PIPER_EXE} --model {VOICE_MODEL} --output_raw | "
        f"aplay -r 22050 -f S16_LE -t raw -D {AUDIO_OUTPUT}"
    )
    subprocess.run(command, shell=True)


def listen_for_wake_word() -> None:
    with _quiet_microphone(device_index=mic_index) as source:
        recognizer.adjust_for_ambient_noise(source)
        print("Say 'Bunny' to start...")

        while True:
            try:
                audio = recognizer.listen(source, phrase_time_limit=WAKE_WORD_PHRASE_TIME_LIMIT_S)
                text = recognizer.recognize_google(audio).lower()

                if WAKE_WORD in text:
                    print("Wake word detected")
                    speak("Yes?")
                    return

            except sr.UnknownValueError:
                pass
            except sr.RequestError as exc:
                print("Speech API error:", exc)


def listen_for_command(cancel_event: threading.Event | None = None) -> str:
    if cancel_event is not None and cancel_event.is_set():
        return ""

    with _quiet_microphone(device_index=mic_index) as source:
        recognizer.adjust_for_ambient_noise(source, duration=COMMAND_AMBIENT_CALIBRATION_S)
        print("Listening...")
        while cancel_event is None or not cancel_event.is_set():
            try:
                audio = recognizer.listen(
                    source,
                    timeout=COMMAND_LISTEN_TIMEOUT_S,
                    phrase_time_limit=COMMAND_PHRASE_TIME_LIMIT_S,
                )
            except sr.WaitTimeoutError:
                continue

            if cancel_event is not None and cancel_event.is_set():
                return ""

            try:
                text = recognizer.recognize_google(audio).lower()
                print("Heard:", text)
                return text
            except sr.UnknownValueError:
                print("Could not understand speech; still listening...")
                continue
            except sr.RequestError as exc:
                print("Speech API error:", exc)
                return ""

    return ""


def handle_command(text: str) -> None:
    if "led" in text or "light" in text:
        if "on" in text:
            apply_led_state(
                led_on=True,
                led_brightness=_DEFAULT_LED_BRIGHTNESS,
                led_color=_DEFAULT_LED_COLOR,
            )
            return
        if "off" in text:
            apply_led_state(
                led_on=False,
                led_brightness=_DEFAULT_LED_BRIGHTNESS,
                led_color=_DEFAULT_LED_COLOR,
            )
            return

    if "fan" in text:
        if "on" in text:
            set_fan(2)
        elif "off" in text:
            set_fan(0)
        return

    if "humidifier" in text:
        if "on" in text:
            set_humidifier(1)
        elif "off" in text:
            set_humidifier(0)
        elif "blink" in text:
            set_humidifier(2)
        return


def should_answer_with_ai(text: str) -> bool:
    if "how" in text:
        return True
    if ("on" in text or "off" in text) and (
        "led" in text or "light" in text or "fan" in text or "humidifier" in text
    ):
        return False
    return True


def _trim_conversation_history() -> None:
    """Keep only the system prompt and the last configured request/answer pair."""
    global conversation
    history_messages = max(0, OPENAI_HISTORY_REQUESTS) * 2
    if history_messages == 0:
        conversation = [conversation[0]]
        return
    conversation = [conversation[0], *conversation[1:][-history_messages:]]


def get_openai_response(command: str) -> str:
    global conversation

    try:
        print("Fetching response...")
        _trim_conversation_history()
        conversation.append({"role": "user", "content": command})

        response = _openai_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=conversation,
            temperature=OPENAI_TEMPERATURE,
        )

        reply = response.choices[0].message.content.strip()
        if not reply:
            raise RuntimeError("Empty response from OpenAI")

        conversation.append({"role": "assistant", "content": reply})
        _trim_conversation_history()
        print("UniMate:", reply)
        return reply
    except Exception as exc:
        if conversation and conversation[-1] == {"role": "user", "content": command}:
            conversation.pop()
        print("OpenAI error:", exc)
        raise


def ask_openai(command: str) -> None:
    try:
        speak(get_openai_response(command))
    except Exception:
        pass


def speak_with_duration(text: str) -> tuple[float, subprocess.Popen | None, str | None]:
    """Non-blocking Piper playback; returns duration for UI sync."""
    clean = text.replace('"', "").replace("'", "")
    if not clean:
        return 0.0, None, None

    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        piper = subprocess.run(
            [PIPER_EXE, "--model", VOICE_MODEL, "--output_file", wav_path],
            input=clean.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if piper.returncode != 0:
            raise RuntimeError("Piper TTS failed")

        with wave.open(wav_path, "rb") as wf:
            duration = wf.getnframes() / float(wf.getframerate())

        proc = subprocess.Popen(
            ["aplay", "-q", "-D", AUDIO_OUTPUT, wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return max(duration, MIN_AUDIO_DURATION_S), proc, wav_path
    except Exception:
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        raise


def stop_playback(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=PLAYBACK_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()


def cleanup_wav(wav_path: str | None) -> None:
    if not wav_path:
        return
    try:
        os.unlink(wav_path)
    except OSError:
        pass


def words_window(words: list[str], index: int, width: int = CAPTION_WORD_WIDTH) -> str:
    if not words:
        return ""
    index = max(0, min(index, len(words) - 1))
    start = max(0, index - width + 1)
    return " ".join(words[start : index + 1])


def caption_target_index(
    elapsed: float,
    duration: float,
    n_words: int,
    lag_s: float = CAPTION_AUDIO_LAG_S,
) -> int:
    if n_words <= 0 or duration <= 0:
        return -1
    if elapsed < lag_s:
        return -1
    effective = elapsed - lag_s
    caption_duration = max(MIN_AUDIO_DURATION_S, duration - lag_s)
    progress = min(1.0, effective / caption_duration)
    return min(n_words - 1, int(progress * n_words))


def format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


@dataclass
class AskBunnyHandlers:
    on_empty_stt: Callable[[], None]
    on_stt_complete: Callable[[str, bool], None]
    on_device_handled: Callable[[], None]
    on_answer_ready: Callable[[str, list[str]], None]
    on_speech_start: Callable[[float, list[str], subprocess.Popen | None, str | None], None]
    on_error: Callable[[str], None]
    on_finished: Callable[[], None]


def run_ask_bunny_session(
    run_on_main: Callable[[Callable[[], None]], None],
    cancel_event: threading.Event,
    handlers: AskBunnyHandlers,
) -> threading.Thread:
    def _work() -> None:
        try:
            if cancel_event.is_set():
                return

            command = listen_for_command(cancel_event)
            if cancel_event.is_set():
                return

            if not command.strip():
                run_on_main(handlers.on_empty_stt)
                run_on_main(handlers.on_finished)
                return

            use_openai = should_answer_with_ai(command)

            def _stt_done() -> None:
                handlers.on_stt_complete(command, use_openai)

            run_on_main(_stt_done)
            if cancel_event.is_set():
                return

            if not use_openai:
                handle_command(command)

                def _device() -> None:
                    handlers.on_device_handled()
                    handlers.on_finished()

                run_on_main(_device)
                return

            try:
                answer = get_openai_response(command)
            except Exception as exc:
                msg = str(exc) if str(exc) else "OpenAI request failed"

                def _err() -> None:
                    handlers.on_error(msg)

                run_on_main(_err)
                return

            if cancel_event.is_set():
                return

            words = answer.split()

            def _answer() -> None:
                handlers.on_answer_ready(answer, words)

            run_on_main(_answer)
            if cancel_event.is_set():
                return

            try:
                duration, proc, wav_path = speak_with_duration(answer)
            except Exception as exc:
                msg = str(exc) or "Speech playback failed"

                def _err() -> None:
                    handlers.on_error(msg)

                run_on_main(_err)
                return

            if cancel_event.is_set():
                stop_playback(proc)
                cleanup_wav(wav_path)
                return

            def _speech() -> None:
                handlers.on_speech_start(duration, words, proc, wav_path)

            run_on_main(_speech)

            if proc is not None:
                proc.wait()
            cleanup_wav(wav_path)

            if not cancel_event.is_set():

                def _done() -> None:
                    handlers.on_finished()

                run_on_main(_done)
        except Exception as exc:
            msg = str(exc) or "Ask Bunny session failed"

            def _err() -> None:
                handlers.on_error(msg)

            run_on_main(_err)

    thread = threading.Thread(target=_work, daemon=True)
    thread.start()
    return thread
