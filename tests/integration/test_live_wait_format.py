"""Live test: does the binary accept the Wait() timeout formats the Connector sends?

Never types anything and never logs in. The session stays on the logon screen.

Accepted formats are recorded in Connector._format_seconds (connector.py), the
single place to change if a binary rejects a form. Known so far: ws3270 4.5
accepts "1" and "1.5".
"""
import os
import shutil
import subprocess

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error

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


def _binary_version(binary: str) -> str:
    for flag in ("--version", "-v"):
        try:
            r = subprocess.run([binary, flag], capture_output=True, timeout=5)
        except Exception:
            continue
        text = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
        if text:
            return text.splitlines()[0]
    return "unknown"


def _error_text(exc: S3270Error) -> str:
    return " ".join([str(exc), *exc.data_lines])


def _probe_raw(conn: Connector, command: str):
    """Return (accepted, detail) for a raw Wait command."""
    try:
        conn.send(command)
        return True, "ok"
    except S3270Error as exc:
        text = _error_text(exc)
        if "timed out" in text.lower():
            return True, f"timed out ({' '.join(exc.data_lines)})"
        return False, text


def _probe_public(conn: Connector, timeout: float):
    try:
        conn.wait_for_output(timeout)
        return True, "ok"
    except ConnectorTimeoutError as exc:
        return True, f"timed out ({exc})"
    except S3270Error as exc:
        return False, _error_text(exc)


@pytest.mark.integration
def test_live_wait_format(host_reachable, record_property):
    binary = _find_binary()
    version = _binary_version(binary)
    config = ConnectorConfig(
        binary=binary,
        host=os.environ.get("GS_HOST", "192.168.68.72"),
        port=int(os.environ.get("GS_PORT", "3270")),
    )
    results: list[tuple[str, bool, str]] = []

    with Connector(config) as conn:
        try:
            conn.wait_for_text(LOGON, timeout=5)
        except ConnectorTimeoutError:
            logo = conn.read_screen()
            text = "\n".join(logo.text_grid)
            assert "Hercules" in text or "tk5" in text.lower(), (
                f"neither logon screen nor Hercules logo; top row: {logo.text_grid[0]!r}"
            )
            conn.enter()
            conn.wait_for_text(LOGON, timeout=8)

        for cmd in ("Wait(1,Output)", "Wait(1.5,Output)",
                    "Wait(0.25,Output)", "Wait(0.001,Output)"):
            conn.read_screen()  # Wait only blocks if the screen was read since last output
            ok, detail = _probe_raw(conn, cmd)
            results.append((f"send {cmd}", ok, detail))
        for t in (1.5, 1, 0.25, 0.001):
            conn.read_screen()
            ok, detail = _probe_public(conn, t)
            results.append((f"wait_for_output({t})", ok, detail))

        healthy = LOGON in "\n".join(conn.read_screen().text_grid)

    table = "\n".join(
        f"  {name:<28} {'ACCEPTED' if ok else 'REJECTED'}  {detail}"
        for name, ok, detail in results
    )
    summary = f"binary={binary}\nversion={version}\n{table}"
    print("\n" + summary)
    record_property("wait_format_results", summary)

    must = {"send Wait(1,Output)", "send Wait(1.5,Output)",
            "wait_for_output(1.5)", "wait_for_output(1)"}
    rejected = [n for n, ok, _ in results if n in must and not ok]
    assert not rejected, f"rejected formats {rejected}\n{summary}"
    assert healthy, f"session no longer shows {LOGON!r} after probes\n{summary}"
