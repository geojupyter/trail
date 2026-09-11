from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Self
from uuid import uuid4

from .events import Events


@dataclass
class File:
    """A registered file whose identity survives changes and renames."""

    id: str
    name: str
    size: int
    mtime: float
    path: str
    revision: int = 0
    exists: bool = True

    @classmethod
    def from_path(cls, path: str | Path) -> Self:
        """Register an existing file with a stable ID and initial metadata."""
        resolved = Path(path).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"not a file: {resolved}")
        stat = resolved.stat()
        return cls(
            id=uuid4().hex,
            name=resolved.name,
            size=stat.st_size,
            mtime=stat.st_mtime,
            path=str(resolved),
        )

    def refresh(self, path: str | Path | None = None) -> None:
        """Refresh path and stat metadata without changing the file's stable ID."""
        resolved = Path(path or self.path).expanduser().resolve(strict=True)
        stat = resolved.stat()
        self.path = str(resolved)
        self.name = resolved.name
        self.size = stat.st_size
        self.mtime = stat.st_mtime
        self.exists = True

    @cached_property
    def events(self) -> Events:
        """Create and cache the chronological event collection for this file."""
        events = Events()
        events.file = self
        return events
