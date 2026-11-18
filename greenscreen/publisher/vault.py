"""The only holders of plaintext values in the publisher.

``SecretBox`` holds the Input values of one Call and is emptied in a ``finally``.
``BoundValues`` holds the Bound_Values of the whole process. Neither object shows a
value in ``repr``, ``str``, iteration, hashing or pickling. Nothing here logs.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import NoReturn

__all__ = ["SecretBox", "BoundValues"]

Value = str | int


def _no_pickle(self: object, protocol: object = None) -> NoReturn:
    raise TypeError("this object cannot be serialised")


class SecretBox:
    """One Call's plaintext. ``repr`` shows names only. Not iterable, not hashable."""

    __slots__ = ("_items", "_merged")
    __hash__ = None  # type: ignore[assignment]
    __iter__ = None  # type: ignore[assignment]
    __reduce_ex__ = _no_pickle  # type: ignore[assignment]

    def __init__(self) -> None:
        self._items: dict[str, object] = {}
        self._merged: dict[str, object] = {}

    @classmethod
    def adopt(cls, items: dict[str, object]) -> SecretBox:
        """Take ownership of ``items`` without copying it; ``clear`` empties it."""
        box = cls()
        box._items = items
        return box

    def mapping(self) -> dict[str, object]:
        """The adopted dict itself, for the validator. Emptied in place by ``clear``."""
        return self._items

    def merged(self, bound: Mapping[str, Value]) -> dict[str, object]:
        """A fresh dict of the supplied values plus ``bound``, kept so ``clear`` empties it."""
        self._merged.clear()
        fresh: dict[str, object] = dict(self._items)
        fresh.update(bound)
        self._merged = fresh
        return fresh

    def clear(self) -> None:
        """Empty the adopted dict and the merged dict in place."""
        self._items.clear()
        self._merged.clear()

    def __repr__(self) -> str:
        return f"SecretBox(names={list(self._items)!r})"

    __str__ = __repr__


class _OpaqueMapping(Mapping[str, Value]):
    """Read-only mapping whose ``repr`` shows no value."""

    __slots__ = ("_data",)
    __hash__ = None  # type: ignore[assignment]
    __reduce_ex__ = _no_pickle  # type: ignore[assignment]

    def __init__(self, data: dict[str, Value]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Value:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"<bound values: {len(self._data)}>"

    __str__ = __repr__


_EMPTY = _OpaqueMapping({})


class BoundValues:
    """Per-process plaintext of the ``GS_BIND_`` variables. Opaque repr, no pickling.

    ``values`` maps a Flow name to a mapping of Input name to parsed value. The store
    copies it, so the caller can clear its own dicts afterwards.
    """

    __slots__ = ("_flows",)
    __hash__ = None  # type: ignore[assignment]
    __iter__ = None  # type: ignore[assignment]
    __reduce_ex__ = _no_pickle  # type: ignore[assignment]

    def __init__(self, values: Mapping[str, Mapping[str, Value]] | None = None) -> None:
        self._flows: dict[str, _OpaqueMapping] = {
            flow: _OpaqueMapping(dict(inputs))
            for flow, inputs in (values or {}).items()
            if inputs
        }

    def for_flow(self, flow_name: str) -> Mapping[str, Value]:
        """Read-only view of one Flow's bound values; empty when it has none."""
        return self._flows.get(flow_name, _EMPTY)

    def names_for(self, flow_name: str) -> frozenset[str]:
        return frozenset(self._flows.get(flow_name, _EMPTY))

    def __repr__(self) -> str:
        return f"BoundValues(flows={len(self._flows)})"

    __str__ = __repr__
