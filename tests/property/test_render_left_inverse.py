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
    rows = draw(st.integers(min_value=1, max_value=24))
    cols = draw(st.integers(min_value=1, max_value=80))

    # Choose SF token positions (up to 5 per screen)
    total = rows * cols
    num_sf = draw(st.integers(min_value=0, max_value=min(5, total)))
    sf_linears = draw(
        st.lists(st.integers(min_value=0, max_value=total - 1),
                 min_size=num_sf, max_size=num_sf, unique=True)
    )
    sf_c0s = {lin: draw(st.integers(0, 0xFF)) for lin in sf_linears}

    # SA tokens: at most 2 per row, at column positions not exceeding cols-1
    # SA tokens are stored per row but emitted inline — we track them per linear pos
    # For simplicity in generation, place up to 2 SA tokens per row before cell 0
    sa_per_row: dict[int, list[tuple[int, int]]] = {}  # row -> [(col, val)]
    for r in range(rows):
        num_sa = draw(st.integers(0, min(2, cols)))
        sa_cols = draw(
            st.lists(st.integers(0, cols - 1), min_size=num_sa, max_size=num_sa, unique=True)
        )
        sa_per_row[r] = [(c, draw(st.integers(0, 0xFF))) for c in sorted(sa_cols)]

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
                byte_val = draw(st.integers(0, 0xFF))
                tokens.append(f"{byte_val:02x}")
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
    return pathlib.Path(__file__).parent.parent.parent / "captures"


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


@pytest.mark.parametrize("capture_file", list(_captures_dir().glob("*.readbuffer.txt")))
def test_render_left_inverse_on_captures(capture_file: pathlib.Path) -> None:
    """render(parse(x)) == x for every actual s3270 capture file."""
    data_lines, status_raw = _parse_capture_readbuffer(capture_file)
    if data_lines is None:
        pytest.skip(f"Could not extract data from {capture_file.name}")

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
