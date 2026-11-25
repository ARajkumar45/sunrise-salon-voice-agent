"""A scripted caller: joins a real call, plays a recorded question, listens for the reply.

It behaves like the browser page (same token, same agent dispatch) so it tests
the deployed agent end to end without a human.

Usage:
    uv run python scripts/fake_caller.py question.wav [business-slug]

Prints how long the agent took to join and greet, and how long after the
question ended the reply audio started. Note: this outside-in number includes
the ~0.55 s of silence the agent waits for before deciding the caller has
finished, so it is always larger than the agent's own latency metric.
"""

import asyncio
import json
import os
import sys
import time
import uuid
import wave

import numpy as np
from dotenv import load_dotenv
from livekit import api, rtc

load_dotenv()
AGENT_NAME = "receptionist"
LOUD = 500  # audio level above which we count the agent as speaking


def make_token(business: str, room_name: str) -> str:
    return (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(f"fake-caller-{uuid.uuid4().hex[:6]}")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .with_room_config(api.RoomConfiguration(agents=[
            api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=json.dumps({"business": business}))]))
        .to_jwt()
    )


class Listener:
    """Tracks when the agent's audio is loud (speaking) or quiet."""

    def __init__(self) -> None:
        self.last_loud = 0.0
        self.speech_started = asyncio.Event()

    async def listen(self, track: rtc.Track) -> None:
        async for event in rtc.AudioStream(track):
            samples = np.frombuffer(event.frame.data, dtype=np.int16)
            if samples.size and np.abs(samples).mean() > LOUD:
                self.last_loud = time.perf_counter()
                self.speech_started.set()

    async def wait_for_speech(self, timeout: float) -> float:
        self.speech_started.clear()
        await asyncio.wait_for(self.speech_started.wait(), timeout)
        return time.perf_counter()

    async def wait_for_quiet(self, quiet_seconds: float = 1.2) -> None:
        while time.perf_counter() - self.last_loud < quiet_seconds:
            await asyncio.sleep(0.05)


async def microphone_loop(source: rtc.AudioSource, rate: int, to_play: asyncio.Queue) -> None:
    """A microphone never stops: send the recording when there is one, silence otherwise.

    The agent needs to hear the silence after a question to know the caller has finished.
    """
    chunk = rate // 50  # 20 ms
    silence = b"\x00\x00" * chunk
    pending = b""
    while True:
        if not pending and not to_play.empty():
            pending = to_play.get_nowait()
        data, pending = (pending[: chunk * 2], pending[chunk * 2:]) if pending else (silence, b"")
        data = data.ljust(chunk * 2, b"\x00")
        await source.capture_frame(rtc.AudioFrame(data, rate, 1, chunk))
        if not pending and data is not silence:
            to_play.task_done()


async def main(wav_path: str, business: str) -> None:
    room, listener = rtc.Room(), Listener()

    @room.on("track_subscribed")
    def on_track(track, publication, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(listener.listen(track))

    with wave.open(wav_path, "rb") as wav:
        rate, question = wav.getframerate(), wav.readframes(wav.getnframes())
    source = rtc.AudioSource(rate, 1)
    to_play: asyncio.Queue = asyncio.Queue()
    microphone = rtc.LocalAudioTrack.create_audio_track("mic", source)

    pressed_call = time.perf_counter()
    room_name = f"{business}-test-{uuid.uuid4().hex[:8]}"
    await room.connect(os.environ["LIVEKIT_URL"], make_token(business, room_name))
    print(f"connected in {time.perf_counter() - pressed_call:.2f}s")
    await room.local_participant.publish_track(
        microphone, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    mic_task = asyncio.create_task(microphone_loop(source, rate, to_play))

    greeted = await listener.wait_for_speech(timeout=30)
    print(f"agent's greeting audio started {greeted - pressed_call:.2f}s after pressing Call")
    await listener.wait_for_quiet()

    to_play.put_nowait(question)
    await to_play.join()  # returns when the last 20 ms of the question has been sent
    question_ended = time.perf_counter()
    replied = await listener.wait_for_speech(timeout=20)
    print(f"reply audio started {replied - question_ended:.2f}s after the question ended")
    await listener.wait_for_quiet()
    mic_task.cancel()
    await room.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "sunrise-salon"))
