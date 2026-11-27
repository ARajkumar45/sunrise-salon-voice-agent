"""All database access lives in this file.

Rule: every function that reads or writes business data takes a business id
(or a slug it resolves first) and filters on it. That is what keeps one
business from ever seeing another's data.
"""

import datetime as dt
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA_FILE = Path(__file__).parent / "schema.sql"
DATA_DIR = Path(__file__).parent.parent / "data"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # index = weekday number

_pool: AsyncConnectionPool | None = None


async def pool() -> AsyncConnectionPool:
    """One small connection pool per process, opened the first time it is needed."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            os.environ["DATABASE_URL"], min_size=1, max_size=int(os.environ.get("DB_POOL_MAX", "5")), open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await _pool.open()
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(SCHEMA_FILE.read_text())


async def seed_missing_businesses() -> list[str]:
    """Load every data/*.yaml whose business is not in the database yet.

    Existing businesses are left alone, so a restart never overwrites live edits.
    """
    loaded = []
    for path in sorted(DATA_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if await get_business_row(data["slug"]) is None:
            await save_business(data)
            loaded.append(data["slug"])
    return loaded


# ---------- business info ----------

async def get_business_row(slug: str) -> dict | None:
    async with (await pool()).connection() as conn:
        cur = await conn.execute("SELECT * FROM businesses WHERE slug = %s", (slug,))
        return await cur.fetchone()


async def first_business_slug() -> str | None:
    async with (await pool()).connection() as conn:
        cur = await conn.execute("SELECT slug FROM businesses ORDER BY id LIMIT 1")
        row = await cur.fetchone()
        return row["slug"] if row else None


async def load_business(slug: str) -> dict | None:
    """Everything the agent needs to know about one business, read fresh for each call."""
    business = await get_business_row(slug)
    if business is None:
        return None
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "SELECT id, name, does FROM staff WHERE business_id = %s AND active ORDER BY id",
            (business["id"],))
        staff = await cur.fetchall()
        for person in staff:
            cur = await conn.execute(
                "SELECT weekday, start_time, end_time FROM staff_hours WHERE staff_id = %s ORDER BY weekday",
                (person["id"],))
            person["hours"] = await cur.fetchall()
        cur = await conn.execute(
            """SELECT s.id, s.name, s.price, s.staff_id, st.name AS staff_name
               FROM services s JOIN staff st ON st.id = s.staff_id
               WHERE s.business_id = %s AND s.active AND st.active ORDER BY s.id""",
            (business["id"],))
        services = await cur.fetchall()
        cur = await conn.execute(
            "SELECT topic, answer FROM faqs WHERE business_id = %s ORDER BY id", (business["id"],))
        faqs = await cur.fetchall()
    return {**business, "staff": staff, "services": services, "faqs": faqs}


async def export_business(slug: str) -> dict | None:
    """The business as a data file would describe it. The opposite of save_business."""
    business = await load_business(slug)
    if business is None:
        return None
    return {
        "slug": business["slug"], "name": business["name"], "timezone": business["timezone"],
        "address": business["address"], "slot_minutes": business["slot_minutes"],
        "staff_word": business["staff_word"], "greeting": business["greeting"],
        "free_cancellation_hours": business["free_cancellation_hours"],
        "staff": [{"name": p["name"], "does": p["does"],
                   "days": [WEEKDAYS[h["weekday"]] for h in p["hours"]],
                   "hours": f"{p['hours'][0]['start_time']:%H:%M}-{p['hours'][0]['end_time']:%H:%M}"}
                  for p in business["staff"] if p["hours"]],
        "services": [{"name": s["name"], "staff": s["staff_name"], "price": s["price"]} for s in business["services"]],
        "not_offered": business["not_offered"], "notes": business["notes"],
        "faqs": [{"topic": f["topic"], "answer": f["answer"]} for f in business["faqs"]],
    }


async def call_belongs_to(call_id: int, slug: str) -> bool:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM calls c JOIN businesses b ON b.id = c.business_id WHERE c.id = %s AND b.slug = %s",
            (call_id, slug))
        return await cur.fetchone() is not None


def check_business_data(data: dict) -> None:
    """Refuse business details that would break calls, with a reason in plain words."""
    def need(ok, message: str) -> None:
        if not ok:
            raise ValueError(message)

    def text(value) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def rows(key: str) -> list:
        value = data.get(key) or []
        need(isinstance(value, list) and all(isinstance(row, dict) for row in value),
             f"'{key}' must be a list of entries, each starting with a dash.")
        return value

    need(isinstance(data, dict), "The details must be a list of 'name: value' lines.")
    for field in ("slug", "name", "timezone", "address", "greeting"):
        need(text(data.get(field)), f"'{field}' is missing or empty.")
    need(re.fullmatch(r"[a-z0-9-]{1,60}", data["slug"]), "'slug' may only have small letters, digits and dashes.")
    try:
        ZoneInfo(data["timezone"])
    except Exception:
        raise ValueError(f"'{data['timezone']}' is not a timezone name. Example: Asia/Kolkata.") from None
    slot = data.get("slot_minutes", 30)
    need(type(slot) is int and 5 <= slot <= 480, "'slot_minutes' must be a whole number from 5 to 480.")
    notice = data.get("free_cancellation_hours", 0)
    need(type(notice) is int and 0 <= notice <= 720, "'free_cancellation_hours' must be a whole number from 0 to 720.")
    for key in ("not_offered", "notes"):
        need(all(isinstance(item, str) for item in data.get(key) or []), f"'{key}' must be a list of short texts.")

    names = set()
    for person in rows("staff"):
        name = person.get("name")
        need(text(name), "Every staff member needs a name.")
        need(name not in names, f"'{name}' is in the staff list twice.")
        names.add(name)
        days = person.get("days")
        need(isinstance(days, list) and days and all(str(day).lower()[:3] in WEEKDAYS for day in days),
             f"{name}: 'days' must list at least one day, for example [mon, wed, fri].")
        try:
            start, end = (dt.time.fromisoformat(part.strip()) for part in str(person.get("hours")).split("-"))
        except ValueError:
            raise ValueError(f"{name}: 'hours' must look like 10:00-14:00 (24-hour clock).") from None
        minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        need(minutes >= slot, f"{name}: the hours must end at least one {slot}-minute slot after they start.")
    seen = set()
    for service in rows("services"):
        need(text(service.get("name")), "Every service needs a name.")
        need(service["name"] not in seen, f"'{service['name']}' is in the services list twice.")
        seen.add(service["name"])
        need(service.get("staff") in names, f"Service '{service['name']}' names a staff member who is not in the staff list.")
        need(str(service.get("price") or "").strip(), f"Service '{service['name']}' needs a price.")
    for faq in rows("faqs"):
        need(text(faq.get("topic")) and text(faq.get("answer")), "Every FAQ needs a topic and an answer.")


async def bookings_that_no_longer_fit(conn, business_id: int, zone: ZoneInfo, slot_minutes: int) -> list[str]:
    """Upcoming bookings that the details now in the database have no slot for.

    Double booking is prevented per staff member and start time. A booking left behind on a
    renamed or removed staff member, or off the slot grid after the hours or the slot length
    changed, would no longer block its time, and that time could be sold twice.
    """
    cur = await conn.execute(
        """SELECT h.staff_id, h.weekday, h.start_time, h.end_time
           FROM staff_hours h JOIN staff st ON st.id = h.staff_id WHERE st.business_id = %s""", (business_id,))
    hours = {(h["staff_id"], h["weekday"]): h for h in await cur.fetchall()}
    cur = await conn.execute(
        """SELECT b.staff_id, b.starts_at, s.name AS service, st.name AS staff,
                  (st.active AND s.active AND s.staff_id = b.staff_id) AS still_offered
           FROM bookings b JOIN services s ON s.id = b.service_id JOIN staff st ON st.id = b.staff_id
           WHERE b.business_id = %s AND b.status = 'booked' AND b.starts_at > now() ORDER BY b.starts_at""",
        (business_id,))
    left_out = []
    for row in await cur.fetchall():
        local = row["starts_at"].astimezone(zone)
        day = hours.get((row["staff_id"], local.weekday()))
        fits = False
        if row["still_offered"] and day is not None:
            since_start = (local.hour * 60 + local.minute) - (day["start_time"].hour * 60 + day["start_time"].minute)
            until_end = (day["end_time"].hour * 60 + day["end_time"].minute) - (local.hour * 60 + local.minute)
            fits = since_start >= 0 and since_start % slot_minutes == 0 and until_end >= slot_minutes
        if not fits:
            left_out.append(f"{row['service']} with {row['staff']} on {local:%a %d %b} at {local:%H:%M}")
    return left_out


async def save_business(data: dict) -> int:
    """Create or update a business from a data file. One transaction: all or nothing.

    Staff and services are matched by name. Ones missing from the file are switched off
    (active = false) rather than deleted, so old bookings keep pointing at real rows.
    A change that would leave an upcoming booking without a slot is refused as a whole.
    """
    check_business_data(data)
    async with (await pool()).connection() as conn, conn.transaction():
        cur = await conn.execute(
            """INSERT INTO businesses (slug, name, timezone, address, slot_minutes, greeting,
                                       staff_word, free_cancellation_hours, not_offered, notes)
               VALUES (%(slug)s, %(name)s, %(timezone)s, %(address)s, %(slot_minutes)s, %(greeting)s,
                       %(staff_word)s, %(free_cancellation_hours)s, %(not_offered)s, %(notes)s)
               ON CONFLICT (slug) DO UPDATE SET
                   name = EXCLUDED.name, timezone = EXCLUDED.timezone, address = EXCLUDED.address,
                   slot_minutes = EXCLUDED.slot_minutes, greeting = EXCLUDED.greeting,
                   staff_word = EXCLUDED.staff_word,
                   free_cancellation_hours = EXCLUDED.free_cancellation_hours,
                   not_offered = EXCLUDED.not_offered, notes = EXCLUDED.notes
               RETURNING id""",
            {"slot_minutes": 30, "staff_word": "staff member", "free_cancellation_hours": 0,
             **data, "not_offered": data.get("not_offered") or [], "notes": data.get("notes") or []})
        business_id = (await cur.fetchone())["id"]

        await conn.execute("UPDATE staff SET active = FALSE WHERE business_id = %s", (business_id,))
        staff_ids = {}
        for person in data.get("staff") or []:
            cur = await conn.execute(
                """INSERT INTO staff (business_id, name, does) VALUES (%s, %s, %s)
                   ON CONFLICT (business_id, name) DO UPDATE SET does = EXCLUDED.does, active = TRUE
                   RETURNING id""",
                (business_id, person["name"], person.get("does", "")))
            staff_id = staff_ids[person["name"]] = (await cur.fetchone())["id"]
            start, end = (part.strip() for part in str(person["hours"]).split("-"))
            await conn.execute("DELETE FROM staff_hours WHERE staff_id = %s", (staff_id,))
            for day in person["days"]:
                await conn.execute(
                    "INSERT INTO staff_hours (staff_id, weekday, start_time, end_time) VALUES (%s, %s, %s, %s)",
                    (staff_id, WEEKDAYS.index(str(day).lower()[:3]), start, end))

        await conn.execute("UPDATE services SET active = FALSE WHERE business_id = %s", (business_id,))
        for service in data.get("services") or []:
            await conn.execute(
                """INSERT INTO services (business_id, staff_id, name, price) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (business_id, name) DO UPDATE SET
                       staff_id = EXCLUDED.staff_id, price = EXCLUDED.price, active = TRUE""",
                (business_id, staff_ids[service["staff"]], service["name"], str(service["price"]).strip()))

        await conn.execute("DELETE FROM faqs WHERE business_id = %s", (business_id,))
        for faq in data.get("faqs") or []:
            await conn.execute(
                "INSERT INTO faqs (business_id, topic, answer) VALUES (%s, %s, %s)",
                (business_id, faq["topic"], faq["answer"]))

        left_out = await bookings_that_no_longer_fit(
            conn, business_id, ZoneInfo(data["timezone"]), data.get("slot_minutes", 30))
        if left_out:
            more = f" and {len(left_out) - 3} more" if len(left_out) > 3 else ""
            raise ValueError(
                f"{len(left_out)} upcoming booking(s) would no longer fit: {'; '.join(left_out[:3])}{more}. "
                "Nothing was saved. Move or cancel those bookings first, or keep that staff member's "
                "name, days and hours, the service's staff member and the slot length as they were.")
    return business_id


# ---------- call logs ----------

async def start_call(business_id: int, room: str) -> int:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "INSERT INTO calls (business_id, room) VALUES (%s, %s) RETURNING id", (business_id, room))
        return (await cur.fetchone())["id"]


async def end_call(call_id: int) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute("UPDATE calls SET ended_at = now() WHERE id = %s", (call_id,))


async def log_event(call_id: int, kind: str, data: dict, at: dt.datetime | None = None) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            "INSERT INTO call_events (call_id, kind, data, at) VALUES (%s, %s, %s, COALESCE(%s, now()))",
            (call_id, kind, json.dumps(data, default=str), at))


async def add_staff_message(business_id: int, call_id: int | None, message: str,
                            caller_name: str = "", caller_phone: str = "") -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            """INSERT INTO staff_messages (business_id, call_id, caller_name, caller_phone, message)
               VALUES (%s, %s, %s, %s, %s)""",
            (business_id, call_id, caller_name, caller_phone, message))


async def list_staff_messages(slug: str, limit: int = 20) -> list[dict]:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            """SELECT m.created_at, m.caller_name, m.caller_phone, m.message, m.call_id
               FROM staff_messages m JOIN businesses b ON b.id = m.business_id
               WHERE b.slug = %s ORDER BY m.id DESC LIMIT %s""", (slug, limit))
        return await cur.fetchall()


async def list_calls(slug: str, limit: int = 20) -> list[dict]:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            """SELECT c.id, c.room, c.started_at, c.ended_at,
                      (SELECT count(*) FROM call_events e WHERE e.call_id = c.id AND e.kind = 'said') AS lines
               FROM calls c JOIN businesses b ON b.id = c.business_id
               WHERE b.slug = %s ORDER BY c.id DESC LIMIT %s""", (slug, limit))
        return await cur.fetchall()


async def get_call_events(call_id: int) -> list[dict]:
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            "SELECT at, kind, data FROM call_events WHERE call_id = %s ORDER BY at, id", (call_id,))
        return await cur.fetchall()


async def latency_rows(slug: str, from_call: int = 0) -> list[dict]:
    """The timing record of every reply, for calls with id >= from_call."""
    async with (await pool()).connection() as conn:
        cur = await conn.execute(
            """SELECT e.call_id, e.data FROM call_events e
               JOIN calls c ON c.id = e.call_id JOIN businesses b ON b.id = c.business_id
               WHERE b.slug = %s AND e.kind = 'latency' AND c.id >= %s ORDER BY e.id""", (slug, from_call))
        return await cur.fetchall()


def format_time(value: dt.time) -> str:
    """10:00 -> '10 AM', 16:30 -> '4:30 PM'. Spoken-friendly."""
    hour = value.hour % 12 or 12
    minutes = f":{value.minute:02d}" if value.minute else ""
    return f"{hour}{minutes} {'AM' if value.hour < 12 else 'PM'}"
