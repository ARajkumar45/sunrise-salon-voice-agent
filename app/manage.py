"""Command-line helper for the person running the system.

    python -m app.manage load data/sunrise-salon.yaml   add or update a business from a file
    python -m app.manage prompt sunrise-salon           show the instructions the agent gets
    python -m app.manage calls sunrise-salon            list recent calls
    python -m app.manage call 42                        show everything that happened on call 42

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


def describe_event(event: dict) -> str:
    kind, data = event["kind"], event["data"]
    if kind == "said":
        cut = "  [cut off by caller]" if data.get("interrupted") else ""
        return f"{data['who'].upper():6}: {data['text']}{cut}"
    if kind == "tool":
        return f"  TOOL  {data['name']}({data['arguments']}) -> {data['result']}"
    if kind == "latency":
        return (f"  (reply started {data['reply_latency_s']}s after end of speech was detected, "
                f"{data.get('since_last_word_s')}s after the caller's last word: "
                f"stt {data['stt_s']}s, llm {data['llm_first_token_s']}s, tts {data['tts_first_audio_s']}s"
                f"{', used a tool' if data['used_tool'] else ''})")
    return f"  [{kind}] {data}"


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
    else:
        print(__doc__)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
