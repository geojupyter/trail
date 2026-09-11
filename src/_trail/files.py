from __future__ import annotations

import asyncio
from collections import UserDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch

from .event import Event, EventKind
from .file import File

if TYPE_CHECKING:
    from .trail import Trail


@dataclass(frozen=True, slots=True)
class _FilesystemHint:
    kind: str
    source: Path
    destination: Path | None


_STOP: Final = object()


def _path(path: str | Path) -> Path:
    """Normalize a path for consistent comparisons with Watchdog event paths."""
    return Path(path).expanduser().resolve(strict=False)


class _EventHandler(FileSystemEventHandler):
    def __init__(self, submit) -> None:
        """Store the callback used to transfer hints to the asyncio loop."""
        self._submit = submit

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Convert a file event into an immutable, normalized filesystem hint."""
        if event.is_directory:
            return
        destination = getattr(event, "dest_path", "")
        self._submit(
            _FilesystemHint(
                kind=event.event_type,
                source=_path(event.src_path),
                destination=_path(destination) if destination else None,
            )
        )


class Files(UserDict[str, File]):
    """Registered files and their asynchronous filesystem observer."""

    trail: Trail | None

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the file mapping and inactive observer runtime state."""
        self.trail = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_FilesystemHint | object] | None = None
        self._handler: _EventHandler | None = None
        self._consumer: asyncio.Task[None] | None = None
        self._debounce = 0.1
        self._watches: dict[Path, ObservedWatch] = {}
        self._resources_by_directory: dict[Path, set[str]] = {}
        super().__init__(*args, **kwargs)

    @cached_property
    def observer(self) -> BaseObserver:
        """Create and cache Watchdog's native observer for the current platform."""
        # Observer selects the native backend for Linux, macOS, or Windows.
        return Observer()

    @property
    def is_observing(self) -> bool:
        """Report whether the asynchronous event consumer is active."""
        return self._consumer is not None

    def __setitem__(self, key: str, item: File) -> None:
        """Store a file and schedule it immediately when observation is active."""
        if key != item.id:
            raise ValueError("the mapping key must equal File.id")
        previous = self.data.get(key)
        if previous is not None and self.is_observing:
            self._unschedule(previous)
        super().__setitem__(key, item)
        if self.is_observing:
            self._schedule(item)

    def __delitem__(self, key: str) -> None:
        """Remove a file and release its parent-directory watch when unused."""
        item = self.data[key]
        if self.is_observing:
            self._unschedule(item)
        super().__delitem__(key)

    async def start_observing(self, *, debounce: float = 0.1) -> None:
        """Start parent-directory watches and an asyncio event consumer.

        Watchdog emits from background threads. The consumer receives their
        normalized hints through an asyncio queue and records logical changes.
        """
        if self.is_observing:
            raise RuntimeError("files are already being observed")
        if debounce < 0:
            raise ValueError("debounce must be non-negative")

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._handler = _EventHandler(self._submit)
        self._debounce = debounce

        for file in self.data.values():
            self._schedule(file)

        self._consumer = asyncio.create_task(
            self._consume(), name="trail-files-observer"
        )
        try:
            self.observer.start()
        except BaseException:
            self._consumer.cancel()
            self._consumer = None
            self._clear_runtime_state()
            raise

    async def stop_observing(self) -> None:
        """Stop all watches after processing every already-submitted hint."""
        consumer = self._consumer
        queue = self._queue
        observer = self.__dict__.get("observer")
        if consumer is None or queue is None or observer is None:
            return

        observer.stop()
        # stop() wakes the platform emitter, so this join should be immediate.
        # Avoid asyncio's default executor here: Trail must not leave an executor
        # thread behind merely to join Watchdog's already-stopping daemon thread.
        observer.join(timeout=5)
        if observer.is_alive():
            raise RuntimeError("filesystem observer did not stop")
        # Run callbacks submitted by the observer thread before placing the
        # sentinel behind them in the asyncio queue.
        await asyncio.sleep(0)
        queue.put_nowait(_STOP)
        try:
            await consumer
        finally:
            self._consumer = None
            self._clear_runtime_state()

    @asynccontextmanager
    async def observing(self, *, debounce: float = 0.1) -> AsyncIterator[Files]:
        """Start observation on entry and guarantee orderly shutdown on exit."""
        await self.start_observing(debounce=debounce)
        try:
            yield self
        finally:
            await self.stop_observing()

    def _submit(self, hint: _FilesystemHint) -> None:
        """Transfer a Watchdog-thread hint safely into the asyncio queue."""
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None:
            return
        loop.call_soon_threadsafe(queue.put_nowait, hint)

    def _schedule(self, file: File) -> None:
        """Watch a file's parent, sharing one non-recursive watch per directory."""
        handler = self._handler
        if handler is None:
            return
        directory = _path(file.path).parent
        resource_ids = self._resources_by_directory.setdefault(directory, set())
        resource_ids.add(file.id)
        if directory in self._watches:
            return
        self._watches[directory] = self.observer.schedule(
            handler,
            str(directory),
            recursive=False,
            event_filter=[
                FileCreatedEvent,
                FileModifiedEvent,
                FileDeletedEvent,
                FileMovedEvent,
            ],
        )

    def _unschedule(self, file: File) -> None:
        """Release a directory watch after its final registered file leaves."""
        directory = _path(file.path).parent
        resource_ids = self._resources_by_directory.get(directory)
        if resource_ids is None:
            return
        resource_ids.discard(file.id)
        if resource_ids:
            return
        watch = self._watches.pop(directory, None)
        self._resources_by_directory.pop(directory, None)
        if watch is not None:
            self.observer.unschedule(watch)

    async def _consume(self) -> None:
        """Debounce queued hints and convert each batch into logical events."""
        assert self._queue is not None
        while True:
            first = await self._queue.get()
            if first is _STOP:
                return

            batch = [first]
            if self._debounce:
                await asyncio.sleep(self._debounce)

            stopping = False
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is _STOP:
                    stopping = True
                    break
                batch.append(item)

            self._record_batch(batch)
            if stopping:
                return

    def _record_batch(self, batch: list[_FilesystemHint | object]) -> None:
        """Match a batch of filesystem hints to registered files by path."""
        paths = {_path(file.path): file for file in self.data.values()}
        affected: dict[str, list[_FilesystemHint]] = {}

        for item in batch:
            assert isinstance(item, _FilesystemHint)
            source_file = paths.get(item.source)
            destination_file = (
                paths.get(item.destination) if item.destination is not None else None
            )
            if source_file is not None:
                affected.setdefault(source_file.id, []).append(item)
            if destination_file is not None and destination_file is not source_file:
                affected.setdefault(destination_file.id, []).append(item)

        for file_id, hints in affected.items():
            file = self.data.get(file_id)
            if file is None:
                continue
            self._record_file_change(file, hints)

    def _record_file_change(self, file: File, hints: list[_FilesystemHint]) -> None:
        """Append one event, increment the revision, and refresh file state."""
        original_path = _path(file.path)
        move = next(
            (
                hint
                for hint in reversed(hints)
                if hint.kind == "moved"
                and hint.source == original_path
                and hint.destination is not None
            ),
            None,
        )

        destination: Path | None = None
        if move is not None:
            kind: EventKind = "moved"
            destination = move.destination
        elif not original_path.exists():
            if not file.exists:
                return
            kind = "deleted"
        elif not file.exists:
            kind = "created"
        else:
            kind = "modified"

        event = Event(
            file_id=file.id,
            kind=kind,
            path=str(original_path),
            destination=str(destination) if destination is not None else None,
        )
        file.events.append(event)
        file.revision += 1

        if destination is not None and destination.exists():
            old_directory = original_path.parent
            new_directory = destination.parent
            if old_directory != new_directory:
                self._unschedule(file)
                file.refresh(destination)
                self._schedule(file)
            else:
                file.refresh(destination)
        elif original_path.exists():
            file.refresh(original_path)
        else:
            file.exists = False

    def _clear_runtime_state(self) -> None:
        """Discard stopped observer state so a later session can start cleanly."""
        self._loop = None
        self._queue = None
        self._handler = None
        self._watches.clear()
        self._resources_by_directory.clear()
        self.__dict__.pop("observer", None)

