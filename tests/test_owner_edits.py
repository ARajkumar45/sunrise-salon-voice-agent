"""Edits from the owner page (and from data files): bad values are refused in plain words,
and no edit may leave an upcoming booking without a slot, because that slot could then be
booked a second time."""

import copy
import datetime as dt

import pytest
import yaml
from fastapi import HTTPException

from app import booking, db
from app.admin import check_key
from tests.conftest import DATA, count_bookings

PHONE = "9876543210"


def salon_file() -> dict:
    return yaml.safe_load((DATA / "sunrise-salon.yaml").read_text())


@pytest.fixture
async def booked(salon):
    """One real upcoming booking with Anita Rao at 10:30, and the file put back afterwards."""
    day = booking.now_at(salon).date() + dt.timedelta(days=3)
    while not booking.slots_on(salon, booking.find_service(salon, "Haircut (men)"), day):
        day += dt.timedelta(days=1)
    await booking.book(salon, "Haircut (men)", day.isoformat(), "10:30", "Asha", PHONE)
    yield day
    async with (await db.pool()).connection() as conn:
        await conn.execute("TRUNCATE bookings RESTART IDENTITY")
    await db.save_business(salon_file())


def with_change(change) -> dict:
    data = copy.deepcopy(salon_file())
    change(data)
    return data


def rename_anita(data):
    data["staff"][0]["name"] = "Anitha Rao"
    for service in data["services"]:
        if service["staff"] == "Anita Rao":
            service["staff"] = "Anitha Rao"


def hour_long_slots(data):
    data["slot_minutes"] = 60


def anita_starts_at_11(data):
    data["staff"][0]["hours"] = "11:00-14:00"


def anita_stops_working_that_day(day):
    def change(data):
        data["staff"][0]["days"] = [d for d in data["staff"][0]["days"] if d != db.WEEKDAYS[day.weekday()]]
    return change


def haircut_moves_to_kavya(data):
    next(s for s in data["services"] if s["name"] == "Haircut (men)")["staff"] = "Kavya Nair"


@pytest.mark.parametrize("change", [rename_anita, hour_long_slots, anita_starts_at_11, haircut_moves_to_kavya])
async def test_an_edit_that_would_orphan_a_booking_is_refused_and_changes_nothing(booked, change):
    with pytest.raises(ValueError, match="would no longer fit"):
        await db.save_business(with_change(change))
    # Nothing was saved, so the booked slot is still blocked and cannot be sold twice.
    salon = await db.load_business("sunrise-salon")
    assert salon["slot_minutes"] == 30 and salon["staff"][0]["name"] == "Anita Rao"
    with pytest.raises(booking.BookingError, match="taken"):
        await booking.book(salon, "Haircut (men)", booked.isoformat(), "10:30", "Ravi", "9000000001")
    assert await count_bookings() == 1


async def test_removing_the_booked_working_day_is_refused(booked):
    with pytest.raises(ValueError, match="would no longer fit"):
        await db.save_business(with_change(anita_stops_working_that_day(booked)))


async def test_the_same_edits_are_fine_when_no_booking_is_affected(booked):
    def price_and_later_finish(data):
        data["services"][0]["price"] = "Rs 650"
        data["staff"][0]["hours"] = "10:00-15:00"   # longer day: the 10:30 booking still fits
    await db.save_business(with_change(price_and_later_finish))
    salon = await db.load_business("sunrise-salon")
    assert booking.find_service(salon, "Haircut (women)")["price"] == "Rs 650"


def bad(change, message):
    with pytest.raises(ValueError, match=message):
        db.check_business_data(with_change(change))


def test_values_that_would_break_calls_are_refused_in_plain_words():
    db.check_business_data(salon_file())  # the real file passes
    db.check_business_data(yaml.safe_load((DATA / "greenline-auto-care.yaml").read_text()))
    bad(lambda d: d.update(slot_minutes=0), "slot_minutes")           # would loop for ever
    bad(lambda d: d.update(slot_minutes=-30), "slot_minutes")
    bad(lambda d: d.update(slot_minutes="thirty"), "slot_minutes")
    bad(lambda d: d.update(timezone="Asia/Bangalor"), "not a timezone")
    bad(lambda d: d.update(name="  "), "'name' is missing")
    bad(lambda d: d.update(greeting=None), "'greeting' is missing")
    bad(lambda d: d.update(free_cancellation_hours=-1), "free_cancellation_hours")
    bad(lambda d: d["staff"][0].update(hours="14:00-10:00"), "hours must end")
    bad(lambda d: d["staff"][0].update(hours="10:00-24:00"), "must look like")
    bad(lambda d: d["staff"][0].update(hours="ten to two"), "must look like")
    bad(lambda d: d["staff"][0].update(days=[]), "at least one day")
    bad(lambda d: d["staff"][0].update(days=["funday"]), "at least one day")
    bad(lambda d: d.update(staff=["Anita Rao"]), "list of entries")
    bad(lambda d: d.update(staff=None), "not in the staff list")       # services now name nobody
    bad(lambda d: d["staff"].append(dict(d["staff"][0])), "twice")
    bad(lambda d: d["services"][0].update(staff="Nobody"), "not in the staff list")
    bad(lambda d: d["services"][0].update(price=""), "needs a price")
    bad(lambda d: d["faqs"].append({"topic": "Parking"}), "topic and an answer")


def test_owner_key_must_match_exactly(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "correct-key")
    check_key("correct-key")
    for wrong in ["", "correct-ke", "correct-key ", "é", "ключ"]:
        with pytest.raises(HTTPException) as refused:
            check_key(wrong)
        assert refused.value.status_code == 403
    monkeypatch.setenv("ADMIN_KEY", "")  # no key set: nobody gets in
    with pytest.raises(HTTPException):
        check_key("")
