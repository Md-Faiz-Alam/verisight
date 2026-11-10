"""Temporary storage for uploaded datasets, and simple per-client rate limits."""

import gc
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
    size_bytes: int = 0
    # Loaded form for fast dashboards; it is dropped with the dataset.
    prepared: object = field(default=None, repr=False)


def remove_leftover_directories(
    ttl_seconds: int, *, clock: Callable[[], float] = time.time
) -> int:
    """Delete upload folders that a crash or power loss left behind.

    Only folders older than an upload may live are touched, so a second copy of
    the server running on the same computer keeps its uploads.
    """
    removed = 0
    for folder in Path(tempfile.gettempdir()).glob("verisight-*"):
        try:
            stale = folder.is_dir() and clock() - folder.stat().st_mtime > ttl_seconds
        except OSError:
            continue
        if stale:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


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
        max_prepared_bytes: int = 60 * 1024 * 1024,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_datasets
        self._clock = clock
        self._max_prepared = max_prepared
        self._max_prepared_bytes = max_prepared_bytes
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
        dropped = False
        with self._lock:
            if dataset.dataset_id in self._items:
                dataset.prepared = built
                self._prepared[dataset.dataset_id] = None
                dropped = self._trim_prepared(incoming=0)
        if dropped:
            gc.collect()
        return built

    def make_room(self, incoming_bytes: int) -> None:
        """Let go of loaded uploads that would not fit beside a new one."""
        with self._lock:
            dropped = self._trim_prepared(incoming=incoming_bytes)
        if dropped:
            gc.collect()

    def _trim_prepared(self, *, incoming: int) -> bool:
        """Drop the oldest loaded uploads; the newest stays unless room is needed.

        Returns whether any were dropped. A loaded upload holds reference cycles,
        so its memory returns only when the collector runs.
        """
        dropped = False
        while self._prepared:
            loaded = sum(self._items[key].size_bytes for key in self._prepared)
            over = loaded + incoming > self._max_prepared_bytes
            if len(self._prepared) <= self._max_prepared and not over:
                break
            if incoming == 0 and len(self._prepared) == 1:
                break
            oldest, _ = self._prepared.popitem(last=False)
            self._items[oldest].prepared = None
            dropped = True
        return dropped

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
        self._next_sweep = 0.0

    def _forget_idle_clients(self, now: float) -> None:
        """Keep memory bounded when many clients ask once and never return."""
        self._next_sweep = now + 3600
        for client in [c for c, e in self._events.items() if now - e[-1] >= 3600]:
            del self._events[client]

    def allow(self, client: str) -> bool:
        now = self._clock()
        with self._lock:
            if now >= self._next_sweep:
                self._forget_idle_clients(now)
            events = self._events[client]
            while events and now - events[0] >= 3600:
                events.popleft()
            if len(events) >= self._limit:
                return False
            events.append(now)
            return True
