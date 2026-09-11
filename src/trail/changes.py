from __future__ import annotations

from collections import UserList
from pathlib import Path

import copy
import csv
import dataclasses
from functools import cached_property
from typing import Self, TYPE_CHECKING

from .node import Node

if TYPE_CHECKING:
    from .file import File
    from .trail import Trail
    from .change import Change


class BaseChanges(
    UserList[Change],
    Node,
):
    _parent: Changes

    def __init__(
            self,
            initlist: list[Change] | None = None,
    ):
        super().__init__(initlist)

    def __set_name__(self, owner, name):
        self.__name__ = name

    def __get__(
            self,
            instance: Changes,
            owner
    ) -> Self:
        if instance is None:
            return self
        changes = [
            change
            for change in instance
            if change.status == self.__name__
        ]
        out = copy.copy(self)
        out._parent = instance
        out.data = changes
        return out


class Changes(
    BaseChanges
):
    file: File
    _parent: Trail

    @BaseChanges
    def unstaged(self):
        ...

    @BaseChanges
    def staged(self):
        ...

    @BaseChanges
    def committed(self):
        ...

    @cached_property
    def csv(self):
        out = self._trail.cache / f'{self.__name__}.csv'
        if not out.exists():
            with out.open('w') as f:
                fieldnames = [field.name for field in dataclasses.fields(Change)]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
        return out

    def __get__(self, instance: Trail, owner) -> Self:
        cache = self.csv
        if cache.exists():
            out = self.from_csv(cache)
        else:
            out = copy.copy(self)
        out._parent = instance
        setattr(instance, self.__name__, out)
        return out

    @classmethod
    def from_csv(cls, path: str | Path) -> Self:
        ...

    @classmethod
    def to_csv(cls, path: str | Path) -> None:
        ...
