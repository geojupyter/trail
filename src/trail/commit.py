from __future__ import annotations

import json
from collections import UserDict
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

    def append(self) -> None:
        path = self.path
        if path is None:
            return
        if not path.exists():
            self.write()
            return
        commits = iter(self._parent.values())
        needs_newline = False
        with path.open(encoding='utf-8') as file:
            for line in file:
                needs_newline = not line.endswith('\n')
                if not line.strip():
                    continue
                commit = next(commits, None)
                if (
                        commit is None
                        or json.loads(line) != commit.to_record()
                ):
                    raise ValueError(
                        f'{path} does not match the commit prefix; use write() to replace it'
                    )
        text = ''.join(
            json.dumps(commit.to_record(), ensure_ascii=False) + '\n'
            for commit in commits
        )
        if not text:
            return
        with path.open('a', encoding='utf-8') as file:
            if needs_newline:
                file.write('\n')
            file.write(text)


class Commits(
    UserDict[int, Commit],
    Node
):
    _parent: Trail

    @cached_property
    def jsonl(self) -> JSONL:
        return JSONL(self)

    def update(self, m, /) -> None:
        self.data.update(m)
        self.jsonl.append()

    def clear(self) -> None:
        super().clear()
        self.jsonl.write()
