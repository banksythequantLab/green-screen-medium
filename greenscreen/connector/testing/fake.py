"""FakeS3270: in-process substitute for the s3270 subprocess (Task 9.1).

Implements the same stdin/stdout protocol as s3270 and the same interface
Connector expects from subprocess.Popen, so it can be injected via the
process_factory parameter.

Requirements: 8.1, 8.2, 8.5
"""
from __future__ import annotations

import io
import os
import re
import threading
from dataclasses import dataclass


@dataclass
class ScriptedResponse:
    """One scripted exchange: a command pattern and the response to emit."""
    command_pattern: str   # Python regex matched against the full command string
    response_lines: list[str]  # zero or more data lines (without 'data: ' prefix)
    status_line: str
    result: str            # "ok" or "error"


class FakeS3270:
    """In-process substitute for the s3270 subprocess.

    Accepts commands on stdin, emits scripted responses on stdout.
    Implements the Popen-compatible interface (stdin, stdout, stderr,
    wait, terminate, kill, poll) so Connector can use it directly.
    """

    def __init__(self, script: list[ScriptedResponse]) -> None:
        self._script = list(script)
        self._index = 0
        self._terminated = False

        # Stdin: Connector writes here; we read from stdin_read
        stdin_read_fd, stdin_write_fd = os.pipe()
        # Stdout: we write here; Connector's PipeReader reads from stdout_read
        stdout_read_fd, stdout_write_fd = os.pipe()
        # Stderr: empty pipe; just needs to be drainable
        stderr_read_fd, stderr_write_fd = os.pipe()

        self.stdin:  io.RawIOBase = os.fdopen(stdin_write_fd, "wb", buffering=0)
        self.stdout: io.RawIOBase = os.fdopen(stdout_read_fd, "rb", buffering=0)
        self.stderr: io.RawIOBase = os.fdopen(stderr_read_fd, "rb", buffering=0)

        self._stdin_read   = os.fdopen(stdin_read_fd,   "rb", buffering=0)
        self._stdout_write = os.fdopen(stdout_write_fd, "wb", buffering=0)
        # Close write end of stderr immediately (nothing to drain)
        os.close(stderr_write_fd)

        # Start handler thread
        self._thread = threading.Thread(
            target=self._handle_loop, daemon=True, name="gs-fake-s3270"
        )
        self._thread.start()

    def _handle_loop(self) -> None:
        """Read commands from stdin pipe and emit scripted responses."""
        for raw_line in self._stdin_read:
            command = raw_line.rstrip(b"\r\n").decode("utf-8", errors="replace")
            if not command:
                continue
            self._dispatch(command)

    def _dispatch(self, command: str) -> None:
        if self._index >= len(self._script):
            raise AssertionError(
                f"FakeS3270 exhausted: no scripted response remains for "
                f"command {command!r}"
            )
        entry = self._script[self._index]
        if not re.fullmatch(entry.command_pattern, command.strip()):
            raise AssertionError(
                f"FakeS3270 command mismatch.\n"
                f"  Expected pattern: {entry.command_pattern!r}\n"
                f"  Actual command:   {command!r}"
            )
        self._index += 1
        for line in entry.response_lines:
            self._stdout_write.write(f"data: {line}\r\n".encode())
        self._stdout_write.write(f"{entry.status_line}\r\n".encode())
        self._stdout_write.write(f"{entry.result}\r\n".encode())

    # ── Popen-compatible interface ────────────────────────────────────────

    def wait(self, timeout: float | None = None) -> int:
        """Return 0 immediately (FakeS3270 never crashes)."""
        return 0

    def terminate(self) -> None:
        self._terminated = True
        try:
            self._stdout_write.close()
        except Exception:
            pass

    def kill(self) -> None:
        self.terminate()

    def poll(self) -> int | None:
        """Return None while running, 0 after terminate/kill."""
        return 0 if self._terminated else None
