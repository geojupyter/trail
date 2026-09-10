
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

@dataclass
class File:
    id: int
    name: str
    size: int
    mtime: float
    path: str

    @classmethod
    def from_path(cls, path: str) -> Self:
        ...

