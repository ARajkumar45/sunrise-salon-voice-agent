"""Text to speech with Piper (open source), running as its own small HTTP service.

LiveKit Agents has no official Piper plugin, so this file is the adapter.
It does one thing: send a sentence to the Piper server and hand the audio
that comes back to the framework.

The framework splits the LLM's reply into sentences and calls `synthesize`
once per sentence, so the first sentence starts playing while the LLM is
still writing the rest.

Piper returns no audio until it has finished a whole piece of text, and it needs about
0.045 s for every second of speech. A long sentence (a booking read-back is 9 s of speech)
would therefore start 0.4 s late. So a long sentence is cut once, after its first clause:
the first clause is ready in under 0.1 s and the rest is made while it plays.
"""

import asyncio
import io
import os
import re
import uuid
import wave

import aiohttp
from livekit.agents import APIConnectionError, APIConnectOptions, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

# The Piper voice we ship (en_US-lessac-medium) produces 22.05 kHz mono audio.
PIPER_SAMPLE_RATE = 22050


LONG_SENTENCE = 60  # characters; shorter sentences are spoken in one piece


def first_clause_and_rest(sentence: str) -> list[str]:
    """Cut a long sentence after its first comma, colon or semicolon: [first clause, rest].

    The first clause must be at least 15 characters and the rest at least 20, so neither
    piece is a stray word. "1,500" is never cut: the mark must be followed by a space.
    """
    if len(sentence) >= LONG_SENTENCE:
        mark = re.search(r"[,:;] ", sentence[15:])
        if mark:
            cut = 15 + mark.end()
            if len(sentence) - cut >= 20:
                return [sentence[:cut].strip(), sentence[cut:].strip()]
    return [sentence]


class PiperTTS(tts.TTS):
    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=PIPER_SAMPLE_RATE,
            num_channels=1,
        )
        self.base_url = (base_url or os.environ.get("PIPER_URL", "http://tts:5000")).rstrip("/")
        self._http: aiohttp.ClientSession | None = None

    def http(self) -> aiohttp.ClientSession:
        """One HTTP session per call process, reused so each sentence skips the TCP handshake."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "PiperStream":
        return PiperStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.close()


class PiperStream(tts.ChunkedStream):
    """One sentence in, its audio out."""

    async def speak(self, text: str) -> bytes:
        """Ask Piper for one piece of text. Returns the sound itself, without the WAV header."""
        piper: PiperTTS = self._tts  # type: ignore[assignment]
        async with piper.http().post(piper.base_url + "/synthesize", json={"text": text},
                                     timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            with wave.open(io.BytesIO(await response.read())) as wav:
                return wav.readframes(wav.getnframes())

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=PIPER_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        # Both pieces are requested at once; the audio is handed over in order.
        pieces = [asyncio.create_task(self.speak(text)) for text in first_clause_and_rest(self.input_text)]
        try:
            for piece in pieces:
                output_emitter.push(await piece)
        except aiohttp.ClientError as error:
            raise APIConnectionError(f"Piper TTS request failed: {error}") from error
        finally:
            for piece in pieces:
                piece.cancel()
        output_emitter.flush()
