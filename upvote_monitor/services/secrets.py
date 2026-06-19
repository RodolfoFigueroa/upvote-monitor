import base64
import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from upvote_monitor.config import settings

DEFAULT_SECRET_PATH = Path("/data/secrets.enc")
SECRET_SUFFIX_LENGTH = 4
SECRET_PREVIEW_LENGTH = 4
_DEFAULT_SECRET_KEY = object()


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretStoreInvalid(RuntimeError):
    pass


class SecretStore:
    def __init__(
        self,
        secret_key: str | None | object = _DEFAULT_SECRET_KEY,
        path: Path = DEFAULT_SECRET_PATH,
    ) -> None:
        if secret_key is _DEFAULT_SECRET_KEY:
            self._secret_key = settings.upvote_monitor_secret_key
        elif isinstance(secret_key, str):
            self._secret_key = secret_key
        else:
            self._secret_key = None
        self.path = path

    @property
    def available(self) -> bool:
        return bool(self._secret_key)

    def source_secret_configured(self, source: str, key: str) -> bool:
        if not self.available:
            return False
        try:
            return bool(self.get_source_secrets(source).get(key))
        except SecretStoreInvalid:
            return False

    def source_secret_suffix(self, source: str, key: str) -> str | None:
        if not self.available:
            return None
        try:
            value = self.get_source_secrets(source).get(key)
        except SecretStoreInvalid:
            return None
        if not value:
            return None
        return value[-SECRET_SUFFIX_LENGTH:]

    def source_secret_prefix(self, source: str, key: str) -> str | None:
        if not self.available:
            return None
        try:
            value = self.get_source_secrets(source).get(key)
        except SecretStoreInvalid:
            return None
        if not value:
            return None
        return value[:SECRET_PREVIEW_LENGTH]

    def get_source_secrets(self, source: str) -> dict[str, str]:
        data = self.read_all()
        value = data.get(source)
        if not isinstance(value, dict):
            return {}
        return {k: str(v) for k, v in value.items() if isinstance(k, str)}

    def update_source_secrets(
        self,
        source: str,
        updates: Mapping[str, str | None],
    ) -> None:
        data = self.read_all()
        source_secrets = data.get(source)
        if not isinstance(source_secrets, dict):
            source_secrets = {}

        for key, value in updates.items():
            if value is None:
                continue
            if value == "":
                source_secrets.pop(key, None)
            else:
                source_secrets[key] = value

        if source_secrets:
            data[source] = source_secrets
        else:
            data.pop(source, None)
        self.write_all(data)

    def read_all(self) -> dict[str, Any]:
        fernet = self._fernet()
        if not self.path.exists():
            return {}

        try:
            plaintext = fernet.decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise SecretStoreInvalid("Encrypted secrets could not be decrypted") from exc

        try:
            value = json.loads(plaintext.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretStoreInvalid("Encrypted secrets are not valid JSON") from exc
        return value if isinstance(value, dict) else {}

    def write_all(self, data: dict[str, Any]) -> None:
        fernet = self._fernet()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(data, sort_keys=True).encode("utf-8")
        self.path.write_bytes(fernet.encrypt(plaintext))

    def _fernet(self) -> Fernet:
        if not self._secret_key:
            raise SecretStoreUnavailable("UPVOTE_MONITOR_SECRET_KEY is not configured")
        digest = sha256(self._secret_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))
