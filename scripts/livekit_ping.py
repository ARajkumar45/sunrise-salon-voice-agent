"""Spike: how long does LiveKit Cloud take to connect, and what is the round trip?

Two copies join the same room. One answers pings, the other sends them:
    on the VM:      python scripts/livekit_ping.py echo  ping-room
    on the laptop:  python scripts/livekit_ping.py ping  ping-room

The ping travels laptop -> LiveKit Cloud -> VM -> LiveKit Cloud -> laptop,
the same path a caller's audio and the agent's reply take.
"""

import asyncio
import os
import statistics
import sys
import time

from dotenv import load_dotenv
from livekit import api, rtc

load_dotenv()


def make_token(identity: str, room_name: str) -> str:
    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity)
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt())


async def main(role: str, room_name: str) -> None:
    room = rtc.Room()
    replies: asyncio.Queue = asyncio.Queue()

    @room.on("data_received")
    def on_data(packet: rtc.DataPacket) -> None:
        if role == "echo" and packet.topic == "ping":
            asyncio.create_task(room.local_participant.publish_data(packet.data, topic="pong"))
        elif role == "ping" and packet.topic == "pong":
            replies.put_nowait(time.perf_counter())

    start = time.perf_counter()
    await room.connect(os.environ["LIVEKIT_URL"], make_token(role, room_name))
    print(f"{role}: connected in {time.perf_counter() - start:.2f}s")

    if role == "echo":
        await asyncio.sleep(120)
    else:
        while not room.remote_participants:
            await asyncio.sleep(0.2)
        await asyncio.sleep(1)
        round_trips = []
        for _ in range(30):
            sent = time.perf_counter()
            await room.local_participant.publish_data(b"x", topic="ping")
            received = await asyncio.wait_for(replies.get(), timeout=5)
            round_trips.append((received - sent) * 1000)
            await asyncio.sleep(0.1)
        round_trips.sort()
        print(f"round trip laptop<->VM through LiveKit over {len(round_trips)} pings: "
              f"median {statistics.median(round_trips):.0f} ms, "
              f"p95 {round_trips[int(len(round_trips) * 0.95) - 1]:.0f} ms, "
              f"worst {round_trips[-1]:.0f} ms")
    await room.disconnect()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
