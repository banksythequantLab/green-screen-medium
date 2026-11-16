"""Property 2: render is the left inverse of parse on ReadBuffer(Ascii) (Task 5.3).

Feature: tn3270-connector
Validates: Requirements 9.2, 5.1
"""
import os
import pathlib
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from greenscreen.connector.models import StatusLine, Response
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.renderer import ScreenRenderer


@st.composite
def arbitrary_readbuffer_output(draw):
    """Generate valid ReadBuffer(Ascii) lines with a matching status line."""
    rows = draw(st.one_of(st.integers(1, 6), st.integers(1, 24)))
    cols = draw(st.one_of(st.integers(1, 8), st.integers(1, 80)))

    # Choose SF token positions (up to 5 per screen)
    total = rows * cols
    num_sf = draw(st.integers(min_value=0, max_value=min(5, total)))
    sf_linears = draw(
        st.lists(st.integers(min_value=0, max_value=total - 1),
                 min_size=num_sf, max_size=num_sf, unique=True)
    )
    sf_c0s = dict(zip(sf_linears,
                      draw(st.lists(st.integers(0, 0xFF),
                                    min_size=num_sf, max_size=num_sf))))
    flat = list(draw(st.binary(min_size=total, max_size=total)))

    # SA tokens: at most 2 per row, at column positions not exceeding cols-1
    # SA tokens are stored per row but emitted inline — we track them per linear pos
    # For simplicity in generation, place up to 2 SA tokens per row before cell 0
    sa_per_row: dict[int, list[tuple[int, int]]] = {}  # row -> [(col, val)]
    for r in range(rows):
        num_sa = draw(st.integers(0, min(2, cols)))
        sa_cols = draw(
            st.lists(st.integers(0, cols - 1), min_size=num_sa, max_size=num_sa, unique=True)
        )
        sa_vals = draw(st.lists(st.integers(0, 0xFF),
                                min_size=num_sa, max_size=num_sa))
        sa_per_row[r] = list(zip(sorted(sa_cols), sa_vals))

    # Build data lines
    data_lines = []
    for r in range(rows):
        tokens = []
        # Build SA lookup for this row: col -> val (emit before that cell)
        sa_at = {col: val for col, val in sa_per_row.get(r, [])}
        for c in range(cols):
            linear = r * cols + c
            # Emit SA before this cell if any
            if c in sa_at:
                tokens.append(f"SA(42={sa_at[c]:02x})")
            if linear in sf_c0s:
                tokens.append(f"SF(c0={sf_c0s[linear]:02x})")
            else:
                tokens.append(f"{flat[linear]:02x}")
        data_lines.append(" ".join(tokens))

    status = StatusLine(
        keyboard_state="U", screen_formatting="F", field_protection="U",
        connection_state="N", emulator_mode="I", model_number="2",
        rows=rows, columns=cols,
        cursor_row=draw(st.integers(0, rows - 1)),
        cursor_col=draw(st.integers(0, cols - 1)),
        window_id="0x0", command_time="0.000",
    )
    return data_lines, status


@given(arbitrary_readbuffer_output())
@settings(max_examples=200)
def test_render_left_inverse(data_and_status) -> None:
    """render(parse(x)) == x for any generated ReadBuffer(Ascii) output."""
    # Feature: tn3270-connector, Property 2: render is left inverse of parse
    data_lines, status = data_and_status
    parser = ScreenParser()
    renderer = ScreenRenderer()

    response = Response(success=True, data_lines=data_lines, status=status)
    screen = parser.parse_readbuffer(response)
    rendered = renderer.render(screen)

    assert rendered == data_lines, (
        f"Render left-inverse failed.\n"
        f"Input:    {data_lines}\n"
        f"Rendered: {rendered}\n"
    )


# --- Regression: must pass on every file in captures/ ---

def _captures_dir() -> pathlib.Path:
    """Resolve captures/ relative to repo root (this file is in tests/property/)."""
    return pathlib.Path(__file__).parents[2] / "captures"


MIN_CAPTURES = 2
REQUIRED_CAPTURES = ("tk5-logo.readbuffer.txt", "tk5-logon.readbuffer.txt")


def _capture_params(directory: pathlib.Path | None = None) -> list:
    """Build parametrization; never empty. Yields a failing case if too few files."""
    directory = _captures_dir() if directory is None else directory
    files = sorted(directory.glob("*.readbuffer.txt")) if directory.is_dir() else []
    if len(files) < MIN_CAPTURES:
        return [pytest.param(None, id="NO-CAPTURES-FOUND")]
    return [pytest.param(f, id=f.name) for f in files]


def test_captures_glob_finds_files() -> None:
    """The captures directory must exist and contain the expected readbuffer files."""
    directory = _captures_dir().resolve()
    found = sorted(p.name for p in directory.glob("*.readbuffer.txt")) if directory.is_dir() else []
    assert directory.is_dir(), f"Captures directory does not exist: {directory}"
    assert len(found) >= MIN_CAPTURES, (
        f"Expected at least {MIN_CAPTURES} *.readbuffer.txt files in {directory}, found: {found}"
    )
    for name in REQUIRED_CAPTURES:
        assert name in found, f"{name} missing from {directory}; found: {found}"


def _parse_capture_readbuffer(path: pathlib.Path):
    """Extract data lines and status line from a raw s3270 capture file.

    The capture format is:
      <status line>
      ok
      [optional more status/ok lines from earlier commands]
      data: ...   (one per row, 24 lines for a 24x80 screen)
      <status line>
      ok
    We want the data: lines from the last block.
    """
    text = path.read_text(encoding="utf-8")
    blocks = []
    current_data = []
    current_status = None
    for line in text.splitlines():
        if line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "ok" and current_data:
            # Find the status line just before this ok (it comes right before ok)
            blocks.append((current_data[:], current_status))
            current_data = []
            current_status = None
        elif not line.startswith("data: ") and line not in ("ok", "error", ""):
            # Likely a status line
            current_status = line
    # Return the last complete block
    if blocks:
        return blocks[-1]
    return None, None


@pytest.mark.parametrize("capture_file", _capture_params())
def test_render_left_inverse_on_captures(capture_file) -> None:
    """render(parse(x)) == x for every actual s3270 capture file."""
    if capture_file is None:
        pytest.fail(
            f"No capture files found: fewer than {MIN_CAPTURES} *.readbuffer.txt "
            f"in {_captures_dir().resolve()}"
        )
    data_lines, status_raw = _parse_capture_readbuffer(capture_file)
    assert data_lines, f"Could not extract data lines from {capture_file.name}"

    parser = ScreenParser()
    renderer = ScreenRenderer()

    status = parser.parse_status_line(status_raw)
    response = Response(success=True, data_lines=data_lines, status=status)
    screen = parser.parse_readbuffer(response)
    rendered = renderer.render(screen)

    assert rendered == data_lines, (
        f"Render left-inverse failed for {capture_file.name}.\n"
        f"First differing row: "
        + next(
            f"row {i}: expected {e!r}, got {g!r}"
            for i, (e, g) in enumerate(zip(data_lines, rendered))
            if e != g
        )
    )
