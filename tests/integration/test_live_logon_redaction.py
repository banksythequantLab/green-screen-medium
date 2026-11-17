"""Live check: a full TSO logon through the Connector leaves no trace of the
typed password in any log record or exception text.

Covers tn3270-connector Requirement 12.44 (and 12.45, 10.4) and the connector
side of flow-runtime Requirements 20.9 and 20.10.

TK5_USERNAME and TK5_PASSWORD come from the environment only. No credential
is written in this file, no screen is captured or stored, and assertion
messages name only the form index and the record index.
"""
import logging
import os
import shutil

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError
from tests.connector_support import (
    LogCapture,
    collect_exception_text,
    collect_record_text,
    forms_of_run,
)

LOGON = "Logon ===>"
WINDOWS_WS3270 = r"D:\tools\wc3270\ws3270.exe"
# Verified capture text (captures/ispf-primary-menu.ascii.txt) is lower case.
ISPF_MENU = "ISPF primary option menu"


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


def _logon_and_logoff(conn: Connector, user: str, password: str) -> None:
    try:
        conn.wait_for_text(LOGON, timeout=5)
    except ConnectorTimeoutError:
        conn.enter()  # logo still up after a few seconds
        conn.wait_for_text(LOGON, timeout=8)
    conn.string(user)
    conn.enter()
    conn.wait_for_text("ENTER CURRENT PASSWORD", timeout=10)
    conn.string(password)
    conn.enter()
    for _ in range(2):  # the two *** pauses
        conn.wait_for_text("***", timeout=10)
        conn.enter()
    conn.wait_for_text(ISPF_MENU, timeout=15)
    conn.string("X")
    conn.enter()
    conn.wait_for_text("READY", timeout=10)
    conn.string("LOGOFF")
    conn.enter()
    conn.wait_for_text(LOGON, timeout=10)


@pytest.mark.integration
def test_live_logon_redaction(host_reachable):
    missing = [
        name for name in ("TK5_USERNAME", "TK5_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(missing))
    user = os.environ["TK5_USERNAME"]
    password = os.environ["TK5_PASSWORD"]
    if len(password) < 4:
        pytest.skip("password too short for a meaningful absence check")
    try:
        password.encode("ascii")
    except UnicodeEncodeError:
        pytest.skip("password is not ASCII; absence check not defined")

    config = ConnectorConfig(
        binary=_find_binary(),
        host=os.environ.get("GS_HOST", "192.168.68.72"),
        port=int(os.environ.get("GS_PORT", "3270")),
    )

    capture = LogCapture(logging.DEBUG)
    logger = logging.getLogger("greenscreen.connector")
    old_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    exc_texts: list[str] = []
    failure: BaseException | None = None
    try:
        try:
            with Connector(config) as conn:
                _logon_and_logoff(conn, user, password)
        except BaseException as exc:  # noqa: BLE001 - checked below, then re-raised
            failure = exc
            exc_texts = collect_exception_text(exc)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(old_level)

    haystack: list[tuple[str, str]] = []
    for i, rec in enumerate(capture.records):
        for text in collect_record_text(rec):
            haystack.append((f"record {i}", text))
    for i, text in enumerate(exc_texts):
        haystack.append((f"exception text {i}", text))

    variants = [password, password.upper(), password.lower()]
    forms: list[str] = []
    for pw in variants:
        for form in sorted(forms_of_run(list(pw.encode("ascii")))):
            if form and form not in forms:
                forms.append(form)

    for form_index, form in enumerate(forms):
        for where, text in haystack:
            assert form not in text, f"form {form_index} found in {where}"

    if failure is not None:
        raise failure
