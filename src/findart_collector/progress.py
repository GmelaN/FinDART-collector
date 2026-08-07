"""Optional tqdm integration for command-line progress reporting."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar


T = TypeVar("T")

try:
    from tqdm import tqdm as _tqdm
except ImportError:  # Allows an already-installed editable checkout to keep running.
    def tqdm(iterable: Iterable[T], **_: object) -> Iterable[T]:
        return iterable
else:
    tqdm = _tqdm
