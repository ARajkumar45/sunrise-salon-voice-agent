"""The actions the agent can take during a call (LLM "tools").

`build_tools(business, call_id)` is called once per call. The tools it returns are
already tied to that one business: the LLM can choose a service, a date and a time,
but it has no way to name a different business or to read another caller's booking.

Each tool returns a short piece of text or data for the LLM to turn into speech.
When something cannot be done, the tool returns the reason as plain words
(a BookingError) so the agent can explain it instead of failing.
"""

import datetime as dt

from livekit.agents import function_tool

from app import booking, db
from app.booking import BookingError


def times_of(slots: list[dt.datetime]) -> str:
    return ", ".join(db.format_time(s.time()) for s in slots)


def spoken_digits(phone: str) -> str:
    return " ".join(booking.clean_phone(phone))


def build_tools(business: dict, call_id: int, caller_turns=lambda: 0) -> list:
    """`caller_turns` returns how many times the caller has spoken so far in this call.

    Safety rules enforced in code, not just in the prompt. The agent can never look something
    up and change it in the same breath; the caller always speaks in between.

    - New booking: TWO calls to book_appointment. The first changes nothing and makes the
      agent read back the details, including the phone number digit by digit. Only a second
      call with the same details, after the caller has spoken again, books it.
    - Move or cancel: refused unless the caller has spoken since find_my_bookings showed
      their booking. So they have heard which booking it is and answered.
    """
    waiting = {"action": None, "turn": -1}
    last_lookup = {"turn": 10**9}  # no lookup yet

    def read_back_confirmed(*action) -> bool:
        """True only on the second request for exactly this action, in a later caller turn."""
        if waiting["action"] == action and caller_turns() > waiting["turn"]:
            waiting["action"] = None
            return True
        if waiting["action"] == action:
            raise BookingError("WAIT. The caller has not answered yet. Ask them to confirm and end your turn.")
        waiting.update(action=action, turn=caller_turns())
        return False

    def caller_spoke_since_lookup() -> bool:
        return caller_turns() > last_lookup["turn"]

    @function_tool
    async def check_availability(service: str, date: str) -> str:
        """Free times for a service on a date. Call before offering or booking any time.

        Args:
            service: Service name from the business information.
            date: YYYY-MM-DD from the Dates list.
        """
        try:
            chosen = booking.find_service(business, service)
            day = booking.parse_date(date)
            free = await booking.free_slots(business, chosen, day)
            if free:
                return (f"{chosen['name']} with {chosen['staff_name']} on {day:%A %d %B} ({day.isoformat()}): "
                        f"free at {times_of(free)}.")
            works_that_day = bool(booking.slots_on(business, chosen, day))
            reason = (f"{chosen['staff_name']} is fully booked or finished for the day on {day:%A %d %B}."
                      if works_that_day else
                      f"{chosen['staff_name']}, who does {chosen['name']}, does not work on {day:%A}s.")
            later = await booking.next_free_days(business, chosen, day)
            if not later:
                return reason + " There are no free times in the next two weeks."
            options = "; ".join(f"{d[0]:%A %d %B} ({d[0].date().isoformat()}) at {times_of(d[:4])}" for d in later)
            return f"{reason} Next free times: {options}."
        except BookingError as problem:
            return str(problem)

    @function_tool
    async def book_appointment(service: str, date: str, time: str, customer_name: str, customer_phone: str) -> str:
        """Book an appointment, after the caller confirmed the details.

        Args:
            service: Service name.
            date: YYYY-MM-DD.
            time: 24-hour HH:MM.
            customer_name: Caller's name.
            customer_phone: Caller's phone number, digits only.
        """
        try:
            chosen = booking.find_service(business, service)
            day = booking.parse_date(date)
            slot = booking.check_slot(business, chosen, day, booking.parse_time(time), booking.now_at(business))
            if slot not in await booking.free_slots(business, chosen, day):
                return f"Not booked. {booking.say_slot(slot)} is already taken. Check availability and offer another time."
            phone = booking.clean_phone(customer_phone)
            if not read_back_confirmed("book", chosen["id"], slot, phone):
                return (f"NOT booked yet. Ask the caller to confirm: {chosen['name']} with {chosen['staff_name']} on "
                        f"{booking.say_slot(slot)}, name {customer_name}, phone {spoken_digits(phone)}. "
                        "When they say yes, call book_appointment again with the same details.")
            done = await booking.book(business, service, date, time, customer_name, customer_phone, call_id)
            return f"Booked. {done['service']} with {done['with']} on {done['when']}. Price: {done['price']}."
        except BookingError as problem:
            return f"Not booked. {problem}"

    @function_tool
    async def find_my_bookings(customer_phone: str) -> str:
        """The caller's own upcoming bookings, by their phone number. Use before moving or cancelling.

        Args:
            customer_phone: Caller's phone number, digits only.
        """
        last_lookup["turn"] = caller_turns()
        try:
            found = await booking.bookings_for_phone(business, customer_phone)
        except BookingError as problem:
            return str(problem)
        if not found:
            return "No upcoming bookings for that phone number."
        return " | ".join(f"booking_id {b['booking_id']}: {b['service']} with {b['with']} on {b['when']}" for b in found)

    @function_tool
    async def reschedule_booking(booking_id: int, customer_phone: str, new_date: str, new_time: str) -> str:
        """Move the caller's booking, after they confirmed the new time.

        Args:
            booking_id: From find_my_bookings.
            customer_phone: Caller's phone number, digits only.
            new_date: YYYY-MM-DD.
            new_time: 24-hour HH:MM.
        """
        try:
            current = await booking.describe_own_booking(business, booking_id, customer_phone)
            chosen = booking.find_service(business, current["service"])
            slot = booking.check_slot(business, chosen, booking.parse_date(new_date),
                                      booking.parse_time(new_time), booking.now_at(business))
            if not caller_spoke_since_lookup():
                return (f"NOT moved yet. Ask the caller to confirm: move {current['service']} from {current['when']} "
                        f"to {booking.say_slot(slot)}. When they say yes, call reschedule_booking again.")
            done = await booking.reschedule(business, booking_id, customer_phone, new_date, new_time)
            return f"Moved. {done['service']} with {done['with']} is now on {done['moved_to']}."
        except BookingError as problem:
            return f"Not moved. {problem}"

    @function_tool
    async def cancel_booking(booking_id: int, customer_phone: str) -> str:
        """Cancel the caller's booking, after they confirmed.

        Args:
            booking_id: From find_my_bookings.
            customer_phone: Caller's phone number, digits only.
        """
        try:
            current = await booking.describe_own_booking(business, booking_id, customer_phone)
            if not caller_spoke_since_lookup():
                cost = ("It is free to cancel." if current["free_to_cancel"] else
                        f"It is less than {business['free_cancellation_hours']} hours before the appointment, "
                        "so it can be cancelled but it is NOT free.")
                return (f"NOT cancelled yet. Ask the caller to confirm: cancel {current['service']} on {current['when']}. "
                        f"{cost} When they say yes, call cancel_booking again.")
            return (await booking.cancel(business, booking_id, customer_phone))["note"]
        except BookingError as problem:
            return f"Not cancelled. {problem}"

    return [check_availability, book_appointment, find_my_bookings, reschedule_booking, cancel_booking]
