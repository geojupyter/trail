from __future__ import annotations
import json

from collections.abc import Iterable
from pathlib import Path

import dataclasses
from functools import cached_property
from typing import Self
from uuid import uuid4
from .commits import Commit, Commits

from .changes import Change, Changes, ChangeStatus
from .dirs import Dir, Dirs
from .files import File, Files
from .node import Node


class JSON(Node):
    _parent: Trail

    @staticmethod
    def setnested(
            obj: object,
            name: str,
            value: object,
    ):
        attrs = name.split('.')
        for attr in attrs[:-1]:
            obj = getattr(obj, attr)
        setattr(obj, attrs[-1], value)

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
            self.setnested(trail, key, value)

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
    ) -> tuple[File | Dir, ...]:
        selected = self._collect(*paths)
        requested = dict.fromkeys(
            Path(path).expanduser().resolve()
            for path in paths
        )
        roots = [
            path
            for path in requested
            if isinstance(selected[path], Dir)
        ]
        if roots:
            for resource in (*self.dirs.id2dir.values(), *self.files.id2file.values()):
                if any(
                    resource.path.is_relative_to(root)
                    for root in roots
                ):
                    selected.setdefault(resource.path, resource)
        registered = self._register(selected.values())
        added = [
            self._change(resource, 'added', 'staged')
            for resource in registered
        ]
        ids = {
            resource.id
            for resource in selected.values()
        }
        staged = [
            dataclasses.replace(change, status='staged')
            for change in self.changes.unstaged
            if change.file_id in ids or change.dir_id in ids
        ]
        try:
            self.changes.record([*added, *staged])
        except Exception:
            for resource in reversed(registered):
                del resource._parent[resource.id]
            raise
        return tuple(
            selected[path]
            for path in requested
        )

    def _ignored(self, path: Path) -> bool:
        return self.dir is not None and path.is_relative_to(self.dir)

    def _collect(self, *paths: str | Path) -> dict[Path, File | Dir]:
        selected: dict[Path, File | Dir] = {}
        pending = []
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if self._ignored(resolved):
                raise ValueError(f'Cannot track Trail metadata: {resolved}')
            pending.append(resolved)
        pending.reverse()
        while pending:
            path = pending.pop()
            if path in selected:
                continue
            if path.is_dir():
                resource = self.dirs.get(path) or Dir.from_path(path)
            elif path.is_file():
                resource = self.files.get(path) or File.from_path(path)
            else:
                resource = self.dirs.get(path) or self.files.get(path) or File.from_path(path)
            selected[path] = resource
            if isinstance(resource, Dir) and path.is_dir():
                for child in path.iterdir():
                    if child.is_symlink() or self._ignored(child):
                        continue
                    if child.is_file() or child.is_dir():
                        pending.append(child)
        return selected

    def _register(self, resources: Iterable[File | Dir]) -> tuple[File | Dir, ...]:
        registered = []
        try:
            for resource in resources:
                if isinstance(resource, Dir):
                    collection = self.dirs
                else:
                    collection = self.files
                if collection.get(resource.id) is resource:
                    resource.add()
                    continue
                # while resource.id in self.files or resource.id in self.dirs:
                while (
                    resource.id in self.files.id2file
                    or resource.id in self.dirs.id2dir
                ):
                    del resource.id
                collection[resource.id] = resource
                registered.append(resource)
        except Exception:
            for resource in reversed(registered):
                del resource._parent[resource.id]
            raise
        return tuple(registered)

    def _change(
            self,
            resource: File | Dir,
            event_type: str,
            status: ChangeStatus = 'unstaged',
    ) -> Change:
        is_directory = isinstance(resource, Dir)
        return Change(
            _parent=self.files,
            src_path=str(resource.path),
            event_type=event_type,
            is_directory=is_directory,
            file_id=None if is_directory else resource.id,
            dir_id=resource.id if is_directory else None,
            status=status,
        )

    def remove(
            self,
            *files: str | Path | File | Dir | int,
    ) -> tuple[File | Dir, ...]:
        selected = {}
        for value in files:
            if isinstance(value, (File, Dir)):
                collection = self.dirs if isinstance(value, Dir) else self.files
                resource = value if collection.get(value.id) is value else None
            else:
                resource = self.dirs.get(value) or self.files.get(value)
            if resource is None:
                continue
            selected[resource.id] = resource
            if isinstance(resource, Dir):
                for child in (*self.dirs.id2dir.values(), *self.files.id2file.values()):
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
            self._change(resource, 'removed', 'staged')
            for resource in removed
        ]
        detached = []
        try:
            for resource in reversed(removed):
                del resource._parent[resource.id]
                detached.append(resource)
            self.changes.record([*staged, *removals])
        except Exception:
            for resource in reversed(detached):
                resource._parent[resource.id] = resource
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
