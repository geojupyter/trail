from __future__ import annotations
import json

from pathlib import Path

import dataclasses
from functools import cached_property
from typing import Self
from uuid import uuid4
from .commits import Commit, Commits

from .changes import Change, Changes
from .dir import Dir, Dirs
from .file import File, Files
from .entry import Entry
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
    def changes(self):
        return Changes(self)

    @cached_property
    def json(self):
        return JSON(self)

    @cached_property
    def commits(self):
        return Commits(self)

    def __init__(
            self,
            dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        if dir is None:
            # nodir mode
            self.dir = None
        else:
            self.dir = (
                Path(dir)
                .expanduser()
                .resolve()
            )
            self.json.load()

    @cached_property
    def id(self) -> int:
        return uuid4().int

    def add(
            self,
            *paths: str | Path,
    ) -> tuple[Entry, ...]:
        requested = dict.fromkeys(
            Path(path).expanduser().resolve()
            for path in paths
        )
        selected: dict[Path, Entry] = {}
        for path in requested:
            if self._ignored(path):
                raise ValueError(f'Cannot track Trail metadata: {path}')
            root = selected.get(path)
            if root is None:
                if path.is_dir():
                    root = self.dirs.get(path)
                elif path.is_file():
                    root = self.files.get(path)
                else:
                    root = (
                        self.dirs.get(path)
                        or self.files.get(path)
                    )
                if root is None:
                    root = Entry.from_path(path, trail=self)
            for entry in root.walk():
                selected.setdefault(entry.path, entry)
        roots = [
            path
            for path in requested
            if isinstance(selected[path], Dir)
        ]
        if roots:
            for entry in (*self.dirs.id2entry.values(), *self.files.id2entry.values()):
                if any(
                    entry.path.is_relative_to(root)
                    for root in roots
                ):
                    selected.setdefault(entry.path, entry)

        registered = []
        try:
            for entry in selected.values():
                if isinstance(entry, Dir):
                    collection = self.dirs
                else:
                    collection = self.files
                if collection.get(entry.id) is entry:
                    entry.add()
                    continue
                while (
                    entry.id in self.files
                    or entry.id in self.dirs
                ):
                    del entry.id
                entry.add()
                registered.append(entry)
            added = [
                entry.change('added', 'staged')
                for entry in registered
            ]
            ids = {
                entry.id
                for entry in selected.values()
            }
            staged = [
                dataclasses.replace(change, status='staged')
                for change in self.changes.unstaged
                if change.file_id in ids or change.dir_id in ids
            ]
            self.changes.record([*added, *staged])
        except Exception:
            for entry in reversed(registered):
                entry.remove()
            raise
        return tuple(
            selected[path]
            for path in requested
        )

    def _ignored(self, path: Path) -> bool:
        return self.dir is not None and path.is_relative_to(self.dir)

    def remove(
            self,
            *files: str | Path | File | Dir | int,
    ) -> tuple[File | Dir, ...]:
        selected = {}
        for value in files:
            if isinstance(value, (File, Dir)):
                if isinstance(value, Dir):
                    collection = self.dirs
                else:
                    collection = self.files
                if collection.get(value.id) is value:
                    resource = value
                else:
                    resource = None
            else:
                resource = (
                    self.dirs.get(value)
                    or self.files.get(value)
                )
            if resource is None:
                continue
            selected[resource.id] = resource
            if isinstance(resource, Dir):
                for child in (*self.dirs.id2entry.values(), *self.files.id2entry.values()):
                    if child.path.is_relative_to(resource.path):
                        selected[child.id] = child
        removed = tuple(selected.values())
        ids = set(selected)
        staged = [
            dataclasses.replace(change, status='staged')
            for change in self.changes.unstaged
            if change.file_id in ids or change.dir_id in ids
        ]
        removals = [
            resource.change('removed', 'staged')
            for resource in removed
        ]
        detached = []
        try:
            for resource in reversed(removed):
                resource.remove()
                detached.append(resource)
            self.changes.record([*staged, *removals])
        except Exception:
            for resource in reversed(detached):
                resource.add()
            raise
        return removed

    def commit(
            self,
            message: str | None = None,
            author: str | None = None,
    ) -> tuple[Change, ...]:
        """Commit staged records, leaving subsequent unstaged changes alone.

        This commits change metadata only; it does not snapshot file contents.
        """
        staged = tuple(self.changes.staged)
        if not staged:
            return ()
        commit = Commit(_parent=self.commits, message=message or '', author=author)
        while commit.id in self.commits.id2commit:
            commit.id = uuid4().int
        snapshots = [
            dataclasses.replace(change, status='committed', commit_id=commit.id)
            for change in staged
        ]
        checkpoints = {}
        if self.dir is not None:
            for path in (self.commits.csv.path, self.changes.csv.path):
                checkpoints[path] = path.stat().st_size if path.exists() else None
        try:
            if self.dir is not None:
                self.commits.csv.append([commit])
            self.changes.record(snapshots)
        except BaseException:
            for path, size in checkpoints.items():
                if size is None:
                    path.unlink(missing_ok=True)
                elif path.exists() and path.stat().st_size != size:
                    with path.open('r+b') as stream:
                        stream.truncate(size)
            raise
        self.commits.id2commit[commit.id] = commit
        return staged

    def push(
            self,
    ):
        ...

    def pull(
            self
    ):
        ...

