"""Text-to-speech bake-off: how fast does each engine return the first audio?

Sends the same short sentence to a TTS server from N callers at once and
measures, per request, the time to the first audio byte and the total time.

Usage (on the machine that runs the TTS servers):
    python tts_bakeoff.py kokoro http://127.0.0.1:8880 short
    python tts_bakeoff.py piper  http://127.0.0.1:5000 long

Uses only the Python standard library.
"""

import json
import statistics
import sys
import threading
import time
import urllib.request

# Two realistic chunks of a receptionist reply. The agent sends text to the
# TTS one sentence at a time, so the short one is what decides reply latency.
SENTENCES = {
    "short": "Sure, I can help with that.",
    "long": "Sure, I can help with that. Rahul Shetty does hair colour on Tuesday, Thursday and Saturday.",
}
SENTENCE = SENTENCES["short"]
PARALLEL_LEVELS = [1, 3, 5, 8]
ROUNDS = 4  # each level is repeated this many times


def build_request(engine: str, base_url: str) -> urllib.request.Request:
    if engine == "kokoro":
        url = base_url + "/v1/audio/speech"
        body = {"model": "kokoro", "voice": "af_heart", "input": SENTENCE,
                "response_format": "pcm", "stream": True}
    else:  # piper's built-in HTTP server
        url = base_url + "/synthesize"
        body = {"text": SENTENCE}
    return urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})


def one_request(engine: str, base_url: str, results: list) -> None:
    start = time.perf_counter()
    with urllib.request.urlopen(build_request(engine, base_url), timeout=120) as response:
        response.read(1)  # blocks until the first audio byte arrives
        first_byte = time.perf_counter() - start
        response.read()
    results.append((first_byte, time.perf_counter() - start))


def run_level(engine: str, base_url: str, parallel: int) -> list:
    results: list = []
    for _ in range(ROUNDS):
        threads = [threading.Thread(target=one_request, args=(engine, base_url, results))
                   for _ in range(parallel)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return results


def main() -> None:
    global SENTENCE
    engine, base_url = sys.argv[1], sys.argv[2].rstrip("/")
    SENTENCE = SENTENCES[sys.argv[3] if len(sys.argv) > 3 else "short"]
    run_level(engine, base_url, 1)  # warm-up, not counted
    print(f"engine={engine} sentence_chars={len(SENTENCE)} rounds={ROUNDS}")
    print("parallel | first audio median | first audio worst | total median")
    for parallel in PARALLEL_LEVELS:
        results = run_level(engine, base_url, parallel)
        first = [r[0] for r in results]
        total = [r[1] for r in results]
        print(f"{parallel:8d} | {statistics.median(first):17.3f}s | {max(first):16.3f}s | "
              f"{statistics.median(total):11.3f}s")


if __name__ == "__main__":
    main()
