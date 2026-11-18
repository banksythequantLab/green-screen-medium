"""Unit tests for FakeS3270 (Requirements 8.1, 8.2, 8.5)."""
from __future__ import annotations

import pytest

from greenscreen.connector._io import PipeReader
from greenscreen.connector.exceptions import ConnectorTimeoutError
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse

T = 2.0


def _resp(pattern, lines=(), status="U F U C(h) I 4 24 80 0 0 0x0 -", result="ok"):
    return ScriptedResponse(pattern, list(lines), status, result)


@pytest.fixture
def make_fake():
    fakes = []

    def _make(script):
        f = FakeS3270(script)
        fakes.append(f)
        return f

    yield _make
    for f in fakes:
        f.terminate()
        try:
            f.stdin.close()
        except Exception:
            pass
        f.close()


@pytest.fixture
def reader_for(make_fake):
    # Depends on make_fake so it is torn down first: every reader thread
    # ends before any pipe is closed.
    readers = []

    def _r(fake):
        reader = PipeReader(fake.stdout)
        readers.append((fake, reader))
        return reader

    yield _r
    for fake, reader in readers:
        fake.terminate()
        thread = getattr(reader, "_thread", None)
        if thread is not None:
            thread.join(2.0)


def _read(reader, n):
    return [reader.readline(T) for _ in range(n)]


def test_wire_format_data_status_ok(make_fake, reader_for):
    fake = make_fake([_resp("Ascii", ["line one", "line two"], "STATUS")])
    reader = reader_for(fake)
    fake._dispatch("Ascii")
    assert _read(reader, 4) == [b"data: line one", b"data: line two", b"STATUS", b"ok"]


def test_zero_response_lines_emit_status_and_ok_only(make_fake, reader_for):
    fake = make_fake([_resp("Enter", [], "ST")])
    reader = reader_for(fake)
    fake._dispatch("Enter")
    assert _read(reader, 2) == [b"ST", b"ok"]
    with pytest.raises(ConnectorTimeoutError):
        reader.readline(0.2)


def test_error_result_emitted(make_fake, reader_for):
    fake = make_fake([_resp("Bad", [], "ST", "error")])
    reader = reader_for(fake)
    fake._dispatch("Bad")
    assert _read(reader, 2) == [b"ST", b"error"]


def test_pattern_is_regex_fullmatch(make_fake, reader_for):
    fake = make_fake([_resp(r"Wait\(\d+,Output\)", [], "ST")])
    reader = reader_for(fake)
    fake._dispatch("Wait(8,Output)")
    assert _read(reader, 2) == [b"ST", b"ok"]


def test_pattern_does_not_match_longer_command(make_fake):
    fake = make_fake([_resp("Enter")])
    with pytest.raises(AssertionError):
        fake._dispatch("Enter extra")


def test_entries_replay_in_order(make_fake, reader_for):
    fake = make_fake([_resp("A", ["a"], "S1"), _resp("B", ["b"], "S2")])
    reader = reader_for(fake)
    fake._dispatch("A")
    fake._dispatch("B")
    assert _read(reader, 6) == [
        b"data: a", b"S1", b"ok", b"data: b", b"S2", b"ok",
    ]


def test_mismatch_raises_with_pattern_and_command(make_fake):
    fake = make_fake([_resp(r"Wait\(\d+\)")])
    with pytest.raises(AssertionError) as ei:
        fake._dispatch("Quit")
    msg = str(ei.value)
    assert repr(r"Wait\(\d+\)") in msg  # fake formats the pattern with !r
    assert "Quit" in msg


def test_exhaustion_raises_with_command_text(make_fake):
    fake = make_fake([_resp("A")])
    fake._dispatch("A")
    with pytest.raises(AssertionError) as ei:
        fake._dispatch("String(\"unexpected\")")
    msg = str(ei.value)
    assert 'String("unexpected")' in msg
    assert "no scripted response remains" in msg


def test_popen_interface(make_fake):
    fake = make_fake([])
    for attr in ("stdin", "stdout", "stderr"):
        assert hasattr(fake, attr)
    assert fake.poll() is None
    assert isinstance(fake.wait(1.0), int)
    fake.terminate()
    assert isinstance(fake.poll(), int)


