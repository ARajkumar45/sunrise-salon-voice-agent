"""Awkward callers, as real voice calls against the running agent.

Each case is one call. After running, read each call with
    python -m app.manage call <id>
to see what the agent heard and did.

Usage (on the server, like scripts/fake_caller.py):
    python scripts/edge_calls.py            all cases
    python scripts/edge_calls.py hang_up    one case
"""

import asyncio
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from fake_caller import FakeCaller  # noqa: E402

A = "tests/audio/"


def audio(name: str) -> bytes:
    with wave.open(A + name, "rb") as wav:
        return wav.readframes(wav.getnframes())


def quiet(seconds: float, rate: int = 22050) -> bytes:
    return b"\x00" * (int(rate * seconds) * 2)


async def play(caller: FakeCaller, data: bytes) -> float:
    caller.to_play = data
    while caller.to_play:
        await asyncio.sleep(0.01)
    return time.perf_counter()


async def answered(caller: FakeCaller, label: str, finished: float, timeout: float = 20) -> None:
    try:
        started = await caller.wait_for_agent_to_start(timeout)
        print(f"  {label}: reply heard {started - finished:.2f}s later")
        await caller.wait_for_agent_to_finish()
    except asyncio.TimeoutError:
        print(f"  {label}: NO REPLY within {timeout:.0f}s")


async def hang_up(caller: FakeCaller) -> None:
    """The caller hangs up half a second into the agent's answer."""
    await play(caller, audio("colour.wav"))
    await caller.wait_for_agent_to_start()
    await asyncio.sleep(0.5)
    print("  hanging up mid-answer")


async def talk_over_greeting(caller: FakeCaller) -> None:
    """Handled in run(): the caller speaks half a second into the greeting."""


async def pause_mid_sentence(caller: FakeCaller) -> None:
    """Two questions with a pause between them that is shorter than the 0.45 s limit:
    the agent should answer once, covering both."""
    first = audio("sunday.wav")
    trimmed = first[:len(first) - int(22050 * 0.2) * 2]  # drop most of the trailing quiet
    finished = await play(caller, trimmed + quiet(0.1) + audio("where.wav"))
    await answered(caller, "one turn with a pause in it", finished)


async def second_question_over_the_answer(caller: FakeCaller) -> None:
    """The caller asks something else while the agent is still answering."""
    await play(caller, audio("colour.wav"))
    await caller.wait_for_agent_to_start()
    await asyncio.sleep(0.8)
    finished = await play(caller, audio("upi.wav"))
    await asyncio.sleep(0.7)  # the old answer must have stopped by now
    await answered(caller, "second question asked over the first answer", finished)


async def long_turn(caller: FakeCaller) -> None:
    """About 15 s of speech with only short gaps: one long caller turn."""
    parts = [audio(n) for n in ("mens_haircut.wav", "sunday.wav", "where.wav", "upi.wav", "colour.wav")]
    data = b"".join(p[:len(p) - int(22050 * 0.2) * 2] + quiet(0.05) for p in parts)
    print(f"  speaking for {len(data) / 2 / 22050:.1f}s")
    finished = await play(caller, data + quiet(0.3))
    await answered(caller, "long turn", finished, timeout=30)


async def noise(caller: FakeCaller) -> None:
    """A second of loud hiss, then a real question. The hiss must not derail the call."""
    hiss = (np.random.default_rng(1).normal(0, 3000, 22050)).astype(np.int16).tobytes()
    finished = await play(caller, hiss)
    await answered(caller, "hiss (no reply is the right outcome)", finished, timeout=6)
    finished = await play(caller, audio("where.wav"))
    await answered(caller, "question after the hiss", finished)


async def nonsense_then_question(caller: FakeCaller) -> None:
    """A caller who says only 'yes' with nothing to confirm, then asks a question."""
    finished = await play(caller, audio("yes.wav"))
    await answered(caller, "a bare yes with nothing to confirm", finished)
    finished = await play(caller, audio("cancel.wav"))
    await answered(caller, "asks to cancel a booking that may not exist", finished)
    finished = await play(caller, audio("no_thanks.wav"))
    await answered(caller, "no thanks", finished)


CASES = [hang_up, talk_over_greeting, pause_mid_sentence, second_question_over_the_answer,
         long_turn, noise, nonsense_then_question]


async def run(case) -> None:
    print(f"\n== {case.__name__} ==")
    caller = FakeCaller("sunrise-salon")
    await caller.connect()
    await caller.wait_for_agent_to_start(timeout=30)
    if case is talk_over_greeting:
        # The framework ignores the caller for the first 3 s of the agent's first speech
        # (its guard against the agent hearing its own echo), so this question is expected
        # to be lost. What matters is that the call carries on normally afterwards.
        await asyncio.sleep(0.6)
        await play(caller, audio("where.wav"))
        await caller.wait_for_agent_to_finish()
        try:
            await caller.wait_for_agent_to_start(timeout=5)
            print("  the question asked over the greeting WAS answered")
            await caller.wait_for_agent_to_finish()
        except asyncio.TimeoutError:
            print("  the question asked over the greeting was not heard (expected, see above)")
        finished = await play(caller, audio("where.wav"))
        await answered(caller, "the same question asked again", finished)
    else:
        await caller.wait_for_agent_to_finish()
        await case(caller)
    await caller.hang_up()
    await asyncio.sleep(3)


async def main(names: list[str]) -> None:
    for case in CASES:
        if not names or case.__name__ in names:
            try:
                await run(case)
            except Exception as error:  # one broken case must not hide the others
                print(f"  CASE FAILED: {type(error).__name__}: {error}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
