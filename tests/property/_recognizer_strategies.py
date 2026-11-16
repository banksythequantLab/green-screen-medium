"""Hypothesis strategies for the screen-recognizer property tests.

Screen strategies need only ``greenscreen.connector``. Signature strategies need
the matcher classes of ``greenscreen.recognizer.signature``; they are imported
inside the strategy functions so this module imports cleanly before that
module exists.
"""
from __future__ import annotations

from typing import NamedTuple

from hypothesis import strategies as st

from greenscreen.connector.models import Screen
from tests.screen_support import make_screen

# Printable ASCII (space included) for ordinary cell content.
_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
# Sentinel alphabet for hidden content: Latin-1 0xC0..0xFF. No other cell
# generated here uses a character outside printable ASCII.
SENTINEL_ALPHABET = [chr(c) for c in range(0xC0, 0x100)]

_PROTECTED_BITS = (0x00, 0x20)


class SentinelScreen(NamedTuple):
    screen: Screen
    sentinel: str  # the characters written into the hidden field's data cells


class LineModeScreen(NamedTuple):
    screen: Screen
    pause_row: int  # row holding " ***"
    sentinel: str   # hidden content below the pause row ("" when none)


# ---------------------------------------------------------------- helpers

@st.composite
def _text_runs(draw, rows: int, columns: int, max_runs: int = 6) -> dict:
    """A few printable runs on an otherwise blank screen."""
    runs: dict[tuple[int, int], str] = {}
    for _ in range(draw(st.integers(0, max_runs))):
        r = draw(st.integers(0, rows - 1))
        c = draw(st.integers(0, columns - 1))
        length = draw(st.integers(1, columns - c))
        runs[(r, c)] = draw(
            st.text(alphabet=_PRINTABLE, min_size=length, max_size=length)
        )
    return runs


def _sf_attr() -> st.SearchStrategy[int]:
    """Attribute byte for an ordinary (not hidden) field."""
    # Bits 0x0C = 0x0C would make it hidden; draw intensity from the other three.
    return st.builds(
        lambda prot, num, mod, inten: 0xC0 | prot | num | mod | inten,
        st.sampled_from(_PROTECTED_BITS),
        st.sampled_from((0x00, 0x10)),
        st.sampled_from((0x00, 0x01)),
        st.sampled_from((0x00, 0x04, 0x08)),
    )


# ---------------------------------------------------------------- screens

