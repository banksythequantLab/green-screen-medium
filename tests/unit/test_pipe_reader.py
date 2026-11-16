"""Unit tests for PipeReader (Task 3.2).

Feature: tn3270-connector, Property — cross-platform pipe I/O with timeout.
Validates: Requirements 11.1, 11.4
"""
import os
import time
import threading
import pytest
from greenscreen.connector._io import PipeReader, start_stderr_drain
from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error


class TestPipeReaderDataBeforeDeadline:
    """Data arrives before the deadline."""

    def test_single_line(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.write(b"hello\r\n")
        wpipe.flush()
        line = reader.readline(timeout=2.0)
        assert line == b"hello"
        wpipe.close()

    def test_crlf_stripped(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.write(b"status line\r\n")
        wpipe.flush()
        line = reader.readline(timeout=2.0)
        assert line == b"status line"
        wpipe.close()

    def test_lf_only_stripped(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.write(b"ok\n")
        wpipe.flush()
        line = reader.readline(timeout=2.0)
        assert line == b"ok"
        wpipe.close()

    def test_multiple_lines_in_order(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.write(b"data: hello\r\nstatus\r\nok\r\n")
        wpipe.flush()
        assert reader.readline(timeout=2.0) == b"data: hello"
        assert reader.readline(timeout=2.0) == b"status"
        assert reader.readline(timeout=2.0) == b"ok"
        wpipe.close()


class TestPipeReaderTimeout:
    """Deadline expires before any data arrives."""

    def test_raises_connector_timeout_error(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        with pytest.raises(ConnectorTimeoutError) as exc_info:
            reader.readline(timeout=0.1)
        assert exc_info.value.deadline == pytest.approx(0.1)
        assert exc_info.value.operation == "readline"
        wpipe.close()

    def test_timeout_is_fast(self):
        """Deadline should fire within a reasonable margin of the specified value."""
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        t0 = time.monotonic()
        with pytest.raises(ConnectorTimeoutError):
            reader.readline(timeout=0.2)
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"timeout took {elapsed:.2f}s, expected ~0.2s"
        wpipe.close()


class TestPipeReaderEOF:
    """Pipe closes (subprocess exited) → S3270Error."""

    def test_raises_s3270_error_on_eof(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.close()
        time.sleep(0.05)  # give the reader thread time to notice EOF
        with pytest.raises(S3270Error) as exc_info:
            reader.readline(timeout=1.0)
        assert "pipe closed" in str(exc_info.value).lower() or \
               "process exited" in str(exc_info.value).lower()

    def test_exit_code_is_none_connector_resolves_it(self):
        """PipeReader sets exit_code=None; the Connector calls proc.wait() after
        catching S3270Error to obtain the actual exit code."""
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        reader = PipeReader(rpipe)
        wpipe.close()
        time.sleep(0.05)
        with pytest.raises(S3270Error) as exc_info:
            reader.readline(timeout=1.0)
        # exit_code is None here; Connector sets it after proc.wait()
        assert exc_info.value.exit_code is None


class TestStderrDrain:
    """start_stderr_drain discards data without blocking."""

    def test_drain_does_not_block(self):
        read_fd, write_fd = os.pipe()
        rpipe = os.fdopen(read_fd, "rb")
        wpipe = os.fdopen(write_fd, "wb")
        t = start_stderr_drain(rpipe)
        # Write more data than a typical OS pipe buffer holds
        wpipe.write(b"x" * 65536)
        wpipe.flush()
        wpipe.close()
        t.join(timeout=2.0)
        assert not t.is_alive()
