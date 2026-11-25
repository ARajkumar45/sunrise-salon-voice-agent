"""Spike: read Groq's real free-tier limits and speed for the models we use.

Makes one tiny request per model and prints the rate-limit headers Groq sends
back, plus how long the first token took. Never prints the API key.

Usage: uv run python scripts/groq_limits.py [path/to/short.wav]
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["GROQ_API_KEY"]
BASE = "https://api.groq.com/openai/v1"
CHAT_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
STT_MODEL = "whisper-large-v3-turbo"


def show_limits(headers) -> None:
    for name, value in sorted(headers.items()):
        if name.lower().startswith("x-ratelimit") or name.lower() == "retry-after":
            print(f"    {name}: {value}")


def chat(model: str) -> None:
    body = {"model": model, "stream": True, "max_tokens": 30,
            "messages": [{"role": "user", "content": "Say hello in five words."}]}
    request = urllib.request.Request(
        BASE + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "User-Agent": "limits-spike"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.readline()  # first streamed chunk
            print(f"{model}: HTTP {response.status}, first chunk after {time.perf_counter() - start:.3f}s")
            show_limits(response.headers)
            response.read()
    except urllib.error.HTTPError as error:
        print(f"{model}: HTTP {error.code} {error.read()[:200].decode(errors='replace')}")
        show_limits(error.headers)


def transcribe(wav_path: str) -> None:
    boundary = "----spike"
    audio = open(wav_path, "rb").read()
    parts = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{STT_MODEL}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nen\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        BASE + "/audio/transcriptions", data=parts,
        headers={"Authorization": f"Bearer {KEY}", "User-Agent": "limits-spike",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    for attempt in range(3):
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=30) as response:
            text = json.loads(response.read())["text"]
            print(f"{STT_MODEL}: {time.perf_counter() - start:.3f}s -> {text!r}")
            if attempt == 0:
                show_limits(response.headers)


if __name__ == "__main__":
    for model in CHAT_MODELS:
        chat(model)
    if len(sys.argv) > 1:
        transcribe(sys.argv[1])
