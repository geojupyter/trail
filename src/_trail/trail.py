from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Self
from uuid import uuid4

from .file import File
from .files import Files


@dataclass
class Trail:
    id: str = field(default_factory=lambda: uuid4().hex)

    @classmethod
    def from_new(
        cls,
    ): ...

    @classmethod
    def from_json(cls, path: str) -> Self: ...

    def to_json(self, path: str) -> None: ...

    def add(
        self,
        *paths,
    ) -> tuple[File, ...]:
        """Register paths as files and return their stable resource objects."""
        files = tuple(File.from_path(path) for path in paths)
        self.files.update({file.id: file for file in files})
        return files

    def remove(
        self,
        *files,
    ): ...

    def commit(self): ...

    def push(
        self,
    ): ...

    def pull(self): ...

    @property
    def head(self):
        """Return the first item in the trail."""
        return self[0]

    @property
    def end(self):
        """Return the final item in the trail."""
        return self[-1]

    def __getitem__(self, item): ...

    @property
    def as_json(self) -> dict:
        """Return the current trail state as a JSON-oriented mapping."""
        return {
            "files": self.files,
        }

    @cached_property
    def files(self):
        """Create and cache the registered-file collection owned by this trail."""
        out = Files()
        out.trail = self
        return out


"""
trail.head -> trail[0]
trail.end -> trail[-1]
"""
