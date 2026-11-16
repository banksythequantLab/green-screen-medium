"""Cross-platform pipe reader for the tn3270-connector.

Uses a background daemon thread + queue.Queue so that pipe reads with
timeouts work identically on Windows (ws3270) and Linux (s3270).
select.select() is NOT used because it does not support pipes on Windows.
"""
from __future__ import annotations

import queue
import threading
from typing import IO

from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error


class PipeReader:
    """Background daemon thread that drains a readable binary pipe into a queue.

    The reader thread calls readline() in a loop and puts each stripped line
    onto a queue.Queue. The main thread calls readline(timeout=N) to retrieve
    lines with a deadline.

    Binary pipes on Windows return lines ending with \\r\\n; this class strips
    \\r\\n explicitly after each readline() call before enqueuing.

    Exit code responsibility: the Connector (not PipeReader) calls proc.wait()
    when it catches S3270Error from readline() and wants the exit code.
    PipeReader itself never touches the subprocess object.
    """

    _SENTINEL = None  # signals EOF / process exited

    def __init__(self, pipe: IO[bytes]) -> None:
        """Start the background reader thread.

        Args:
            pipe: A binary-mode readable pipe (e.g. subprocess.stdout).
        """
        self._pipe = pipe
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._eof = False  # set True once sentinel is dequeued
        self._thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="gs-pipe-reader",
        )
        self._thread.start()

    def _reader_loop(self) -> None:
        """Run in background thread. Reads lines and enqueues them stripped of CRLF.
        Puts None sentinel on EOF."""
        try:
            for raw_line in self._pipe:
                # Binary pipe on Windows yields lines ending with \r\n;
                # strip explicitly so downstream code receives bare bytes.
                line = raw_line.rstrip(b"\r\n")
                self._queue.put(line)
        finally:
            self._queue.put(self._SENTINEL)

    def readline(self, timeout: float) -> bytes:
        """Block until one line is available or timeout seconds elapse.

        Returns the line as bytes (CRLF stripped).

        Once EOF has been observed, every subsequent call raises S3270Error
        immediately without waiting for the timeout.

        Raises:
            ConnectorTimeoutError: if no data arrives within `timeout` seconds.
            S3270Error: if the pipe is closed (subprocess exited). The caller
                (Connector) is responsible for calling proc.wait() to obtain
                the exit code after catching this exception.
        """
        # Fast path: if we already know EOF, raise without blocking.
        if self._eof:
            raise S3270Error(
                "s3270 subprocess pipe closed unexpectedly (process exited)",
                action="<pipe read>",
                exit_code=None,
            )

        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise ConnectorTimeoutError(
                f"Pipe read timed out after {timeout}s",
                operation="readline",
                deadline=timeout,
            )
        if line is self._SENTINEL:
            self._eof = True
            raise S3270Error(
                "s3270 subprocess pipe closed unexpectedly (process exited)",
                action="<pipe read>",
                exit_code=None,
            )
        return line


def start_stderr_drain(pipe: IO[bytes]) -> threading.Thread:
    """Start a daemon thread that reads and discards all stderr output.

    This prevents the subprocess from blocking on a full stderr pipe buffer.
    The drained bytes are silently discarded.
    """
    def _drain() -> None:
        try:
            for _ in pipe:
                pass
        except Exception:
            pass

    t = threading.Thread(target=_drain, daemon=True, name="gs-stderr-drain")
    t.start()
    return t