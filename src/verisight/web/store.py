"""Temporary storage for uploaded datasets, and simple per-client rate limits."""

import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

ALLOWED_SUFFIXES = (".csv", ".json", ".xlsx", ".xls")
_UNSAFE = re.compile(r"[^\w.-]+")


def safe_file_name(name: str, taken: set[str]) -> str:
    """Return a plain, unique file name; directories in the name are dropped."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    path = PurePath(base)
    clean_stem = _UNSAFE.sub("_", path.stem).strip("._")[:60] or "data"
    suffix = _UNSAFE.sub("", path.suffix.lower())
    candidate = f"{clean_stem}{suffix}"
    number = 2
    while candidate.lower() in taken:
        candidate = f"{clean_stem}_{number}{suffix}"
        number += 1
    taken.add(candidate.lower())
    return candidate


@dataclass
class StoredDataset:
    """Files of one upload, kept in a private temporary directory."""

    dataset_id: str
    directory: Path
    paths: tuple[Path, ...]
    created: float
    profile: dict[str, object] = field(default_factory=dict)


class DatasetStore:
    """Thread-safe store that deletes datasets after a time limit."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_datasets: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_datasets
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, StoredDataset] = {}

    def create_directory(self) -> tuple[str, Path]:
        """Reserve a new dataset id and an empty private directory."""
        self.purge_expired()
        with self._lock:
            if len(self._items) >= self._max:
                oldest = min(self._items.values(), key=lambda item: item.created)
                self._remove(oldest.dataset_id)
        dataset_id = uuid.uuid4().hex
        directory = Path(tempfile.mkdtemp(prefix="verisight-"))
        return dataset_id, directory

    def add(self, dataset: StoredDataset) -> None:
        with self._lock:
            self._items[dataset.dataset_id] = dataset

    def get(self, dataset_id: str) -> StoredDataset | None:
        self.purge_expired()
        with self._lock:
            return self._items.get(dataset_id)

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            return self._remove(dataset_id)

    def purge_expired(self) -> None:
        now = self._clock()
        with self._lock:
            for dataset_id in [
                key
                for key, item in self._items.items()
                if now - item.created > self._ttl
            ]:
                self._remove(dataset_id)

    def clear(self) -> None:
        with self._lock:
            for dataset_id in list(self._items):
                self._remove(dataset_id)

    def _remove(self, dataset_id: str) -> bool:
        item = self._items.pop(dataset_id, None)
        if item is None:
            return False
        shutil.rmtree(item.directory, ignore_errors=True)
        return True


class RateLimiter:
    """Allow at most ``limit`` events per client in any rolling hour."""

    def __init__(
        self, limit: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        now = self._clock()
        with self._lock:
            events = self._events[client]
            while events and now - events[0] >= 3600:
                events.popleft()
            if len(events) >= self._limit:
                return False
            events.append(now)
            return True
