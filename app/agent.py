"""The voice agent. LiveKit starts one copy of `handle_call` for every call.

Milestone 0 version: proves the full audio loop works end to end
(browser -> LiveKit -> speech to text -> LLM -> text to speech -> browser).
Business data and booking tools arrive in the next milestones.

Run locally:   python -m app.agent dev
Run in Docker: python -m app.agent start
"""

import json
import logging

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli
from livekit.plugins import groq, silero

from app.tts_piper import PiperTTS

load_dotenv()
log = logging.getLogger("receptionist")

AGENT_NAME = "receptionist"
STT_MODEL = "whisper-large-v3-turbo"  # open model (OpenAI Whisper), served by Groq
LLM_MODEL = "openai/gpt-oss-120b"     # open-weight model, served by Groq

server = AgentServer()


def prewarm(process: JobProcess) -> None:
    """Runs once per worker process, before any call, so the first turn is not slow."""
    process.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def handle_call(ctx: JobContext) -> None:
    # The web server put the business slug into the call token. See app/web.py.
    metadata = json.loads(ctx.job.metadata or "{}")
    business_slug = metadata.get("business", "unknown")
    log.info("call started room=%s business=%s", ctx.room.name, business_slug)

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=groq.STT(model=STT_MODEL, language="en"),
        llm=groq.LLM(model=LLM_MODEL),
        tts=PiperTTS(),
        turn_handling={
            # Plain voice-activity detection decides when the caller has finished.
            "turn_detection": "vad",
            # Interrupt the agent as soon as the caller has spoken for 0.3 s.
            "interruption": {"mode": "vad", "min_duration": 0.3},
        },
    )
    await session.start(
        room=ctx.room,
        agent=Agent(
            instructions=(
                "You are a voice assistant being tested. Reply in one short, friendly sentence. "
                "Plain spoken English only, no lists or symbols."
            )
        ),
    )
    await session.say("Hello! The line is working. Say something and I will reply.")


if __name__ == "__main__":
    cli.run_app(server)
