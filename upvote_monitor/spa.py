from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "build"


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
