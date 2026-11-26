"""A scripted caller: joins a real call, plays recorded questions, listens to the replies.

It behaves like the browser page (same kind of token, same agent dispatch), so it
tests the deployed agent end to end without a human.

Usage:
    uv run python scripts/fake_caller.py ask tests/audio/sunday.wav tests/audio/where.wav
    uv run python scripts/fake_caller.py interrupt tests/audio/colour.wav tests/audio/interrupt.wav
    uv run python scripts/fake_caller.py silence
    (add --business other-slug to call a different business)

Timings printed here are measured from outside, at the caller's end. They include
the 0.45 s the agent waits to be sure the caller has finished, plus network time.
The agent's own numbers (python -m app.manage call <id>) are the official latency.
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
AGENT_NAME = os.environ.get("AGENT_NAME", "receptionist")
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


class FakeCaller:
    def __init__(self, business: str) -> None:
        self.business = business
        self.room = rtc.Room()
        self.rate = 22050  # our test recordings are 22.05 kHz mono
        # A small send buffer, so "finished sending" really means the audio has left.
        self.source = rtc.AudioSource(self.rate, 1, queue_size_ms=60)
        self.to_play = b""
        self.last_loud = 0.0
        self.heard_speech = asyncio.Event()
        self.hung_up = asyncio.Event()

    async def connect(self) -> None:
        @self.room.on("track_subscribed")
        def on_track(track, publication, participant) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(self.listen(track))

        self.room.on("disconnected", lambda *args: self.hung_up.set())

        self.pressed_call = time.perf_counter()
        room_name = f"{self.business}-test-{uuid.uuid4().hex[:8]}"
        await self.room.connect(os.environ["LIVEKIT_URL"], make_token(self.business, room_name))
        track = rtc.LocalAudioTrack.create_audio_track("mic", self.source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        self.mic_task = asyncio.create_task(self.microphone())
        print(f"connected in {self.since(self.pressed_call):.2f}s, room {room_name}")

    @staticmethod
    def since(moment: float) -> float:
        return time.perf_counter() - moment

    async def listen(self, track: rtc.Track) -> None:
        """Note every moment the agent's audio is loud."""
        async for event in rtc.AudioStream(track):
            samples = np.frombuffer(event.frame.data, dtype=np.int16)
            if samples.size and np.abs(samples).mean() > LOUD:
                self.last_loud = time.perf_counter()
                self.heard_speech.set()

    async def microphone(self) -> None:
        """A microphone never stops: send the recording if there is one, silence otherwise."""
        chunk_bytes = (self.rate // 50) * 2  # 20 ms of 16-bit audio
        while True:
            data, self.to_play = self.to_play[:chunk_bytes], self.to_play[chunk_bytes:]
            data = data.ljust(chunk_bytes, b"\x00")
            await self.source.capture_frame(rtc.AudioFrame(data, self.rate, 1, chunk_bytes // 2))

    async def say(self, wav_path: str) -> float:
        """Play a recording into the call. Returns the moment the last of it was sent."""
        with wave.open(wav_path, "rb") as wav:
            self.to_play = wav.readframes(wav.getnframes())
        while self.to_play:
            await asyncio.sleep(0.01)
        return time.perf_counter()

    async def wait_for_agent_to_start(self, timeout: float = 20) -> float:
        self.heard_speech.clear()
        await asyncio.wait_for(self.heard_speech.wait(), timeout)
        return time.perf_counter()

    async def wait_for_agent_to_finish(self, quiet_seconds: float = 1.2) -> None:
        while self.since(self.last_loud) < quiet_seconds:
            await asyncio.sleep(0.05)

    async def hang_up(self) -> None:
        self.mic_task.cancel()
        await self.room.disconnect()


async def ask(caller: FakeCaller, wavs: list[str]) -> None:
    for wav_path in wavs:
        finished = await caller.say(wav_path)
        started = await caller.wait_for_agent_to_start()
        print(f"{os.path.basename(wav_path)}: reply heard {started - finished:.2f}s after the question ended")
        await caller.wait_for_agent_to_finish()


async def interrupt(caller: FakeCaller, question: str, interruption: str) -> None:
    await caller.say(question)
    await caller.wait_for_agent_to_start()
    await asyncio.sleep(1.0)  # let the agent get into its answer
    started_talking_over = time.perf_counter()
    asyncio.create_task(caller.say(interruption))
    await asyncio.sleep(0.2)
    await caller.wait_for_agent_to_finish(quiet_seconds=0.6)
    print(f"agent went quiet {caller.last_loud - started_talking_over:.2f}s after the caller started talking over it")


async def silence(caller: FakeCaller) -> None:
    quiet_since = time.perf_counter()
    while not caller.hung_up.is_set():
        try:
            await caller.wait_for_agent_to_start(timeout=1)
            print(f"agent spoke after {caller.since(quiet_since):.1f}s of caller silence")
            await caller.wait_for_agent_to_finish()
        except asyncio.TimeoutError:
            pass
        if caller.since(quiet_since) > 90:
            print("gave up waiting after 90 s"); return
    print(f"agent ended the call after {caller.since(quiet_since):.1f}s of caller silence")


async def main(args: list[str]) -> None:
    business = "sunrise-salon"
    if "--business" in args:
        business = args.pop(args.index("--business") + 1)
        args.remove("--business")
    mode, files = args[0], args[1:]

    caller = FakeCaller(business)
    await caller.connect()
    greeted = await caller.wait_for_agent_to_start(timeout=30)
    print(f"greeting heard {greeted - caller.pressed_call:.2f}s after pressing Call")
    await caller.wait_for_agent_to_finish()

    if mode == "ask":
        await ask(caller, files)
    elif mode == "interrupt":
        await interrupt(caller, files[0], files[1])
    elif mode == "silence":
        await silence(caller)
    await caller.hang_up()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
