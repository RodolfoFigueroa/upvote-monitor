import asyncio
import json
from typing import Any

_subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue[tuple[str, dict[str, Any]]]:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[tuple[str, dict[str, Any]]]) -> None:
    _subscribers.discard(queue)


def _deliver(event: str, data: dict[str, Any]) -> None:
    for queue in list(_subscribers):
        queue.put_nowait((event, data))


def broadcast(event: str, data: dict[str, Any]) -> None:
    if _loop is None or _loop.is_closed():
        return
    _loop.call_soon_threadsafe(_deliver, event, data)


def format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
