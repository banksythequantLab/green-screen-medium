"""Live test: reach the TK5 logon screen and check its structure.

Never types anything; the session is left at the logon screen and closed by
the Connector context manager (Disconnect/Quit).
"""
import os
import shutil

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.renderer import ScreenRenderer
from greenscreen.connector.models import Response

LOGON = "Logon ===>"
WINDOWS_WS3270 = r"D:\tools\wc3270\ws3270.exe"


def _find_binary() -> str:
    env = os.environ.get("GS_S3270_BINARY")
    if env:
        return env
    for name in ("s3270", "ws3270"):
        found = shutil.which(name)
        if found:
            return found
    if os.path.isfile(WINDOWS_WS3270):
        return WINDOWS_WS3270
    pytest.skip("no s3270/ws3270 binary: set GS_S3270_BINARY, add one to PATH, "
                f"or install {WINDOWS_WS3270}")


@pytest.mark.integration
def test_live_logon_screen(host_reachable):
    config = ConnectorConfig(
        binary=_find_binary(),
        host=os.environ.get("GS_HOST", "192.168.68.72"),
        port=int(os.environ.get("GS_PORT", "3270")),
    )
    with Connector(config) as conn:
        try:
            screen = conn.wait_for_text(LOGON, timeout=5)
        except ConnectorTimeoutError:
            # Logo may still be showing; only then press Enter.
            logo = conn.read_screen()
            text = "\n".join(logo.text_grid)
            assert "Hercules" in text or "TK5" in text or "tk5" in text.lower(), (
                f"neither logon screen nor Hercules logo; top row: {logo.text_grid[0]!r}"
            )
            conn.enter()
            screen = conn.wait_for_text(LOGON, timeout=8)

        grid = screen.text_grid
        assert any(LOGON in row for row in grid)
        assert (screen.rows, screen.columns) == (24, 80)

        row = next(i for i, r in enumerate(grid) if LOGON in r)
        end_col = grid[row].index(LOGON) + len(LOGON)

        unprotected = [f for f in screen.fields if not f.protected]
        assert len(unprotected) == 1, (
            f"expected 1 unprotected field, got {len(unprotected)}; top row: {grid[0]!r}"
        )
        field = unprotected[0]
        assert (field.start_row, field.start_col) == (row, end_col)
        assert not field.hidden
        assert screen.find_field(screen.cursor_row, screen.cursor_col) == field

        # Live render/parse round-trip.
        status = conn.send("ReadBuffer(Ascii)").status
        lines = ScreenRenderer().render(screen)
        again = ScreenParser().parse_readbuffer(
            Response(success=True, data_lines=lines, status=status)
        )
        assert again == screen
