"""All database access lives in this file.

Rule: every function that reads or writes business data takes a business id
(or a slug it resolves first) and filters on it. That is what keeps one
business from ever seeing another's data.
"""

import datetime as dt
import json
import os
from pathlib import Path

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


async def save_business(data: dict) -> int:
    """Create or update a business from a data file. One transaction: all or nothing.

    Staff and services are matched by name. Ones missing from the file are switched off
    (active = false) rather than deleted, so old bookings keep pointing at real rows.
    """
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
             "not_offered": [], "notes": [], **data})
        business_id = (await cur.fetchone())["id"]

        await conn.execute("UPDATE staff SET active = FALSE WHERE business_id = %s", (business_id,))
        staff_ids = {}
        for person in data.get("staff", []):
            cur = await conn.execute(
                """INSERT INTO staff (business_id, name, does) VALUES (%s, %s, %s)
                   ON CONFLICT (business_id, name) DO UPDATE SET does = EXCLUDED.does, active = TRUE
                   RETURNING id""",
                (business_id, person["name"], person.get("does", "")))
            staff_id = staff_ids[person["name"]] = (await cur.fetchone())["id"]
            start, end = person["hours"].split("-")
            await conn.execute("DELETE FROM staff_hours WHERE staff_id = %s", (staff_id,))
            for day in person["days"]:
                await conn.execute(
                    "INSERT INTO staff_hours (staff_id, weekday, start_time, end_time) VALUES (%s, %s, %s, %s)",
                    (staff_id, WEEKDAYS.index(day.lower()[:3]), start, end))

        await conn.execute("UPDATE services SET active = FALSE WHERE business_id = %s", (business_id,))
        for service in data.get("services", []):
            await conn.execute(
                """INSERT INTO services (business_id, staff_id, name, price) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (business_id, name) DO UPDATE SET
                       staff_id = EXCLUDED.staff_id, price = EXCLUDED.price, active = TRUE""",
                (business_id, staff_ids[service["staff"]], service["name"], service["price"]))

        await conn.execute("DELETE FROM faqs WHERE business_id = %s", (business_id,))
        for faq in data.get("faqs", []):
            await conn.execute(
                "INSERT INTO faqs (business_id, topic, answer) VALUES (%s, %s, %s)",
                (business_id, faq["topic"], faq["answer"]))
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


async def log_event(call_id: int, kind: str, data: dict) -> None:
    async with (await pool()).connection() as conn:
        await conn.execute(
            "INSERT INTO call_events (call_id, kind, data) VALUES (%s, %s, %s)",
            (call_id, kind, json.dumps(data, default=str)))


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
            "SELECT at, kind, data FROM call_events WHERE call_id = %s ORDER BY id", (call_id,))
        return await cur.fetchall()


def format_time(value: dt.time) -> str:
    """10:00 -> '10 AM', 16:30 -> '4:30 PM'. Spoken-friendly."""
    hour = value.hour % 12 or 12
    minutes = f":{value.minute:02d}" if value.minute else ""
    return f"{hour}{minutes} {'AM' if value.hour < 12 else 'PM'}"
