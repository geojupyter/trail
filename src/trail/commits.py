from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from stat import S_ISREG
from typing import TYPE_CHECKING, Self, overload
from uuid import uuid4

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from .changes import Change, EVENT_TYPES
from .node import Node

if TYPE_CHECKING:
    from .trail import Trail
    from .files import Files


class Commit(Node):
    _parent: Commits

    @cached_property
    def id(self) -> int:
        return uuid4().int



class Commits(Node):
    _parent: Trail
