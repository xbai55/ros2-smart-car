"""对象存储抽象（MinIO 优先，未配置时退回本地文件存储）。

数据库只保存资源元数据与地址，真实文件交给存储服务，对应项目文档中
MinIO 用于保存证据图片、地图等非结构化资产的约定。
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..core.config import settings


def normalize_key(key: str) -> str:
    cleaned = (key or "").strip().lstrip("/").replace("\\", "/")
    if not cleaned or ".." in cleaned.split("/"):
        raise ValueError("非法的资源 key")
    return cleaned


class StorageService:
    backend = "local"

    @property
    def configured(self) -> bool:
        return True

    def presign_upload(self, key: str, *, expires_in: int = 900) -> dict:
        raise NotImplementedError

    def presign_download(self, key: str, *, expires_in: int = 900) -> dict:
        raise NotImplementedError

    def put(self, key: str, data: bytes, *, content_type: str = "") -> dict:
        raise NotImplementedError

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class LocalStorageService(StorageService):
    backend = "local"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.storage_local_dir)

    def _path(self, key: str) -> Path:
        safe = normalize_key(key)
        return self.root / safe

    def presign_upload(self, key: str, *, expires_in: int = 900) -> dict:
        safe = normalize_key(key)
        return {
            "backend": self.backend,
            "key": safe,
            "method": "PUT",
            "url": f"/api/v1/media/object/{safe}",
            "expires_in": expires_in,
        }

    def presign_download(self, key: str, *, expires_in: int = 900) -> dict:
        safe = normalize_key(key)
        return {
            "backend": self.backend,
            "key": safe,
            "method": "GET",
            "url": f"/api/v1/media/object/{safe}",
            "expires_in": expires_in,
        }

    def put(self, key: str, data: bytes, *, content_type: str = "") -> dict:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "backend": self.backend,
            "key": normalize_key(key),
            "size": len(data),
            "content_type": content_type,
            "url": f"/api/v1/media/object/{normalize_key(key)}",
        }

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class MinioStorageService(StorageService):
    backend = "minio"

    def __init__(self, client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        except Exception:
            pass

    def presign_upload(self, key: str, *, expires_in: int = 900) -> dict:
        from datetime import timedelta

        safe = normalize_key(key)
        url = self._client.presigned_put_object(
            self._bucket, safe, expires=timedelta(seconds=expires_in)
        )
        return {"backend": self.backend, "key": safe, "method": "PUT", "url": url, "expires_in": expires_in}

    def presign_download(self, key: str, *, expires_in: int = 900) -> dict:
        from datetime import timedelta

        safe = normalize_key(key)
        url = self._client.presigned_get_object(
            self._bucket, safe, expires=timedelta(seconds=expires_in)
        )
        return {"backend": self.backend, "key": safe, "method": "GET", "url": url, "expires_in": expires_in}

    def put(self, key: str, data: bytes, *, content_type: str = "") -> dict:
        import io

        safe = normalize_key(key)
        self._client.put_object(
            self._bucket,
            safe,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return {"backend": self.backend, "key": safe, "size": len(data), "content_type": content_type, "url": None}

    def get(self, key: str) -> bytes | None:
        response = None
        try:
            response = self._client.get_object(self._bucket, normalize_key(key))
            return response.read()
        except Exception:
            return None
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

    def delete(self, key: str) -> None:
        self._client.remove_object(self._bucket, normalize_key(key))


_storage: StorageService | None = None
_lock = threading.Lock()


def _build_storage() -> StorageService:
    if settings.minio_endpoint:
        try:
            from minio import Minio  # type: ignore

            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            return MinioStorageService(client, settings.minio_bucket)
        except Exception:
            return LocalStorageService()
    return LocalStorageService()


def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        with _lock:
            if _storage is None:
                _storage = _build_storage()
    return _storage


def reset_storage() -> None:
    global _storage
    with _lock:
        _storage = None
