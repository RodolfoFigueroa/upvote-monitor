from collections.abc import Iterator
from pathlib import Path
from typing import Self

import pytest

from upvote_monitor import functions


class FakeStreamingResponse:
    def __init__(self, chunks: list[bytes | Exception]) -> None:
        self.headers = {"Content-Type": "image/jpeg"}
        self._chunks = chunks

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
        assert chunk_size == functions.DOWNLOAD_CHUNK_SIZE
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def test_http_download_streams_fsyncs_and_atomically_replaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeStreamingResponse([b"first", b"", b"second"])
    monkeypatch.setattr(functions.requests, "get", lambda *_args, **_kwargs: response)
    functions.download_file_from_url("https://example.test/image.jpg", tmp_path / "00")

    assert (tmp_path / "00.jpg").read_bytes() == b"firstsecond"
    assert list(tmp_path.glob("*.tmp")) == []


def test_interrupted_http_download_preserves_previous_file_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "00.jpg"
    target.write_bytes(b"previous")
    response = FakeStreamingResponse([b"partial", OSError("connection interrupted")])
    monkeypatch.setattr(functions.requests, "get", lambda *_args, **_kwargs: response)

    with pytest.raises(OSError, match="connection interrupted"):
        functions.download_file_from_url(
            "https://example.test/image.jpg",
            tmp_path / "00",
        )

    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
