from __future__ import annotations
from functools import cached_property

from collections.abc import Iterator
from pathlib import Path
from typing import Self

from .entry import Entries, Entry


class Dir(Entry):
    _parent: Dirs
    is_directory = True

    @cached_property
    def _parent(self) -> Dirs:
        return self._trail.dirs

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((self.path, self.directory)))

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
            if not entry.is_directory or not entry.path.is_dir():
                continue
            for child in entry.path.iterdir():
                if child.is_symlink() or trail._ignored(child):
                    continue
                if child.is_file() or child.is_dir():
                    collection = trail.dirs if child.is_dir() else trail.files
                    pending.append(
                        collection.get(child)
                        or Entry.from_path(child, trail=trail)
                    )

    def remove(self) -> None:
        collection = self._parent
        if collection is None or collection.id2entry.get(self.id) is not self:
            return
        for path in self._watch_paths:
            self._watchdog.release(path, self.id)
        super().remove()

    def move(self, destination: str | Path) -> Self:
        dirs = self._trail.dirs
        if dirs.id2entry.get(self.id) is not self:
            raise KeyError(f'Directory is not tracked: {self.path}')
        destination = Path(destination).expanduser().resolve()
        source = self.path
        if source == destination:
            return self
        if destination.is_relative_to(source):
            raise ValueError('Cannot move a directory inside itself')

        files = self._trail.files
        directories = [
            (directory, directory.path, destination / directory.path.relative_to(source))
            for directory in dirs.id2entry.values()
            if directory.path.is_relative_to(source)
        ]
        descendants = [
            (file, destination / file.path.relative_to(source))
            for file in files.id2entry.values()
            if file.path.is_relative_to(source)
        ]
        watchdog = files.watchdog
        retained: list[tuple[Path, int]] = []
        try:
            for directory, previous, target in directories:
                for path in dict.fromkeys((target, target.parent)):
                    watchdog.watch(path)
                    ids = watchdog.dir2ids.setdefault(path, set())
                    if directory.id not in ids:
                        ids.add(directory.id)
                        retained.append((path, directory.id))
            for file, target in descendants:
                watchdog.watch(target.parent)
                ids = watchdog.dir2ids.setdefault(target.parent, set())
                if file.id not in ids:
                    ids.add(file.id)
                    retained.append((target.parent, file.id))
        except Exception:
            for path, identifier in reversed(retained):
                watchdog.release(path, identifier)
            raise

        for directory, previous, target in directories:
            occupant = dirs.path2entry.get(target)
            if occupant is not None and occupant is not directory:
                occupant.remove()
            retained_paths = {target, target.parent}
            for path in dict.fromkeys((previous, previous.parent)):
                if path not in retained_paths:
                    watchdog.release(path, directory.id)
            del dirs.path2entry[previous]
            directory.path = target
            dirs.path2entry[target] = directory
        for file, target in descendants:
            file.move(target)
        return self


class Dirs(Entries[Dir]):
    entry_type = Dir
