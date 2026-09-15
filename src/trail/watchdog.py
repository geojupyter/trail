from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
    DirModifiedEvent
)
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from ._changes import Change, EVENT_TYPES
from .entry import Entry
from .node import Node

if TYPE_CHECKING:
    from .trail import Trail

STOP: Final = object()


class Handler(FileSystemEventHandler, Node):
    _parent: Watchdog

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in EVENT_TYPES:
            return
        watchdog = self._parent
        change = Change(_parent=watchdog, **asdict(event))
        watchdog.loop.call_soon_threadsafe(watchdog.queue.put_nowait, change)


class Watchdog(Node):
    _parent: Trail
    debounce = 0.1

    @classmethod
    def from_path(cls, path: Path | str) -> Self:
        """Metadata lives in path"""

    @cached_property
    def handler(self) -> Handler:
        return Handler(self)

    @cached_property
    def observer(self):
        return Observer()

    @cached_property
    def queue(self) -> asyncio.Queue:
        return asyncio.Queue()

    @cached_property
    def loop(self):
        return asyncio.get_running_loop()

    @cached_property
    def watches(self) -> dict[Path, ObservedWatch]:
        return {}

    @cached_property
    def dir2ids(self) -> dict[Path, set[int]]:
        return {}

    @cached_property
    def consumer(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.apply(), name="watchdog-consumer")

    def watch(self, directory: Path) -> None:
        if (
            directory not in self.watches
            and directory.is_dir()
        ):
            self.watches[directory] = self.observer.schedule(
                self.handler,
                str(directory),
                recursive=False,
                event_filter=[
                    FileCreatedEvent,
                    FileModifiedEvent,
                    FileDeletedEvent,
                    FileMovedEvent,
                    DirCreatedEvent,
                    DirDeletedEvent,
                    DirMovedEvent,
                ],
            )

    def release(
            self,
            directory: Path,
            identifier: int,
    ) -> None:
        ids = self.dir2ids.get(directory)
        if ids is None or identifier not in ids:
            return
        if len(ids) == 1:
            watch = self.watches.get(directory)
            if watch is not None:
                with suppress(KeyError):
                    self.observer.unschedule(watch)
                del self.watches[directory]
            del self.dir2ids[directory]
        else:
            ids.remove(identifier)

    def invalidate(self, directory: Path) -> None:
        for path in tuple(self.watches):
            if path.is_relative_to(directory):
                with suppress(KeyError):
                    self.observer.unschedule(self.watches[path])
                del self.watches[path]

    async def start(self) -> None:
        consumer = self.consumer
        if consumer.done():
            await consumer
        else:
            return
        self.loop = asyncio.get_running_loop()
        try:
            for directory in self.dir2ids:
                self.watch(directory)
            consumer = self.consumer
            self.observer.start()
        except BaseException:
            self.observer.stop()
            if self.observer.is_alive():
                self.observer.join(5)
            if consumer is not None:
                consumer.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer
            self.clear()
            raise

    async def stop(self) -> None:
        observer = self.observer
        observer.stop()
        if observer.is_alive():
            observer.join(5)
        if observer.is_alive():
            raise RuntimeError(f"Failed to stop observer {observer}")
        # Drain callbacks submitted by the observer before closing the queue.
        await asyncio.sleep(0)
        self.queue.put_nowait(STOP)
        try:
            await self.consumer
        finally:
            self.clear()

    @asynccontextmanager
    async def context(self) -> AsyncIterator[Self]:
        """Observe asynchronously, draining queued changes when the context exits.

        Stage changes after they appear in the log or after leaving this context.
        """
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    def clear(self) -> None:
        # Native observer threads cannot be restarted. Retain directory membership
        # so a new observer can recreate the watches on the next start.
        del self.consumer
        for name in ("loop", "queue", "handler", "observer", "watches"):
            with suppress(AttributeError):
                delattr(self, name)

    async def apply(self) -> None:
        while True:
            first = await self.queue.get()
            if first is STOP:
                return
            if self.debounce:
                await asyncio.sleep(self.debounce)

            stopped = False
            batch = [first]
            while True:
                try:
                    event = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if event is STOP:
                    stopped = True
                    break
                batch.append(event)

            trail = self._trail
            tracked = []
            for event in batch:
                if event.tracked() is None:
                    continue
                tracked.append(event)
                if event.is_directory and event.event_type in ('created', 'moved'):
                    path = Path(event.dest_path or event.src_path)
                    # if path.is_dir() and not trail._ignored(path):
                    if (
                        path.is_dir()
                        and not trail._ignored(path)
                    ):
                        try:
                            root = trail.dirs.get(path)
                            if root is None:
                                root = Entry.from_path(path, trail=trail)
                            resources = tuple(root.walk())
                        except (FileNotFoundError, NotADirectoryError):
                            continue
                        added = []
                        try:
                            for resource in resources:
                                if resource._parent.id2entry.get(resource.id) is resource:
                                    continue
                                resource.add()
                                added.append(resource)
                        except Exception:
                            for resource in reversed(added):
                                resource.remove()
                            raise
                        for resource in added:
                            discovered = resource.event('created', is_synthetic=True)
                            tracked.append(discovered)
            trail.events.record(tracked)
            if stopped:
                return
