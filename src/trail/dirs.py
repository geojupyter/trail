from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from stat import S_ISDIR
from typing import TYPE_CHECKING, Self, overload
from uuid import uuid4

from .changes import Changes
from .node import Node

if TYPE_CHECKING:
    from .trail import Trail
    from .watchdog import Watchdog

DirKey = str | Path | int


class Dir(Node):
    path: Path
    _parent: Dirs

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        path = Path(path).expanduser().resolve()
        metadata = path.stat()
        if not S_ISDIR(metadata.st_mode):
            raise ValueError(f'Not a directory: {path}')
        out = cls()
        out.path = path
        out.size = metadata.st_size
        out.mtime = metadata.st_mtime
        _ = out.id
        return out

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def directory(self) -> Path:
        return self.path.parent

    @cached_property
    def size(self) -> int:
        return self.path.stat().st_size

    @cached_property
    def mtime(self) -> float:
        return self.path.stat().st_mtime

    @cached_property
    def id(self) -> int:
        return uuid4().int

    @property
    def events(self) -> Changes:
        changes = self._trail.changes
        selected = (
            change
            for change in changes
            if change.dir_id == self.id
        )
        return Changes(changes, selected)

    def add(self) -> None:
        self._parent._retain(self)

    def remove(self) -> None:
        watchdog = self._trail.files.watchdog
        for path in dict.fromkeys((self.path, self.directory)):
            watchdog.release(path, self.id)

    def move(self, destination: str | Path) -> Self:
        dirs = self._trail.dirs
        if dirs.id2dir.get(self.id) is not self:
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
            for directory in dirs.id2dir.values()
            if directory.path.is_relative_to(source)
        ]
        descendants = [
            (file, destination / file.path.relative_to(source))
            for file in files.id2file.values()
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
            occupant = dirs.path2dir.get(target)
            if occupant is not None and occupant is not directory:
                del dirs[occupant.id]
            retained_paths = {target, target.parent}
            for path in dict.fromkeys((previous, previous.parent)):
                if path not in retained_paths:
                    watchdog.release(path, directory.id)
            del dirs.path2dir[previous]
            directory.path = target
            dirs.path2dir[target] = directory
        for file, target in descendants:
            file.move(target)
        return self


class Dirs(Node):
    _parent: Trail

    @cached_property
    def path2dir(self) -> dict[Path, Dir]:
        return {}

    @cached_property
    def id2dir(self) -> dict[int, Dir]:
        return {}

    @property
    def watchdog(self) -> Watchdog:
        return self._trail.files.watchdog

    @overload
    def __getitem__(self, key: DirKey) -> Dir: ...

    @overload
    def __getitem__(self, key: Iterable[DirKey]) -> tuple[Dir, ...]: ...

    def __getitem__(self, key: DirKey | Iterable[DirKey]) -> Dir | tuple[Dir, ...]:
        if isinstance(key, int):
            return self.id2dir[key]
        if isinstance(key, (str, Path)):
            return self.path2dir[Path(key).expanduser().resolve()]
        selected = []
        for value in key:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or directory ID')
            selected.append(self[value])
        return tuple(selected)

    def _retain(self, directory: Dir) -> None:
        watchdog = self.watchdog
        retained = []
        try:
            for path in dict.fromkeys((directory.path, directory.directory)):
                watchdog.watch(path)
                ids = watchdog.dir2ids.setdefault(path, set())
                if directory.id not in ids:
                    ids.add(directory.id)
                    retained.append(path)
        except Exception:
            for path in reversed(retained):
                watchdog.release(path, directory.id)
            raise

    def __setitem__(
            self,
            key: DirKey,
            directory: Dir,
    ) -> None:
        if not isinstance(directory, Dir):
            raise TypeError('Expected a Dir')
        path = Path(directory.path).expanduser().resolve()
        if isinstance(key, int):
            matches = key == directory.id
        elif isinstance(key, (str, Path)):
            matches = Path(key).expanduser().resolve() == path
        else:
            raise TypeError('Expected a path or directory ID')
        if not matches:
            raise ValueError('Key must match the directory ID or normalized path')
        parent = directory.__dict__.get('_parent')
        if (
            parent is not None
            and parent is not self
            and parent.get(directory.id) is directory
        ):
            raise ValueError('Directory already belongs to another collection')

        previous_path = directory.path
        directory.path = path
        try:
            self._retain(directory)
        except Exception:
            directory.path = previous_path
            raise
        previous = self.id2dir.get(directory.id)
        occupant = self.path2dir.get(path)
        retained_paths = {path, path.parent}
        for old in (previous, occupant):
            if (
                old is not None
                and old is not directory
                and self.id2dir.get(old.id) is old
            ):
                for watched_path in dict.fromkeys((old.path, old.directory)):
                    if old.id != directory.id or watched_path not in retained_paths:
                        self.watchdog.release(watched_path, old.id)
                del self.path2dir[old.path]
                del self.id2dir[old.id]
        directory._parent = self
        if parent is not self:
            directory.__dict__.pop('_trail', None)
        self.path2dir[path] = directory
        self.id2dir[directory.id] = directory

    def __delitem__(self, key: DirKey | Iterable[DirKey]) -> None:
        keys = (key,) if isinstance(key, (str, Path, int)) else key
        directories = {}
        for value in keys:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or directory ID')
            directory = self.get(value)
            if directory is not None:
                directories[directory.id] = directory
        for directory in directories.values():
            directory.remove()
            del self.path2dir[directory.path]
            del self.id2dir[directory.id]

    def __iter__(self) -> Iterator[int]:
        return iter(self.id2dir)

    def __len__(self) -> int:
        return len(self.id2dir)

    def __contains__(self, key: DirKey) -> bool:
        if isinstance(key, int):
            return key in self.id2dir
        return Path(key).expanduser().resolve() in self.path2dir

    def get(
            self,
            key: DirKey,
            default=None,
    ):
        try:
            return self[key]
        except KeyError:
            return default

    def items(self):
        return self.id2dir.items()

    def observing(self, *, debounce: float | None = None):
        return self._trail.files.observing(debounce=debounce)

    def add(self, *paths: str | Path) -> tuple[Dir, ...]:
        selected: dict[Path, Dir] = {}
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved not in selected:
                selected[resolved] = self.path2dir.get(resolved) or Dir.from_path(resolved)

        registered = []
        try:
            for directory in selected.values():
                if self.id2dir.get(directory.id) is directory:
                    continue
                while directory.id in self.id2dir:
                    del directory.id
                self[directory.id] = directory
                registered.append(directory)
        except Exception:
            for directory in reversed(registered):
                del self[directory.id]
            raise
        return tuple(selected.values())
