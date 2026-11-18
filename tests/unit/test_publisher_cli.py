"""Startup, shutdown and stdio tests for ``greenscreen.publisher.cli`` (task 6.2).

Everything runs on the Fake_Host or before any host exists. Values are made up per test
run (random tokens), never credentials. The subprocess tests start
``tests/publisher_cli_entry.py``, a test-only wrapper around the real ``cli.main`` that
injects the Fake_Host; no environment variable can select a factory in production code.

Platform notes
    * The graceful HTTP stop test sends the platform's graceful signal: CTRL_BREAK_EVENT
      on Windows (uvicorn handles SIGBREAK there) and SIGTERM on POSIX.
    * ``test_stdio_sigterm_stops_cleanly`` needs POSIX SIGTERM (on Windows a SIGTERM is
      a hard kill) and is skipped on Windows. It did not run on the author's platform.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")

from greenscreen.publisher import app as app_module  # noqa: E402
from greenscreen.publisher import cli, registry  # noqa: E402
from greenscreen.publisher.app import build_app, prepare  # noqa: E402
from greenscreen.publisher.vault import SecretBox  # noqa: E402
from tests.flow_support import FakeClock  # noqa: E402
from tests.publisher_support import FakeHost, system_info_states  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WIN = sys.platform == "win32"


def tok(prefix: str = "pbv", n: int = 12) -> str:
    return prefix + uuid.uuid4().hex[:n]


def leak_forms(value: str) -> set[str]:
    """The Leak_Forms of the Glossary for one value."""
    raw = value.encode("utf-8")
    forms = {
        value,
        json.dumps(value)[1:-1],
        urllib.parse.quote(value, safe=""),
        urllib.parse.quote_plus(value),
    }
    for upper in (False, True):
        h = raw.hex().upper() if upper else raw.hex()
        forms.add(h)
        forms.add(" ".join(f"{b:02x}" if not upper else f"{b:02X}" for b in raw))
    for enc in (base64.b64encode, base64.urlsafe_b64encode):
        b = enc(raw).decode()
        forms.update({b, b.rstrip("=")})
    return {f for f in forms if f}


def base_env() -> dict[str, str]:
    return {
        "GS_S3270_BINARY": tok("bin-"),
        "GS_HOST": tok("host-") + ".invalid",
        "GS_API_KEY": tok("key", 20),
    }


def set_env(monkeypatch, env: dict[str, str]) -> None:
    for name in list(os.environ):
        if name.startswith(("GS_", "TK5_")):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


# --------------------------------------------------------------------------
# Startup failures: exit 2, message names the variable and rule, no value
# --------------------------------------------------------------------------

BUNDLED_DIR_FILE = (
    ROOT / "greenscreen" / "flow" / "flows" / "tk5-logoff.yaml"
)


def _dir_with(tmp_path: Path, files: dict[str, str]) -> str:
    d = tmp_path / "flows"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    return str(d)


# id -> (env builder(tmp_path), substrings the message must hold, env names whose value the
# spec lets the message name (a Flow name or a path), names of Binding_Variables to leak-check)
def _cases():
    bind_pw = "GS_BIND_TK5_SYSTEM_INFO__PASSWORD"
    bind_uid = "GS_BIND_TK5_SYSTEM_INFO__USERID"
    only = {"GS_PUBLISH_FLOWS": "tk5-system-info"}
    return {
        # Requirement 1
        "flows_dir_missing": (
            lambda t: {"GS_FLOWS_DIR": str(t / "absent")},
            ["GS_FLOWS_DIR", "not_a_readable_directory"],
            {"GS_FLOWS_DIR"},
        ),
        "flow_file_invalid": (
            lambda t: {"GS_FLOWS_DIR": _dir_with(t, {"broken.yaml": "version: 1\nname: [\n"})},
            ["broken.yaml"],
            {"GS_FLOWS_DIR"},
        ),
        "flow_name_duplicate": (
            lambda t: {
                "GS_FLOWS_DIR": _dir_with(
                    t, {"dup.yaml": BUNDLED_DIR_FILE.read_text(encoding="utf-8")}
                )
            },
            ["tk5-logoff", "bundled", "dup.yaml"],
            {"GS_FLOWS_DIR"},
        ),
        "publish_list_empty_item": (
            lambda t: {"GS_PUBLISH_FLOWS": "tk5-logon,,tk5-logoff"},
            ["GS_PUBLISH_FLOWS", "empty_item"],
            set(),
        ),
        "publish_list_whitespace_only": (
            lambda t: {"GS_PUBLISH_FLOWS": "   "},
            ["GS_PUBLISH_FLOWS", "empty_item"],
            set(),
        ),
        "publish_list_duplicate_name": (
            lambda t: {"GS_PUBLISH_FLOWS": "tk5-logon, tk5-logon"},
            ["GS_PUBLISH_FLOWS", "duplicate_name", "tk5-logon"],
            {"GS_PUBLISH_FLOWS"},
        ),
        "publish_list_unknown_flow": (
            lambda t: {"GS_PUBLISH_FLOWS": "tk5-logon,ghost-flow"},
            ["GS_PUBLISH_FLOWS", "unknown_flow", "ghost-flow"],
            {"GS_PUBLISH_FLOWS"},
        ),
        # Requirement 13
        "api_key_missing": (lambda t: {"GS_API_KEY": ""}, ["GS_API_KEY"], set()),
        "api_key_too_short": (
            lambda t: {"GS_API_KEY": tok("k", 7)},
            ["GS_API_KEY", "min_length"],
            set(),
        ),
        "auth_disabled_on_public_host": (
            lambda t: {"GS_AUTH_DISABLED": "true", "GS_PUBLISH_HOST": "203.0.113.77"},
            ["GS_AUTH_DISABLED", "GS_PUBLISH_HOST"],
            set(),
        ),
        # Requirement 15
        "port_not_an_integer": (
            lambda t: {"GS_PUBLISH_PORT": tok("port")},
            ["GS_PUBLISH_PORT", "not_an_integer"],
            set(),
        ),
        "port_out_of_range": (
            lambda t: {"GS_PUBLISH_PORT": "70000"},
            ["GS_PUBLISH_PORT", "out_of_range"],
            set(),
        ),
        "transport_unknown": (
            lambda t: {"GS_TRANSPORT": tok("tcp")},
            ["GS_TRANSPORT"],
            set(),
        ),
        "boolean_invalid": (
            lambda t: {"GS_ENABLE_DOCS": tok("yes")},
            ["GS_ENABLE_DOCS", "not_a_boolean"],
            set(),
        ),
        "host_missing": (lambda t: {"GS_HOST": ""}, ["GS_HOST", "missing"], set()),
        "binary_missing": (
            lambda t: {"GS_S3270_BINARY": ""},
            ["GS_S3270_BINARY", "missing"],
            set(),
        ),
        "max_concurrency_out_of_range": (
            lambda t: {"GS_MAX_CONCURRENCY": "9999"},
            ["GS_MAX_CONCURRENCY", "out_of_range"],
            set(),
        ),
        # Requirement 22 (values are Probe_Values; the first two violate a rule)
        "binding_name_format": (
            lambda t: {"GS_BIND_NOSEPARATOR": tok("pw")},
            ["GS_BIND_NOSEPARATOR", "name_format"],
            set(),
        ),
        "binding_unknown_flow": (
            lambda t: {"GS_BIND_NO_SUCH_FLOW__X": tok("pw")},
            ["GS_BIND_NO_SUCH_FLOW__X", "unknown_flow"],
            set(),
        ),
        "binding_flow_not_published": (
            lambda t: {**only, "GS_BIND_TK5_LOGON__USERID": tok("pw")},
            ["GS_BIND_TK5_LOGON__USERID", "flow_not_published"],
            set(),
        ),
        "binding_unknown_input": (
            lambda t: {**only, "GS_BIND_TK5_SYSTEM_INFO__NOPE": tok("pw")},
            ["GS_BIND_TK5_SYSTEM_INFO__NOPE", "unknown_input"],
            set(),
        ),
        "binding_too_long": (
            lambda t: {**only, bind_pw: tok("pw")},  # 14 characters, max_length is 8
            [bind_pw],
            set(),
        ),
        "binding_regex_violation": (
            lambda t: {**only, bind_pw: tok("p", 7), bind_uid: "!" + uuid.uuid4().hex[:6]},
            [bind_uid],
            set(),
        ),
        "binding_not_ascii": (
            lambda t: {**only, bind_pw: "\u00e9" + uuid.uuid4().hex[:6]},
            [bind_pw],
            set(),
        ),
    }


CASES = _cases()


@pytest.fixture
def never_serves(monkeypatch):
    """Fail the test if a failing startup builds the app, serves, binds, listens or spawns."""
    touched: list[str] = []

    def trip(name):
        def fn(*a, **k):
            touched.append(name)
            raise AssertionError(f"{name} reached after a startup failure")

        return fn

    monkeypatch.setattr(cli, "_run_http", trip("_run_http"))
    monkeypatch.setattr(cli, "_run_stdio", trip("_run_stdio"))
    monkeypatch.setattr(cli, "_stdio_streams", trip("_stdio_streams"))
    monkeypatch.setattr(app_module, "build_app", trip("build_app"))
    monkeypatch.setattr(socket.socket, "bind", trip("bind"))
    monkeypatch.setattr(socket.socket, "listen", trip("listen"))
    monkeypatch.setattr(subprocess, "Popen", trip("Popen"))
    return touched


def _assert_failed_cleanly(rc, out, err, env, expected, exempt, touched):
    assert rc == 2
    assert touched == []
    assert out == ""  # nothing on stdout (Requirement 14.9)
    assert err.startswith("greenscreen-publish: ") and err.count("\n") == 1
    for text in expected:
        assert text in err
    shown = out + err
    for name, value in env.items():
        if name in exempt or len(value) < 4:
            continue
        for form in leak_forms(value) if name.startswith("GS_BIND_") else {value}:
            assert form not in shown, f"{name} value leaked ({form[:6]}...)"


@pytest.mark.parametrize("case", sorted(CASES))
def test_startup_failure_exits_2_and_leaks_no_value(case, tmp_path, monkeypatch, capsys, never_serves):
    build, expected, exempt = CASES[case]
    env = {**base_env(), **build(tmp_path)}
    env = {k: v for k, v in env.items() if v != ""}
    set_env(monkeypatch, env)
    rc = cli.main()
    captured = capsys.readouterr()
    _assert_failed_cleanly(rc, captured.out, captured.err, env, expected, exempt, never_serves)


def test_signature_load_failure_exits_2_before_a_port_is_bound(monkeypatch, capsys, never_serves):
    # The one accepted loader patch (design, "Implementation notes"): there is no way to make
    # the bundled signature files unreadable without editing the package, and patching
    # here is limited to this one test. Nothing else in this file patches a loader.
    secret = tok("host-")
    env = {**base_env(), "GS_HOST": secret}
    set_env(monkeypatch, env)

    def boom():
        raise RuntimeError(secret)  # an exception text that holds a value must not surface

    monkeypatch.setattr(registry, "load_bundled_signatures", boom)
    rc = cli.main()
    captured = capsys.readouterr()
    assert rc == 2 and never_serves == []
    assert captured.out == ""
    assert "load_failed" in captured.err
    assert secret not in captured.err and env["GS_API_KEY"] not in captured.err


def test_unexpected_exception_in_prepare_is_reported_by_class_only(monkeypatch, capsys, never_serves):
    secret = tok("pw")

    def boom(environ):
        raise RuntimeError(secret)

    set_env(monkeypatch, base_env())
    monkeypatch.setattr(app_module, "prepare", boom)
    rc = cli.main()
    err = capsys.readouterr().err
    assert rc == 2 and "RuntimeError" in err and secret not in err


# --------------------------------------------------------------------------
# Missing extra (Requirement 16.5)
# --------------------------------------------------------------------------

_BLOCK_SCRIPT = r"""
import contextlib, io, json, sys
from greenscreen.publisher import cli
out = {}
for name in ("mcp", "fastapi", "uvicorn"):
    sys.modules[name] = None  # an import of the name raises ImportError
    err, so = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(so):
        rc = cli.main()
    out[name] = [rc, err.getvalue(), so.getvalue()]
    del sys.modules[name]
