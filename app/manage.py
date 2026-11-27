"""Command-line helper for the person running the system.

    python -m app.manage load data/sunrise-salon.yaml   add or update a business from a file
    python -m app.manage prompt sunrise-salon           show the instructions the agent gets
    python -m app.manage calls sunrise-salon            list recent calls
    python -m app.manage call 42                        show everything that happened on call 42
    python -m app.manage messages sunrise-salon         questions callers left for the staff
    python -m app.manage latency sunrise-salon [N]      reply latency report (calls from id N onwards)

In Docker, put `docker compose exec web` in front, for example:
    docker compose exec web python -m app.manage calls sunrise-salon
"""

import asyncio
import sys

import yaml
from dotenv import load_dotenv

from app import db
from app.prompt import build_instructions

load_dotenv()


def seconds(value) -> str:
    return "not recorded" if value is None else f"{value}s"


def describe_event(event: dict) -> str:
    kind, data = event["kind"], event["data"]
    if kind == "said":
        cut = "  [cut off by caller]" if data.get("interrupted") else ""
        return f"{data['who'].upper():6}: {data['text']}{cut}"
    if kind == "tool":
        failed = "  [THE TOOL FAILED]" if data.get("failed") else ""
        return f"  TOOL  {data['name']}({data['arguments']}) -> {data['result']}{failed}"
    if kind == "latency":
        return (f"  (reply started {data['reply_latency_s']}s after end of speech was detected, "
                f"{data.get('since_last_word_s')}s after the caller's last word: "
                f"stt {seconds(data['stt_s'])}, llm {seconds(data['llm_first_token_s'])}, "
                f"tts {seconds(data['tts_first_audio_s'])}"
                f"{', used a tool' if data['used_tool'] else ''})")
    return f"  [{kind}] {data}"


def percentile(values: list[float], percent: float) -> float:
    """Nearest-rank percentile: the value below which `percent` of the measurements fall."""
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * percent // 100) - 1)] if ordered else float("nan")


def latency_report(rows: list[dict]) -> str:
    """Median and 95th percentile of reply latency over EVERY reply, then per stage."""
    turns = [row["data"] for row in rows]
    if not turns:
        return "No replies recorded."

    def line(label: str, values: list) -> str:
        values = [v for v in values if v is not None]
        if not values:
            return f"{label:<34} no data"
        return (f"{label:<34} n={len(values):<3} median {percentile(values, 50):.2f}s   "
                f"p95 {percentile(values, 95):.2f}s   worst {max(values):.2f}s")

    with_tool = [t for t in turns if t["used_tool"]]
    without = [t for t in turns if not t["used_tool"]]
    calls = len({row["call_id"] for row in rows})
    return "\n".join([
        f"Reply latency over {len(turns)} replies in {calls} calls",
        "(from the moment end of speech is detected to the first reply audio sent)",
        "",
        line("ALL REPLIES (headline)", [t["reply_latency_s"] for t in turns]),
        line("  replies that used a tool", [t["reply_latency_s"] for t in with_tool]),
        line("  replies without a tool", [t["reply_latency_s"] for t in without]),
        "",
        "Stages (all replies):",
        line("  speech to text (Whisper)", [t["stt_s"] for t in turns]),
        line("    of which after detection", [t.get("text_ready_after_s") for t in turns]),
        line("  LLM, time to first token", [t["llm_first_token_s"] for t in turns]),
        line("  text to speech, first audio", [t["tts_first_audio_s"] for t in turns]),
        "",
        line("As the caller feels it (from last word)", [t.get("since_last_word_s") for t in turns]),
    ])


async def main(args: list[str]) -> None:
    command = args[0] if args else ""
    await db.init_schema()
    if command == "load":
        data = yaml.safe_load(open(args[1]).read())
        await db.save_business(data)
        print(f"Loaded {data['name']}. Call page: /call/{data['slug']}")
    elif command == "prompt":
        print(build_instructions(await db.load_business(args[1])))
    elif command == "calls":
        for call in await db.list_calls(args[1]):
            print(f"call {call['id']:>4}  {call['started_at']:%d %b %H:%M:%S}  {call['lines']} lines  {call['room']}")
    elif command == "call":
        for event in await db.get_call_events(int(args[1])):
            print(f"{event['at']:%H:%M:%S}  {describe_event(event)}")
    elif command == "latency":
        print(latency_report(await db.latency_rows(args[1], int(args[2]) if len(args) > 2 else 0)))
    elif command == "messages":
        for m in await db.list_staff_messages(args[1]):
            who = " ".join(x for x in (m["caller_name"], m["caller_phone"]) if x) or "unknown caller"
            print(f"{m['created_at']:%d %b %H:%M}  call {m['call_id']}  {who}: {m['message']}")
    else:
        print(__doc__)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
