from __future__ import annotations

import json
from collections import UserDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .event import Event
    from .trail import Trail

@dataclass
class Commit:
    id: int = field(default_factory=lambda: uuid4().int, kw_only=True)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC),
        kw_only=True,
    )
    events: list[Event | int]
    message: str = ''
    author: str | None = None

    @classmethod
    def from_record(cls, /, **record) -> Commit:
        record['timestamp'] = datetime.fromisoformat(record['timestamp'])
        return cls(**record)

    def to_record(self) -> dict:
        event_ids = [
            event if isinstance(event, int) else event.id
            for event in self.events
        ]
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'events': event_ids,
            'message': self.message,
            'author': self.author,
        }


class JSONL(Node):
    _parent: Commits

    @property
    def path(self) -> Path | None:
        trail = self._trail
        if trail.dir:
            return trail.dir / 'commits.jsonl'
        return None

    def read(self) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        loaded: dict[int, Commit] = {}
        with path.open(encoding='utf-8') as file:
            for line in file:
                if not line.strip():
                    continue
                commit = Commit.from_record(**json.loads(line))
                if commit.id in loaded:
                    raise ValueError(f'Duplicate commit ID in {path}: {commit.id}')
                loaded[commit.id] = commit
        self._parent.data.clear()
        self._parent.data.update(loaded)

    def write(self) -> None:
        path = self.path
        if path is None:
            return
        text = ''.join(
            json.dumps(commit.to_record(), ensure_ascii=False) + '\n'
            for commit in self._parent.values()
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def append(self, commits: Iterable[Commit]) -> None:
        path = self.path
        if path is None:
            return
        text = ''.join(
            json.dumps(commit.to_record(), ensure_ascii=False) + '\n'
            for commit in commits
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


class Commits(
    UserDict[int, Commit],
    Node
):
    _parent: Trail

    @cached_property
    def jsonl(self) -> JSONL:
        return JSONL(self)

    def update(self, m, /) -> None:
        batch = dict(m)
        self.jsonl.append(batch.values())
        self.data.update(batch)

    def clear(self) -> None:
        super().clear()
        self.jsonl.write()

    def __setitem__(
            self,
            key: int,
            value: Commit,
    ) -> None:
        if not isinstance(value, Commit):
            raise TypeError(f'Expected Commit, got {type(value).__name__}')
        self.jsonl.append([value])
        self.data[key] = value
