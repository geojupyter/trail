from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Self, TYPE_CHECKING

from .entry import Entries, Entry
from ._changes import Change, Changes, ChangeStatus

if TYPE_CHECKING:
    from .trail import Trail

class File(Entry):
    _parent: Files

    @cached_property
    def _parent(self) -> Files:
        return self._trail.files

    @property
    def _watch_paths(self) -> tuple[Path, ...]:
        return (self.directory,)

    @property
    def events(self) -> Changes:
        changes = self._trail.changes
        selected = (
            change
            for change in changes
            if change.file_id == self.id
        )
        return Changes(changes, selected)

    def add(self) -> Self:
        collection = self._parent
        if collection is None:
            raise ValueError('Entry has no Trail; pass trail to from_path')
        trail = collection._trail
        if self._trail is not trail:
            raise ValueError('Entry already belongs to another Trail')
        if collection is not trail.files:
            raise ValueError('Entry belongs to the wrong collection')
        path = Path(self.path).expanduser().resolve()
        if trail._ignored(path):
            raise ValueError(f'Cannot track Trail metadata: {path}')
        while self.id in trail.dirs.id2entry:
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

    def remove(self) -> None:
        collection = self._parent
        if (
            collection is None
            or collection.id2entry.get(self.id) is not self
        ):
            return
        self._watchdog.release(self.directory, self.id)
        super().remove()

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
            is_directory=False,
            file_id=self.id,
            dir_id=None,
            status=status,
            **kwargs,
        )

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
