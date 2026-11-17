"""Live run of the bundled ``tk5-system-info`` flow through a Connector.

Covers flow-runtime Requirements 16.6 and 20.1 to 20.10.

TK5_USERNAME and TK5_PASSWORD come from the environment only. No credential
is written in this file and no screen is captured or stored. Assertions on the
password are computed as booleans, so a failure never prints it.
"""
from __future__ import annotations

import logging
import os
import time

import pytest

from greenscreen.connector.connector import Connector
from greenscreen.flow import load_bundled_flows, run_flow
from greenscreen.flow.errors import FlowError
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.connector_support import (
    LogCapture,
    collect_exception_text,
    collect_record_text,
    forms_of_run,
)
from tests.flow_support import live_connector_config

OUTPUT_ORDER = ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]


def _password_forms(password: str) -> tuple[list[str], list[str]]:
    """Return (plain forms, hex forms) of the password and its case variants."""
    plain: list[str] = []
    hexed: list[str] = []
    for variant in (password, password.upper(), password.lower()):
        raw = list(variant.encode("utf-8"))
        for form in sorted(forms_of_run(raw)):
            if not form:
                continue
            target = plain if form == "".join(chr(b) for b in raw if b != 0) else hexed
            if form not in target:
                target.append(form)
    return plain, hexed


@pytest.mark.integration
def test_live_tk5_system_info(request, record_property):
    missing = [
        name for name in ("TK5_USERNAME", "TK5_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(missing))
    user = os.environ["TK5_USERNAME"]
    password = os.environ["TK5_PASSWORD"]

    request.getfixturevalue("host_reachable")  # skips when the host is unreachable
    config = live_connector_config()  # skips when no binary is found
    flow = load_bundled_flows()["tk5-system-info"]
    signatures = load_bundled_signatures()

    capture = LogCapture(logging.DEBUG)
    root = logging.getLogger()
    connector_logger = logging.getLogger("greenscreen.connector")
    old_root_level = root.level
    old_conn_level = connector_logger.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    connector_logger.setLevel(logging.DEBUG)

    result = None
    error: BaseException | None = None
    final_name = None
    started = time.perf_counter()
    try:
        with Connector(config) as conn:
            try:
                result = run_flow(
                    flow, conn,
                    {"userid": user, "password": password},
                )
            except BaseException as exc:  # noqa: BLE001 - checked below, then re-raised
                error = exc
            if error is None:
                final_name = recognize(conn.read_screen(), signatures)
    finally:
        duration = time.perf_counter() - started
        root.removeHandler(capture)
        root.setLevel(old_root_level)
        connector_logger.setLevel(old_conn_level)
    record_property("duration_seconds", round(duration, 2))

    # Texts to search for the password.
    haystack: list[tuple[str, str]] = []
    for i, rec in enumerate(capture.records):
        for text in collect_record_text(rec):
            haystack.append((f"record {i}", text))
    if error is not None:
        for i, text in enumerate(collect_exception_text(error)):
            haystack.append((f"error text {i}", text))
    if result is not None:
        haystack.append(("repr(result)", repr(result)))
        for i, audit in enumerate(result.audit):
            haystack.append((f"audit {i}", repr(audit)))
            haystack.append((f"audit {i} str", str(audit)))

    plain_forms, hex_forms = _password_forms(password)
    forms = list(plain_forms)
    if len(password) >= 4:
        forms += hex_forms
    for form_index, form in enumerate(forms):
        for where, text in haystack:
            absent = form not in text
            assert absent, f"password form {form_index} found in {where}"

    if error is not None:
        # The run failed: report it without any credential. A FlowError carries
        # its reason, step index and summary only.
        if isinstance(error, FlowError):
            pytest.fail(
                f"flow stopped: reason={error.reason} step={error.step_index}",
                pytrace=False,
            )
        raise error

    assert result is not None
    assert list(result.outputs) == OUTPUT_ORDER
    assert result.outputs["USERID"].casefold() == user.casefold()
    assert result.outputs["SYSTEMID"].strip() != ""
    assert result.outputs["RELEASE"].strip() != ""
    assert final_name == "tk5-logon"
