"""Booking rules: slots, availability, booking, moving, cancelling, and who may touch a booking."""

import datetime as dt

import pytest

from app import booking
from app.booking import BookingError
from tests.conftest import IST, count_bookings

MON, TUE, WED, SUN = "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-29"
PHONE, OTHER_PHONE = "9876543210", "9123456780"


def times(slots):
    return [f"{s:%H:%M}" for s in slots]


def service(salon, name):
    return booking.find_service(salon, name)


# ---- which slots exist ----

def test_anita_has_eight_half_hour_slots_on_monday(salon):
    slots = booking.slots_on(salon, service(salon, "Haircut (men)"), dt.date.fromisoformat(MON))
    assert times(slots) == ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]


def test_rahul_works_tuesday_evening_only(salon):
    colour = service(salon, "Hair colour")
    assert times(booking.slots_on(salon, colour, dt.date.fromisoformat(TUE)))[0] == "16:00"
    assert times(booking.slots_on(salon, colour, dt.date.fromisoformat(TUE)))[-1] == "19:30"
    assert booking.slots_on(salon, colour, dt.date.fromisoformat(MON)) == []


def test_nobody_works_on_sunday(salon):
    for s in salon["services"]:
        assert booking.slots_on(salon, s, dt.date.fromisoformat(SUN)) == []


def test_service_names_are_matched_forgivingly(salon):
    assert service(salon, "haircut (MEN)")["name"] == "Haircut (men)"
    assert service(salon, "men's haircut")["name"] == "Haircut (men)"
    assert service(salon, "facial")["name"] == "Facial"
    with pytest.raises(BookingError, match="No service called"):
        service(salon, "nail art")
    with pytest.raises(BookingError):       # "haircut" alone is ambiguous: men or women?
        service(salon, "haircut")


# ---- availability ----

async def test_past_slots_are_not_offered(salon):
    monday_1110 = dt.datetime(2026, 11, 23, 11, 10, tzinfo=IST)
    free = await booking.free_slots(salon, service(salon, "Haircut (men)"), dt.date.fromisoformat(MON), monday_1110)
    assert times(free)[0] == "11:30"


async def test_facial_on_tuesday_offers_wednesday(salon, now):
    """The brief's test question: Kavya is not in on Tuesday, offer the next Mon/Wed/Fri."""
    facial = service(salon, "Facial")
    assert await booking.free_slots(salon, facial, dt.date.fromisoformat(TUE), now) == []
    later = await booking.next_free_days(salon, facial, dt.date.fromisoformat(TUE), now)
    assert f"{later[0][0]:%A %Y-%m-%d %H:%M}" == "Wednesday 2026-11-25 09:00"
    assert f"{later[1][0]:%A}" == "Friday"


async def test_a_booked_slot_is_no_longer_free(salon, now):
    await booking.book(salon, "Haircut (men)", MON, "10:30", "Asha", PHONE, now=now)
    free = await booking.free_slots(salon, service(salon, "Haircut (men)"), dt.date.fromisoformat(MON), now)
    assert "10:30" not in times(free) and "10:00" in times(free)
    # The slot belongs to Anita, so her other services lose it too.
    free = await booking.free_slots(salon, service(salon, "Haircut (women)"), dt.date.fromisoformat(MON), now)
    assert "10:30" not in times(free)


# ---- booking ----

async def test_booking_returns_details(salon, now):
    done = await booking.book(salon, "Hair spa", TUE, "17:00", "Asha", "98765 43210", now=now)
    assert done["with"] == "Rahul Shetty" and done["price"] == "Rs 1,200"
    assert done["when"] == "Tuesday 24 November at 5 PM"


@pytest.mark.parametrize("svc, date, time, why", [
    ("Facial", TUE, "10:00", "does not have a slot"),         # Kavya is off on Tuesday
    ("Haircut (men)", MON, "15:00", "does not have a slot"),   # Anita finishes at 14:00
    ("Haircut (men)", MON, "10:15", "does not have a slot"),   # not on a 30 minute boundary
    ("Haircut (men)", SUN, "10:00", "does not have a slot"),   # closed
    ("Haircut (men)", MON, "07:30pm", "not a time"),
    ("Haircut (men)", "next tuesday", "10:00", "not a date"),
    ("Tattoo", MON, "10:00", "No service called"),
])
async def test_impossible_bookings_are_refused(salon, now, svc, date, time, why):
    with pytest.raises(BookingError, match=why):
        await booking.book(salon, svc, date, time, "Asha", PHONE, now=now)
    assert await count_bookings() == 0


async def test_cannot_book_in_the_past(salon):
    tuesday = dt.datetime(2026, 11, 24, 9, 0, tzinfo=IST)
    with pytest.raises(BookingError, match="already passed"):
        await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=tuesday)


async def test_same_slot_cannot_be_booked_twice(salon, now):
    await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    with pytest.raises(BookingError, match="just been taken"):
        await booking.book(salon, "Haircut (women)", MON, "10:00", "Bela", OTHER_PHONE, now=now)
    assert await count_bookings() == 1


