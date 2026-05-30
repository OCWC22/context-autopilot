"""Deterministic train/eval split. Held-out eval is non-negotiable at small
dataset sizes (the band where memorization is the default failure mode)."""

from __future__ import annotations

import hashlib
from typing import Sequence, TypeVar

T = TypeVar("T")


def _bucket(key: str) -> float:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def split(items: Sequence[T], key_fn, eval_frac: float = 0.2) -> tuple[list[T], list[T]]:
    """Stable hash-based split so the same item always lands in the same side."""
    train: list[T] = []
    held: list[T] = []
    for it in items:
        (held if _bucket(str(key_fn(it))) < eval_frac else train).append(it)
    return train, held
