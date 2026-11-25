"""The voice agent. LiveKit starts one copy of `handle_call` for every call.

Each caller turn goes:
    voice detector (Silero VAD) hears the caller stop
    -> speech to text (Whisper on Groq)
    -> LLM (gpt-oss on Groq), with the business's data in its instructions
    -> text to speech (Piper, one sentence at a time)
    -> audio back to the caller

Run locally:   python -m app.agent dev
Run in Docker: python -m app.agent start
"""

import asyncio
import json
import logging

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli
from livekit.plugins import groq, silero

from app import db
from app.call_log import CallRecorder
from app.prompt import build_instructions
from app.tts_piper import PiperTTS

load_dotenv()
log = logging.getLogger("receptionist")

AGENT_NAME = "receptionist"
STT_MODEL = "whisper-large-v3-turbo"  # open model (OpenAI Whisper), served by Groq
LLM_MODEL = "openai/gpt-oss-120b"     # open-weight model, served by Groq

# How long the caller must be quiet before we treat them as finished speaking.
END_OF_SPEECH_SILENCE = 0.45
# How long the caller must talk over the agent before the agent stops.
INTERRUPT_AFTER = 0.2
# Silence handling: check in after this many quiet seconds, twice, then end the call.
SILENCE_BEFORE_CHECK_IN = 15.0
SILENCE_BETWEEN_CHECK_INS = 10.0
CHECK_INS = ["Are you still there?", "Hello? I can't hear anything. Are you still on the line?"]
GOODBYE = "I'll end the call for now. Please call again any time. Goodbye."

server = AgentServer()


def prewarm(process: JobProcess) -> None:
    """Runs once per worker process, before any call, so the first turn is not slow."""
    process.userdata["vad"] = silero.VAD.load(min_silence_duration=END_OF_SPEECH_SILENCE)


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def handle_call(ctx: JobContext) -> None:
    # 1. Which business was called? The web server put the slug into the signed call token.
    slug = json.loads(ctx.job.metadata or "{}").get("business", "")
    business = await db.load_business(slug)
    if business is None:
        log.warning("call for unknown business %r, hanging up", slug)
        ctx.shutdown(reason="unknown business")
        return
    call_id = await db.start_call(business["id"], ctx.room.name)
    log.info("call %s started for %s in room %s", call_id, slug, ctx.room.name)

    # 2. Build the voice pipeline.
    stt = groq.STT(model=STT_MODEL, language="en")
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=stt,
        llm=groq.LLM(model=LLM_MODEL),
        tts=PiperTTS(),
        turn_handling={
            # The voice detector alone decides when the caller has finished.
            "turn_detection": "vad",
            # It already waited END_OF_SPEECH_SILENCE, so do not wait any longer on top.
            "endpointing": {"mode": "fixed", "min_delay": 0.0, "max_delay": 3.0},
            # The agent stops talking once the caller has spoken over it for INTERRUPT_AFTER.
            "interruption": {"mode": "vad", "min_duration": INTERRUPT_AFTER},
        },
        user_away_timeout=SILENCE_BEFORE_CHECK_IN,
    )

    # 3. Record the transcript and the latency of every reply.
    recorder = CallRecorder(call_id, session)
    stt.on("metrics_collected", recorder.on_stt_metrics)
    ctx.add_shutdown_callback(recorder.finish)

    # 4. Long silence: check in politely, then end the call.
    silence_task: asyncio.Task | None = None

    async def handle_silence() -> None:
        for line in CHECK_INS:
            recorder.write("silence", {"action": "check_in"})
            await session.say(line)
            await asyncio.sleep(SILENCE_BETWEEN_CHECK_INS)
        recorder.write("silence", {"action": "hang_up"})
        await session.say(GOODBYE, allow_interruptions=False)
        await ctx.delete_room()  # disconnects the caller and ends this call

    @session.on("user_state_changed")
    def on_user_state(event) -> None:
        nonlocal silence_task
        if event.new_state == "away":
            silence_task = asyncio.create_task(handle_silence())
        elif silence_task is not None:  # the caller spoke again
            silence_task.cancel()
            silence_task = None

    # 5. Start talking. Instructions and greeting both come from the database.
    await session.start(room=ctx.room, agent=Agent(instructions=build_instructions(business)))
    await session.say(business["greeting"])


if __name__ == "__main__":
    cli.run_app(server)
