from __future__ import annotations

from collections import UserList
from pathlib import Path

import csv
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, UTC
from functools import cached_property
from typing import get_args, Literal, Self, TYPE_CHECKING
from uuid import uuid4
from watchdog.events import FileSystemEvent

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail

ChangeStatus = Literal['unstaged', 'staged', 'committed']


@dataclass(slots=True)
class Change(
    FileSystemEvent,
):
    """One logical change to a registered file."""
    event_type: str = ''
    is_directory: bool = False
    id: int = field(default_factory=lambda: uuid4().int)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: ChangeStatus = 'unstaged'
    file_id: int | None = None


class CSV(
    Node
):
    """Nested-namespace to encapsulate CSV-related functionality for changes."""
    _parent: BaseChanges

    @cached_property
    def path(self) -> Path:
        return self._trail.cache / 'changes.csv'

    @staticmethod
    def _row(change: Change) -> dict:
        row = asdict(change)
        row['timestamp'] = change.timestamp.isoformat()
        return row

    def append(self, changes: Iterable[Change]) -> None:
        """Append snapshots without rewriting previously recorded changes."""
        batch = list(changes)
        if not batch:
            return
        path = self.path
        fieldnames = [field.name for field in fields(Change)]
        if path.exists() and path.stat().st_size:
            with path.open(encoding='utf-8', newline='') as file:
                if next(csv.reader(file), None) != fieldnames:
                    raise ValueError(f'Unexpected change CSV header in {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0:
                writer.writeheader()
            writer.writerows(self._row(change) for change in batch)

    def record(self, changes: Iterable[Change]) -> None:
        """Persist new or revised snapshots, preserving existing object identity."""
        batch = list(changes)
        if not batch:
            return
        owner = self._parent
        existing = {change.id: change for change in owner}
        ids: set[int] = set()
        for change in batch:
            if change.id in ids:
                raise ValueError(f'Change {change.id} occurs more than once in the batch')
            original = existing.get(change.id)
            if original is not None and original.file_id != change.file_id:
                raise ValueError(f'Cannot change the tracked file for change {change.id}')
            ids.add(change.id)
        self.append(batch)
        for change in batch:
            original = existing.get(change.id)
            if original is None:
                owner.append(change)
            else:
                for field in fields(Change):
                    setattr(original, field.name, getattr(change, field.name))

    def read(self, path: str | Path | None = None) -> Changes:
        """Read a separate change log using the latest snapshot for each ID."""
        path = self.path if path is None else Path(path)
        changes: dict[int, Change] = {}
        with path.open(encoding='utf-8', newline='') as file:
            for row in csv.DictReader(file):
                row['id'] = int(row['id'])
                row['timestamp'] = datetime.fromisoformat(row['timestamp'])
                row['file_id'] = int(row['file_id']) if row.get('file_id') else None
                for name in ('is_directory', 'is_synthetic'):
                    value = row[name].lower()
                    if value not in ('true', 'false', '1', '0'):
                        raise ValueError(f'Invalid {name} value: {row[name]!r}')
                    row[name] = value in ('true', '1')
                if row['status'] not in get_args(ChangeStatus):
                    raise ValueError(f'Unknown change status: {row["status"]}')
                change = Change(**row)
                changes[change.id] = change
        out = Changes(changes.values())
        out._parent = self._parent
        out.csv.path = path
        return out

    def write(self, path: str | Path | None = None) -> None:
        """Export the owning collection as a snapshot, replacing the target CSV."""
        path = self.path if path is None else Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=[field.name for field in fields(Change)])
            writer.writeheader()
            writer.writerows(self._row(change) for change in self._parent)


class BaseChanges(UserList[Change], Node):
    """A collection and descriptor for binding filtered views of change records."""

    _parent: Trail | BaseChanges
    __name__: str

    def __set_name__(
            self,
            owner: type,
            name: str,
    ) -> None:
        self.__name__ = name

    def __get__(
            self,
            instance: BaseChanges | None,
            owner: type | None = None,
    ) -> Self:
        if instance is None:
            return self
        cls = type(self)
        out = cls(
            change
            for change in instance
            if change.status == self.__name__
        )
        out.__name__ = self.__name__
        out._parent = instance
        return out

    @cached_property
    def csv(self) -> CSV:
        out = CSV()
        out._parent = self
        return out


class Unstaged(BaseChanges):
    """Changes awaiting staging."""


class Staged(BaseChanges):
    """Changes selected for the next commit."""


class Committed(BaseChanges):
    """Changes already committed."""


class Changes(BaseChanges):
    """The change log, with status collections bound through descriptors."""

    unstaged = Unstaged()
    staged = Staged()
    committed = Committed()

    def record(self, changes: Iterable[Change]) -> None:
        """Delegate recording to the persistence backend."""
        return self.csv.record(changes)

    def set_status(
            self,
            changes: Iterable[Change],
            status: ChangeStatus,
    ) -> None:
        """Append revised snapshots and update the existing Change objects."""
        if status not in get_args(ChangeStatus):
            raise ValueError(f'Unknown change status: {status}')
        owned = {
            change.id: change
            for change in self
        }
        pending: dict[int, Change] = {}
        for change in changes:
            if owned.get(change.id) is not change:
                raise ValueError(f'Change {change.id} does not belong to this log')
            if change.status != status:
                pending[change.id] = change
        if not pending:
            return
        snapshots = [
            replace(change, status=status)
            for change in pending.values()
        ]
        self.record(snapshots)

    def __repr__(self) -> str:
        sections = []
        for label, changes in (
                ('Changes to be committed:', self.staged),
                ('Changes not staged for commit:', self.unstaged),
        ):
            if changes:
                lines = [f'  {change.event_type}: {change.src_path}' for change in changes]
                sections.append('\n'.join([label, *lines]))
        return '\n\n'.join(sections) if sections else 'No changes.'
