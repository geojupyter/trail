from __future__ import annotations

import dataclasses

import csv

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import cached_property
from pathlib import Path
from typing import Final, Self, TYPE_CHECKING

from watchdog.events import FileClosedEvent, FileClosedNoWriteEvent, FileCreatedEvent, FileDeletedEvent, \
    FileModifiedEvent, FileMovedEvent, FileOpenedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from .node import Node
from .change import Change

if TYPE_CHECKING:
    from .files import Files

STOP: Final = object()


class Handler(
    FileSystemEventHandler,
    Node,
):
    _parent: Watchdog

    def on_any_event(self, event: FileSystemEvent) -> None:
        event = Change(**asdict(event))
        watchdog = self._watchdog
        watchdog.loop.call_soon_threadsafe(watchdog.queue.put_nowait, event)


class Watchdog(Node):
    parent: Files
    debounce = .1

    @cached_property
    def handler(self) -> Handler:
        out = Handler(self)
        return out

    @cached_property
    def observer(self):
        """Create and cache Watchdog's native observer for the current platform."""
        # Observer selects the native backend for Linux, macOS, or Windows.
        return Observer()

    @cached_property
    def queue(self) -> asyncio.Queue[Change]:
        return asyncio.Queue()

    @cached_property
    def loop(self):
        return asyncio.get_event_loop()

    @cached_property
    def watches(self) -> dict[Path, ObservedWatch]:
        return {}

    @cached_property
    def dir2ids(self) -> dict[Path, set[int]]:
        return {}

    @cached_property
    def consumer(self):
        return asyncio.create_task(self.consume(), name='watchdog-consumer')

    def start(self):
        _ = self.loop, self.queue, self.handler, self.debounce
        consumer = self.consumer
        try:
            self.observer.start()
        except BaseException:
            consumer.cancel()
            self.clear()

    async def stop(self):
        observer = self.observer
        if observer.is_alive():
            observer.stop()
            observer.join(5)
        if observer.is_alive():
            raise RuntimeError(f"Failed to stop observer {observer}")
        await asyncio.sleep(0)
        try:
            await self.consumer
        finally:
            self.clear()

    @asynccontextmanager
    async def context(self) -> AsyncIterator[Self]:
        """Start observation on entry and guarantee orderly shutdown on exit."""
        await self.start()
        try:
            yield self
        finally:
            await self.stop()

    def clear(self):
        del self.loop, self.queue, self.handler, self.debounce, self.consumer

    async def consume(self):
        while True:
            first = self.queue.get()
            if first is STOP:
                break
            if self.debounce:
                await asyncio.sleep(self.debounce)

            stop_queue = False
            batch = [first]
            while True:
                try:
                    event = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if event is STOP:
                    stop_queue = True
                    break
                batch.append(event)

            changes = self._trail.changes
            fieldnames = dataclasses.fields(Change)
            with changes.csv.open('a', encoding='utf-8', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)

                for change in batch:
                    change: Change
                    row = dataclasses.asdict(change)
                    writer.writerow(row)

            if stop_queue:
                break

