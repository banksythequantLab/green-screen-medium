from __future__ import annotations

"""Cross-platform pipe reader for the tn3270-connector.

Uses a background daemon thread + queue.Queue so that pipe reads with
timeouts work identically on Windows (ws3270) and Linux (s3270).
select.select() is NOT used because it does not support pipes on Windows.
"""

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
    """

    _SENTINEL = None  # signals EOF / process exited

    def __init__(self, pipe: IO[bytes], exit_code_ref: list[int | None] | None = None) -> None:
        """Start the background reader thread.

        Args:
            pipe: A binary-mode readable pipe (e.g. subprocess.stdout).
            exit_code_ref: Optional single-element list; if the process exits,
                the reader thread sets exit_code_ref[0] to the exit code so
                readline() can include it in the S3270Error it raises.
                Pass None if the exit code is not available at construction time.
        """
        self._pipe = pipe
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._exit_code_ref = exit_code_ref
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

        Raises:
            ConnectorTimeoutError: if no data arrives within `timeout` seconds.
            S3270Error: if the pipe closed (subprocess exited).
        """
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise ConnectorTimeoutError(
                f"Pipe read timed out after {timeout}s",
                operation="readline",
                deadline=timeout,
            )
        if line is self._SENTINEL:
            exit_code = (
                self._exit_code_ref[0]
                if self._exit_code_ref is not None
                else None
            )
            raise S3270Error(
                "s3270 subprocess pipe closed unexpectedly (process exited)",
                action="<pipe read>",
                exit_code=exit_code,
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
