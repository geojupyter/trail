from __future__ import annotations
import asyncio
from collections import UserDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch
import asyncio
from collections import UserDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final

from watchdog.events import (
    DirCreatedEvent, DirDeletedEvent, DirModifiedEvent, DirMovedEvent, FileClosedEvent, FileClosedNoWriteEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent, FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Self, TYPE_CHECKING
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)

from uuid import uuid4
import watchdog

from dataclasses import dataclass

import dataclasses
from functools import cache, cached_property, lru_cache, partial, partialmethod, update_wrapper, wraps
from collections import UserDict, UserList, UserString, defaultdict, deque, namedtuple, defaultdict, deque
from functools import cached_property, lru_cache, partial, partialmethod, reduce, singledispatch, singledispatchmethod, \
    update_wrapper, wraps
from typing import Any, Callable, Optional, Union, Type, TypeVar, Generic, Protocol, Annotated, Literal, Final, \
    ClassVar, TypeAlias, NamedTuple, TypedDict, Iterable, Iterator, Generator, cast, overload, TYPE_CHECKING, Self
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from pathlib import Path
from dataclasses import dataclass, field
from uuid import uuid4
from .change import Change
from .changes import Changes
from .node import Node

if TYPE_CHECKING:
    from .files import Files


# @dataclass
# class File(
#     Node
# ):
#     id: int
#     name: str
#     size: int
#     mtime: float
#     path: str
#     parent: Files

class File(
    Node
):
    path: Path
    _parent: Files

    @classmethod
    def from_path(cls, path: Path) -> Self:
        path = Path(path)
        out = cls()
        out.path = path
        _ = out.size, out.name, out.mtime, out.id
        return out

    @cached_property
    def name(self):
        return self.path.name

    @cached_property
    def size(self):
        return self.path.stat().st_size

    @cached_property
    def mtime(self):
        return self.path.stat().st_mtime

    @cached_property
    def id(self) -> int:
        return uuid4().int

    @cached_property
    def events(self):
        out = Changes()
        out.file = self
        return out

    @cached_property
    def directory(self):
        return Path(self.path)._parent

    def add(self):
        watchdog = self._watchdog
        dir2ids = watchdog.dir2ids
        ids = dir2ids.setdefault(self.directory, set())
        ids.add(self.id)
        if self.directory not in watchdog.watches:
            watchdog.observer.schedule(
                watchdog.handler,
                self.directory.__str__(),
                recursive=False,
                event_filter=[
                    FileCreatedEvent,
                    FileModifiedEvent,
                    FileDeletedEvent,
                    FileMovedEvent,
                ],
            )

    def remove(self):
        watchdog = self._watchdog
        dir2ids = watchdog.dir2ids
        ids = dir2ids[self.directory]
        ids.remove(self.id)
        if ids:
            return
        del dir2ids[self.directory]
        watches = watchdog.watches
        del watches[self.directory]
