from __future__ import annotations

from collections import UserList, UserDict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from functools import cached_property
from pathlib import Path
from typing import Self, TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail


@dataclass(kw_only=True, slots=True)
class Event:
    id: int = field(default_factory=lambda: uuid4().int)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def apply(self, trail: Trail):
        raise NotImplementedError

    def to_record(self) -> dict:
        out = {}
        out['cls'] = self.__class__.__name__
        return out


@dataclass(kw_only=True, slots=True)
class WatchdogEvent(Event):
    src_path: str
    dest_path: str = ""
    event_type: str = field(default="", init=False)
    is_directory: bool = field(default=False, init=False)
    is_synthetic: bool = field(default=False)

    def apply(self, trail: Trail):
        if self.is_directory:
            entry = trail.dirs[self.src_path]
        else:
            entry = trail.files[self.src_path]
        if self.dest_path != self.src_path:
            entry.move(self.dest_path)
        trail.events.unstaged[self.id] = self


@dataclass(kw_only=True, slots=True)
class JupyterEvent(Event):
    def apply(self, trail: Trail):
        ...


class JSONL(
    Node
):
    """Nested-namespace to encapsulate CSV-related functionality for changes."""
    _parent: EventDict

    @property
    def path(self):
        trail = self._trail
        events = self._parent
        if trail.dir:
            return trail.dir / f'{events.__name__}.jsonl'
        else:
            return None

    def read(self):
        events = self._parent
        events.clear()

    def write(self):
        events = self._parent
        for event in events:
            ...

    def append(self):
        # todo: compare length of self to length of jsonl file and only append new events
        events = self._parent

class EventDict(
    UserDict[int, Event],
    Node,
):
    """A collection and descriptor for binding filtered views of change records."""

    @cached_property
    def jsonl(self):
        return JSONL(self)

    def __set_name__(
            self,
            owner: type,
            name: str,
    ) -> None:
        self.__name__ = name

    def __get__(
            self,
            instance: Events,
            owner: type[Event],
    ) -> Self:
        if instance is None:
            return self
        key = self.__name__
        cache = instance.__dict__
        if key in cache:
            return cache[key]
        out = self.__class__()
        out._parent = instance
        out.jsonl.read()
        cache[key] = out
        return out


class Unstaged(EventDict):
    def stage(self):
        ...

class Staged(EventDict):
    def commit(self):
        ...


class Events(
    Node
):
    unstaged = Unstaged()
    staged = Staged()
    committed = EventDict()

"""
watchdog.queue -> events.unstaged -> events.staged -> events.committed
"""