print(json.dumps(out))
"""


def test_missing_extra_names_the_module_and_the_extra():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GS_", "TK5_"))}
    done = subprocess.run(
        [sys.executable, "-c", _BLOCK_SCRIPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    results = json.loads(done.stdout)
    assert set(results) == {"mcp", "fastapi", "uvicorn"}
    for name, (rc, err, out) in results.items():
        assert rc == 2 and out == ""
        assert f"'{name}'" in err and "publish" in err


# --------------------------------------------------------------------------
# Environment scrub (Requirement 15.8)
# --------------------------------------------------------------------------

def test_api_key_and_bindings_are_removed_from_the_environment_after_prepare(
    monkeypatch, capsys, restore_logging
):
    env = {
        **base_env(),
        "GS_PUBLISH_FLOWS": "tk5-system-info",
        "GS_BIND_TK5_SYSTEM_INFO__PASSWORD": tok("pw", 6),
        "GS_BIND_TK5_SYSTEM_INFO__USERID": tok("u", 6),
    }
    set_env(monkeypatch, env)
    seen: dict[str, str] = {}

    def fake_run_http(app, settings):
        seen.update(os.environ)

    monkeypatch.setattr(cli, "_run_http", fake_run_http)
    rc = cli.main()
    assert rc == 0
    assert "GS_API_KEY" not in seen
    assert not [n for n in seen if n.startswith("GS_BIND_")]
    assert seen["GS_HOST"] == env["GS_HOST"]  # other variables stay
    assert "GS_API_KEY" not in os.environ
    shown = capsys.readouterr()
    for name in ("GS_API_KEY", "GS_BIND_TK5_SYSTEM_INFO__PASSWORD", "GS_BIND_TK5_SYSTEM_INFO__USERID"):
        for form in leak_forms(env[name]):
            assert form not in shown.out + shown.err


# --------------------------------------------------------------------------
# StripTraceback (Requirement 8.7)
# --------------------------------------------------------------------------

def _raise_with(marker: str):
    local_value = marker  # noqa: F841  (a frame local the filter must not read)
    raise ValueError(f"failed with {marker}")


def test_strip_traceback_keeps_class_file_line_and_function_only():
    marker = tok()
    try:
        _raise_with(marker)
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord("any.logger", logging.ERROR, __file__, 1, "call failed", None, exc_info)
    record.stack_info = f"Stack (most recent call last): {marker}"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(cli.StripTraceback())
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.handle(record)
    text = stream.getvalue()
    assert text.count("\n") == 1
    assert "call failed" in text and "ValueError" in text
    assert f"{Path(__file__).name}:" in text and "in _raise_with" in text
    assert marker not in text and "Traceback" not in text and "Stack (most" not in text
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None


def test_installed_stderr_handler_strips_tracebacks_from_any_logger(
    capsys, restore_logging
):
    marker = tok()
    cli._install_logging()
    try:
        _raise_with(marker)
    except ValueError:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application", exc_info=True)
        logging.getLogger("greenscreen.publisher").exception("third party failure")
    err = capsys.readouterr().err
    assert "Exception in ASGI application" in err and "ValueError" in err
    assert marker not in err and "Traceback" not in err


# --------------------------------------------------------------------------
# Shutdown (Requirements 16.1 to 16.3, 19.7)
# --------------------------------------------------------------------------

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": "tk5-system-info",
    "GS_SHUTDOWN_GRACE": "1",
}


def test_shutdown_closes_every_opened_session():
    host = FakeHost(lambda _n: system_info_states(), block_read=1)
    prepared = prepare(ENV)
    app = build_app(prepared, session_factory=host, clock=FakeClock(), poll_interval=0.01)
    flow = prepared.registry["tk5-system-info"]
    probe = {"userid": tok("U", 7), "password": tok("P", 7)}

    async def go():
        task = None
        try:
            async with app.lifespan():
                task = asyncio.create_task(
                    app.service.execute(flow, SecretBox.adopt(dict(probe)), "rest")
                )
                for _ in range(500):
                    if host.sessions and host.sessions[0].blocked.is_set():
                        break
                    await asyncio.sleep(0.01)
                else:
                    raise AssertionError("the call never reached the host")
            # leaving the lifespan drained the service: grace of 1 s, then teardown
            return await asyncio.wait_for(task, 10)
        finally:
            host.release_all()

    out = asyncio.run(go())
    assert out.code == "shutting_down"
    assert host.created == host.opened == host.closed == 1
    assert host.aborted == 1 and host.live == 0
    assert app.service.closing is True
    # a new call after shutdown opens no session
    late = asyncio.run(app.service.execute(flow, SecretBox.adopt(dict(probe)), "rest"))
    assert late.code == "shutting_down" and host.factory_calls == 1


# --------------------------------------------------------------------------
# Subprocess runs through tests/publisher_cli_entry.py
# --------------------------------------------------------------------------

def _clean_env(extra: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GS_", "TK5_"))}
    env.update(extra)
    return env


def _spawn(report: Path, env: dict[str, str], errfile: Path, *, stdout=None, stdin=None):
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    return subprocess.Popen(
        [sys.executable, "-m", "tests.publisher_cli_entry", str(report)],
        cwd=ROOT, env=env, stdin=stdin, stdout=stdout,
        stderr=errfile.open("wb"), creationflags=flags,
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_graceful_stop_after_a_call_exits_0_and_closes_the_session(tmp_path):
    """SIGTERM-equivalent stop of the HTTP server: exit code 0 (the handle_exit override).

    A plain ``uvicorn.Server.handle_exit`` of 0.38 re-raises the captured signal after a
    graceful stop, which ends the process with a non-zero code before the final drain.
    Windows has no graceful SIGTERM, so the test sends CTRL_BREAK_EVENT there.
    """
    port = _free_port()
    key, userid, password = tok("key", 20), tok("U", 7), tok("P", 7)
    env = _clean_env(
        {
            "GS_S3270_BINARY": "unused-" + tok(),
            "GS_HOST": "unused.invalid",
            "GS_PUBLISH_PORT": str(port),
            "GS_API_KEY": key,
            "GS_PUBLISH_FLOWS": "tk5-system-info",
        }
    )
    report, errfile = tmp_path / "report.json", tmp_path / "stderr.txt"
    proc = _spawn(report, env, errfile, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    watchdog = threading.Timer(90, proc.kill)
    watchdog.start()
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 40
        while True:
            assert proc.poll() is None, errfile.read_text(errors="replace")
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    assert json.loads(r.read()) == {"status": "ok", "flows": 1}
                    break
            except OSError:
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.2)
        req = urllib.request.Request(
            base + "/flows/tk5-system-info",
            data=json.dumps({"userid": userid, "password": password}).encode(),
            headers={"Content-Type": "application/json", "X-API-Key": key},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
        assert body["flow"] == "tk5-system-info" and "outputs" in body

        proc.send_signal(signal.CTRL_BREAK_EVENT if WIN else signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()
    result = json.loads(report.read_text())
    assert result["rc"] == 0
    assert result["created"] == result["opened"] == result["closed"] == 1
    assert result["live"] == 0
    err = errfile.read_text(errors="replace")
    for secret in (key, userid, password):
        for form in leak_forms(secret):
            assert form not in err
    assert "Traceback" not in err


def _rpc(proc, message: dict) -> None:
    proc.stdin.write((json.dumps(message) + "\n").encode())
    proc.stdin.flush()


def _read_response(proc, wanted_id: int, lines: list[bytes]) -> dict:
    while True:
        line = proc.stdout.readline()
        assert line, "stdout closed before the response arrived"
        lines.append(line)
        obj = json.loads(line)
        if obj.get("id") == wanted_id:
            return obj


def test_stdio_stdout_holds_only_json_rpc_even_when_a_handler_prints(tmp_path):
    userid, password = tok("U", 7), tok("P", 7)
    env = _clean_env(
        {
            "GS_S3270_BINARY": "unused-" + tok(),
            "GS_HOST": "unused.invalid",
            "GS_TRANSPORT": "stdio",
            "GS_API_KEY": tok("key", 20),  # ignored by stdio (Requirement 13.10)
            "GS_PUBLISH_FLOWS": "tk5-system-info",
        }
    )
    report, errfile = tmp_path / "report.json", tmp_path / "stderr.txt"
    proc = _spawn(report, env, errfile, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    watchdog = threading.Timer(90, proc.kill)
    watchdog.start()
    lines: list[bytes] = []
    try:
        _rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "cli-test", "version": "0"},
            },
        })
        init = _read_response(proc, 1, lines)
        assert "result" in init
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = _read_response(proc, 2, lines)["result"]["tools"]
        assert [t["name"] for t in tools] == ["tk5-system-info"]
        _rpc(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "tk5-system-info",
                "arguments": {"userid": userid, "password": password},
            },
        })
        call = _read_response(proc, 3, lines)["result"]
        assert not call.get("isError"), call
        assert call["structuredContent"]["flow"] == "tk5-system-info"

        proc.stdin.close()  # end of input is the normal stop
        lines.extend(proc.stdout.read().splitlines(keepends=True))
        assert proc.wait(timeout=30) == 0
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()

    assert lines
    for line in lines:
        message = json.loads(line)  # every stdout line is JSON ...
        assert message["jsonrpc"] == "2.0"  # ... and a JSON-RPC message
    stdout_text = b"".join(lines).decode("utf-8")
    err = errfile.read_text(errors="replace")
    for marker in ("STRAY-PRINT", "STRAY-FD1", "STRAY-DUNDER"):
        assert marker not in stdout_text
        assert marker in err  # the stray writes went to stderr
    for secret in (userid, password):
        for form in leak_forms(secret):
            assert form not in err and form not in stdout_text
    result = json.loads(report.read_text())
    assert result["rc"] == 0
    assert result["created"] == result["opened"] == result["closed"] == 1


@pytest.mark.skipif(WIN, reason="POSIX only: SIGTERM is a hard kill on Windows")
def test_stdio_sigterm_stops_cleanly(tmp_path):
    env = _clean_env(
        {
            "GS_S3270_BINARY": "unused-" + tok(),
            "GS_HOST": "unused.invalid",
            "GS_TRANSPORT": "stdio",
            "GS_PUBLISH_FLOWS": "tk5-system-info",
        }
    )
    report, errfile = tmp_path / "report.json", tmp_path / "stderr.txt"
    proc = _spawn(report, env, errfile, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    watchdog = threading.Timer(60, proc.kill)
    watchdog.start()
    try:
        deadline = time.monotonic() + 40
        while "publishing 1 of 3" not in errfile.read_text(errors="replace"):
            assert proc.poll() is None and time.monotonic() < deadline
            time.sleep(0.1)
        time.sleep(1.0)  # let the SIGTERM handler be installed
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()
    assert json.loads(report.read_text())["rc"] == 0
