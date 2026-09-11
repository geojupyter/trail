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
from .file import File
from .changes import Changes


class Trail(
    Node
):
    id: int

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
            *args,
            **kwargs
    ):
        paths: Iterable[Path]
        for path in paths:
            path = Path(path)
            file = File.from_path(path)
            file._parent = self.files
            file.add()

    def remove(
            self,
            # *files,
            files,
    ):
        ...

    def commit(
            self
    ):
        ...

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
        return platformdirs.user_cache_path('trail') / "cache"


