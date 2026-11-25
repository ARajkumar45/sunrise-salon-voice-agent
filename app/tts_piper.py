"""Text to speech with Piper (open source), running as its own small HTTP service.

LiveKit Agents has no official Piper plugin, so this file is the adapter.
It does one thing: send a sentence to the Piper server and hand the audio
that comes back to the framework.

The framework splits the LLM's reply into sentences and calls `synthesize`
once per sentence, so the first sentence starts playing while the LLM is
still writing the rest.
"""

import os
import uuid

import aiohttp
from livekit.agents import APIConnectionError, APIConnectOptions, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

# The Piper voice we ship (en_US-lessac-medium) produces 22.05 kHz mono audio.
PIPER_SAMPLE_RATE = 22050


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
    """One sentence in, one WAV file out."""

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        piper: PiperTTS = self._tts  # type: ignore[assignment]
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=PIPER_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/wav",
        )
        try:
            async with piper.http().post(
                piper.base_url + "/synthesize",
                json={"text": self.input_text},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_chunked(4096):
                    output_emitter.push(chunk)
        except aiohttp.ClientError as error:
            raise APIConnectionError(f"Piper TTS request failed: {error}") from error
        output_emitter.flush()
