from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Self, TYPE_CHECKING

from .entry import Entries, Entry
from .watchdog import Watchdog

if TYPE_CHECKING:
    from .trail import Trail

class File(Entry):
    _parent: Files
    is_directory = False

    @cached_property
    def _parent(self) -> Files:
        return self._trail.files

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        return (self.directory,)

    def remove(self) -> None:
        collection = self._parent
        if collection is None or collection.id2entry.get(self.id) is not self:
            return
        self._watchdog.release(self.directory, self.id)
        super().remove()

    def move(self, destination: str | Path) -> Self:
        """Update tracking after a filesystem move; do not move anything on disk."""
        files = self._files
        if files.id2entry.get(self.id) is not self:
            raise KeyError(f'File is not tracked: {self.path}')
        destination = Path(destination).expanduser().resolve()
        source = self.path
        if source == destination:
            return self
        watchdog = self._watchdog
        watchdog.watch(destination.parent)
        watchdog.dir2ids.setdefault(destination.parent, set()).add(self.id)
        occupant = self._files.path2entry.get(destination)
        if occupant is not None:
            occupant.remove()
        if source.parent != destination.parent:
            watchdog.release(source.parent, self.id)
        del files.path2entry[source]
        self.path = destination
        files.path2entry[destination] = self
        return self


class Files(Entries[File]):
    entry_type = File
    _parent: Trail

    @cached_property
    def watchdog(self) -> Watchdog:
        return Watchdog(self)

