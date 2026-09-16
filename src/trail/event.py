from __future__ import annotations

import json
from collections import UserDict
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, UTC
from functools import cached_property
from pathlib import Path
from typing import ClassVar, Self, TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail


@dataclass(kw_only=True, slots=True)
class Event:
    classes: ClassVar[dict[str, type[Event]]] = {}

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
        self._parent.clear()
        self._parent.update(loaded)

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

    def append(self) -> None:
        path = self.path
        if path is None:
            return
        if not path.exists():
            self.write()
            return
        events = iter(self._parent.values())
        needs_newline = False
        with path.open(encoding='utf-8') as file:
            for line in file:
                needs_newline = not line.endswith('\n')
                if not line.strip():
                    continue
                event = next(events, None)
                if (
                        event is None
                        or json.loads(line) != event.to_record()
                ):
                    raise ValueError(
                        f'{path} does not match the event prefix; use write() to replace it'
                    )
        text = ''.join(
            json.dumps(event.to_record(), ensure_ascii=False) + '\n'
            for event in events
        )
        if not text:
            return
        with path.open('a', encoding='utf-8') as file:
            if needs_newline:
                file.write('\n')
            file.write(text)


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

    def __set_name__(
            self,
            owner: type,
            name: str,
    ) -> None:
        self.__name__ = name

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

    def update(self, m, /):
        self.data.update(m)
        self.jsonl.append()

    def clear(self):
        super().clear()
        self.jsonl.write()


class Unstaged(EventDict):
    _parent: Events

    def stage(self):
        """Move all unstaged events to the staged state."""
        self._parent.staged.update(self)
        self.clear()


class Staged(EventDict):
    _parent: Events

    def commit(
            self,
    ):
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
