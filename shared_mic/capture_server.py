"""Capture server for sharing microphone between voice agent and UI's quiz system."""
import sys
import multiprocessing as mp
import pyaudio

from alexa import voiceAgent2_shared as va2s

def audio_server(queues):
    """Server process that accesses the microphone and keeps the queues filled."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=1280,
    )
    try:
        while True:
            data = stream.read(1280, exception_on_overflow=False)
            for q in queues:
                if not q.full():
                    q.put(data)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

def start_ui(audio_queue):
    """UIUX_FC2 starter function to avoide flickering"""
    with open("./ui_log", "a", encoding="utf-8", buffering=1) as log: # Logging
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
