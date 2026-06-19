import sys

import uvicorn

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # ty:ignore[unresolved-attribute]
    sys.stderr.reconfigure(encoding="utf-8")  # ty:ignore[unresolved-attribute]
    uvicorn.run("upvote_monitor.app:app", host="0.0.0.0", port=8000, reload=False)  # noqa: S104
