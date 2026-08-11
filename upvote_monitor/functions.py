import mimetypes
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from pydantic import HttpUrl

from upvote_monitor.constants import REQUESTS_TIMEOUT

DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def download_file_from_url(
    url: str,
    path: os.PathLike | str,
    extension: str | None = None,
) -> None:
    path = Path(path)

    if path.suffix != "":
        msg = "Path must not have a suffix"
        raise ValueError(msg)

    temporary_path: Path | None = None
    try:
        with requests.get(
            url,
            stream=True,
            timeout=REQUESTS_TIMEOUT,
        ) as response:
            response.raise_for_status()

            suffix = extension or Path(urlparse(url).path).suffix
            if not suffix:
                content_type = response.headers.get("Content-Type", "").split(
                    ";",
                    1,
                )[0]
                suffix = mimetypes.guess_extension(content_type.strip().lower()) or ""

            target_path = path.with_suffix(suffix)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                dir=target_path.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as file:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(target_path)
            temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def download_image_from_url(url: HttpUrl, path: os.PathLike | str) -> None:
    download_file_from_url(str(url), path)
