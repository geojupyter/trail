from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, UTC
from typing import Literal, TYPE_CHECKING
from uuid import uuid4
from watchdog.events import FileSystemEvent

if TYPE_CHECKING:
    pass

@dataclass(slots=True)
class Change(
    FileSystemEvent,
):
    """One logical change to a registered file."""
    id: int = field(default_factory=lambda : uuid4().int)
    timestamp: datetime = field(default_factory=lambda : datetime.now(UTC))
    status: Literal['unstaged', 'staged', 'committed'] = field(default='unstaged')

