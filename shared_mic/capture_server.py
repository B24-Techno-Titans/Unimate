"""Capture server for sharing microphone between voice agent and UI's quiz system."""
import json
import sys
import multiprocessing as mp
from pathlib import Path

import pyaudio

from alexa import voiceAgent2_shared as va2s

RATE = 16000
CHUNK_FRAMES = 1280
SAMPLE_WIDTH = 2
# Must match queue order in __main__: [q_voice, q_quiz]
VOICE_QUEUE_INDEX = 0
MIC_IN_USE_PATH = Path(__file__).resolve().parent / "mic_in_use.json"
SILENT_CHUNK = b"\x00" * (CHUNK_FRAMES * SAMPLE_WIDTH)


def is_ui_using_mic() -> bool:
    try:
        with MIC_IN_USE_PATH.open("r", encoding="utf-8") as f:
            return bool(json.load(f).get("is_ui_using", False))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def audio_server(queues):
    """Server process that accesses the microphone and keeps the queues filled."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK_FRAMES,
    )
    try:
        while True:
            data = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
            ui_using = is_ui_using_mic()
            for i, q in enumerate(queues):
                payload = SILENT_CHUNK if (i == VOICE_QUEUE_INDEX and ui_using) else data
                if not q.full():
                    q.put(payload)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def start_ui(audio_queue):
    """UIUX_FC2 starter function to avoide flickering"""
    with open("/home/unimate/Unimate/shared_mic/ui_log", "a", encoding="utf-8", buffering=1) as log:  # Logging
        sys.stdout = log
        sys.stderr = log

        from UIUX_FC2 import main as ui_main
        ui_main.shared_start(audio_queue)


if __name__ == "__main__":
    q_voice = mp.Queue(maxsize=50)
    q_quiz = mp.Queue(maxsize=50)

    server = mp.Process(target=audio_server, args=([q_voice, q_quiz],))
    voice_worker = mp.Process(target=va2s.shared_start, args=(q_voice,))
    ui_worker = mp.Process(target=start_ui, args=(q_quiz,))

    processes = [server, voice_worker, ui_worker]

    for proc in processes:
        proc.start()

    try:
        server.join()
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Stopping processes...")
    finally:
        for proc in processes:
            if proc.is_alive():
                proc.terminate()
        for proc in processes:
            proc.join(timeout=3)
            if proc.is_alive():
                print(f"Force killing {proc.name}...")
                proc.kill()
        print("All processes stopped.")
        sys.exit(0)
