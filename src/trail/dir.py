from __future__ import annotations
from functools import cached_property

from collections.abc import Iterator
from pathlib import Path
from typing import Self

from .entry import Entries, Entry
from .event import Event, Events


class Dir(Entry):
    _parent: Dirs

    @cached_property
    def _parent(self) -> Dirs:
        return self._trail.dirs

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((self.path, self.directory)))

    # @property
    # def events(self) -> Events:
    #     changes = self._trail.changes
    #     selected = (
    #         change
    #         for change in changes
    #         if change.dir_id == self.id
    #     )
    #     return Changes(changes, selected)

    def add(self) -> Self:
        collection = self._parent
        if collection is None:
            raise ValueError('Entry has no Trail; pass trail to from_path')
        trail = collection._trail
        if self._trail is not trail:
            raise ValueError('Entry already belongs to another Trail')
        if collection is not trail.dirs:
            raise ValueError('Entry belongs to the wrong collection')
        path = Path(self.path).expanduser().resolve()
        if trail._ignored(path):
            raise ValueError(f'Cannot track Trail metadata: {path}')
        while self.id in trail.files.id2entry:
            del self.id
        previous_path = self.path
        self.path = path
        watchdog = self._watchdog
        retained = []
        try:
            for watched_path in self._watch_paths:
                watchdog.watch(watched_path)
                ids = watchdog.dir2ids.setdefault(watched_path, set())
                if self.id not in ids:
                    ids.add(self.id)
                    retained.append(watched_path)
        except Exception:
            for watched_path in reversed(retained):
                watchdog.release(watched_path, self.id)
            self.path = previous_path
            raise

        previous = collection.id2entry.get(self.id)
        occupant = collection.path2entry.get(path)
        for old in (previous, occupant):
            if (
                old is None
                or old is self
                or collection.id2entry.get(old.id) is not old
            ):
                continue
            if old.id == self.id:
                for watched_path in old._watch_paths:
                    if watched_path not in self._watch_paths:
                        watchdog.release(watched_path, old.id)
                Entry.remove(old)
            else:
                old.remove()
        collection.path2entry[path] = self
        collection.id2entry[self.id] = self
        return self

    def walk(self) -> Iterator[Entry]:
        trail = self._trail
        pending: list[Entry] = [self]
        seen: set[Path] = set()
        while pending:
            entry = pending.pop()
            if entry.path in seen:
                continue
            seen.add(entry.path)
            yield entry
            if not isinstance(entry, Dir) or not entry.path.is_dir():
                continue
            for child in entry.path.iterdir():
                if (
                    child.is_symlink()
                    or trail._ignored(child)
                    or child in trail._removed_paths
                ):
                    continue
                if child.is_dir():
                    collection = trail.dirs
                else:
                    collection = trail.files
                pending.append(
                    collection.get(child)
                    or Entry.from_path(child, trail=trail)
                )

    def remove(self) -> None:
        collection = self._parent
        if (
            collection is None
            or collection.id2entry.get(self.id) is not self
        ):
            return
        for path in self._watch_paths:
            self._watchdog.release(path, self.id)
        super().remove()

class Dirs(Entries[Dir]):
    entry_type = Dir
