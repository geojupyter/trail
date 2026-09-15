from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import cached_property
from pathlib import Path
from stat import S_ISREG
from typing import TYPE_CHECKING, Self, overload
from uuid import uuid4

from .changes import Changes
from .node import Node

from .watchdog import Watchdog

if TYPE_CHECKING:
    from .trail import Trail
    from .files import File
    from .dirs import Dir

FileKey = str | Path | int



class Entry(Node):
    @classmethod
    def from_path(
            cls,
            path: str | Path,
            parent: Entries = None,
    ) -> Self | File | Dir:
        path = Path(path).expanduser().resolve()
        metadata = path.stat()
        if not S_ISREG(metadata.st_mode):
            raise ValueError(f"Not a regular file: {path}")
        out = cls(parent=parent)
        out.path = path
        return out

    def add(self) -> None:
        watchdog = self._watchdog

    def remove(self) -> None:
        watchdog = self._watchdog

    def change(self, /, **kwargs):
        ...


class Entries(Node):
    ...

