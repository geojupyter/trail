from __future__ import annotations

import platformdirs
from dataclasses import dataclass

import dataclasses
from functools import cache, cached_property, lru_cache, partial, partialmethod, update_wrapper, wraps
from collections import UserDict, UserList, UserString, defaultdict, deque, namedtuple, defaultdict, deque
from functools import cached_property, lru_cache, partial, partialmethod, reduce, singledispatch, singledispatchmethod, \
    update_wrapper, wraps
from .node import Node
from typing import Any, Callable, Optional, Union, Type, TypeVar, Generic, Protocol, Annotated, Literal, Final, \
    ClassVar, TypeAlias, NamedTuple, TypedDict, Iterable, Iterator, Generator, cast, overload, TYPE_CHECKING, Self
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from pathlib import Path
from dataclasses import dataclass, field
from uuid import uuid4
from .files import Files
from .files import File
from .changes import Changes
from .changes import Change


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
            if (file := self.files.by_path(path)) is not None
        }
        files = self.files.add(*paths)
        new_files = [
            file
            for file in files
            if file.id not in previous_ids
        ]
        added = [
            Change(
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

    def __getitem__(self, item):
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
