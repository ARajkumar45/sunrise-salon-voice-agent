"""The agent's tools: the two-step confirmation rule, and that tools only see their own business."""

from app import booking
from app.tools import build_tools, is_plain_yes
from tests.conftest import count_bookings

PHONE = "9876543210"


def tools_for(business, turn_counter):
    """Returns the tools as plain async functions, keyed by name."""
    tools, finish_booking = build_tools(business, call_id=None, caller_turns=lambda: turn_counter["n"])
    return {**{tool.info.name: tool for tool in tools}, "finish_booking": finish_booking}


def far_future_slot(salon) -> tuple[str, str]:
    """A real bookable slot a few days from the real today (tools use the real clock)."""
    import datetime as dt
    day = booking.now_at(salon).date() + dt.timedelta(days=3)
    while not booking.slots_on(salon, booking.find_service(salon, "Haircut (men)"), day):
        day += dt.timedelta(days=1)
    return day.isoformat(), "10:30"


async def test_booking_needs_a_second_call_after_the_caller_speaks(salon):
    turn = {"n": 1}
    tools = tools_for(salon, turn)
    date, time = far_future_slot(salon)
    args = dict(service="Haircut (men)", date=date, time=time, customer_name="Asha", customer_phone=PHONE)

    first = await tools["book_appointment"](**args)
    assert first.startswith("NOT booked yet") and "9 8 7 6 5 4 3 2 1 0" in first
    assert await count_bookings() == 0

    # Calling again in the SAME caller turn (the model answering its own question) still does nothing.
    assert "WAIT" in await tools["book_appointment"](**args)
    assert await count_bookings() == 0

    turn["n"] = 2  # the caller said something (yes)
    assert (await tools["book_appointment"](**args)).startswith("Booked.")
    assert await count_bookings() == 1


async def test_changing_the_details_restarts_the_confirmation(salon):
    turn = {"n": 1}
    tools = tools_for(salon, turn)
    date, time = far_future_slot(salon)
    args = dict(service="Haircut (men)", date=date, customer_name="Asha", customer_phone=PHONE)
    await tools["book_appointment"](time=time, **args)
    turn["n"] = 2
    assert (await tools["book_appointment"](time="11:00", **args)).startswith("NOT booked yet")
    assert await count_bookings() == 0


async def test_move_and_cancel_need_the_caller_to_speak_after_the_lookup(salon):
    turn = {"n": 1}
    tools = tools_for(salon, turn)
    date, time = far_future_slot(salon)
    made = await booking.book(salon, "Haircut (men)", date, time, "Asha", PHONE)
    move = dict(booking_id=made["booking_id"], customer_phone=PHONE, new_date=date, new_time="12:00")
    cancel = dict(booking_id=made["booking_id"], customer_phone=PHONE)

    # Without any lookup in this call, nothing can be changed.
    assert (await tools["cancel_booking"](**cancel)).startswith("NOT cancelled yet")

    # Lookup and change in the same caller turn: refused.
    assert "booking_id" in await tools["find_my_bookings"](customer_phone=PHONE)
    assert (await tools["reschedule_booking"](**move)).startswith("NOT moved yet")
    first = await tools["cancel_booking"](**cancel)
    assert first.startswith("NOT cancelled yet") and "free to cancel" in first
    assert await count_bookings() == 1

    turn["n"] = 2  # the caller answered
    assert (await tools["reschedule_booking"](**move)).startswith("Moved.")
    assert "Cancelled" in await tools["cancel_booking"](**cancel)
    assert await count_bookings() == 0


async def test_tools_never_reveal_who_has_a_slot(salon):
    turn = {"n": 5}
    tools = tools_for(salon, turn)
    date, time = far_future_slot(salon)
    await booking.book(salon, "Haircut (men)", date, time, "Secret Person", "9000000001")
    answer = await tools["check_availability"](service="Haircut (men)", date=date)
    assert "Secret" not in answer and "9000000001" not in answer and "10:30 AM" not in answer
    assert await tools["find_my_bookings"](customer_phone=PHONE) == "No upcoming bookings for that phone number."
    # Guessing someone else's booking id with the wrong phone gets nothing.
    assert (await tools["cancel_booking"](booking_id=1, customer_phone=PHONE)).startswith("Not cancelled.")


async def test_facial_on_tuesday_tool_answer(salon):
    """The brief's test question, as the tool answers it."""
    import datetime as dt
    tools = tools_for(salon, {"n": 1})
    day = booking.now_at(salon).date() + dt.timedelta(days=1)
    while day.weekday() != 1:
        day += dt.timedelta(days=1)
    answer = await tools["check_availability"](service="Facial", date=day.isoformat())
    assert "does not work on Tuesdays" in answer and "Wednesday" in answer


def test_what_counts_as_a_plain_yes():
    for text in ["Yes.", "Yes, that's right, please book it.", "yeah go ahead", "Correct", "OK, confirm", "Sure, sounds good"]:
        assert is_plain_yes(text), text
    for text in ["No", "Yes but make it 11 instead", "Actually, change the time", "not yet", "wait",
                 "What was the price again?", "", "yes " * 20, "Is the stylist nice?"]:
        assert not is_plain_yes(text), text


async def test_code_completes_the_booking_when_the_caller_says_yes(salon):
    """The LLM does not have to remember the second call: a plain yes after the read-back books it."""
    turn = {"n": 1}
    tools = tools_for(salon, turn)
    date, time = far_future_slot(salon)

    assert await tools["finish_booking"]("yes") is None            # nothing was read back yet
    await tools["book_appointment"](service="Haircut (men)", date=date, time=time,
                                    customer_name="Asha", customer_phone=PHONE)
    assert await tools["finish_booking"]("Hmm, what was the price?") is None
    assert await count_bookings() == 0

    turn["n"] = 2
    result = await tools["finish_booking"]("Yes, that's right, please book it.")
    assert result.startswith("BOOKED") and await count_bookings() == 1
    assert await tools["finish_booking"]("yes") is None            # a second yes books nothing more
    assert await count_bookings() == 1


async def test_one_yes_is_enough_when_the_agent_already_read_the_time_back(salon):
    date, time = far_future_slot(salon)
    lines = {"agent": "Men's haircut with Anita Rao at 10:30 AM, shall I book that?", "caller": "Yes, please go ahead."}
    tools, _ = build_tools(salon, None, lambda: 3, lambda: (lines["agent"], lines["caller"]))
    book = {tool.info.name: tool for tool in tools}["book_appointment"]
    args = dict(service="Haircut (men)", date=date, time=time, customer_name="Asha", customer_phone=PHONE)
    assert (await book(**args)).startswith("Booked.")

    # But not if the agent never said the time, or the caller did not plainly agree.
    lines["agent"] = "May I have your phone number?"
    other = dict(args, time="11:00")
    assert (await book(**other)).startswith("NOT booked yet")
