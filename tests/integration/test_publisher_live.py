"""Live run of ``POST /flows/tk5-system-info`` through the Publisher (task 10.2).

Covers publisher Requirements 21.1 to 21.6 and 7.10.

TK5_USERNAME and TK5_PASSWORD are read here, by the test, and handed to the
application under test as Binding_Variables (``GS_BIND_*``) in an injected
environment. The Publisher never reads them. The call body is empty, so the
credentials never travel in a request. No credential is written in this file,
and every assertion message is fixed text, so a failure cannot print one.

The Flow logs off by itself, so there is no account recovery here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import subprocess

import pytest

from greenscreen.publisher.app import build_app, prepare
from tests.property._publisher_strategies import all_leak_forms
from tests.publisher_support import LogCapture, rest_client

FLOW = "tk5-system-info"
PROCESS_NAMES = ("s3270", "ws3270")


# -- helpers ---------------------------------------------------------------

def _is_s3270(name: str) -> bool:
    base = name.lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base in PROCESS_NAMES


def _snapshot_pids() -> tuple[str, set[int]]:
    """PIDs of running s3270/ws3270 processes, and the method used to find them.

    psutil is used when it is already installed (children of this process only).
    Otherwise ``tasklist`` (Windows) or ``ps`` (POSIX) lists every such process on the
    machine, and the test compares the set before and after.
    """
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        pids = set()
        for child in psutil.Process().children(recursive=True):
            try:
                if _is_s3270(child.name()):
                    pids.add(child.pid)
            except psutil.NoSuchProcess:
                pass
        return "psutil", pids
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False
        ).stdout
        pids = set()
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and _is_s3270(parts[0].strip('"')) and parts[1].strip('"').isdigit():
                pids.add(int(parts[1].strip('"')))
        return "tasklist", pids
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=,comm="], capture_output=True, text=True, check=False
    ).stdout
    pids = set()
    for line in out.splitlines():
        pid, _, comm = line.strip().partition(" ")
        if pid.isdigit() and _is_s3270(os.path.basename(comm.strip())):
            pids.add(int(pid))
    return "ps", pids


# -- test ------------------------------------------------------------------

@pytest.mark.integration
def test_publisher_live_tk5_system_info(request):
    missing = [n for n in ("TK5_USERNAME", "TK5_PASSWORD") if not os.environ.get(n)]
    if missing:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(missing))
    user = os.environ["TK5_USERNAME"]
    password = os.environ["TK5_PASSWORD"]

    request.getfixturevalue("host_reachable")  # skips when the host is unreachable

    from tests.flow_support import live_connector_config

    config = live_connector_config()  # skips when no s3270/ws3270 binary is found
    api_key = secrets.token_urlsafe(24)
    environ = {
        "GS_S3270_BINARY": str(config.binary),
        "GS_HOST": str(config.host),
        "GS_PORT": str(config.port),
        "GS_API_KEY": api_key,
        "GS_PUBLISH_FLOWS": FLOW,
        "GS_MAX_CONCURRENCY": "1",
        "GS_BIND_TK5_SYSTEM_INFO__USERID": user,
        "GS_BIND_TK5_SYSTEM_INFO__PASSWORD": password,
    }

    method, before = _snapshot_pids()
    names = ("", "greenscreen.connector")
    saved = {n: logging.getLogger(n).level for n in names}
    texts: list[str] = []
    try:
        with LogCapture() as logs:
            logging.getLogger("greenscreen.connector").setLevel(logging.DEBUG)
            app = build_app(prepare(environ))  # default Session_Factory: ConnectorSession
            logs.refresh()

            async def call():
                async with rest_client(app, headers={"X-API-Key": api_key}) as client:
                    return await client.post(f"/flows/{FLOW}", json={}, timeout=170.0)

            response = asyncio.run(call())
            status = response.status_code
            texts.append(response.text)
            texts.append(repr(dict(response.headers)))
            try:
                body = response.json()
            except ValueError:
                body = None
            logs.refresh()
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)

    _, after = _snapshot_pids()
    leftover = after - before

    # The password is in no response and in no DEBUG record of any logger.
    forms = all_leak_forms([password]) if len(password) >= 4 else (password,)
    response_hits = [i for i, t in enumerate(texts) if any(f in t for f in forms)]
    log_hits = logs.find(forms)
    assert not response_hits, "the password occurs in a response"
    assert not log_hits, "the password occurs in a captured log record"
    assert any(r.level <= logging.DEBUG for r in logs.records), "no DEBUG record was captured"

    # The call succeeded with the expected outputs.
    assert status == 200, f"unexpected HTTP status {status}"
    assert isinstance(body, dict) and isinstance(body.get("outputs"), dict), "not a Success_Body"
    outputs = body["outputs"]
    userid_ok = str(outputs.get("USERID", "")).casefold() == user.casefold()
    assert userid_ok, "USERID differs from TK5_USERNAME"
    assert str(outputs.get("SYSTEMID", "")).strip() != "", "SYSTEMID is blank"
    assert str(outputs.get("RELEASE", "")).strip() != "", "RELEASE is blank"

    # No s3270/ws3270 process started by this test is still running.
    assert not leftover, f"{len(leftover)} s3270/ws3270 process(es) still running"
