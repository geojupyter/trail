from __future__ import annotations

from collections.abc import Iterable, Iterator, ItemsView
from functools import cached_property
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Self, cast, overload
from uuid import uuid4

from .changes import Change, Changes, ChangeStatus
from .node import Node

if TYPE_CHECKING:
    from .trail import Trail
    from .watchdog import Watchdog

EntryKey = str | Path | int


class Entry(Node):
    path: Path
    is_directory: bool
    _parent: Entries[Self]
    id: int

    @classmethod
    def from_path(
            cls,
            path: str | Path,
            trail: Trail | None = None,
    ) -> Self:
        from .dir import Dir
        from .file import File

        path = Path(path).expanduser().resolve()
        if trail is not None and trail._ignored(path):
            raise ValueError(f'Cannot track Trail metadata: {path}')
        metadata = path.stat()
        entry_type = cls
        if cls is Entry:
            entry_type = cast(type[Self], Dir if S_ISDIR(metadata.st_mode) else File)
        valid = S_ISDIR(metadata.st_mode) if entry_type.is_directory else S_ISREG(metadata.st_mode)
        if not valid:
            kind = 'directory' if entry_type.is_directory else 'regular file'
            raise ValueError(f'Not a {kind}: {path}')
        out = entry_type()
        out.path = path
        out.size = metadata.st_size
        out.mtime = metadata.st_mtime
        _ = out.id
        if trail is not None:
            out._trail = trail
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
            if (change.dir_id if self.is_directory else change.file_id) == self.id
        )
        return Changes(changes, selected)

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        raise NotImplementedError

    def walk(self) -> Iterator[Entry]:
        yield self

    def add(self) -> Self:
        collection = self._parent
        if collection is None:
            raise ValueError('Entry has no Trail; pass trail to from_path')
        trail = collection._trail
        if self._trail is not trail:
            raise ValueError('Entry already belongs to another Trail')
        expected = trail.dirs if self.is_directory else trail.files
        if collection is not expected:
            raise ValueError('Entry belongs to the wrong collection')
        path = Path(self.path).expanduser().resolve()
        if trail._ignored(path):
            raise ValueError(f'Cannot track Trail metadata: {path}')
        other = trail.files if self.is_directory else trail.dirs
        while self.id in other.id2entry:
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
            if old is None or old is self or collection.id2entry.get(old.id) is not old:
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

    def remove(self) -> None:
        collection = self._parent
        if collection is None or collection.id2entry.get(self.id) is not self:
            return
        del collection.id2entry[self.id]
        if collection.path2entry.get(self.path) is self:
            del collection.path2entry[self.path]

    def change(
            self,
            event_type: str,
            status: ChangeStatus = 'unstaged',
            **kwargs,
    ) -> Change:
        return Change(
            _parent=self._trail.files,
            src_path=str(self.path),
            event_type=event_type,
            is_directory=self.is_directory,
            file_id=None if self.is_directory else self.id,
            dir_id=self.id if self.is_directory else None,
            status=status,
            **kwargs,
        )

    def move(self, destination: str | Path) -> Self:
        raise NotImplementedError


class Entries[E: Entry](Node):
    _parent: Trail
    entry_type: type[E]

    @cached_property
    def path2entry(self) -> dict[Path, E]:
        return {}

    @cached_property
    def id2entry(self) -> dict[int, E]:
        return {}

    @property
    def watchdog(self) -> Watchdog:
        return self._trail.files.watchdog

    @property
    def _watchdog(self) -> Watchdog:
        return self.watchdog

    @overload
    def __getitem__(self, key: EntryKey) -> E: ...

    @overload
    def __getitem__(self, key: Iterable[EntryKey]) -> tuple[E, ...]: ...

    def __getitem__(
            self,
            key: EntryKey | Iterable[EntryKey],
    ) -> E | tuple[E, ...]:
        if isinstance(key, int):
            return self.id2entry[key]
        if isinstance(key, (str, Path)):
            return self.path2entry[Path(key).expanduser().resolve()]
        selected = []
        for value in key:
            if not isinstance(value, (str, Path, int)):
                raise TypeError('Expected a path or entry ID')
            selected.append(self[value])
        return tuple(selected)

    def __iter__(self) -> Iterator[int]:
        return iter(self.id2entry)

    def __len__(self) -> int:
        return len(self.id2entry)

    def __contains__(self, key: EntryKey) -> bool:
        if isinstance(key, int):
            return key in self.id2entry
        return Path(key).expanduser().resolve() in self.path2entry

    @overload
    def get(self, key: EntryKey) -> E | None: ...

    @overload
    def get[D](
            self,
            key: EntryKey,
            default: D,
    ) -> E | D: ...

    def get[D](
            self,
            key: EntryKey,
            default: D | None = None,
    ) -> E | D | None:
        try:
            return self[key]
        except KeyError:
            return default

    def items(self) -> ItemsView[int, E]:
        return self.id2entry.items()

    def add(self, *paths: str | Path) -> tuple[E, ...]:
        selected: dict[Path, E] = {}
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved not in selected:
                selected[resolved] = self.get(resolved) or self.entry_type.from_path(
                    resolved,
                    trail=self._trail,
                )
        registered = []
        try:
            for entry in selected.values():
                if self.id2entry.get(entry.id) is entry:
                    entry.add()
                    continue
                while entry.id in self._trail.files or entry.id in self._trail.dirs:
                    del entry.id
                entry.add()
                registered.append(entry)
        except Exception:
            for entry in reversed(registered):
                entry.remove()
            raise
        return tuple(selected.values())

    def observing(self, *, debounce: float | None = None):
        if debounce is not None:
            self._watchdog.debounce = debounce
        return self._watchdog.context()
