from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from upvote_monitor.services import secrets
from upvote_monitor.services.secrets import SecretStore

ENCRYPTION_KEY = "atomic-secret-test-key"


def test_concurrent_secret_updates_retain_both_complete_changes(tmp_path: Path) -> None:
    secret_path = tmp_path / "secrets.enc"
    barrier = Barrier(2)

    def update(source: str, value: str) -> None:
        store = SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)
        barrier.wait()
        store.update_source_secrets(source, {"token": value})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update, "reddit", "reddit-value"),
            executor.submit(update, "x", "x-value"),
        ]
        for future in futures:
            future.result()

    assert SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path).read_all() == {
        "reddit": {"token": "reddit-value"},
        "x": {"token": "x-value"},
    }


def test_interrupted_secret_write_preserves_decryptable_previous_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = tmp_path / "secrets.enc"
    store = SecretStore(secret_key=ENCRYPTION_KEY, path=secret_path)
    store.update_source_secrets("reddit", {"token": "previous"})

    def fail_fsync(_descriptor: int) -> None:
        message = "simulated interrupted write"
        raise OSError(message)

    monkeypatch.setattr(secrets.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="simulated interrupted write"):
        store.update_source_secrets("reddit", {"token": "next"})

    assert store.get_source_secrets("reddit") == {"token": "previous"}
    assert list(tmp_path.iterdir()) == [secret_path]
