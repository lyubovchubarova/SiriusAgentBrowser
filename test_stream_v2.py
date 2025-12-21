import json
import threading
import time

import requests


def listen_to_stream() -> None:
    url = "http://127.0.0.1:8000/stream"
    print(f"Connecting to {url}...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            print("Connected to stream. Listening for events...")
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    # print(f"RAW STREAM: {decoded_line}")
                    if decoded_line.startswith("data: "):
                        json_str = decoded_line[6:]
                        try:
                            event = json.loads(json_str)
                            print(f"Stream Event: {event}")
                        except json.JSONDecodeError:
                            print(f"Stream Raw (Not JSON): {decoded_line}")
    except Exception as e:
        print(f"Stream Error: {e}")


def send_chat_request() -> None:
    time.sleep(2)  # Wait for stream to connect
    url = "http://127.0.0.1:8000/chat"
    data = {"query": "Hello", "chat_history": []}
    print(f"Sending chat request to {url}...")
    try:
        resp = requests.post(url, json=data)
        print(f"Chat Response: {resp.json()}")
    except Exception as e:
        print(f"Chat Error: {e}")


if __name__ == "__main__":
    # Start stream listener in background
    t = threading.Thread(target=listen_to_stream)
    t.daemon = True
    t.start()

    # Send chat request
    send_chat_request()

    # Keep main thread alive for a bit to see stream events
    print("Waiting for events...")
    time.sleep(10)
    print("Done.")
