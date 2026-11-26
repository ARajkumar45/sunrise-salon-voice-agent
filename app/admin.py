"""The owner's page: edit the business's details and read call logs.

    /admin/<business>?key=<ADMIN_KEY>

This is deliberately small. It is protected by one shared key from the .env file, which is
enough for a demo but is not real user accounts (a proper staff login is listed as future work).
Saving here writes to the database, and the very next call uses the new details.
"""

import hmac
import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from app import db
from app.manage import describe_event, latency_report

router = APIRouter(prefix="/admin")
PAGE = Path(__file__).parent / "static" / "admin.html"


def check_key(key: str) -> None:
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected or not hmac.compare_digest(key, expected):
        raise HTTPException(403, "Wrong or missing key")


@router.get("/{business}")
def admin_page(business: str, key: str = "") -> FileResponse:
    check_key(key)
    return FileResponse(PAGE)


@router.get("/{business}/data", response_class=PlainTextResponse)
async def get_data(business: str, key: str = "") -> str:
    check_key(key)
    data = await db.export_business(business)
    if data is None:
        raise HTTPException(404, "No such business")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


@router.post("/{business}/data", response_class=PlainTextResponse)
async def save_data(business: str, request: Request, key: str = "") -> str:
    """Check the edited text carefully before saving, and explain mistakes in plain words."""
    check_key(key)
    try:
        data = yaml.safe_load((await request.body()).decode())
    except yaml.YAMLError as error:
        raise HTTPException(400, f"The text is not laid out correctly: {error}") from None
    if not isinstance(data, dict) or data.get("slug") != business:
        raise HTTPException(400, f"The 'slug' line must stay as: {business}")
    staff_names = {person.get("name") for person in data.get("staff", [])}
    for service in data.get("services", []):
        if service.get("staff") not in staff_names:
            raise HTTPException(400, f"Service '{service.get('name')}' names a staff member who is not in the staff list.")
    try:
        await db.save_business(data)
    except Exception as error:  # a missing field, a bad time, an unknown day name...
        raise HTTPException(400, f"Could not save: {error}") from None
    return "Saved. The next call will use the new details."


@router.get("/{business}/calls", response_class=PlainTextResponse)
async def calls(business: str, key: str = "") -> str:
    check_key(key)
    rows = await db.list_calls(business, limit=50)
    lines = [f"call {c['id']:>4}   {c['started_at']:%d %b %H:%M:%S} UTC   {c['lines']} lines spoken" for c in rows]
    return "Recent calls (newest first). Open one with /admin/<business>/calls/<number>?key=...\n\n" + "\n".join(lines)


@router.get("/{business}/calls/{call_id}", response_class=PlainTextResponse)
async def one_call(business: str, call_id: int, key: str = "") -> str:
    check_key(key)
    if not await db.call_belongs_to(call_id, business):  # a business can only read its own calls
        raise HTTPException(404, "No such call for this business")
    events = await db.get_call_events(call_id)
    return "\n".join(f"{e['at']:%H:%M:%S}  {describe_event(e)}" for e in events) or "Nothing was said on this call."


@router.get("/{business}/messages", response_class=PlainTextResponse)
async def messages(business: str, key: str = "") -> str:
    check_key(key)
    rows = await db.list_staff_messages(business, limit=50)
    return "\n".join(f"{m['created_at']:%d %b %H:%M}  {m['caller_name']} {m['caller_phone']}: {m['message']}"
                     for m in rows) or "No messages."


@router.get("/{business}/latency", response_class=PlainTextResponse)
async def latency(business: str, key: str = "", from_call: int = 0) -> str:
    check_key(key)
    return latency_report(await db.latency_rows(business, from_call))
