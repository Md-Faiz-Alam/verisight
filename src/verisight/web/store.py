"""Temporary storage for uploaded datasets, and simple per-client rate limits."""

import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import TypeVar, cast

T = TypeVar("T")
ALLOWED_SUFFIXES = (".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".xlsx", ".xls")
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
    # Loaded form for fast dashboards; it is dropped with the dataset.
    prepared: object = field(default=None, repr=False)


class StoreFullError(Exception):
    """Every upload slot is taken by uploads that are still being checked."""


class DatasetStore:
    """Thread-safe store that deletes datasets after a time limit.

    An upload first reserves a slot and a private directory. Capacity is
    enforced when the upload is added, after it passed validation, so a failed
    upload never evicts a stored dataset, and concurrent uploads can never
    leave more than ``max_datasets`` stored. At most ``max_datasets`` uploads
    may be in progress at once.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_datasets: int,
        clock: Callable[[], float] = time.monotonic,
        max_prepared: int = 4,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_datasets
        self._clock = clock
        self._max_prepared = max_prepared
        self._lock = threading.Lock()
        self._items: dict[str, StoredDataset] = {}
        self._pending: dict[str, Path] = {}
        self._prepared: OrderedDict[str, None] = OrderedDict()

    def create_directory(self) -> tuple[str, Path]:
        """Reserve an upload slot: a new dataset id and an empty directory."""
        self.purge_expired()
        with self._lock:
            if len(self._pending) >= self._max:
                raise StoreFullError
            dataset_id = uuid.uuid4().hex
            directory = Path(tempfile.mkdtemp(prefix="verisight-"))
            self._pending[dataset_id] = directory
        return dataset_id, directory

    def release(self, dataset_id: str) -> None:
        """Give up a reservation and delete its directory; stored data is kept."""
        with self._lock:
            directory = self._pending.pop(dataset_id, None)
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)

    def add(self, dataset: StoredDataset) -> None:
        """Store a validated upload, evicting the oldest others beyond capacity."""
        with self._lock:
            self._pending.pop(dataset.dataset_id, None)
            self._items[dataset.dataset_id] = dataset
            while len(self._items) > self._max:
                oldest = min(
                    (
                        item
                        for item in self._items.values()
                        if item.dataset_id != dataset.dataset_id
                    ),
                    key=lambda item: item.created,
                )
                self._remove(oldest.dataset_id)

    def get(self, dataset_id: str) -> StoredDataset | None:
        self.purge_expired()
        with self._lock:
            return self._items.get(dataset_id)

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            return self._remove(dataset_id)

    def prepared(self, dataset: StoredDataset, build: Callable[[], T]) -> T:
        """Return a dataset's loaded form, keeping only the most recent few."""
        with self._lock:
            value = dataset.prepared
            if value is not None:
                self._prepared.move_to_end(dataset.dataset_id)
                return cast(T, value)
        built = build()
        with self._lock:
            if dataset.dataset_id in self._items:
                dataset.prepared = built
                self._prepared[dataset.dataset_id] = None
                while len(self._prepared) > self._max_prepared:
                    oldest, _ = self._prepared.popitem(last=False)
                    self._items[oldest].prepared = None
        return built

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
            pending = list(self._pending.values())
            self._pending.clear()
        for directory in pending:
            shutil.rmtree(directory, ignore_errors=True)

    def _remove(self, dataset_id: str) -> bool:
        item = self._items.pop(dataset_id, None)
        self._prepared.pop(dataset_id, None)
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
