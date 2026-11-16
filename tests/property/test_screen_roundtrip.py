"""Property 1: Screen parse→render→parse round-trip (Task 5.2).

Feature: tn3270-connector
Validates: Requirements 9.1, 5.2, 5.3
"""
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from greenscreen.connector.models import Screen, SFToken, SAToken, StatusLine, Response
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.renderer import ScreenRenderer


@st.composite
def arbitrary_screen(draw):
    """Build a Screen from raw cell grid with SF tokens at chosen positions."""
    rows = draw(st.integers(min_value=1, max_value=24))
    cols = draw(st.integers(min_value=1, max_value=80))
    total = rows * cols

    # Choose SF token positions (up to 10, unique linear positions)
    num_sf = draw(st.integers(min_value=0, max_value=min(10, total)))
    sf_linears = draw(
        st.lists(st.integers(min_value=0, max_value=total - 1),
                 min_size=num_sf, max_size=num_sf, unique=True)
    )
    sf_c0s = [draw(st.integers(min_value=0, max_value=0xFF)) for _ in sf_linears]

    # Build the cell grid
    cell_grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            linear = r * cols + c
            if linear in sf_linears:
                idx = sf_linears.index(linear)
                row.append(SFToken(c0=sf_c0s[idx]))
            else:
                row.append(draw(st.integers(min_value=0, max_value=0xFF)))
        cell_grid.append(row)

    # SA tokens: 0–3 per row, but at most cols distinct column indices
    sa_tokens = []
    for r in range(rows):
        row_sa = []
        num_sa = draw(st.integers(min_value=0, max_value=min(3, cols)))
        sa_cols = draw(
            st.lists(st.integers(min_value=0, max_value=cols - 1),
                     min_size=num_sa, max_size=num_sa, unique=True)
        )
        for col_idx in sorted(sa_cols):
            val = draw(st.integers(min_value=0, max_value=0xFF))
            row_sa.append((col_idx, SAToken(value=val)))
        sa_tokens.append(row_sa)

    cursor_row = draw(st.integers(min_value=0, max_value=rows - 1))
    cursor_col = draw(st.integers(min_value=0, max_value=cols - 1))

    return Screen(rows, cols, cursor_row, cursor_col, cell_grid, sa_tokens)


def _make_status(screen: Screen) -> StatusLine:
    return StatusLine(
        keyboard_state="U", screen_formatting="F", field_protection="U",
        connection_state="N", emulator_mode="I", model_number="2",
        rows=screen.rows, columns=screen.columns,
        cursor_row=screen.cursor_row, cursor_col=screen.cursor_col,
        window_id="0x0", command_time="0.000",
    )


@given(arbitrary_screen())
@settings(max_examples=200)
def test_parse_render_parse_roundtrip(screen: Screen) -> None:
    """parse(render(screen)) == screen for any generated Screen."""
    # Feature: tn3270-connector, Property 1: Screen parse-render round-trip
    renderer = ScreenRenderer()
    parser = ScreenParser()

    rendered_lines = renderer.render(screen)
    status = _make_status(screen)
    response = Response(success=True, data_lines=rendered_lines, status=status)
    recovered = parser.parse_readbuffer(response)

    assert recovered == screen, (
        f"Round-trip failed.\n"
        f"Original cell_grid:  {screen.cell_grid}\n"
        f"Rendered:            {rendered_lines}\n"
        f"Recovered cell_grid: {recovered.cell_grid}\n"
    )
