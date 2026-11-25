"""The small web server: serves the call page and hands out call tokens.

Run locally: uvicorn app.web:app --port 8000
"""

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from livekit import api

load_dotenv()

AGENT_NAME = "receptionist"
DEFAULT_BUSINESS = "sunrise-salon"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Voice receptionist")


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


@app.get("/api/token")
def token(business: str) -> dict:
    """Create a one-off room for this call and a token that lets the browser join it.

    The token also tells LiveKit to send our agent into the room, and carries the
    business slug as metadata. That is how the agent knows which business was called.
    The caller cannot change it: the token is signed with our LiveKit secret.
    """
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
