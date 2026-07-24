from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from upvote_monitor.db.engine import engine
from upvote_monitor.services.event_bus import format_sse, subscribe, unsubscribe
from upvote_monitor.services.refresh_status import get_refresh_status

router = APIRouter(prefix="/events", tags=["events"])


async def _event_stream() -> AsyncIterator[str]:
    queue = subscribe()
    try:
        yield format_sse("connected", {})

        with Session(engine) as session:
            refresh_status = get_refresh_status(session).model_dump(mode="json")
        yield format_sse("refresh_status", refresh_status)

        while True:
            event, data = await queue.get()
            yield format_sse(event, data)
    finally:
        unsubscribe(queue)


@router.get("")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
