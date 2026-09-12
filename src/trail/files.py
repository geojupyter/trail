from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from stat import S_ISREG
from typing import TYPE_CHECKING, Self, overload
from uuid import uuid4

from .changes import Changes
from .node import Node

from .watchdog import Watchdog

if TYPE_CHECKING:
    from .trail import Trail

FileKey = str | Path | int


class File(Node):
    path: Path
    _parent: Files

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        path = Path(path).expanduser().resolve()
        metadata = path.stat()
        if not S_ISREG(metadata.st_mode):
            raise ValueError(f"Not a regular file: {path}")
        out = cls()
        out.path = path
        out.size = metadata.st_size
        out.mtime = metadata.st_mtime
        _ = out.id
        return out

    @property
    def name(self) -> str:
        return self.path.name

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
        out = Changes([change for change in changes if change.file_id == self.id])
        out._parent = changes
        return out

    @property
    def directory(self) -> Path:
        return self.path.parent

    def add(self) -> None:
        watchdog = self._files.watchdog
        watchdog.watch(self.directory)
        watchdog.dir2ids.setdefault(self.directory, set()).add(self.id)

    def remove(self) -> None:
        watchdog = self._files.watchdog
        ids = watchdog.dir2ids.get(self.directory)
        if ids is None or self.id not in ids:
            return
        if len(ids) == 1:
            watch = watchdog.watches.get(self.directory)
            if watch is not None:
                watchdog.observer.unschedule(watch)
                del watchdog.watches[self.directory]
            del watchdog.dir2ids[self.directory]
        else:
            ids.remove(self.id)

    def move(self, destination: str | Path) -> Self:
        """Update tracking after a filesystem move; do not move anything on disk."""
        files = self._files
        if files.id2file.get(self.id) is not self:
            raise KeyError(f'File is not tracked: {self.path}')
        destination = Path(destination).expanduser().resolve()
        source = self.path
        if source == destination:
            return self
        watchdog = files.watchdog
        watchdog.watch(destination.parent)
        watchdog.dir2ids.setdefault(destination.parent, set()).add(self.id)
        occupant = files.path2file.get(destination)
        if occupant is not None:
            del files[occupant.id]
        if source.parent != destination.parent:
            self.remove()
        del files.path2file[source]
        self.path = destination
        files.path2file[destination] = self
        return self

class Files(Node):
    """Tracked files indexed by normalized path and stable ID.

    Mutate through this collection, and use File.move() to change a tracked path.
    Assignment keys must match the supplied File's path or ID. Replacing a
    file removes its old entries from both indexes and updates its watches.
    """

    _parent: Trail

    @cached_property
    def path2file(self) -> dict[Path, File]:
        """Mapping from normalized file paths to File objects."""
        return {}

    @cached_property
    def id2file(self) -> dict[int, File]:
        """Mapping from stable file IDs to File objects."""
        return {}

    @overload
    def __getitem__(self, key: FileKey) -> File: ...

    @overload
    def __getitem__(self, key: Iterable[FileKey]) -> tuple[File, ...]: ...

    def __getitem__(self, key: FileKey | Iterable[FileKey]) -> File | tuple[File, ...]:
        if isinstance(key, int):
            return self.id2file[key]
        if isinstance(key, (str, Path)):
            return self.path2file[Path(key).expanduser().resolve()]
        selected = []
        for value in key:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or file ID')
            selected.append(self[value])
        return tuple(selected)

    def __setitem__(
            self,
            key: str | Path | int,
            file: File,
    ) -> None:
        """Key-agnostic method to register a file by path or ID, replacing any existing entries."""
        if not isinstance(file, File):
            raise TypeError('Expected a File')
        path = Path(file.path).expanduser().resolve()
        if isinstance(key, int):
            matches = key == file.id
        else:
            matches = Path(key).expanduser().resolve() == path
        if not matches:
            raise ValueError('Key must match the file ID or normalized path')
        parent = file.__dict__.get('_parent')
        if (
            parent is not None
            and parent is not self
            and parent.get(file.id) is file
        ):
            raise ValueError('File already belongs to another collection')

        # Schedule before replacing anything, so failure leaves both indexes intact.
        self.watchdog.watch(path.parent)
        self.watchdog.dir2ids.setdefault(path.parent, set()).add(file.id)
        previous = self.id2file.get(file.id)
        occupant = self.path2file.get(path)
        for old in (previous, occupant):
            if (
                old is not None
                and old is not file
                and self.id2file.get(old.id) is old
            ):
                if (
                    old.id != file.id
                    or old.directory != path.parent
                ):
                    old.remove()
                del self.path2file[old.path]
                del self.id2file[old.id]
        file.path = path
        file._parent = self
        self.path2file[path] = file
        self.id2file[file.id] = file

    def __delitem__(self, key: FileKey | Iterable[FileKey]) -> None:
        keys = (key,) if isinstance(key, (str, Path, int)) else key
        files = {}
        for value in keys:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or file ID')
            file = self.get(value)
            if file is not None:
                files[file.id] = file
        for file in files.values():
            file.remove()
            del self.path2file[file.path]
            del self.id2file[file.id]

    def __iter__(self) -> Iterator[int]:
        return iter(self.id2file)

    def __len__(self) -> int:
        return len(self.id2file)

    def __contains__(self, key: str | Path | int) -> bool:
        if isinstance(key, int):
            return key in self.id2file
        return Path(key).expanduser().resolve() in self.path2file

    def get(
            self,
            key: str | Path | int,
            default=None,
    ):
        try:
            return self[key]
        except KeyError:
            return default

    def items(self):
        return self.id2file.items()

    def by_path(self, path: str | Path) -> File | None:
        return self.path2file.get(Path(path).expanduser().resolve())

    def add(self, *paths: str | Path) -> tuple[File, ...]:
        """Register each distinct path once, validating the batch first."""
        selected: dict[Path, File] = {}
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved not in selected:
                selected[resolved] = self.path2file.get(resolved) or File.from_path(resolved)

        registered = []
        try:
            for file in selected.values():
                if self.id2file.get(file.id) is file:
                    continue
                while file.id in self.id2file:
                    del file.id
                self[file.id] = file
                registered.append(file)
        except Exception:
            for file in reversed(registered):
                del self[file.id]
            raise
        return tuple(selected.values())

    @cached_property
    def watchdog(self) -> Watchdog:
        out = Watchdog()
        out._parent = self
        return out

    def observing(self, *, debounce: float | None = None):
        """Observe registered resources for the duration of an async context.

        Events are processed asynchronously; exiting drains pending events.
        Stage changes after they appear in changes.unstaged, or after exit.
        """
        if debounce is not None:
            self.watchdog.debounce = debounce
        return self.watchdog.context()
