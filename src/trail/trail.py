from __future__ import annotations

from pathlib import Path

import dataclasses
import platformdirs
from functools import cached_property
from typing import Self
from uuid import uuid4

from .changes import Change, Changes
from .files import File, Files
from .node import Node


class Trail(
    Node
):
    @cached_property
    def id(self) -> int:
        return uuid4().int

    @classmethod
    def from_new(
            cls,
    ):
        ...

    @classmethod
    def from_json(
            cls,
            path: str
    ) -> Self:
        ...

    def to_json(
            self,
            path: str
    ) -> None:
        ...

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
            value.id if isinstance(value, File) else value
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
            self
    ) -> tuple[Change, ...]:
        """Commit staged records, leaving subsequent unstaged changes alone.

        This commits change metadata only; it does not snapshot file contents.
        """
        staged = tuple(self.changes.staged)
        self.changes.set_status(staged, 'committed')
        return staged

    def push(
            self,
    ):
        ...

    def pull(
            self
    ):
        ...

    @property
    def as_json(self) -> dict:
        data = {
            'files': {
                ...
            }
        }

    @cached_property
    def files(self):
        out = Files()
        out._parent = self
        return out

    @cached_property
    def changes(self):
        out = Changes()
        out._parent = self
        return out

    @cached_property
    def cache(self) -> Path:
        return platformdirs.user_cache_path('trail') / 'cache' / str(self.id)
