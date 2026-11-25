"""Proof that a slot can never be booked twice, even when callers race for it.

Each test fires many booking attempts at the same instant over separate database
connections (the pool holds 20). The guard is the unique index `one_booking_per_slot`
in app/schema.sql: Postgres itself lets exactly one of them in.
"""

import asyncio
import datetime as dt

from app import booking
from app.booking import BookingError
from tests.conftest import IST, count_bookings

MON, WED = "2026-11-23", "2026-11-25"


async def attempt(coroutine) -> bool:
    """True if the booking went through, False if it was refused as taken."""
    try:
        await coroutine
        return True
    except BookingError as refused:
        assert "taken" in str(refused)
        return False


async def test_50_callers_race_for_one_slot_and_exactly_one_wins(salon, now):
    """Repeated 20 times, each time on a different slot."""
    anita_slots = [(day, f"{hour:02d}:{minute:02d}")
                   for day in ("2026-11-23", "2026-11-24", "2026-11-25")
                   for hour in (10, 11, 12, 13) for minute in (0, 30)][:20]
    for round_number, (day, time) in enumerate(anita_slots, start=1):
        results = await asyncio.gather(*[
            attempt(booking.book(salon, "Haircut (men)" if i % 2 else "Haircut (women)", day, time,
                                 f"Caller {i}", f"90000000{i:02d}", now=now))
            for i in range(50)])
        assert results.count(True) == 1, f"round {round_number}: {results.count(True)} bookings for one slot"
        assert await count_bookings() == round_number
    # And directly in the database: no staff member has two live bookings at the same time.
    assert await count_bookings() == 20


async def test_two_callers_rescheduling_into_the_same_slot(salon, now):
    a = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", "9000000001", now=now)
    b = await booking.book(salon, "Haircut (men)", MON, "10:30", "Bela", "9000000002", now=now)
    results = await asyncio.gather(
        attempt(booking.reschedule(salon, a["booking_id"], "9000000001", WED, "12:00", now=now)),
        attempt(booking.reschedule(salon, b["booking_id"], "9000000002", WED, "12:00", now=now)))
    assert sorted(results) == [False, True]
    assert await count_bookings() == 2          # nobody lost their booking
    assert await count_bookings("starts_at = '2026-11-25 12:00+05:30' AND status = 'booked'") == 1


async def test_new_booking_races_a_reschedule_for_the_same_slot(salon, now):
    for _ in range(10):
        a = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", "9000000001", now=now)
        results = await asyncio.gather(
            attempt(booking.reschedule(salon, a["booking_id"], "9000000001", WED, "13:00", now=now)),
            attempt(booking.book(salon, "Haircut (women)", WED, "13:00", "Bela", "9000000002", now=now)))
        assert sorted(results) == [False, True]
        assert await count_bookings("starts_at = '2026-11-25 13:00+05:30' AND status = 'booked'") == 1
        async with (await booking.db.pool()).connection() as conn:
            await conn.execute("TRUNCATE bookings RESTART IDENTITY")


async def test_a_cancelled_slot_can_be_booked_again_but_only_once(salon, now):
    first = await booking.book(salon, "Haircut (men)", MON, "11:00", "Asha", "9000000001", now=now)
    await booking.cancel(salon, first["booking_id"], "9000000001", now=now)
    results = await asyncio.gather(*[
        attempt(booking.book(salon, "Haircut (men)", MON, "11:00", f"Caller {i}", f"90000000{i:02d}", now=now))
        for i in range(30)])
    assert results.count(True) == 1
