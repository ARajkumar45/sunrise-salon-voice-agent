"""The small web server: serves the call page and hands out call tokens.

Run locally: uvicorn app.web:app --port 8000
"""

import json
import os
import uuid
from pathlib import Path

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from livekit import api

from app import db
from app.admin import router as admin_router

load_dotenv()

AGENT_NAME = "receptionist"
DEFAULT_BUSINESS = "sunrise-salon"
STATIC = Path(__file__).parent / "static"



@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup: create the tables if needed and load any business file not in the database yet."""
    await db.init_schema()
    await db.seed_missing_businesses()
    yield
    await db.close()


app = FastAPI(title="Voice receptionist", lifespan=lifespan)
app.include_router(admin_router)


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse(f"/call/{DEFAULT_BUSINESS}")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/call/{business}")
def call_page(business: str) -> FileResponse:
    """The same page serves every business. The page reads the slug from its own URL."""
    return FileResponse(STATIC / "call.html")


@app.get("/api/business/{business}")
async def business_name(business: str) -> dict:
    """Only the public name, for the page heading."""
    row = await db.get_business_row(business)
    if row is None:
        raise HTTPException(404, "No such business")
    return {"name": row["name"]}


@app.get("/api/token")
async def token(business: str) -> dict:
    """Create a one-off room for this call and a token that lets the browser join it.

    The token also tells LiveKit to send our agent into the room, and carries the
    business slug as metadata. That is how the agent knows which business was called.
    The caller cannot change it: the token is signed with our LiveKit secret.
    """
    if await db.get_business_row(business) is None:
        raise HTTPException(404, "No such business")
    room_name = f"{business}-{uuid.uuid4().hex[:10]}"
    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(f"caller-{uuid.uuid4().hex[:8]}")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=AGENT_NAME,
                        metadata=json.dumps({"business": business}),
                    )
                ]
            )
        )
        .to_jwt()
    )
    return {"url": os.environ["LIVEKIT_URL"], "token": jwt, "room": room_name}
