import asyncio
import json
from dataclasses import dataclass
from typing import Any

_subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()


@dataclass
class _EventBusState:
    loop: asyncio.AbstractEventLoop | None = None


_state = _EventBusState()


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    _state.loop = loop


def subscribe() -> asyncio.Queue[tuple[str, dict[str, Any]]]:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[tuple[str, dict[str, Any]]]) -> None:
    _subscribers.discard(queue)


def subscriber_count() -> int:
    """Return the active subscription count for lifecycle diagnostics."""
    return len(_subscribers)


def _deliver(event: str, data: dict[str, Any]) -> None:
    for queue in list(_subscribers):
        queue.put_nowait((event, data))


def broadcast(event: str, data: dict[str, Any]) -> None:
    if _state.loop is None or _state.loop.is_closed():
        return
    _state.loop.call_soon_threadsafe(_deliver, event, data)


def format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
