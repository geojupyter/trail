from __future__ import annotations

import collections

import watchdog

from dataclasses import dataclass
import dataclasses
from functools import cache, cached_property, lru_cache, partial, partialmethod, update_wrapper, wraps
from collections import UserDict, UserList, UserString, defaultdict, deque, namedtuple, defaultdict, deque
from functools import cached_property, lru_cache, partial, partialmethod, reduce, singledispatch, singledispatchmethod, update_wrapper, wraps
from typing import Any, Callable, Optional, Union, Type, TypeVar, Generic, Protocol, Annotated, Literal, Final, ClassVar, TypeAlias, NamedTuple, TypedDict, Iterable, Iterator, Generator, cast, overload, TYPE_CHECKING, Self
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from pathlib import Path
from dataclasses import dataclass, field
from uuid import uuid4
from .watchdog import Watchdog
from .node import Node
from .file import File

if TYPE_CHECKING:
    from .trail import Trail

class Files(
    collections.UserDict,
    Node,
):
    trail: Trail = None
    _parent: Trail = None

    @cached_property
    def watchdog(self):
        out = Watchdog()
        out._parent = self
        return out

