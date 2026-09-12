from __future__ import annotations

from collections import UserList
from pathlib import Path

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, UTC
from functools import cached_property
from os import fsdecode
from os.path import relpath
from typing import get_args, Final, Literal, Self, TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail

ChangeStatus = Literal['unstaged', 'staged', 'committed']
EVENT_TYPES: Final = {"created", "modified", "deleted", "moved"}


@dataclass
class Change(Node):
    """One logical change to a registered file."""
    src_path: bytes | str
    dest_path: bytes | str = ""
    event_type: str = ""
    is_directory: bool = False
    is_synthetic: bool = False
    id: int = field(default_factory=lambda: uuid4().int)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: ChangeStatus = 'unstaged'
    file_id: int | None = None
    commit_id: int | None = None
    _parent: Node = field(kw_only=True, repr=False, compare=False, metadata={'csv': False})

    def tracked(self) -> Self | None:
        if self.is_directory or self.event_type not in EVENT_TYPES:
            return None
        source = Path(fsdecode(self.src_path)).expanduser().resolve()
        file = self._files.get(source)
        if file is None:
            return None
        self.src_path = str(source)
        self.file_id = file.id
        if self.event_type == "moved" and self.dest_path:
            destination = Path(fsdecode(self.dest_path)).expanduser().resolve()
            self.dest_path = str(destination)
            file.move(destination)
        return self

class CSV(
    Node
):
    """Nested-namespace to encapsulate CSV-related functionality for changes."""
    _parent: BaseChanges
    fieldnames = [
        field.name
        for field in fields(Change)
        if field.metadata.get('csv', True)
    ]

    @cached_property
    def path(self):
        trail = self._trail
        if trail.dir:
            return trail.dir / 'changes.csv'
        else:
            return None

    def change2row(self, change: Change) -> dict:
        """Return a dictionary representation of a Change suitable for CSV writing."""
        row = {
            name: getattr(change, name)
            for name in self.fieldnames
        }
        row['timestamp'] = change.timestamp.isoformat()
        return row

    def append(self, changes: Iterable[Change]) -> None:
        """Append snapshots without rewriting previously recorded changes."""
        batch = list(changes)
        if not batch:
            return
        path = self.path
        if path is None:
            return
        fieldnames = self.fieldnames
        if path.exists() and path.stat().st_size:
            with path.open(encoding='utf-8', newline='') as file:
                if next(csv.reader(file), None) != fieldnames:
                    raise ValueError(f'Unexpected change CSV header in {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0:
                writer.writeheader()
            writer.writerows(self.change2row(change) for change in batch)

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
        if self._trail.dir is not None:
            self.append(batch)
        for change in batch:
            original = existing.get(change.id)
            if original is None:
                owner.append(change)
            else:
                for name in self.fieldnames:
                    setattr(original, name, getattr(change, name))

    def read(self, path: str | Path | None = None) -> Changes:
        """Read a separate change log using the latest snapshot for each ID."""
        path = self.path if path is None else Path(path)
        if path is None:
            raise ValueError('Pass a CSV path or configure Trail.dir to read a change log')
        changes: dict[int, Change] = {}
        with path.open(encoding='utf-8', newline='') as file:
            for row in csv.DictReader(file):
                row.update(
                    id=int(row['id']),
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    file_id=int(row['file_id']) if row.get('file_id') else None,
                    commit_id=int(row['commit_id']) if row.get('commit_id') else None,
                )
                for name in ('is_directory', 'is_synthetic'):
                    value = row[name].lower()
                    if value not in ('true', 'false', '1', '0'):
                        raise ValueError(f'Invalid {name} value: {row[name]!r}')
                    row[name] = value in ('true', '1')
                if row['status'] not in get_args(ChangeStatus):
                    raise ValueError(f'Unknown change status: {row["status"]}')
                change = Change(_parent=self._trail.files, **row)
                changes[change.id] = change
        out = Changes(self._parent, changes.values())
        out.csv.path = path
        return out

    def write(self, path: str | Path | None = None) -> None:
        """Export the owning collection as a snapshot, replacing the target CSV."""
        path = self.path if path is None else Path(path)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(self.change2row(change) for change in self._parent)


class BaseChanges(UserList[Change], Node):
    """A collection and descriptor for binding filtered views of change records."""

    _parent: Trail | BaseChanges
    __name__: str

    def __init__(
            self,
            parent: Node | Iterable[Change] | None = None,
            changes: Iterable[Change] = (),
    ) -> None:
        if parent is not None and not isinstance(parent, Node):
            changes = parent
            parent = None
        UserList.__init__(self, changes)
        Node.__init__(self, parent)

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
        selected = (
            change
            for change in instance
            if change.status == self.__name__
        )
        out = cls(instance, selected)
        out.__name__ = self.__name__
        return out

    @cached_property
    def csv(self) -> CSV:
        return CSV(self)


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
        labels = {
            'added': 'new file',
            'created': 'new file',
            'moved': 'renamed',
        }
        for heading, hint, changes in (
                (
                    'Changes to be committed:',
                    '  (use "trail.commit()" to commit staged changes)',
                    self.staged,
                ),
                (
                    'Changes not staged for commit:',
                    '  (use "trail.add(<file>, ...)" to update what will be committed)',
                    self.unstaged,
                ),
        ):
            if not changes:
                continue
            lines = [heading, hint]
            for change in changes:
                label = labels.get(change.event_type, change.event_type) + ':'
                path = relpath(fsdecode(change.src_path))
                if change.event_type == 'moved' and change.dest_path:
                    destination = relpath(fsdecode(change.dest_path))
                    path = f'{path} -> {destination}'
                lines.append(f'        {label:<12}{path}')
            sections.append('\n'.join(lines))
        return '\n\n'.join(sections) if sections else 'nothing to commit, no pending changes'