@st.composite
def small_screens(draw, max_fields: int = 5, allow_hidden: bool = False) -> Screen:
    """1..24 rows by 1..80 columns, mostly blank, optional SF layout.

    The SF count is 0 or 1 about as often as it is larger. Hidden fields
    (attribute bits 0x0C) appear only when ``allow_hidden`` is true. Cell text
    is printable ASCII; the cursor may sit on any cell.
    """
    rows = draw(st.integers(1, 24))
    columns = draw(st.integers(1, 80))
    total = rows * columns
    text = draw(_text_runs(rows, columns))
    n_sf = draw(st.integers(0, min(max_fields, total)))
    positions = draw(
        st.lists(
            st.integers(0, total - 1), min_size=n_sf, max_size=n_sf, unique=True
        )
    )
    attr = _sf_attr()
    if allow_hidden:
        attr = st.one_of(attr, st.sampled_from((0x0C, 0x2C, 0x4C, 0x6C)).map(lambda v: v | 0xC0))
    fields = [(p // columns, p % columns, draw(attr)) for p in positions]
    cursor = (draw(st.integers(0, rows - 1)), draw(st.integers(0, columns - 1)))
    return make_screen(rows, columns, text=text, fields=fields, cursor=cursor)


@st.composite
def sentinel_screens(draw) -> SentinelScreen:
    """A screen with one hidden field whose data cells hold a sentinel.

    The hidden field is an SF whose attribute byte has bits 0x0C set. Its
    extent runs to a following SF, so the field extent is real. All other
    cells are printable ASCII or null, so no sentinel character occurs outside
    the hidden field. The cursor may be inside or outside the hidden field.
    """
    rows = draw(st.integers(2, 24))
    columns = draw(st.integers(10, 80))
    total = rows * columns
    length = draw(st.integers(1, min(80, total - 3)))
    sentinel = "".join(
        draw(st.lists(st.sampled_from(SENTINEL_ALPHABET), min_size=length, max_size=length))
    )
    start = draw(st.integers(0, total - length - 2))
    hidden_c0 = 0x0C | 0xC0 | draw(st.sampled_from(_PROTECTED_BITS)) | draw(st.sampled_from((0x00, 0x01)))
    end_sf = start + length + 1  # terminating SF right after the sentinel
    extra = draw(st.integers(0, max(0, min(10, total - end_sf - 1))))
    end_sf += extra  # blank data cells inside the hidden extent
    cells: dict[tuple[int, int], str] = {}
    # Ordinary text outside the hidden extent and not on SF cells.
    for (r, c), s in draw(_text_runs(rows, columns)).items():
        cells[(r, c)] = s
    fields = [(start // columns, start % columns, hidden_c0),
              (end_sf // columns, end_sf % columns, draw(_sf_attr()))]
    if draw(st.booleans()) and start > 0:
        first = draw(st.integers(0, start - 1))
        fields.append((first // columns, first % columns, draw(_sf_attr())))
    screen = make_screen(rows, columns, text=cells, fields=fields)
    # Clear any ordinary text that landed inside the hidden extent, then write the sentinel.
    for lin in range(start + 1, end_sf):
        screen.cell_grid[lin // columns][lin % columns] = 0x00
    for i, ch in enumerate(sentinel):
        lin = start + 1 + i
        screen.cell_grid[lin // columns][lin % columns] = ord(ch)
    screen.cursor_row = draw(st.integers(0, rows - 1))
    screen.cursor_col = draw(st.integers(0, columns - 1))
    return SentinelScreen(screen, sentinel)


@st.composite
def line_mode_screens(draw, with_hidden: bool = False) -> LineModeScreen:
    """A 24x80 TSO line-mode screen with a ``" ***"`` row and the cursor after it.

    Text above the pause row is random. With ``with_hidden`` a hidden field
    holding a sentinel sits on the rows below the pause row, inside a field
    whose extent is closed by a following SF, so without blanking it would
    become the last non-blank row. Row 0 col 0 holds a protected SF in that
    case, so the pause row (>= 1) belongs to a visible field.
    """
    rows, columns = 24, 80
    pause_row = draw(st.integers(1, 20))
    text = {}
    for _ in range(draw(st.integers(0, 6))):
        r = draw(st.integers(1, pause_row - 1)) if pause_row > 1 else 1
        if r >= pause_row:
            continue
        c = draw(st.integers(0, 40))
        text[(r, c)] = draw(st.text(alphabet=_PRINTABLE[1:], min_size=1, max_size=30))
    text[(pause_row, 0)] = " ***"
    fields = []
    sentinel = ""
    hidden_cells: list[tuple[int, int, str]] = []
    if with_hidden:
        fields.append((0, 0, 0xE0))  # protected, visible
        hs = (pause_row + 1) * columns + draw(st.integers(0, 10))
        length = draw(st.integers(1, min(80, rows * columns - hs - 3)))
        sentinel = "".join(
            draw(st.lists(st.sampled_from(SENTINEL_ALPHABET), min_size=length, max_size=length))
        )
        fields.append((hs // columns, hs % columns, 0xEC))
        end = hs + length + 1
        fields.append((end // columns, end % columns, 0xE0))
        hidden_cells = [
            ((hs + 1 + i) // columns, (hs + 1 + i) % columns, ch)
            for i, ch in enumerate(sentinel)
        ]
    screen = make_screen(rows, columns, text=text, fields=fields,
                         cursor=(pause_row, 4))
    for r, c, ch in hidden_cells:
        screen.cell_grid[r][c] = ord(ch)
    return LineModeScreen(screen, pause_row, sentinel)


# ------------------------------------------------------------- signatures

def _coord() -> st.SearchStrategy[int]:
    return st.integers(0, 80)


def _text(max_size: int = 20) -> st.SearchStrategy[str]:
    return st.text(alphabet=_PRINTABLE, min_size=1, max_size=max_size)


def matcher_strategies() -> dict[str, st.SearchStrategy]:
    """One strategy per matcher kind (all seven), keyed by ``kind``.

    Needs ``greenscreen.recognizer.signature`` (task 2.1).
    """
    from greenscreen.recognizer.signature import (
        BeforeCursorMatcher,
        CursorFieldMatcher,
        FieldLayoutMatcher,
        LastRowMatcher,
        RegionRegexMatcher,
        RowContainsMatcher,
        TextAtMatcher,
    )

    positions = st.lists(st.tuples(st.integers(0, 23), _coord()), max_size=5)
    return {
        "text_at": st.builds(TextAtMatcher, row=st.integers(0, 23), col=_coord(), text=_text()),
        "row_contains": st.builds(RowContainsMatcher, row=st.integers(0, 23), text=_text()),
        "field_layout": positions.map(
            lambda ps: FieldLayoutMatcher(count=len(ps), positions=tuple(ps))
        ),
        "cursor_field": st.builds(
            CursorFieldMatcher, row=st.integers(0, 23), col=_coord(), hidden=st.booleans()
        ),
        "region_regex": st.builds(
            RegionRegexMatcher,
            row=st.integers(0, 23),
            col=_coord(),
            length=st.integers(1, 40),
            pattern=st.sampled_from(
                [r"[A-Z]+", r"\d+", r"^ *$", r"READY", r"[^ ]{1,8}-", r"x|y", r"."]
            ),
        ),
        "last_row": st.builds(LastRowMatcher, text=_text()),
        "before_cursor": st.builds(BeforeCursorMatcher, text=_text()),
    }


def matchers() -> st.SearchStrategy:
    """Any of the seven matcher kinds."""
    return st.one_of(*matcher_strategies().values())


def _overlaps(m, v) -> bool:
    kind = getattr(m, "kind", None)
    if kind == "text_at":
        length = len(m.text)
    elif kind == "region_regex":
        length = m.length
    else:
        return False
    return (
        m.row == v.row
        and m.col <= v.col + v.length - 1
        and v.col <= m.col + length - 1
    )


def volatile_regions() -> st.SearchStrategy:
    """A VolatileRegion with row/col/length inside the valid 0..255 limits."""
    from greenscreen.recognizer.signature import VolatileRegion

    return st.builds(
        VolatileRegion,
        row=st.integers(0, 23),
        col=_coord(),
        length=st.integers(1, 12),
    )


@st.composite
def signatures(draw, max_matchers: int = 6, max_volatile: int = 3):
    """Valid ScreenSignatures using all seven matcher kinds.

    Volatile regions that would share a cell with a text_at or region_regex
    rectangle are dropped, so construction always succeeds.
    """
    from greenscreen.recognizer.signature import ScreenSignature

    ms = draw(st.lists(matchers(), min_size=1, max_size=max_matchers))
    vs = draw(st.lists(volatile_regions(), max_size=max_volatile))
    vs = [v for v in vs if not any(_overlaps(m, v) for m in ms)]
    name = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=20))
    description = draw(st.text(alphabet=_PRINTABLE, max_size=40))
    return ScreenSignature(name=name, matchers=ms, volatile=vs, description=description)
