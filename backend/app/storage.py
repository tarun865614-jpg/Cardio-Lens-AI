"""Encrypted private object storage for recordings.

Every object is Fernet-encrypted (AES-128-CBC + HMAC-SHA256) *before* it
leaves the process, so the storage provider only ever holds ciphertext.
Object keys are random and carry no patient information.

Backends (CARDIOLENS_STORAGE_BACKEND):
  * local — files under CARDIOLENS_STORAGE_DIR (development, single host)
  * s3    — private S3 bucket (or S3-compatible: MinIO etc.). Objects are
            additionally written with SSE-KMS when CARDIOLENS_S3_KMS_KEY_ID
            is set, giving two independent layers of encryption at rest.

The contract every backend implements is `put`, `get`, `delete`, `exists`.
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


def _fernet(key: str | None, fallback_secret: str) -> Fernet:
    if key:
        return Fernet(key.encode())
    # Development only (production config refuses to start without a key).
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("storage:" + fallback_secret).encode()).digest()))


def _check_key(key: str) -> None:
    if not key or any(c not in "0123456789abcdef" for c in key):
        raise StorageError("invalid object key")


class EncryptedStorage:
    """Shared encryption layer; subclasses implement the raw byte operations."""

    def __init__(self, fernet: Fernet):
        self._fernet = fernet

    def put(self, data: bytes) -> str:
        key = secrets.token_hex(24)
        self._write(key, self._fernet.encrypt(data))
        return key

    def get(self, key: str) -> bytes:
        _check_key(key)
        blob = self._read(key)
        try:
            return self._fernet.decrypt(blob)
        except InvalidToken as e:
            raise StorageError("object failed integrity check") from e

    def delete(self, key: str) -> bool:
        _check_key(key)
        return self._delete(key)

    def exists(self, key: str) -> bool:
        _check_key(key)
        return self._exists(key)

    # Raw operations ---------------------------------------------------------
    def _write(self, key: str, blob: bytes) -> None: ...
    def _read(self, key: str) -> bytes: ...
    def _delete(self, key: str) -> bool: ...
    def _exists(self, key: str) -> bool: ...


class LocalEncryptedStorage(EncryptedStorage):
    def __init__(self, root: Path, key: str | None, fallback_secret: str):
        super().__init__(_fernet(key, fallback_secret))
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        _check_key(key)
        return self.root / key[:2] / key

    def _write(self, key, blob):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)

    def _read(self, key):
        path = self._path(key)
        if not path.exists():
            raise StorageError("object not found")
        return path.read_bytes()

    def _delete(self, key):
        path = self._path(key)
        if not path.exists():
            return False
        # Overwrite before unlink; on SSD/cloud storage crypto-erasure (key
        # destruction) is the real guarantee, this is defence in depth.
        path.write_bytes(secrets.token_bytes(path.stat().st_size))
        path.unlink()
        return True

    def _exists(self, key):
        return self._path(key).exists()


class S3EncryptedStorage(EncryptedStorage):
    def __init__(self, bucket: str, prefix: str, key: str | None, fallback_secret: str, *,
                 kms_key_id: str | None = None, client=None, region: str | None = None, endpoint_url: str | None = None):
        super().__init__(_fernet(key, fallback_secret))
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
        self.s3 = client
        self.bucket = bucket
        self.prefix = prefix
        self.kms_key_id = kms_key_id

    def _obj(self, key: str) -> str:
        return f"{self.prefix}{key[:2]}/{key}"

    def _write(self, key, blob):
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id} if self.kms_key_id else {}
        try:
            self.s3.put_object(Bucket=self.bucket, Key=self._obj(key), Body=blob,
                               ContentType="application/octet-stream", **extra)
        except Exception as e:
            raise StorageError(f"object store write failed: {type(e).__name__}") from e

    def _read(self, key):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self._obj(key))["Body"].read()
        except self.s3.exceptions.NoSuchKey as e:
            raise StorageError("object not found") from e
        except Exception as e:
            raise StorageError(f"object store read failed: {type(e).__name__}") from e

    def _exists(self, key):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._obj(key))
            return True
        except Exception:
            return False

    def _delete(self, key):
        if not self._exists(key):
            return False
        # With bucket versioning enabled, also remove prior versions so the
        # ciphertext is not retained after an erasure request.
        name = self._obj(key)
        try:
            versions = self.s3.list_object_versions(Bucket=self.bucket, Prefix=name).get("Versions", [])
            for v in versions:
                if v["Key"] == name:
                    self.s3.delete_object(Bucket=self.bucket, Key=name, VersionId=v["VersionId"])
            self.s3.delete_object(Bucket=self.bucket, Key=name)
        except Exception as e:
            raise StorageError(f"object store delete failed: {type(e).__name__}") from e
        return True


_storage: EncryptedStorage | None = None


def build_storage() -> EncryptedStorage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3EncryptedStorage(s.s3_bucket, s.s3_prefix, s.storage_key, s.jwt_secret, kms_key_id=s.s3_kms_key_id,
                                  region=s.s3_region, endpoint_url=s.s3_endpoint_url)
    return LocalEncryptedStorage(s.storage_dir, s.storage_key, s.jwt_secret)


def get_storage() -> EncryptedStorage:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def set_storage(storage: EncryptedStorage | None) -> None:
    global _storage
    _storage = storage
