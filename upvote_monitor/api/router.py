from fastapi import APIRouter

from upvote_monitor.api import events, health, items, refresh, rules, settings

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(items.router)
api_router.include_router(settings.router)
api_router.include_router(rules.router)
api_router.include_router(refresh.router)
