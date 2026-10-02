from abc import ABC, abstractmethod


class StorageError(RuntimeError):
    pass


class RawStorage(ABC):
    """Storage boundary for immutable source response bytes."""

    @abstractmethod
    def put(self, source_key: str, raw_sha256: str, content: bytes) -> str:
        """Store content and return a stable storage key."""

    @abstractmethod
    def get(self, storage_key: str) -> bytes:
        """Read content previously stored under a storage key."""
