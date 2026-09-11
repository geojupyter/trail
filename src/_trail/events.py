from __future__ import annotations

from collections import UserList
from typing import TYPE_CHECKING

from .event import Event

if TYPE_CHECKING:
    from .file import File


class Events(UserList[Event]):
    """Chronological events belonging to one registered file."""

    file: File | None = None
