import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from backend.app.storage.base import RawStorage, StorageError

_SAFE_SOURCE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalRawStorage(RawStorage):
    """Content-addressed raw storage rooted at a local directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def put(self, source_key: str, raw_sha256: str, content: bytes) -> str:
        if not _SAFE_SOURCE_KEY.fullmatch(source_key):
            raise StorageError(f"Unsafe source key: {source_key!r}")
        if not _SHA256.fullmatch(raw_sha256):
            raise StorageError("raw_sha256 must be a lowercase SHA-256 hex digest")

        storage_key = f"{source_key}/{raw_sha256}.bin"
        target = self._resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            if target.read_bytes() != content:
                raise StorageError(f"Stored content differs for digest {raw_sha256}")
            return storage_key

        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{raw_sha256}-", suffix=".tmp"
        )
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_name, target)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise

        return storage_key

    def get(self, storage_key: str) -> bytes:
        target = self._resolve_key(storage_key)
        try:
            return target.read_bytes()
        except OSError as exc:
            raise StorageError(f"Unable to read {storage_key!r}") from exc

    def _resolve_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if key.is_absolute() or ".." in key.parts:
            raise StorageError(f"Unsafe storage key: {storage_key!r}")

        target = (self.root / Path(*key.parts)).resolve()
        if not target.is_relative_to(self.root):
            raise StorageError(f"Storage key escapes root: {storage_key!r}")
        return target
