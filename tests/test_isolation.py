"""One business must never see another business's data or bookings.

Two businesses share the database: Sunrise Salon and Greenline Auto Care (a garage that was
added with a data file only). Everything here is checked at the level the agent works at:
the instructions it is given and the tools it can call.
"""

import datetime as dt

import pytest

from app import booking, db
from app.booking import BookingError
from app.prompt import build_instructions
from app.tools import build_tools
from tests.conftest import count_bookings

PHONE = "9876543210"
MON = "2026-11-23"


def tools_of(business):
    tools, _ = build_tools(business, call_id=None, caller_turns=lambda: 9)
    return {tool.info.name: tool for tool in tools}


def test_each_agent_is_told_only_about_its_own_business(salon, garage):
    salon_prompt, garage_prompt = build_instructions(salon), build_instructions(garage)
    for fact in ("Sunrise Salon", "Anita Rao", "Lake Road", "Haircut", "Rs 400", "stylist"):
        assert fact in salon_prompt and fact not in garage_prompt
    for fact in ("Greenline Auto Care", "Imran Sheikh", "Baner Road", "Oil change", "Rs 1,800", "mechanic"):
        assert fact in garage_prompt and fact not in salon_prompt


def test_the_second_business_runs_on_its_own_data(garage):
    """Different slot length, different days, different cancellation rule: all from data."""
    oil = booking.find_service(garage, "Oil change")
    slots = booking.slots_on(garage, oil, dt.date.fromisoformat(MON))
    assert [f"{s:%H:%M}" for s in slots] == ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    assert garage["free_cancellation_hours"] == 24 and garage["slot_minutes"] == 60


def test_one_business_cannot_use_the_others_services(salon, garage):
    with pytest.raises(BookingError, match="No service called"):
        booking.find_service(garage, "Haircut (men)")
    with pytest.raises(BookingError, match="No service called"):
        booking.find_service(salon, "Oil change")


async def test_bookings_do_not_leak_between_businesses(salon, garage, now):
    made = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)

    # The same phone number, calling the garage, has no bookings there.
    assert await booking.bookings_for_phone(garage, PHONE, now) == []
    # The garage's 10:00 is still free: the salon's booking does not occupy it.
    free = await booking.free_slots(garage, booking.find_service(garage, "Oil change"), dt.date.fromisoformat(MON), now)
    assert "10:00" in [f"{s:%H:%M}" for s in free]
    # And the garage can book its own 10:00.
    await booking.book(garage, "Oil change", MON, "10:00", "Asha", PHONE, now=now)
    assert len(await booking.bookings_for_phone(garage, PHONE, now)) == 1
    assert len(await booking.bookings_for_phone(salon, PHONE, now)) == 1

    # Knowing the salon booking's id and the right phone is not enough from the garage's side.
    with pytest.raises(BookingError, match="No active booking"):
        await booking.cancel(garage, made["booking_id"], PHONE, now=now)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.reschedule(garage, made["booking_id"], PHONE, MON, "11:00", now=now)
    assert await count_bookings() == 2


async def test_the_agents_tools_are_locked_to_their_business(salon, garage):
    """The same checks through the tools the LLM actually calls."""
    day = booking.now_at(salon).date() + dt.timedelta(days=3)
    while day.weekday() == 6:
        day += dt.timedelta(days=1)
    made = await booking.book(salon, "Haircut (men)", day.isoformat(), "10:00", "Asha", PHONE)
    garage_tools = tools_of(garage)

    assert await garage_tools["find_my_bookings"](customer_phone=PHONE) == "No upcoming bookings for that phone number."
    assert (await garage_tools["cancel_booking"](booking_id=made["booking_id"], customer_phone=PHONE)).startswith("Not cancelled.")
    assert "No service called" in await garage_tools["check_availability"](service="Haircut (men)", date=day.isoformat())
    assert await count_bookings() == 1

    # No tool takes a "which business" argument, so the LLM has nothing to aim at another business.
    import inspect
    for tool in garage_tools.values():
        parameters = inspect.signature(tool).parameters
        assert not any("business" in name or "slug" in name for name in parameters)


async def test_staff_messages_and_calls_stay_with_their_business(salon, garage):
    await db.add_staff_message(garage["id"], None, "Do you do warranty repairs?", "Asha", PHONE)
    assert len(await db.list_staff_messages("greenline-auto-care")) == 1
    assert await db.list_staff_messages("sunrise-salon") == []

    call_id = await db.start_call(garage["id"], "greenline-test-room")
    assert call_id in [c["id"] for c in await db.list_calls("greenline-auto-care")]
    assert call_id not in [c["id"] for c in await db.list_calls("sunrise-salon")]


async def test_reloading_a_business_file_keeps_its_bookings(salon, now):
    """A data change (the live-change case) must not disturb existing bookings."""
    import yaml
    from tests.conftest import DATA
    await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    data = yaml.safe_load((DATA / "sunrise-salon.yaml").read_text())
    data["services"].append({"name": "Beard trim", "staff": "Anita Rao", "price": "Rs 200"})
    await db.save_business(data)
    changed = await db.load_business("sunrise-salon")
    assert "Beard trim" in [s["name"] for s in changed["services"]]
    assert len(await booking.bookings_for_phone(changed, PHONE, now)) == 1
    # Put the file's original contents back so later tests see the seeded salon.
    await db.save_business(yaml.safe_load((DATA / "sunrise-salon.yaml").read_text()))
    assert "Beard trim" not in [s["name"] for s in (await db.load_business("sunrise-salon"))["services"]]
