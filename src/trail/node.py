from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .trail import Trail
    from .changes import Changes
    from .file import File
    from .change import Change
    from .files import Files
    from .watchdog import Watchdog, Handler

class Node:
    @cached_property
    def _parent(self) -> Node:
        msg = f'Node {self} has no parent'
        raise AttributeError(msg)

    @cached_property
    def _event(self) -> Change:
        from .change import Change
        parent = self._parent
        if isinstance(parent, Change):
            return parent
        return parent._event

    @cached_property
    def _trail(self) -> Trail:
        from .trail import Trail
        parent = self._parent
        if isinstance(parent, Trail):
            return parent
        return parent._trail

    @cached_property
    def _files(self) -> Files:
        from .files import Files
        parent = self._parent
        if isinstance(parent, Files):
            return parent
        return parent._files

    @cached_property
    def _file(self) -> File:
        from .file import File
        parent = self._parent
        if isinstance(parent, File):
            return parent
        return parent._file

    @cached_property
    def _events(self) -> Changes:
        from .changes import Changes
        parent = self._parent
        if isinstance(parent, Changes):
            return parent
        return parent._events

    @cached_property
    def _watchdog(self) -> Watchdog:
        from .watchdog import Watchdog
        parent = self._parent
        if isinstance(parent, Watchdog):
            return parent
        return parent._watchdog

    @cached_property
    def _handler(self) -> Handler:
        from .watchdog import Handler
        parent = self._parent
        if isinstance(parent, Handler):
            return parent
        return parent._handler