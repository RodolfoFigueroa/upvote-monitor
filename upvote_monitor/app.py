import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from upvote_monitor.api.router import api_router
from upvote_monitor.config import settings
from upvote_monitor.db.engine import init_db
from upvote_monitor.scheduler import (
    queue_refresh_run,
    shutdown_scheduler,
    start_scheduler,
)
from upvote_monitor.services.event_bus import set_event_loop
from upvote_monitor.spa import STATIC_DIR, SPAStaticFiles

__all__ = ["app", "create_app", "settings"]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    set_event_loop(asyncio.get_running_loop())
    should_queue_initial_refresh = init_db()
    start_scheduler()
    if should_queue_initial_refresh:
        queue_refresh_run()
    yield
    shutdown_scheduler()


def create_app() -> FastAPI:
    application = FastAPI(title="Upvote Monitor", lifespan=lifespan)
    if settings.cors_dev:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    application.include_router(api_router)
    if STATIC_DIR.is_dir():
        application.mount(
            "/",
            SPAStaticFiles(directory=STATIC_DIR, html=True),
            name="spa",
        )
    return application


app = create_app()
