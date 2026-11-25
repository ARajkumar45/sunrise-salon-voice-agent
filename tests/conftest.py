"""Shared test setup.

Tests run against a real Postgres, in a separate throwaway database called
`receptionist_test`, so they can never touch live data. Run them with:

    docker compose --profile test run --rm tests
"""

import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest
import yaml

# Point the app at the throwaway database BEFORE app.db is used.
LIVE_URL = os.environ["DATABASE_URL"]
TEST_URL = LIVE_URL.rsplit("/", 1)[0] + "/receptionist_test"
os.environ["DATABASE_URL"] = TEST_URL
os.environ["DB_POOL_MAX"] = "20"  # enough real connections to race against each other

from app import db  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
# A fixed "now" so tests give the same result every day: Monday 23 November 2026, 08:00 IST.
MONDAY_8AM = dt.datetime(2026, 11, 23, 8, 0, tzinfo=IST)
DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="session", autouse=True)
async def database():
    with psycopg.connect(LIVE_URL, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS receptionist_test WITH (FORCE)")
        admin.execute("CREATE DATABASE receptionist_test")
    await db.init_schema()
    await db.save_business(yaml.safe_load((DATA / "sunrise-salon.yaml").read_text()))
    yield
    await db.close()


@pytest.fixture
async def salon(database) -> dict:
    """Sunrise Salon with no bookings."""
    async with (await db.pool()).connection() as conn:
        await conn.execute("TRUNCATE bookings RESTART IDENTITY")
    return await db.load_business("sunrise-salon")


@pytest.fixture
def now() -> dt.datetime:
    return MONDAY_8AM


async def count_bookings(where: str = "status = 'booked'") -> int:
    async with (await db.pool()).connection() as conn:
        cur = await conn.execute(f"SELECT count(*) AS n FROM bookings WHERE {where}")
        return (await cur.fetchone())["n"]
