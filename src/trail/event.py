from __future__ import annotations

import json
from collections import UserDict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, UTC
from functools import cached_property
from pathlib import Path
from typing import ClassVar, Self, TYPE_CHECKING
from uuid import uuid4

from .entry import Entry
from .node import Node

if TYPE_CHECKING:
    from .trail import Trail


@dataclass(kw_only=True, slots=True)
class Event:
    classes: ClassVar[dict[str, type[Event]]] = {}

    entry: Entry | None = field(default=None, init=False)
    id: int = field(default_factory=lambda: uuid4().int)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def apply(self, trail: Trail):
        raise NotImplementedError

    def __init_subclass__(cls, **kwargs) -> None:
        # slots=True replaces the class captured by zero-argument super()
        super(Event, cls).__init_subclass__(**kwargs)
        cls.classes[cls.__name__] = cls

    @classmethod
    def from_record(cls, /, **record) -> Event:
        name = record.pop('cls')
        event_cls = cls.classes.get(name)
        # todo: needs access to trail to resolve entry by ID
        id = record.pop('entry')


        if name == cls.__name__:
            event_cls = cls
        if event_cls is None:
            raise ValueError(f'Unknown event class: {name!r}')
        record['timestamp'] = datetime.fromisoformat(record['timestamp'])
        deferred = {
            field.name: record.pop(field.name)
            for field in fields(event_cls)
            if not field.init and field.name in record
        }
        event = event_cls(**record)
        for name, value in deferred.items():
            setattr(event, name, value)
        return event

    def to_record(self) -> dict:
        out = dict(
            cls=type(self).__name__,
            **asdict(self),
        )
        out['timestamp'] = self.timestamp.isoformat()
        out['entry'] = self.entry.id
        return out

@dataclass(kw_only=True, slots=True)
class AddEntryEvent(Event):
    src_path: str
    entry: Entry | None = field(default=None, init=False)

    def apply(self, trail: Trail) -> Entry:
        entry = trail.entries.get(self.src_path)
        if entry is None:
            entry = Entry.from_path(self.src_path, trail=trail)
        self.entry = entry
        return entry.add()


@dataclass(kw_only=True, slots=True)
class RemoveEntryEvent(Event):
    src_path: str
    entry: Entry | None = field(default=None, init=False)

    def apply(self, trail: Trail) -> Entry | None:
        entry = trail.entries.get(self.src_path)
        if entry is None:
            return None
        self.entry = entry
        entry.remove()
        return entry


@dataclass(kw_only=True, slots=True)
class WatchdogEvent(Event):
    src_path: str
    dest_path: str = ""
    event_type: str = field(default="", init=False)
    is_directory: bool = field(default=False, init=False)
    is_synthetic: bool = field(default=False)
    entry: Entry | None = field(default=None, init=False)

    def apply(self, trail: Trail):
        entry = trail.entries[self.src_path]
        self.entry = entry
        if (
                self.event_type == 'moved'
                and self.dest_path
                and self.dest_path != self.src_path
        ):
            entry.move(self.dest_path)
        trail.events.unstaged[self.id] = self


@dataclass(kw_only=True, slots=True)
class JupyterEvent(Event):
    def apply(self, trail: Trail):
        ...


class JSONL(
    Node
):
    _parent: EventDict

    @property
    def path(self) -> Path | None:
        trail = self._trail
        events = self._parent
        if trail.dir:
            return trail.dir / f'{events.__name__}.jsonl'
        else:
            return None

    def read(self) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        loaded: dict[int, Event] = {}
        with path.open(encoding='utf-8') as file:
            for line in file:
                if not line.strip():
                    continue
                event = Event.from_record(**json.loads(line))
                if event.id in loaded:
                    raise ValueError(f'Duplicate event ID in {path}: {event.id}')
                loaded[event.id] = event
        self._parent.data.clear()
        self._parent.data.update(loaded)

    def write(self) -> None:
        path = self.path
        if path is None:
            return
        text = ''.join(
            json.dumps(event.to_record(), ensure_ascii=False) + '\n'
            for event in self._parent.values()
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def append(self, events: Iterable[Event]) -> None:
        path = self.path
        if path is None:
            return
        text = ''.join(
            json.dumps(event.to_record(), ensure_ascii=False) + '\n'
            for event in events
        )
        if not text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as file:
            if file.tell():
                file.seek(-1, 2)
                if file.read(1) != b'\n':
                    file.write(b'\n')
            file.write(text.encode('utf-8'))


class EventDict(
    UserDict[int, Event],
    Node,
):
    """A collection and descriptor for binding filtered views of change records."""
    _parent: Events
    __name__: str

    @cached_property
    def jsonl(self) -> JSONL:
        return JSONL(self)

    def _get(
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
        out.__name__ = key
        out.jsonl.read()
        cache[key] = out
        return out

    locals().update(__get__=_get)

    def update(self, m, /) -> None:
        batch = dict(m)
        self.jsonl.append(batch.values())
        self.data.update(batch)

    def __setitem__(
            self,
            key: int,
            value: Event,
    ) -> None:
        if not isinstance(value, Event):
            raise TypeError(f'Expected Event, got {type(value).__name__}')
        self.jsonl.append([value])
        self.data[key] = value

    def clear(self):
        super().clear()
        self.jsonl.write()


class Unstaged(EventDict):
    _parent: Events

    def stage(self, *entries: Entry):
        """
        todo: User needs to be able to do `trail add <path>` to stage events
        """
        staged = self._parent.staged
        if entries:
            entries = set(entries)
            subset = {
                key: event
                for key, event in self.items()
                if event.entry in entries
            }
            staged.update(subset)
            for key in subset:
                del self.data[key]
            self.jsonl.write()
        else:
            staged.update(self)
            self.clear()


class Staged(EventDict):
    _parent: Events

    def commit( self):
        """Move all staged events to the committed state."""
        self._parent.committed.update(self)
        self.clear()

class Committed(EventDict):
    _parent: Events

class Events(
    Node
):
    # watchdog.queue -> events.unstaged -> events.staged -> events.committed
    unstaged = Unstaged()
    staged = Staged()
    committed = EventDict()
