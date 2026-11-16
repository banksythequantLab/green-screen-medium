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
    rows = draw(st.one_of(st.integers(1, 6), st.integers(1, 24)))
    cols = draw(st.one_of(st.integers(1, 8), st.integers(1, 80)))
    total = rows * cols

    num_sf = draw(st.integers(min_value=0, max_value=min(10, total)))
    sf_linears = draw(
        st.lists(st.integers(min_value=0, max_value=total - 1),
                 min_size=num_sf, max_size=num_sf, unique=True)
    )
    sf_c0s = draw(st.lists(st.integers(0, 0xFF), min_size=num_sf, max_size=num_sf))

    # Bulk-draw cells, then overwrite SF positions.
    flat = list(draw(st.binary(min_size=total, max_size=total)))
    for lin, c0 in zip(sf_linears, sf_c0s):
        flat[lin] = SFToken(c0=c0)
    cell_grid = [flat[r * cols:(r + 1) * cols] for r in range(rows)]

    # SA tokens: 0–3 per row, but at most cols distinct column indices
    sa_tokens = []
    for r in range(rows):
        row_sa = []
        num_sa = draw(st.integers(min_value=0, max_value=min(3, cols)))
        sa_cols = draw(
            st.lists(st.integers(min_value=0, max_value=cols - 1),
                     min_size=num_sa, max_size=num_sa, unique=True)
        )
        vals = draw(st.lists(st.integers(0, 0xFF),
                             min_size=num_sa, max_size=num_sa))
        for col_idx, val in zip(sorted(sa_cols), vals):
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
