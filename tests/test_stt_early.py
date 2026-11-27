"""The early speech to text (app/stt_early.py), tested with the real voice detector,
real recordings, and a stand-in for Whisper so no network is needed."""

import asyncio
import wave
from pathlib import Path

from livekit import rtc
from livekit.agents import stt
from livekit.plugins import silero

from app.stt_early import EARLY_SILENCE, EarlySTT

AUDIO = Path(__file__).parent / "audio"
RATE = 22050  # our test recordings are 22.05 kHz mono


class FakeWhisper(stt.STT):
    """Remembers how much audio each request carried, and answers with a fixed text."""

    def __init__(self) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self.request_seconds: list[float] = []

    async def _recognize_impl(self, buffer, *, language=None, conn_options=None):
        self.request_seconds.append(buffer.duration)
        await asyncio.sleep(0.05)
        return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                               alternatives=[stt.SpeechData(language="en", text=f"request {len(self.request_seconds)}")])


def recording(name: str) -> bytes:
    with wave.open(str(AUDIO / name), "rb") as wav:
        return wav.readframes(wav.getnframes())


def silence(seconds: float) -> bytes:
    return b"\x00" * (int(RATE * seconds) * 2)


async def transcripts_for(audio: bytes, whisper=None, on_lost_turn=None) -> tuple[list[str], FakeWhisper]:
    """Play audio into the early speech to text at real speed; return the final transcripts."""
    whisper = whisper or FakeWhisper()
    early = EarlySTT(wrapped=whisper,
                     early_vad=silero.VAD.load(min_silence_duration=EARLY_SILENCE),
                     turn_vad=silero.VAD.load(min_silence_duration=0.45))
    if on_lost_turn:
        early.on_lost_turn = on_lost_turn
    stream = early.stream()
    finals: list[str] = []

    async def collect() -> None:
        async for event in stream:
            if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                finals.append(event.alternatives[0].text)

    collector = asyncio.create_task(collect())
    chunk = (RATE // 50) * 2  # 20 ms
    for start in range(0, len(audio), chunk):
        data = audio[start:start + chunk].ljust(chunk, b"\x00")
        stream.push_frame(rtc.AudioFrame(data, RATE, 1, chunk // 2))
        await asyncio.sleep(0.02)
    stream.end_input()
    await asyncio.wait_for(collector, 10)
    return finals, whisper


async def test_one_question_gives_one_transcript():
    finals, whisper = await transcripts_for(recording("sunday.wav") + silence(1.5))
    assert finals == ["request 1"]            # one transcript, from the request that was started early
    assert len(whisper.request_seconds) == 1  # and nothing was sent twice


async def test_a_pause_mid_sentence_still_gives_one_transcript_of_everything():
    # The recordings have about 0.25 s of quiet at their ends, so played back to back they
    # leave a pause long enough to start an early attempt but too short to end the turn.
    first, second = recording("sunday.wav"), recording("where.wav")
    finals, whisper = await transcripts_for(first + silence(0.05) + second + silence(1.5))
    assert len(finals) == 1                   # still exactly one transcript for the turn
    assert len(whisper.request_seconds) == 2  # the first attempt was thrown away
    assert finals == ["request 2"]
    # The transcript that was used came from a recording holding both halves...
    assert whisper.request_seconds[1] > whisper.request_seconds[0] + 0.5
    # ...and holding them once: no stretch of audio may be sent twice (a repeated stretch
    # would make Whisper hear a digit of a phone number twice).
    spoken = (len(first) + len(second)) / 2 / RATE
    assert whisper.request_seconds[1] <= spoken + 0.6  # the lead-in before the first word


async def test_two_separate_questions_give_two_transcripts():
    audio = recording("sunday.wav") + silence(1.5) + recording("where.wav") + silence(1.5)
    finals, whisper = await transcripts_for(audio)
    assert finals == ["request 1", "request 2"]


async def test_many_pauses_do_not_cause_many_requests():
    # Five short stretches of speech with brief pauses, like someone reading out a number.
    part = recording("sunday.wav")
    finals, whisper = await transcripts_for((part + silence(0.05)) * 5 + silence(1.5))
    assert len(finals) == 1
    assert len(whisper.request_seconds) <= 3  # two thrown away at most, then one for the whole turn
    assert whisper.request_seconds[-1] == max(whisper.request_seconds)  # the last one had everything


async def test_a_failed_transcription_loses_one_turn_but_not_the_call():
    class FailsOnce(FakeWhisper):
        async def _recognize_impl(self, buffer, *, language=None, conn_options=None):
            self.request_seconds.append(buffer.duration)
            if len(self.request_seconds) == 1:
                raise RuntimeError("speech to text is down")
            return await super()._recognize_impl(buffer, language=language, conn_options=conn_options)

    lost: list[Exception] = []
    audio = recording("sunday.wav") + silence(1.5) + recording("where.wav") + silence(1.5)
    finals, whisper = await transcripts_for(audio, FailsOnce(), on_lost_turn=lost.append)
    assert len(lost) == 1    # the first question was reported as lost...
    assert len(finals) == 1  # ...and the second was still heard
