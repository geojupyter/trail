from __future__ import annotations

from collections.abc import ItemsView, Iterable, Iterator
from functools import cached_property
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import overload, Self, TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail
    from .event import Event

EntryKey = str | Path | int


class Entry(Node):
    path: Path
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
        metadata = path.stat()

        if trail is not None and trail._ignored(path):
            raise ValueError(f'Cannot track Trail metadata: {path}')

        if issubclass(cls, Dir):
            if not S_ISDIR(metadata.st_mode):
                raise ValueError(f'Not a directory: {path}')
        elif issubclass(cls, File):
            if not S_ISREG(metadata.st_mode):
                raise ValueError(f'Not a regular file: {path}')
        else:
            if S_ISDIR(metadata.st_mode):
                cls = Dir
            elif S_ISREG(metadata.st_mode):
                cls = File
            else:
                raise ValueError(f'Not a regular file or directory: {path}')

        out = cls()
        out.path = path
        out._trail = trail
        if trail is not None:
            if isinstance(out, Dir):
                out._parent = trail.dirs
            else:
                out._parent = trail.files
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

    @cached_property
    def events(self) -> dict[int, Event]:
        return {}

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        raise NotImplementedError

    def walk(self) -> Iterator[Entry]:
        yield self

    def add(self) -> Self:
        raise NotImplementedError

    def remove(self) -> None:
        collection = self._parent
        if (
            collection is None
            or collection.id2entry.get(self.id) is not self
        ):
            return
        del collection.id2entry[self.id]
        if collection.path2entry.get(self.path) is self:
            del collection.path2entry[self.path]


class Entries[E: Entry](Node):
    _parent: Trail
    entry_type: type[E]

    @cached_property
    def path2entry(self) -> dict[Path, E]:
        return {}

    @cached_property
    def id2entry(self) -> dict[int, E]:
        return {}

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
                selected[resolved] = (
                    self.get(resolved)
                    or self.entry_type.from_path(resolved, trail=self._trail)
                )
        registered = []
        try:
            for entry in selected.values():
                if self.id2entry.get(entry.id) is entry:
                    entry.add()
                    continue
                while (
                    entry.id in self._trail.files
                    or entry.id in self._trail.dirs
                ):
                    del entry.id
                entry.add()
                registered.append(entry)
        except Exception:
            for entry in reversed(registered):
                entry.remove()
            raise
        return tuple(selected.values())
