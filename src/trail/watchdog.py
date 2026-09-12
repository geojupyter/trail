from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from .changes import Change, EVENT_TYPES
from .node import Node

if TYPE_CHECKING:
    from .files import Files

STOP: Final = object()


class Handler(FileSystemEventHandler, Node):
    _parent: Watchdog

    def on_any_event(self, event: FileSystemEvent) -> None:
        if (
            event.is_directory
            or event.event_type not in EVENT_TYPES
        ):
            return
        watchdog = self._parent
        change = Change(_parent=watchdog, **asdict(event))
        watchdog.loop.call_soon_threadsafe(watchdog.queue.put_nowait, change)


class Watchdog(Node):
    _parent: Files
    debounce = 0.1

    @cached_property
    def handler(self) -> Handler:
        out = Handler()
        out._parent = self
        return out

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
    def consumer(self):
        return asyncio.create_task(self.consume(), name="watchdog-consumer")

    def watch(self, directory: Path) -> None:
        if directory not in self.watches:
            self.watches[directory] = self.observer.schedule(
                self.handler,
                str(directory),
                recursive=False,
                event_filter=[
                    FileCreatedEvent,
                    FileModifiedEvent,
                    FileDeletedEvent,
                    FileMovedEvent,
                ],
            )

    async def start(self) -> None:
        consumer = self.__dict__.get("consumer")
        if consumer is not None:
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
        for name in ("loop", "queue", "handler", "consumer", "observer", "watches"):
            self.__dict__.pop(name, None)

    async def consume(self) -> None:
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

            self._trail.changes.record(
                tracked
                for change in batch
                if (tracked := change.tracked()) is not None
            )
            if stopped:
                return