# ---- moving ----

async def test_reschedule_frees_the_old_slot(salon, now):
    made = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    moved = await booking.reschedule(salon, made["booking_id"], PHONE, WED, "11:00", now=now)
    assert moved["moved_to"] == "Wednesday 25 November at 11 AM"
    await booking.book(salon, "Haircut (men)", MON, "10:00", "Bela", OTHER_PHONE, now=now)  # old slot is free again
    assert await count_bookings() == 2


async def test_reschedule_into_a_taken_slot_changes_nothing(salon, now):
    mine = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    await booking.book(salon, "Haircut (men)", MON, "11:00", "Bela", OTHER_PHONE, now=now)
    with pytest.raises(BookingError, match="original booking is unchanged"):
        await booking.reschedule(salon, mine["booking_id"], PHONE, MON, "11:00", now=now)
    assert (await booking.bookings_for_phone(salon, PHONE, now))[0]["when"] == "Monday 23 November at 10 AM"


# ---- cancelling ----

async def test_cancel_early_is_free_and_frees_the_slot(salon, now):
    made = await booking.book(salon, "Hair spa", TUE, "17:00", "Asha", PHONE, now=now)
    result = await booking.cancel(salon, made["booking_id"], PHONE, now=now)
    assert result["free_of_charge"] is True
    await booking.book(salon, "Hair colour", TUE, "17:00", "Bela", OTHER_PHONE, now=now)


async def test_cancel_5pm_booking_at_4pm_is_allowed_but_not_free(salon, now):
    """The brief's test question."""
    made = await booking.book(salon, "Hair spa", TUE, "17:00", "Asha", PHONE, now=now)
    tuesday_4pm = dt.datetime(2026, 11, 24, 16, 0, tzinfo=IST)
    result = await booking.cancel(salon, made["booking_id"], PHONE, now=tuesday_4pm)
    assert result["cancelled"] is True and result["free_of_charge"] is False
    assert await count_bookings() == 0


# ---- privacy: a caller can only see and change bookings made with their own number ----

async def test_bookings_are_only_visible_to_their_own_phone(salon, now):
    await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    assert len(await booking.bookings_for_phone(salon, PHONE, now)) == 1
    assert await booking.bookings_for_phone(salon, OTHER_PHONE, now) == []


async def test_another_phone_cannot_move_or_cancel_my_booking(salon, now):
    mine = await booking.book(salon, "Haircut (men)", MON, "10:00", "Asha", PHONE, now=now)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.cancel(salon, mine["booking_id"], OTHER_PHONE, now=now)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.reschedule(salon, mine["booking_id"], OTHER_PHONE, WED, "10:00", now=now)
    assert await count_bookings() == 1


async def test_a_date_more_than_a_year_away_is_refused(salon, now):
    with pytest.raises(BookingError, match="more than a year away"):
        await booking.book(salon, "Haircut (men)", "2031-11-24", "10:30", "Asha", PHONE, now=now)
    with pytest.raises(BookingError, match="more than a year away"):
        await booking.book(salon, "Haircut (men)", "9999-12-27", "10:30", "Asha", PHONE, now=now)


async def test_the_last_slot_ends_at_closing_time(salon, now):
    # Anita Rao works 10:00 to 14:00: 13:30 is the last slot, 14:00 is not one.
    await booking.book(salon, "Haircut (men)", MON, "13:30", "Asha", PHONE, now=now)
    with pytest.raises(BookingError, match="does not have a slot"):
        await booking.book(salon, "Haircut (men)", MON, "14:00", "Asha", PHONE, now=now)


async def test_a_phone_number_is_the_same_however_it_is_written(salon, now):
    made = await booking.book(salon, "Haircut (men)", MON, "10:30", "Asha", "+91 98765 43210", now=now)
    found = await booking.bookings_for_phone(salon, "098765-43210", now=now)
    assert [b["booking_id"] for b in found] == [made["booking_id"]]
    await booking.cancel(salon, made["booking_id"], "9876543210", now=now)


async def test_cancelling_twice_and_moving_a_cancelled_booking_are_refused(salon, now):
    made = await booking.book(salon, "Haircut (men)", MON, "10:30", "Asha", PHONE, now=now)
    await booking.cancel(salon, made["booking_id"], PHONE, now=now)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.cancel(salon, made["booking_id"], PHONE, now=now)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.reschedule(salon, made["booking_id"], PHONE, WED, "11:00", now=now)


async def test_a_booking_that_has_passed_cannot_be_moved_or_cancelled(salon, now):
    made = await booking.book(salon, "Haircut (men)", MON, "10:30", "Asha", PHONE, now=now)
    next_day = now + dt.timedelta(days=1)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.cancel(salon, made["booking_id"], PHONE, now=next_day)
    with pytest.raises(BookingError, match="No active booking"):
        await booking.reschedule(salon, made["booking_id"], PHONE, WED, "11:00", now=next_day)
