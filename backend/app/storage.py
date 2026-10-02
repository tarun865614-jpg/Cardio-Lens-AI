"""Encrypted private object storage for recordings.

Local filesystem backend with Fernet (AES-128-CBC + HMAC-SHA256) encryption at
rest. Object keys are random and carry no patient information. Swap
`LocalEncryptedStorage` for an S3/GCS backend with SSE-KMS in production; the
interface (`put`, `get`, `delete`) is the contract.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class StorageError(RuntimeError):
    pass


class LocalEncryptedStorage:
    def __init__(self, root: Path, key: str | None, fallback_secret: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if key:
            fkey = key.encode()
        else:
            # Development only (production config refuses to start without a key).
            fkey = base64.urlsafe_b64encode(hashlib.sha256(("storage:" + fallback_secret).encode()).digest())
        self._fernet = Fernet(fkey)

    def _path(self, key: str) -> Path:
        if not key or any(c not in "0123456789abcdef" for c in key):
            raise StorageError("invalid object key")
        return self.root / key[:2] / key

    def put(self, data: bytes) -> str:
        key = secrets.token_hex(24)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(self._fernet.encrypt(data))
        tmp.replace(path)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError("object not found")
        try:
            return self._fernet.decrypt(path.read_bytes())
        except InvalidToken as e:
            raise StorageError("object failed integrity check") from e

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.exists():
            # Overwrite before unlink; on SSD/cloud storage crypto-erasure (key
            # destruction) is the real guarantee, this is defence in depth.
            path.write_bytes(secrets.token_bytes(path.stat().st_size))
            path.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


_storage: LocalEncryptedStorage | None = None


def get_storage() -> LocalEncryptedStorage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = LocalEncryptedStorage(s.storage_dir, s.storage_key, s.jwt_secret)
    return _storage


def set_storage(storage: LocalEncryptedStorage | None) -> None:
    global _storage
    _storage = storage
