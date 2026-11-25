"""Records everything that happens on one call into the database.

Two jobs:
1. Call log: every line spoken (and later every tool call), so a bad call can be explained.
2. Latency: for every reply, the time from "we detected the caller stopped speaking"
   to "the first reply audio was sent". This is the number the assignment asks for.

How the latency clock works:
- The voice detector (VAD) decides the caller has finished -> user state goes
  "speaking" -> "listening". We read the clock at that moment. That is the start.
  (The framework's own event timestamp is back-dated to the caller's last word,
  so we deliberately use our own clock reading for "the moment we detected it".
  We also keep the back-dated one, to report how long the caller really waited.)
- The first audio of the reply is sent -> agent state becomes "speaking".
  We note the time. That is the end of the clock.
Every reply is measured this way, including replies that needed a tool call.
"""

import asyncio
import logging
import time

from livekit.agents import AgentSession

from app import db

log = logging.getLogger("receptionist")


class CallRecorder:
    def __init__(self, call_id: int, session: AgentSession) -> None:
        self.call_id = call_id
        self.session = session
        self.pending: set[asyncio.Task] = set()

        self.user_stopped_at: float | None = None      # start of the latency clock (detection)
        self.last_word_at: float | None = None         # when the caller's last word really ended
        self.reply_latency: float | None = None        # measured, waiting for its transcript line
        self.interrupt_started_at: float | None = None
        self.stt_seconds: float | None = None          # time Whisper took for the last utterance
        self.transcript_at: float | None = None        # when the caller's words arrived as text
        self.used_tool = False

        session.on("user_state_changed", self.on_user_state)
        session.on("agent_state_changed", self.on_agent_state)
        session.on("user_input_transcribed", self.on_transcript)
        session.on("conversation_item_added", self.on_item)
        session.on("function_tools_executed", self.on_tools)
        session.on("error", self.on_error)

    def write(self, kind: str, data: dict) -> None:
        """Save one event without making the conversation wait for the database."""
        task = asyncio.create_task(db.log_event(self.call_id, kind, data))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    # ---- timing ----

    def on_user_state(self, event) -> None:
        if event.old_state == "speaking" and event.new_state == "listening":
            self.user_stopped_at = time.time()
            self.last_word_at = event.created_at
        elif event.new_state == "speaking" and self.session.agent_state == "speaking":
            # The caller started talking over the agent.
            self.interrupt_started_at = event.created_at

    def on_transcript(self, event) -> None:
        if event.is_final:
            self.transcript_at = event.created_at

    def on_agent_state(self, event) -> None:
        if event.new_state == "speaking" and self.user_stopped_at is not None:
            self.reply_latency = event.created_at - self.user_stopped_at
            self.since_last_word = event.created_at - (self.last_word_at or self.user_stopped_at)
            # Split the wait into "until we had the text" and "from text to first audio".
            self.text_ready_after = (self.transcript_at or event.created_at) - self.user_stopped_at
            self.user_stopped_at = None
        if event.old_state == "speaking" and self.interrupt_started_at is not None:
            stop_seconds = event.created_at - self.interrupt_started_at
            self.write("interruption", {"agent_stopped_after_s": round(stop_seconds, 3)})
            log.info("interruption: agent stopped %.3fs after caller speech was detected", stop_seconds)
            self.interrupt_started_at = None

    def on_stt_metrics(self, metrics) -> None:
        self.stt_seconds = getattr(metrics, "duration", None)

    # ---- transcript ----

    def on_item(self, event) -> None:
        item = event.item
        if getattr(item, "type", None) != "message" or item.role not in ("user", "assistant"):
            return
        metrics = dict(item.metrics or {})
        self.write("said", {"who": "caller" if item.role == "user" else "agent",
                            "text": item.text_content, "interrupted": item.interrupted})
        if item.role == "assistant" and self.reply_latency is not None:
            timing = {
                "reply_latency_s": round(self.reply_latency, 3),
                "since_last_word_s": round(self.since_last_word, 3),
                "text_ready_after_s": round(self.text_ready_after, 3),
                "stt_s": round(self.stt_seconds, 3) if self.stt_seconds else None,
                "llm_first_token_s": round(metrics.get("llm_node_ttft", 0), 3) or None,
                "tts_first_audio_s": round(metrics.get("tts_node_ttfb", 0), 3) or None,
                "used_tool": self.used_tool,
            }
            self.write("latency", timing)
            log.info("latency %s", timing)
            self.reply_latency, self.stt_seconds, self.used_tool = None, None, False

    def on_tools(self, event) -> None:
        self.used_tool = True
        for call, output in event.zipped():
            self.write("tool", {"name": call.name, "arguments": call.arguments,
                                "result": output.output if output else None,
                                "failed": bool(output and output.is_error)})

    def on_error(self, event) -> None:
        self.write("error", {"error": str(event.error)[:500]})

    async def finish(self) -> None:
        """Called when the call ends: make sure every event reached the database."""
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
        await db.end_call(self.call_id)
