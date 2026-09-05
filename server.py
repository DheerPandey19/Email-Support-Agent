"""FastAPI front door for the email support graph (async Postgres checkpointer)."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from graph import build_app

load_dotenv()

_SCRIPT_DIR = Path(__file__).resolve().parent
_STATIC_INDEX = _SCRIPT_DIR / "static" / "index.html"


#---pudantic models----

class EmailIn(BaseModel):
    email_content : str
    sender_email: str
    email_id : str | None = None

class ReviewIn(BaseModel):
    approved: bool
    edited_response : str | None=None

#---helper functions---

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_payload(result: dict) -> object | None:
    """Pull the first interrupt value from an ainvoke result."""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _format_invoke_response(thread_id: str, result: dict) -> dict:
    payload = _interrupt_payload(result)
    if payload is not None:
        return {
            "status": "interrupted",
            "thread_id": thread_id,
            "interrupt": payload,
        }
    return {
        "status": "completed",
        "thread_id": thread_id,
        "result": result,
    }


def _pending_from_snapshot(snapshot) -> object | None:
    """Pending interrupt value from aget_state (survives server restart)."""
    for task in snapshot.tasks:
        if task.interrupts:
            first = task.interrupts[0]
            return getattr(first, "value", first)
    return None

#---lifespan---

@asynccontextmanager

async def lifespan(app: FastAPI):
    db_uri = os.environ["DATABASE_URL"]
    pool = AsyncConnectionPool(
        conninfo=db_uri,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    app.state.pool = pool
    app.state.graph = build_app(checkpointer)  # never get_sync_app here
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(lifespan=lifespan)

# --- Endpoints ---


@app.get("/")
async def review_page():
    if not _STATIC_INDEX.is_file():
        raise HTTPException(status_code=404, detail="static/index.html missing")
    return FileResponse(_STATIC_INDEX)


@app.post("/emails")
async def create_email(body: EmailIn, request: Request):
    graph = request.app.state.graph
    thread_id = str(uuid.uuid4())
    email_id = body.email_id or str(uuid.uuid4())
    result = await graph.ainvoke(
        {
            "email_content": body.email_content,
            "sender_email": body.sender_email,
            "email_id": email_id,
        },
        _config(thread_id),
    )
    return _format_invoke_response(thread_id, result)


@app.get("/emails/{thread_id}")
async def get_email(thread_id: str, request: Request):
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_config(thread_id))
    if snapshot.values is None or snapshot.values == {}:
        # No checkpoint yet (or empty) — treat as not found
        raise HTTPException(status_code=404, detail="Unknown thread_id")

    pending = _pending_from_snapshot(snapshot)
    if pending is not None:
        return {
            "status": "interrupted",
            "thread_id": thread_id,
            "interrupt": pending,
        }
    return {
        "status": "completed",
        "thread_id": thread_id,
        "result": snapshot.values,
    }


@app.post("/emails/{thread_id}/review")
async def review_email(thread_id: str, body: ReviewIn, request: Request):
    graph = request.app.state.graph
    resume: dict = {"approved": body.approved}
    if body.edited_response is not None:
        resume["edited_response"] = body.edited_response

    result = await graph.ainvoke(
        Command(resume=resume),
        _config(thread_id),
    )
    return _format_invoke_response(thread_id, result)