from __future__ import annotations

import json
from collections import UserDict
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
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
    def from_record(
            cls,
            /,
            trail: Trail,
            **record
    ) -> Event:
        name = record.pop('cls')
        event_cls = cls.classes.get(name)

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

        id = record.pop('entry')
        entry = trail.entries[id]
        event.entry = entry
        return event

    def to_record(self) -> dict:
        out = {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != 'entry'
        }
        out['cls'] = type(self).__name__
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

        entry.add()
        trail._removed_paths.discard(entry.path)
        return entry


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
        trail._removed_paths.add(entry.path)
        return entry


@dataclass(kw_only=True, slots=True)
class WatchdogEvent(Event):
    src_path: str
    dest_path: str = ""
    event_type: str = ""
    is_directory: bool = False
    is_synthetic: bool = field(default=False)
    entry: Entry | None = field(default=None, init=False)

    def apply(self, trail: Trail) -> Entry | None:
        if (
            self.event_type not in {'created', 'modified', 'deleted', 'moved'}
            or (self.is_directory and self.event_type == 'modified')
        ):
            return None
        source = Path(self.src_path).expanduser().resolve()
        destination = None
        if self.event_type == 'moved' and self.dest_path:
            destination = Path(self.dest_path).expanduser().resolve()
        for path in (source, destination):
            if path is not None and (
                path in trail._removed_paths
                or trail._ignored(path)
            ):
                return None
        if self.is_directory:
            collection = trail.dirs
        else:
            collection = trail.files
        entry = collection.get(source)
        if entry is None and destination is not None:
            entry = collection.get(destination)
        if entry is None:
            if destination is None:
                path = source
            else:
                path = destination
            target = Path(self.dest_path or self.src_path)
            if (
                self.event_type not in {'created', 'moved'}
                or trail.dirs.get(path.parent) is None
                or target.is_symlink()
            ):
                return None
            try:
                if self.is_directory:
                    exists = path.is_dir()
                else:
                    exists = path.is_file()
                if not exists:
                    return None
                entry = collection.add(path)[0]
            except (FileNotFoundError, NotADirectoryError):
                return None
        self.src_path = str(source)
        if destination is not None:
            self.dest_path = str(destination)
            if entry.path != destination:
                entry.move(destination)
        elif self.event_type == 'created':
            entry.add()
        if self.is_directory and self.event_type == 'deleted':
            trail.watchdog.invalidate(source)
        self.entry = entry
        trail.events[self.id] = self
        return entry


@dataclass(kw_only=True, slots=True)
class JupyterEvent(Event):
    def apply(self, trail: Trail):
        ...


class JSONL(
    Node
):
    _parent: Events

    @property
    def path(self) -> Path | None:
        trail = self._trail
        events = self._parent
        if trail.dir:
            return trail.dir / f'events.jsonl'
        else:
            return None

    def read(self) -> None:
        path = self.path
        trail = self._trail
        if path is None or not path.exists():
            return
        loaded: dict[int, Event] = {}
        with path.open(encoding='utf-8') as file:
            for line in file:
                if not line.strip():
                    continue
                event = Event.from_record(**json.loads(line), trail=trail)
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


class Events(
    UserDict[int, Event],
    Node,
):
    """A collection and descriptor for binding filtered views of change records."""
    _parent: Trail

    @cached_property
    def jsonl(self) -> JSONL:
        return JSONL(self)

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
