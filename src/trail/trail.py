from __future__ import annotations
import json

from pathlib import Path

import dataclasses
from functools import cached_property
from typing import Self
from uuid import uuid4
from .commits import Commit, Commits

from .changes import Change, Changes
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
    ) -> tuple[File, ...]:
        """Track new files and stage pending changes to already tracked files."""
        previous_ids = {
            file.id for path in paths
            if (file := self.files.get(path)) is not None
        }
        files = self.files.add(*paths)
        new_files = [
            file
            for file in files
            if file.id not in previous_ids
        ]
        added = [
            Change(
                _parent=self.files,
                src_path=str(file.path),
                event_type='added',
                file_id=file.id,
                status='staged'
            )
            for file in new_files
        ]
        ids = {file.id for file in files}
        staged = [
            dataclasses.replace(change, status='staged')
            for change in self.changes.unstaged
            if change.file_id in ids
        ]
        try:
            self.changes.record([*added, *staged])
        except Exception:
            ids = (
                file.id
                for file in new_files
            )
            del self.files[ids]
            raise
        return files

    def remove(
            self,
            *files: str | Path | File | int,
    ) -> tuple[File, ...]:
        """Stop tracking files, staging their pending changes and removal.

        Files remain on disk; this operation is analogous to git rm --cached.
        """
        keys = (
            value.id if isinstance(value, File)
            else value
            for value in files
            if not isinstance(value, File) or self.files.id2file.get(value.id) is value
        )
        selected = {
            file.id: file
            for key in keys
            if (file := self.files.get(key)) is not None
        }
        removed = tuple(selected.values())
        ids = set(selected)
        del self.files[ids]
        staged = [
            dataclasses.replace(change, status='staged')
            for change in self.changes.unstaged
            if change.file_id in ids
        ]
        removals = [
            Change(
                _parent=self.files,
                src_path=str(file.path),
                event_type='removed',
                file_id=file.id,
                status='staged'
            )
            for file in removed
        ]
        try:
            self.changes.record([*staged, *removals])
        except Exception:
            for file in removed:
                self.files[file.id] = file
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
    def changes(self):
        return Changes(self)

    @cached_property
    def json(self):
        return JSON(self)

    @cached_property
    def commits(self):
        return Commits(self)
