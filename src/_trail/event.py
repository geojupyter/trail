from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    """One logical change to a registered file."""

    file_id: str
    path: str
    destination: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
