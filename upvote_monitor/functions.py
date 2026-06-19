import os
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests
from pydantic import HttpUrl

from upvote_monitor.constants import REQUESTS_TIMEOUT


def download_file_from_url(
    url: str,
    path: os.PathLike | str,
    extension: str | None = None,
) -> None:
    path = Path(path)

    if path.suffix != "":
        raise ValueError("Path must not have a suffix")

    response = requests.get(url, timeout=REQUESTS_TIMEOUT)
    response.raise_for_status()

    suffix = extension or Path(urlparse(url).path).suffix
    if not suffix:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        suffix = mimetypes.guess_extension(content_type.strip().lower()) or ""

    path = path.with_suffix(suffix)
    with open(path, "wb") as f:
        f.write(response.content)


def download_image_from_url(url: HttpUrl, path: os.PathLike | str) -> None:
    download_file_from_url(str(url), path)
