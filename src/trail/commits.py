from __future__ import annotations

import csv
from .event import Event
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


