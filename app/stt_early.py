"""Speech to text that starts early, so the reply is not kept waiting for it.

The problem this solves
    We wait END_OF_SPEECH_SILENCE (0.45 s) of quiet before deciding the caller has
    finished. Whisper is not a streaming model: it needs the whole recording. If we only
    send the recording once the 0.45 s is over, the caller waits 0.45 s AND then the
    0.25 s Whisper takes. Those two waits can overlap.

What this does
    A second, quicker voice detector notices after EARLY_SILENCE (0.2 s) of quiet that the
    caller has *probably* finished, and we send the recording to Whisper straight away.
    - If the caller stays quiet, the text is ready at about the moment the 0.45 s is over.
    - If the caller carries on talking, we throw that attempt away and send the longer
      recording at the next pause.
    Either way the framework gets exactly one transcript per caller turn, made from the
    whole turn. Deciding when the caller has finished still takes the full 0.45 s.

The cost: a caller who pauses mid-sentence causes one extra Whisper request. Someone
reading out a phone number digit by digit could cause many, and the free tier allows only
20 requests a minute, so after MAX_WASTED thrown-away attempts in one turn we stop guessing
and simply wait for the end of that turn, as before.
"""

import asyncio
import logging
import time

from livekit.agents import stt, utils, vad
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions

log = logging.getLogger("receptionist")

# Quiet time after which we start transcribing, as a guess that the caller has finished.
EARLY_SILENCE = 0.2
# Early attempts we allow ourselves to throw away in one caller turn.
MAX_WASTED = 2
# Audio kept from just before the caller starts, so the first word is not clipped.
LEAD_IN = 0.5


class EarlySTT(stt.STT):
    def __init__(self, *, wrapped: stt.STT, early_vad: vad.VAD, turn_vad: vad.VAD) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=False))
        self.wrapped = wrapped      # the real speech to text (Whisper on Groq)
        self.early_vad = early_vad  # reports the end of speech after EARLY_SILENCE
        self.turn_vad = turn_vad    # reports it after the full END_OF_SPEECH_SILENCE
        # Called with the error when a caller turn could not be turned into text at all
        # (speech to text failed even after its own retries). The call itself carries on.
        self.on_lost_turn = lambda error: None

    @property
    def model(self) -> str:
        return self.wrapped.model

    @property
    def provider(self) -> str:
        return self.wrapped.provider

    async def _recognize_impl(self, buffer, *, language=NOT_GIVEN, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return await self.wrapped.recognize(buffer=buffer, language=language, conn_options=conn_options)

    def stream(self, *, language=NOT_GIVEN, conn_options=DEFAULT_API_CONNECT_OPTIONS) -> "EarlyStream":
        return EarlyStream(self, language, conn_options)


class EarlyStream(stt.RecognizeStream):
    """The audio of one call goes in; one transcript per caller turn comes out."""

    def __init__(self, owner: EarlySTT, language, conn_options: APIConnectOptions) -> None:
        # The wrapped speech to text already retries by itself, so this stream does not.
        super().__init__(stt=owner, conn_options=APIConnectOptions(max_retry=0, timeout=conn_options.timeout))
        self.owner = owner
        self.language = language
        self.wrapped_options = conn_options

    async def _metrics_monitor_task(self, events) -> None:
        async for _ in events:  # the wrapped speech to text reports its own timings
            pass

    def transcribe(self, frames: list) -> asyncio.Task:
        task = asyncio.create_task(self.owner.wrapped.recognize(
            buffer=utils.merge_frames(frames), language=self.language, conn_options=self.wrapped_options))
        # An attempt we throw away must not complain later that nobody read its result.
        task.add_done_callback(lambda done: done.cancelled() or done.exception())
        return task

    async def _run(self) -> None:
        early = self.owner.early_vad.stream()
        turn = self.owner.turn_vad.stream()
        recording: list = []               # this turn's audio so far, as one continuous recording
        in_turn = False                    # has the caller started speaking in this turn?
        guess: asyncio.Task | None = None  # the transcription we started early
        wasted = 0                         # early attempts thrown away in this turn

        async def feed_both_detectors() -> None:
            async for frame in self._input_ch:
                if isinstance(frame, self._FlushSentinel):
                    early.flush()
                    turn.flush()
                    continue
                early.push_frame(frame)
                turn.push_frame(frame)
                recording.append(frame)
                # Between turns, keep only the last LEAD_IN seconds.
                while not in_turn and sum(f.duration for f in recording) > LEAD_IN:
                    recording.pop(0)
            early.end_input()
            turn.end_input()

        async def start_early() -> None:
            nonlocal guess, wasted, in_turn
            async for event in early:
                if event.type == vad.VADEventType.START_OF_SPEECH:
                    in_turn = True
                    if guess is not None:
                        guess.cancel()  # the caller carried on talking: that attempt is out of date
                        guess = None
                        wasted += 1
                elif event.type == vad.VADEventType.END_OF_SPEECH and wasted < MAX_WASTED:
                    guess = self.transcribe(list(recording))

        async def finish_turn() -> None:
            nonlocal guess, wasted, in_turn
            async for event in turn:
                if event.type == vad.VADEventType.START_OF_SPEECH:
                    in_turn = True  # normally set already by the quicker detector
                    self._event_ch.send_nowait(stt.SpeechEvent(stt.SpeechEventType.START_OF_SPEECH))
                elif event.type == vad.VADEventType.END_OF_SPEECH:
                    ended_at = time.time() - event.silence_duration - event.inference_duration
                    self._event_ch.send_nowait(stt.SpeechEvent(
                        type=stt.SpeechEventType.END_OF_SPEECH, speech_end_time=ended_at))
                    # The caller has finished. Take the early transcription (normally ready
                    # by now). If there is none, transcribe the whole turn now.
                    task = guess or self.transcribe(list(recording) or event.frames)
                    guess, wasted, in_turn = None, 0, False
                    recording.clear()
                    try:
                        result = await task
                    except Exception as error:
                        # Speech to text failed (it has already retried). Losing one turn
                        # must not end the call: report it and keep listening.
                        log.warning("speech to text failed for one caller turn: %s", error)
                        self.owner.on_lost_turn(error)
                        continue
                    if result.alternatives and result.alternatives[0].text:
                        self._event_ch.send_nowait(stt.SpeechEvent(
                            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                            alternatives=[result.alternatives[0]], speech_end_time=ended_at))

        tasks = [asyncio.create_task(feed_both_detectors()),
                 asyncio.create_task(start_early()),
                 asyncio.create_task(finish_turn())]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)
            if guess is not None:
                guess.cancel()
            await early.aclose()
            await turn.aclose()
