from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .node import Node

if TYPE_CHECKING:
    from .trail import Trail


@dataclass
class Commit(Node):
    id: int = field(default_factory=lambda: uuid4().int, kw_only=True)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC), kw_only=True)
    message: str = ''
    _parent: Commits = field(
        kw_only=True,
        repr=False,
        compare=False,
        metadata={'csv': False},
    )


class CSV(Node):
    _parent: Commits
    fieldnames = [
        field.name
        for field in fields(Commit)
        if field.metadata.get('csv', True)
    ]

    @cached_property
    def path(self):
        trail = self._trail
        if trail.dir:
            return trail.dir / 'commits.csv'
        else:
            return None

    def commit2row(self, commit: Commit) -> dict[str, int | str]:
        row = {
            name: getattr(commit, name)
            for name in self.fieldnames
        }
        row['timestamp'] = commit.timestamp.isoformat()
        return row

    def append(self, commits: Iterable[Commit]) -> None:
        batch = list(commits)
        if not batch:
            return
        path = self.path
        if path is None:
            return
        if path.exists() and path.stat().st_size:
            with path.open(encoding='utf-8', newline='') as file:
                if next(csv.reader(file), None) != self.fieldnames:
                    raise ValueError(f'Unexpected commit CSV header in {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            if file.tell() == 0:
                writer.writeheader()
            rows = (
                self.commit2row(commit)
                for commit in batch
            )
            writer.writerows(rows)

    def record(self, commits: Iterable[Commit]) -> None:
        batch = list(commits)
        if not batch:
            return
        ids: set[int] = set()
        for commit in batch:
            if commit.id in ids:
                raise ValueError(f'Commit {commit.id} occurs more than once in the batch')
            ids.add(commit.id)
        if self._trail.dir is not None:
            self.append(batch)
        existing = self._parent.id2commit
        for commit in batch:
            original = existing.get(commit.id)
            if original is None:
                existing[commit.id] = commit
            else:
                for name in self.fieldnames:
                    setattr(original, name, getattr(commit, name))

    def read(self, path: str | Path | None = None) -> Commits:
        path = self.path if path is None else Path(path)
        if path is None:
            raise ValueError('Pass a CSV path or configure Trail.dir to read a commit log')
        out = Commits(self._trail)
        with path.open(encoding='utf-8', newline='') as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != self.fieldnames:
                raise ValueError(f'Unexpected commit CSV header in {path}')
            for row in reader:
                commit = Commit(
                    id=int(row['id']),
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    message=row['message'],
                    _parent=out,
                )
                out.id2commit[commit.id] = commit
        out.csv.path = Path(path)
        return out

    def write(self, path: str | Path | None = None) -> None:
        path = self.path if path is None else Path(path)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            rows = (
                self.commit2row(commit)
                for commit in self._parent.id2commit.values()
            )
            writer.writerows(rows)


class Commits(Node):
    _parent: Trail

    @cached_property
    def csv(self) -> CSV:
        return CSV(self)

    @cached_property
    def id2commit(self) -> dict[int, Commit]:
        return {}

    def record(self, commits: Iterable[Commit]) -> None:
        return self.csv.record(commits)
