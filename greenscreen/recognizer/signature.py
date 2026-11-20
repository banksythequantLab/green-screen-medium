"""Screen signatures: seven matcher kinds, volatile regions and validation.

Validation runs in ``ScreenSignature.__post_init__`` and raises
``SignatureError``. Messages name the matcher kind, the field and the index;
they never echo matcher text or patterns (an invalid signature name is the one
exception, since it is the identifier the caller needs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar, Union

from greenscreen.recognizer.errors import SignatureError

_NAME_RE = re.compile(r"[a-z0-9_-]{1,64}")
_MAX_COORD = 255
_MAX_DESCRIPTION = 500
_MAX_PATTERN = 200
_MAX_MATCHERS = 50
_MAX_VOLATILE = 50
_MAX_STABLE_FOR = 5


@dataclass(frozen=True, slots=True)
class TextAtMatcher:
    kind: ClassVar[str] = "text_at"
    row: int
    col: int
    text: str


@dataclass(frozen=True, slots=True)
class RowContainsMatcher:
    kind: ClassVar[str] = "row_contains"
    row: int
    text: str


@dataclass(frozen=True, slots=True)
class FieldLayoutMatcher:
    kind: ClassVar[str] = "field_layout"
    count: int
    positions: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", _normalize_positions(self.positions))


@dataclass(frozen=True, slots=True)
class CursorFieldMatcher:
    kind: ClassVar[str] = "cursor_field"
    row: int
    col: int
    hidden: bool


@dataclass(frozen=True, slots=True)
class RegionRegexMatcher:
    kind: ClassVar[str] = "region_regex"
    row: int
    col: int
    length: int
    pattern: str
    _compiled: Any = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        compiled = None
        if isinstance(self.pattern, str) and len(self.pattern) <= _MAX_PATTERN:
            try:
                compiled = re.compile(self.pattern)
            except re.error:
                compiled = None
        object.__setattr__(self, "_compiled", compiled)


@dataclass(frozen=True, slots=True)
class LastRowMatcher:
    kind: ClassVar[str] = "last_row"
    text: str


@dataclass(frozen=True, slots=True)
class BeforeCursorMatcher:
    kind: ClassVar[str] = "before_cursor"
    text: str


Matcher = Union[
    TextAtMatcher,
    RowContainsMatcher,
    FieldLayoutMatcher,
    CursorFieldMatcher,
    RegionRegexMatcher,
    LastRowMatcher,
    BeforeCursorMatcher,
]

MATCHER_KINDS: dict[str, type] = {
    cls.kind: cls
    for cls in (
        TextAtMatcher,
        RowContainsMatcher,
        FieldLayoutMatcher,
        CursorFieldMatcher,
        RegionRegexMatcher,
        LastRowMatcher,
        BeforeCursorMatcher,
    )
}


@dataclass(frozen=True, slots=True)
class VolatileRegion:
    row: int
    col: int
    length: int


def _normalize_positions(positions: Any) -> Any:
    """Turn a sequence of (row, col) pairs into a tuple of tuples when possible."""
    try:
        return tuple(tuple(p) for p in positions)
    except TypeError:
        return positions


def _is_int(v: Any) -> bool:
    return type(v) is int


def _check_coord(where: str, what: str, v: Any) -> None:
    if not _is_int(v):
        raise SignatureError(f"{where}: {what} must be an integer")
    if v < 0 or v > _MAX_COORD:
        raise SignatureError(f"{where}: {what} out of range 0..{_MAX_COORD}")


def _check_rect(where: str, row: Any, col: Any, length: Any) -> None:
    _check_coord(where, "row", row)
    _check_coord(where, "col", col)
    if not _is_int(length):
        raise SignatureError(f"{where}: length must be an integer")
    if length < 1:
        raise SignatureError(f"{where}: length below 1")
    if col + length - 1 > _MAX_COORD:
        raise SignatureError(f"{where}: last column above {_MAX_COORD}")


def _check_text(where: str, text: Any) -> None:
    if not isinstance(text, str):
        raise SignatureError(f"{where}: text must be a string")
    if text == "":
        raise SignatureError(f"{where}: text must not be empty")


def _validate_matcher(index: int, m: Any) -> tuple[int, int, int, int] | None:
    """Validate one matcher; return its (row, col, length) rectangle if it has one."""
    if not isinstance(m, tuple(MATCHER_KINDS.values())):
        raise SignatureError(f"matchers[{index}]: not a matcher")
    where = f"matchers[{index}] ({m.kind})"
    if isinstance(m, TextAtMatcher):
        _check_text(where, m.text)
        _check_rect(where, m.row, m.col, len(m.text))
        return (m.row, m.col, len(m.text), index)
    if isinstance(m, RowContainsMatcher):
        _check_coord(where, "row", m.row)
        _check_text(where, m.text)
    elif isinstance(m, FieldLayoutMatcher):
        if not _is_int(m.count):
            raise SignatureError(f"{where}: count must be an integer")
        if not isinstance(m.positions, tuple):
            raise SignatureError(f"{where}: positions must be a sequence")
        if m.count != len(m.positions):
            raise SignatureError(f"{where}: count differs from number of positions")
        for i, p in enumerate(m.positions):
            if not isinstance(p, tuple) or len(p) != 2:
                raise SignatureError(f"{where}: positions[{i}] must be a (row, col) pair")
            _check_coord(f"{where}: positions[{i}]", "row", p[0])
            _check_coord(f"{where}: positions[{i}]", "col", p[1])
    elif isinstance(m, CursorFieldMatcher):
        _check_coord(where, "row", m.row)
        _check_coord(where, "col", m.col)
        if type(m.hidden) is not bool:
            raise SignatureError(f"{where}: hidden must be a boolean")
    elif isinstance(m, RegionRegexMatcher):
        _check_rect(where, m.row, m.col, m.length)
        if not isinstance(m.pattern, str):
            raise SignatureError(f"{where}: pattern must be a string")
        if len(m.pattern) > _MAX_PATTERN:
            raise SignatureError(f"{where}: pattern longer than {_MAX_PATTERN} characters")
        try:
            re.compile(m.pattern)
        except re.error as exc:
            pos = exc.pos if isinstance(exc.pos, int) else 0
            raise SignatureError(
                f"{where}: invalid regular expression (error at position {pos})"
            ) from None
        return (m.row, m.col, m.length, index)
    else:  # LastRowMatcher, BeforeCursorMatcher
        _check_text(where, m.text)
    return None


@dataclass(frozen=True, slots=True)
class ScreenSignature:
    name: str
    matchers: tuple[Matcher, ...]
    volatile: tuple[VolatileRegion, ...] = ()
    description: str = ""
    stable_for: float = 0.0

    def __post_init__(self) -> None:
        sf = self.stable_for
        if type(sf) not in (int, float) or not 0 <= sf <= _MAX_STABLE_FOR:
            raise SignatureError(
                f"stable_for must be a number from 0 to {_MAX_STABLE_FOR}"
            )
        object.__setattr__(self, "stable_for", float(sf))
        for attr in ("matchers", "volatile"):
            value = getattr(self, attr)
            if isinstance(value, (str, bytes)):
                raise SignatureError(f"{attr} must be a sequence")
            try:
                object.__setattr__(self, attr, tuple(value))
            except TypeError:
                raise SignatureError(f"{attr} must be a sequence") from None

        if not isinstance(self.name, str):
            raise SignatureError("invalid signature name: not a string")
        if _NAME_RE.fullmatch(self.name) is None:
            raise SignatureError(f"invalid signature name {self.name[:64]!r}")
        if not isinstance(self.description, str):
            raise SignatureError("description must be a string")
        if len(self.description) > _MAX_DESCRIPTION:
            raise SignatureError(f"description longer than {_MAX_DESCRIPTION} characters")

        if len(self.matchers) == 0:
            raise SignatureError("signature has no matchers and would match every screen")
        if len(self.matchers) > _MAX_MATCHERS:
            raise SignatureError(f"more than {_MAX_MATCHERS} matchers")
        if len(self.volatile) > _MAX_VOLATILE:
            raise SignatureError(f"more than {_MAX_VOLATILE} volatile regions")

        rects: list[tuple[int, int, int, int]] = []
        kinds: dict[int, str] = {}
        for i, m in enumerate(self.matchers):
            rect = _validate_matcher(i, m)
            if rect is not None:
                rects.append(rect)
                kinds[i] = m.kind

        for j, v in enumerate(self.volatile):
            if not isinstance(v, VolatileRegion):
                raise SignatureError(f"volatile[{j}]: not a volatile region")
            _check_rect(f"volatile[{j}]", v.row, v.col, v.length)

        for j, v in enumerate(self.volatile):
            for row, col, length, i in rects:
                if (
                    row == v.row
                    and col < v.col + v.length
                    and v.col < col + length
                ):
                    raise SignatureError(
                        f"matchers[{i}] ({kinds[i]}) overlaps volatile[{j}]"
                    )

    def to_yaml(self) -> str:
        from greenscreen.recognizer import yamlio

        return yamlio.to_yaml(self)

    @classmethod
    def from_yaml(cls, text: str) -> ScreenSignature:
        from greenscreen.recognizer import yamlio

        return yamlio.from_yaml(text)
