from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from functools import cached_property
from pathlib import Path
from typing import overload
from uuid import uuid4

from .commit import Commit, Commits
from .dir import Dirs
from .entry import Entry, EntryKey
from .event import AddEntryEvent, Events, RemoveEntryEvent
from .file import Files
from .node import Node
from .watchdog import Watchdog


class JSON(Node):
    _parent: Trail

    @property
    def dict(self) -> dict:
        trail = self._parent
        out = {
            'id': trail.id,
        }
        return out

    def dump(self):
        path = self.path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w') as f:
            json.dump(self.dict, f)

    def load(self):
        path = self.path
        if path is None or not path.exists():
            return
        with path.open('r') as f:
            data = json.load(f)
        trail = self._parent
        for key, value in data.items():
            self._setnested(trail, key, value)

    @cached_property
    def path(self):
        trail = self._trail
        if trail.dir:
            return trail.dir / 'path.json'
        else:
            return None


class EntryLookup(
    Mapping[EntryKey, Entry],
    Node,
):
    _parent: Trail

    @overload
    def __getitem__(self, key: EntryKey) -> Entry:
        ...

    @overload
    def __getitem__(self, key: Iterable[EntryKey]) -> tuple[Entry, ...]:
        ...

    def __getitem__(
            self,
            key: EntryKey | Iterable[EntryKey],
    ) -> Entry | tuple[Entry, ...]:
        if isinstance(key, (str, Path, int)):
            try:
                return self._parent.files[key]
            except KeyError:
                return self._parent.dirs[key]
        selected = []
        for value in key:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or entry ID')
            selected.append(self[value])
        return tuple(selected)

    def __iter__(self) -> Iterator[int]:
        yield from self._parent.files
        yield from self._parent.dirs

    def __len__(self) -> int:
        out = len(self._parent.files)
        out += len(self._parent.dirs)
        return out


class Trail(
    Node
):

    @cached_property
    def watchdog(self):
        return Watchdog(self)

    @cached_property
    def files(self):
        return Files(self)

    @cached_property
    def dirs(self):
        return Dirs(self)

    @cached_property
    def entries(self) -> EntryLookup:
        return EntryLookup(self)

    @cached_property
    def json(self):
        return JSON(self)

    @cached_property
    def commits(self):
        out = Commits()
        out._parent = self
        out.jsonl.read()
        return out

    @cached_property
    def events(self):
        return Events(self)

    def __init__(
            self,
            dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        if dir is None:
            # nodir mode
            self.dir = None
        else:
            dir = (
                Path(dir)
                .expanduser()
                .resolve()
            )
            if not dir.name == '.trail':
                dir /= '.trail'
            self.dir = dir
            self.json.load()

    @cached_property
    def id(self) -> int:
        return uuid4().int

    def add(self, *paths: str | Path) -> tuple[Entry, ...]:
        requested = dict.fromkeys(
            Path(path).expanduser().resolve()
            for path in paths
        )
        for path in requested:
            if self._ignored(path):
                raise ValueError(f'Cannot track Trail metadata: {path}')
            if path not in self.entries:
                Entry.from_path(path, trail=self)
        added = []
        for path in requested:
            entry = self.entries.get(path)
            if entry is None:
                # Adding new File or Dir Entry goes straight to staged
                event = AddEntryEvent(src_path=str(path))
                entry = event.apply(self)
                self.events.staged[event.id] = event
            else:
                # Staging the events of an existing Entry
                self.events.unstaged.stage(entry)
            added.append(entry)
        return tuple(added)

    def _ignored(self, path: Path) -> bool:
        return (
                self.dir is not None
                and path.is_relative_to(self.dir)
        )

    def remove(self, *entries: EntryKey | Entry, ) -> tuple[Entry, ...]:
        selected: dict[int, Entry] = {}
        for value in entries:
            if isinstance(value, Entry):
                entry = self.entries.get(value.id)
                if entry is not value:
                    continue
            else:
                if not isinstance(value, (str, Path, int)):
                    raise TypeError('Expected a path, entry ID, or Entry')
                entry = self.entries.get(value)
            if entry is not None:
                selected.setdefault(entry.id, entry)
        removed = []
        for entry in selected.values():
            self.events.unstaged.stage(entry)
            event = RemoveEntryEvent(src_path=str(entry.path))
            result = event.apply(self)
            if result is not None:
                self.events.staged[event.id] = event
                removed.append(result)
        return tuple(removed)

    def commit(
            self,
            message: str = '',
            author: str | None = None,
    ) -> Commit:
        events = self.events.staged
        if not events:
            raise ValueError('No staged events to commit.')
        commit = Commit(
            events=list(events.values()),
            message=message,
            author=author,
        )
        self.commits[commit.id] = commit
        events.commit()
        return commit

    def push(
            self,
    ):
        ...

    def pull(
            self
    ):
        ...