def test_kill_sets_poll(make_fake):
    fake = make_fake([])
    assert fake.poll() is None
    fake.kill()
    assert isinstance(fake.poll(), int)


def test_stderr_empty_eof(make_fake):
    fake = make_fake([])
    assert fake.stderr.read(1) == b""


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_stdin_command_triggers_response(make_fake, reader_for, eol):
    fake = make_fake([_resp("Enter", ["x"], "ST")])
    reader = reader_for(fake)
    fake.stdin.write(b"Enter" + eol)
    assert _read(reader, 3) == [b"data: x", b"ST", b"ok"]


def test_empty_stdin_line_ignored(make_fake, reader_for):
    fake = make_fake([_resp("Enter", [], "ST")])
    reader = reader_for(fake)
    fake.stdin.write(b"\n\r\nEnter\n")
    assert _read(reader, 2) == [b"ST", b"ok"]


# ── Handler-thread failure surfacing ─────────────────────────────────────
import time

from tests.conftest import finalize_fakes
from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorError, S3270Error


def _assert_fast_eof(reader):
    start = time.monotonic()
    with pytest.raises(S3270Error):
        reader.readline(5.0)
    assert time.monotonic() - start < 1.5


def test_mismatch_via_stdin_gives_eof_and_failure(make_fake, reader_for):
    fake = make_fake([_resp(r"Enter")])
    reader = reader_for(fake)
    fake.stdin.write(b"Quit\n")
    _assert_fast_eof(reader)
    assert isinstance(fake.failure, AssertionError)
    assert repr("Enter") in str(fake.failure) and "Quit" in str(fake.failure)
    with pytest.raises(AssertionError) as ei:
        fake.raise_if_failed()
    assert ei.value is fake.failure


def test_exhaustion_via_stdin_gives_eof_and_failure(make_fake, reader_for):
    fake = make_fake([])
    reader = reader_for(fake)
    fake.stdin.write(b"Unexpected\n")
    _assert_fast_eof(reader)
    assert "Unexpected" in str(fake.failure)
    assert "no scripted response remains" in str(fake.failure)


def test_writes_and_terminate_safe_after_failure(make_fake, reader_for):
    fake = make_fake([])
    reader = reader_for(fake)
    fake.stdin.write(b"X\n")
    _assert_fast_eof(reader)
    first = fake.failure
    for _ in range(50):
        fake.stdin.write(b"more commands\n")
    fake.terminate()
    fake.kill()
    assert fake.failure is first  # first failure wins


def test_healthy_fake_has_no_failure(make_fake, reader_for):
    fake = make_fake([_resp("Enter", ["x"], "ST")])
    reader = reader_for(fake)
    fake.stdin.write(b"Enter\n")
    assert _read(reader, 3) == [b"data: x", b"ST", b"ok"]
    assert fake.failure is None
    fake.raise_if_failed()


def test_finalize_fakes_raises_stored_failure(make_fake):
    fake = make_fake([])
    fake.stdin.write(b"X\n")
    deadline = time.monotonic() + 2
    while fake.failure is None and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(AssertionError, match="no scripted response remains"):
        finalize_fakes([fake])


def test_finalize_fakes_passes_for_healthy_fake(make_fake):
    finalize_fakes([make_fake([])])


def test_factory_fixture_creates_working_fake(fake_s3270_factory):
    fake = fake_s3270_factory([_resp("Enter", [], "ST")])
    fake._dispatch("Enter")
    assert fake.failure is None


def test_connector_open_fails_fast_on_script_mismatch(make_fake):
    fake = make_fake([_resp(r"Nope\(\)")])
    cfg = ConnectorConfig(binary="fake", host="h", port=3270)
    conn = Connector(cfg, process_factory=lambda cmd, **kw: fake)
    start = time.monotonic()
    with pytest.raises(ConnectorError):
        conn.open()
    assert time.monotonic() - start < 5
    assert isinstance(fake.failure, AssertionError)
    assert "Nope" in str(fake.failure)
