"""The instructions the agent gets: dates in the business's own timezone, opening times
worked out from staff hours, and no number that belongs to one particular business."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.prompt import build_instructions

# 23 November 2026, 20:00 UTC. In India it is already 01:30 on Tuesday the 24th;
# in New York it is still 3 PM on Monday the 23rd.
MOMENT = dt.datetime(2026, 11, 23, 20, 0, tzinfo=dt.timezone.utc)


def test_today_and_tomorrow_follow_the_business_timezone(salon):
    india = build_instructions(salon, MOMENT)
    assert "Today is 2026-11-24, tomorrow is 2026-11-25" in india and "Tuesday 24 November 2026, 01:30 AM" in india
    new_york = build_instructions({**salon, "timezone": "America/New_York"}, MOMENT)
    assert "Today is 2026-11-23, tomorrow is 2026-11-24" in new_york


def test_the_dates_list_names_each_weekday_once_so_next_tuesday_is_unambiguous(salon):
    dates = next(line for line in build_instructions(salon, MOMENT).splitlines() if line.startswith("Dates:"))
    assert "Tue 24 Nov=2026-11-24" in dates and "Tue 01 Dec=2026-12-01" in dates
    assert "Sun 29 Nov=2026-11-29" in dates


def test_opening_times_are_worked_out_from_who_is_working(salon):
    text = build_instructions(salon, MOMENT)
    assert "Monday 9 AM to 2 PM;" in text                       # Kavya from 9, Anita until 2
    assert "Tuesday 10 AM to 2 PM and 4 PM to 8 PM;" in text    # a gap in the afternoon
    assert "Closed on: Sunday." in text


def test_the_rules_carry_no_number_from_one_business(salon, garage):
    # The salon gives 2 hours' notice and the garage 24; neither number may be fixed in the rules.
    assert "24 hours" in build_instructions(garage, MOMENT)
    assert "2 hours" not in build_instructions(garage, MOMENT).replace("24 hours", "")
    assert "2 hours" not in build_instructions({**salon, "free_cancellation_hours": 5}, MOMENT)
