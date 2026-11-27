"""Booking rules: which slots exist, which are free, and how to book, move and cancel.

Every function takes the `business` dictionary loaded at the start of the call
(see db.load_business) and only ever touches that business's rows.

Double booking is prevented by the database, not by this file: the unique index
`one_booking_per_slot` (app/schema.sql) rejects a second live booking for the same
staff member and start time. Here we just catch that rejection and report "taken".
"""

import datetime as dt
from zoneinfo import ZoneInfo

from psycopg.errors import UniqueViolation

from app import db

LOOK_AHEAD_DAYS = 14  # how far ahead we search when a requested day has nothing free
MAX_DAYS_AHEAD = 365  # a date further away than this is almost certainly a wrong year


class BookingError(Exception):
    """A request that cannot be done, with a message the agent can say to the caller."""


# ---------- pure helpers (no database) ----------

def now_at(business: dict) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(business["timezone"]))


def find_service(business: dict, name: str) -> dict:
    wanted = name.strip().lower()
    for service in business["services"]:
        if service["name"].lower() == wanted:
            return service
    # Forgiving match: "men's haircut" should find "Haircut (men)".
    words = set(wanted.replace("'s", "").replace("(", " ").replace(")", " ").split())
    matches = [s for s in business["services"]
               if words and words <= set(s["name"].lower().replace("(", " ").replace(")", " ").split())]
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(s["name"] for s in business["services"])
    raise BookingError(f"No service called '{name}'. The services are: {names}.")


def parse_date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text.strip())
    except ValueError:
        raise BookingError(f"'{text}' is not a date. Use the form YYYY-MM-DD.") from None


def parse_time(text: str) -> dt.time:
    try:
        return dt.time.fromisoformat(text.strip())
    except ValueError:
        raise BookingError(f"'{text}' is not a time. Use 24-hour HH:MM, for example 16:30.") from None


def clean_phone(text: str) -> str:
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 7:
        raise BookingError("That phone number looks too short. Ask the caller to repeat it digit by digit.")
    return digits[-10:]


def slots_on(business: dict, service: dict, day: dt.date) -> list[dt.datetime]:
    """Every slot the service's staff member works on that day, as timezone-aware times."""
    zone = ZoneInfo(business["timezone"])
    person = next(p for p in business["staff"] if p["id"] == service["staff_id"])
    hours = next((h for h in person["hours"] if h["weekday"] == day.weekday()), None)
    if hours is None:
        return []
    step = dt.timedelta(minutes=business["slot_minutes"])
    slot = dt.datetime.combine(day, hours["start_time"], zone)
    end = dt.datetime.combine(day, hours["end_time"], zone)
    slots = []
    while slot + step <= end:
        slots.append(slot)
        slot += step
    return slots


def say_slot(slot: dt.datetime) -> str:
    return f"{slot:%A %d %B} at {db.format_time(slot.time())}"


# ---------- availability ----------

async def taken_slots(business: dict, staff_id: int, day: dt.date) -> set[dt.datetime]:
    zone = ZoneInfo(business["timezone"])
    start = dt.datetime.combine(day, dt.time.min, zone)
    async with (await db.pool()).connection() as conn:
        cur = await conn.execute(
            """SELECT starts_at FROM bookings
               WHERE business_id = %s AND staff_id = %s AND status = 'booked'
                 AND starts_at >= %s AND starts_at < %s""",
            (business["id"], staff_id, start, start + dt.timedelta(days=1)))
        return {row["starts_at"].astimezone(zone) for row in await cur.fetchall()}


async def free_slots(business: dict, service: dict, day: dt.date, now: dt.datetime | None = None) -> list[dt.datetime]:
    now = now or now_at(business)
    possible = [s for s in slots_on(business, service, day) if s > now]
    if not possible:
        return []
    taken = await taken_slots(business, service["staff_id"], day)
    return [s for s in possible if s not in taken]


async def next_free_days(business: dict, service: dict, after: dt.date, now: dt.datetime | None = None,
                         how_many: int = 2) -> list[list[dt.datetime]]:
    """The next few days (after the given one) that have at least one free slot."""
    found = []
    for offset in range(1, LOOK_AHEAD_DAYS + 1):
        slots = await free_slots(business, service, after + dt.timedelta(days=offset), now)
        if slots:
            found.append(slots)
            if len(found) == how_many:
                break
    return found


# ---------- book, move, cancel ----------

def check_day(business: dict, day: dt.date, now: dt.datetime) -> None:
    if day > now.date() + dt.timedelta(days=MAX_DAYS_AHEAD):
        raise BookingError(f"{day.isoformat()} is more than a year away. Check the year and use a date from the Dates list.")


def check_slot(business: dict, service: dict, day: dt.date, time: dt.time, now: dt.datetime) -> dt.datetime:
    """Return the slot if it is a real, future slot for this service. Otherwise explain why not."""
    check_day(business, day, now)
    slot = dt.datetime.combine(day, time, ZoneInfo(business["timezone"]))
    if slot not in slots_on(business, service, day):
        raise BookingError(
            f"{service['staff_name']} does not have a slot on {slot:%A %d %B} at {db.format_time(time)}. "
            "Check availability for that day first.")
    if slot <= now:
        raise BookingError("That time has already passed.")
    return slot


