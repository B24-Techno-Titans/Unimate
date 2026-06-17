import sys
import pyaudio
import multiprocessing as mp

from alexa import voiceAgent2_shared as va2s

def audio_server(queues):
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

# def consumer_a(queue):
#     print("Consumer A started")
#     while True:
#         data = queue.get()
#         # do something — e.g. keyword detection, volume meter, etc.
#         print(f"A got {len(data)} bytes")

def consumer_b(queue):
    print("Consumer B started")
    while True:
        data = queue.get()
        # print(f"B got {len(data)} bytes")
        pass

if __name__ == "__main__":
    q1 = mp.Queue(maxsize=50)
    q2 = mp.Queue(maxsize=50)

    server  = mp.Process(target=audio_server, args=([q1, q2],))
    worker_a = mp.Process(target=va2s.shared_start, args=(q1,))
    worker_b = mp.Process(target=consumer_b, args=(q2,))

    processes = [server, worker_a, worker_b]

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