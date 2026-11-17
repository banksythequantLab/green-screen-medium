"""Live check: does s3270 echo the argument of String(...) in an error response?

One-time measurement for tn3270-connector Requirement 12 (open item). The
test records what it sees and passes on either outcome.

State used to provoke the error: the session sits on the logon screen, the
cursor is moved to row 0 col 0 (a protected field) with MoveCursor(0,0), then
String(<sentinel>) is sent. s3270 rejects typing into a protected field.

The sentinel is not a secret. No TK5 credential is read or typed and the
session never logs in.
"""
import os
import shutil

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error

LOGON = "Logon ===>"
SENTINEL = "echo-probe-7q"
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
def test_live_string_echo(host_reachable, record_property):
    config = ConnectorConfig(
        binary=_find_binary(),
        host=os.environ.get("GS_HOST", "192.168.68.72"),
        port=int(os.environ.get("GS_PORT", "3270")),
    )
    action = f'String("{SENTINEL}")'
    error: S3270Error | None = None

    with Connector(config) as conn:
        try:
            conn.wait_for_text(LOGON, timeout=5)
        except ConnectorTimeoutError:
            conn.enter()
            conn.wait_for_text(LOGON, timeout=8)

        conn.send("MoveCursor(0,0)")  # row 0 col 0 is a protected field
        try:
            conn.string(SENTINEL)
        except S3270Error as exc:
            error = exc

    if error is None:
        summary = "state=logon screen, cursor on protected field\nno error response (String accepted)"
        record_property("string_echo_result", summary)
        print("\n" + summary)
        return

    lines = [*error.data_lines, repr(error.status_line)]
    echoed_sentinel = any(SENTINEL in ln for ln in lines)
    echoed_action = any(action in ln for ln in lines)
    summary = (
        "state=logon screen, MoveCursor(0,0) onto a protected field, then String(sentinel)\n"
        f"sentinel_in_response={echoed_sentinel}\n"
        f"whole_action_in_response={echoed_action}\n"
        f"data_lines={list(error.data_lines)!r}\n"
        f"status_line={error.status_line!r}"
    )
    record_property("string_echo_result", summary)
    print("\n" + summary)