async def book(business: dict, service_name: str, date: str, time: str, customer_name: str,
               customer_phone: str, call_id: int | None = None, now: dt.datetime | None = None) -> dict:
    service = find_service(business, service_name)
    slot = check_slot(business, service, parse_date(date), parse_time(time), now or now_at(business))
    phone = clean_phone(customer_phone)
    if not customer_name.strip():
        raise BookingError("Ask for the caller's name first.")
    try:
        async with (await db.pool()).connection() as conn:
            cur = await conn.execute(
                """INSERT INTO bookings (business_id, staff_id, service_id, customer_name,
                                         customer_phone, starts_at, call_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (business["id"], service["staff_id"], service["id"], customer_name.strip(), phone, slot, call_id))
            booking_id = (await cur.fetchone())["id"]
    except UniqueViolation:
        # Someone else got this slot first, possibly a split second ago.
        raise BookingError(f"{say_slot(slot)} has just been taken. Check availability again and offer another time.") from None
    return {"booking_id": booking_id, "service": service["name"], "with": service["staff_name"],
            "when": say_slot(slot), "price": service["price"]}


async def bookings_for_phone(business: dict, customer_phone: str, now: dt.datetime | None = None) -> list[dict]:
    """Upcoming bookings for one phone number, in this business only."""
    zone = ZoneInfo(business["timezone"])
    async with (await db.pool()).connection() as conn:
        cur = await conn.execute(
            """SELECT b.id, b.starts_at, s.name AS service, st.name AS staff_name
               FROM bookings b JOIN services s ON s.id = b.service_id JOIN staff st ON st.id = b.staff_id
               WHERE b.business_id = %s AND b.customer_phone = %s AND b.status = 'booked' AND b.starts_at > %s
               ORDER BY b.starts_at""",
            (business["id"], clean_phone(customer_phone), now := now or now_at(business)))
        free_notice = dt.timedelta(hours=business["free_cancellation_hours"])
        return [{"booking_id": r["id"], "service": r["service"], "with": r["staff_name"],
                 "when": say_slot(r["starts_at"].astimezone(zone)),
                 "free_to_cancel": r["starts_at"] - now >= free_notice} for r in await cur.fetchall()]


async def get_own_booking(conn, business: dict, booking_id: int, customer_phone: str, now: dt.datetime) -> dict:
    """Fetch an upcoming booking only if it belongs to this business AND this phone number."""
    cur = await conn.execute(
        """SELECT b.*, s.name AS service_name FROM bookings b JOIN services s ON s.id = b.service_id
           WHERE b.id = %s AND b.business_id = %s AND b.customer_phone = %s AND b.status = 'booked'
             AND b.starts_at > %s""",
        (booking_id, business["id"], clean_phone(customer_phone), now))
    row = await cur.fetchone()
    if row is None:
        raise BookingError("No active booking with that number for that phone. Look up the caller's bookings first.")
    return row


async def describe_own_booking(business: dict, booking_id: int, customer_phone: str,
                               now: dt.datetime | None = None) -> dict:
    """What a booking is, and whether cancelling it right now would be free. Changes nothing."""
    now = now or now_at(business)
    async with (await db.pool()).connection() as conn:
        row = await get_own_booking(conn, business, booking_id, customer_phone, now)
    notice = row["starts_at"] - now
    return {"service": row["service_name"],
            "when": say_slot(row["starts_at"].astimezone(ZoneInfo(business["timezone"]))),
            "free_to_cancel": notice >= dt.timedelta(hours=business["free_cancellation_hours"])}


async def reschedule(business: dict, booking_id: int, customer_phone: str, new_date: str, new_time: str,
                     now: dt.datetime | None = None) -> dict:
    now = now or now_at(business)
    try:
        async with (await db.pool()).connection() as conn:
            row = await get_own_booking(conn, business, booking_id, customer_phone, now)
            service = find_service(business, row["service_name"])
            slot = check_slot(business, service, parse_date(new_date), parse_time(new_time), now)
            # One UPDATE: the old slot is freed and the new one taken together, or nothing changes.
            # "AND status = 'booked'": if it was cancelled a moment ago, it must not be moved.
            cur = await conn.execute(
                "UPDATE bookings SET starts_at = %s WHERE id = %s AND status = 'booked'", (slot, row["id"]))
            if cur.rowcount == 0:
                raise BookingError("That booking has just been cancelled, so it was not moved.")
    except UniqueViolation:
        raise BookingError("That new time has just been taken. The original booking is unchanged. "
                           "Check availability again and offer another time.") from None
    return {"booking_id": row["id"], "service": service["name"], "with": service["staff_name"],
            "moved_to": say_slot(slot)}


async def cancel(business: dict, booking_id: int, customer_phone: str, now: dt.datetime | None = None) -> dict:
    now = now or now_at(business)
    async with (await db.pool()).connection() as conn:
        row = await get_own_booking(conn, business, booking_id, customer_phone, now)
        await conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = %s", (row["id"],))
    notice = row["starts_at"] - now
    free = notice >= dt.timedelta(hours=business["free_cancellation_hours"])
    return {"cancelled": True, "free_of_charge": free,
            "note": "Cancelled free of charge." if free else
                    f"Cancelled, but it was less than {business['free_cancellation_hours']} hours before "
                    "the appointment, so it is not a free cancellation."}
