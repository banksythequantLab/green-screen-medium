"""Connector: drives an s3270/ws3270 subprocess (lifecycle + basic send)."""
from __future__ import annotations

import logging
import math
import subprocess
import time
from types import TracebackType
from typing import Any, Callable

from greenscreen.connector._io import PipeReader, start_stderr_drain
from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.exceptions import (
    ConnectorError,
    ConnectorTimeoutError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.connector.models import Response, Screen
from greenscreen.connector.parser import ScreenParser, _escape_s3270_string

logger = logging.getLogger("greenscreen.connector")


class Connector:
    """Headless 3270 session backed by an s3270/ws3270 subprocess."""

    def __init__(
        self,
        config: ConnectorConfig,
        process_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._config = config
        self._process_factory = process_factory
        self._proc: Any = None
        self._reader: PipeReader | None = None
        self._closed = False
        self._opened = False

    # ── Context manager ──────────────────────────────────────────────────
    def __enter__(self) -> "Connector":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.close()
        return False

    # ── Lifecycle ────────────────────────────────────────────────────────
    def open(self) -> None:
        """Start the subprocess and send Connect(host:port)."""
        if self._opened and not self._closed:
            raise ConnectorError("Session is already open")
        if self._closed:
            raise SessionClosedError("Session has been closed and cannot be reopened")

        cfg = self._config
        cmd = [cfg.binary, "-model", cfg.model]
        try:
            proc = self._process_factory(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise ConnectorError(
                f"Could not start s3270 binary at {cfg.binary!r}: {exc}"
            ) from exc

        self._proc = proc
        self._reader = PipeReader(proc.stdout)
        start_stderr_drain(proc.stderr)
        self._opened = True

        try:
            self.send(f"Connect({cfg.host}:{cfg.port})")
        except SessionClosedError:
            # send() already tore the process down after a timeout
            raise
        except S3270Error as exc:
            self._terminate_proc()
            self._closed = True
            raise ConnectorError(
                f"Connect to {cfg.host}:{cfg.port} failed: {exc}"
            ) from exc

    def close(self) -> None:
        """Disconnect, quit, and reap the subprocess. Idempotent."""
        if self._closed or not self._opened or self._proc is None:
            return
        proc = self._proc
        try:
            for action in ("Disconnect()", "Quit()"):
                try:
                    self.send(action)
                except (ConnectorError, OSError):
                    pass
                if self._closed:  # send() tore the session down
                    return
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("s3270 did not exit within 5s; terminating")
                self._terminate_proc()
        finally:
            self._closed = True

    # ── Core I/O ─────────────────────────────────────────────────────────
    def send(self, action: str) -> Response:
        """Write an action to s3270 and return its Response."""
        return self._send_with_deadline(action, self._config.default_timeout)

    def _send_with_deadline(self, action: str, deadline: float) -> Response:
        """Write an action and read its response with a pipe deadline of `deadline` seconds.

        Shared implementation for send() and the wait_* methods: validates the
        action, checks the session is open, and tears the session down on a
        pipe-level timeout.
        """
        if not action or "\n" in action or "\r" in action:
            raise ValueError(f"Invalid action string: {action!r}")
        if self._closed or not self._opened or self._proc is None:
            raise SessionClosedError("Session is not open")
        self._write(action)
        try:
            return self._read_response(action, deadline)
        except ConnectorTimeoutError as exc:
            self._terminate_proc()
            self._closed = True
            raise ConnectorTimeoutError(
                f"Timed out waiting for response to {action!r}: {exc}",
                operation=action,
                deadline=exc.deadline,
            ) from exc

    # ── Action helpers ───────────────────────────────────────────────────
    def enter(self) -> Response:
        """Send Enter()."""
        return self.send("Enter()")

    def clear(self) -> Response:
        """Send Clear()."""
        return self.send("Clear()")

    @staticmethod
    def _check_key_number(kind: str, n: int) -> None:
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 24:
            raise ValueError(f"{kind} key n must be an integer in 1-24, got {n!r}")

    def pf(self, n: int) -> Response:
        """Send PF(n); n must be an int in 1..24."""
        self._check_key_number("PF", n)
        return self.send(f"PF({n})")

    def pa(self, n: int) -> Response:
        """Send PA(n); n must be an int in 1..24."""
        self._check_key_number("PA", n)
        return self.send(f"PA({n})")

    def string(self, text: str) -> Response:
        """Type text via String("..."), escaping backslash then double quote."""
        if len(text) > 3000:
            raise ValueError(f"text length {len(text)} exceeds 3000-character limit")
        return self.send(f'String("{_escape_s3270_string(text)}")')

    def move_cursor(self, row: int, col: int) -> Response:
        """Send MoveCursor(row,col); both must be non-negative."""
        if row < 0 or col < 0:
            raise ValueError(f"row and col must be non-negative, got ({row}, {col})")
        return self.send(f"MoveCursor({row},{col})")

    def snap_save(self) -> Response:
        """Send Snap(Save)."""
        return self.send("Snap(Save)")

    # ── Wait operations ──────────────────────────────────────────────────
    # Added to the s3270 Wait(N,...) timeout so s3270's own timeout answers
    # before the pipe read deadline expires.
    WAIT_GRACE_SECONDS: float = 5.0

    MIN_TIMEOUT: float = 0.001
    MAX_TIMEOUT: float = 3600.0

    def _resolve_timeout(self, timeout: float | None) -> float:
        """None -> config.default_timeout; ValueError unless 0.001 <= t <= 3600.

        Also rejects bool, non-numbers, NaN and infinity with ValueError.
        """
        t = timeout if timeout is not None else self._config.default_timeout
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            raise ValueError(f"timeout must be a number, got {t!r}")
        if math.isnan(t) or math.isinf(t):
            raise ValueError(f"timeout must be finite, got {t!r}")
        if t <= 0:
            raise ValueError(f"timeout must be positive, got {t!r}")
        if t < self.MIN_TIMEOUT:
            raise ValueError(
                f"timeout must be at least {self.MIN_TIMEOUT}, got {t!r}"
            )
        if t > self.MAX_TIMEOUT:
            raise ValueError(f"timeout must be at most 3600, got {t!r}")
        return t

    @staticmethod
    def _format_seconds(t: float) -> str:
        """Format a Wait() timeout in fixed-point notation (never an exponent).

        Valid timeouts are 0.001..3600 seconds. The value is rounded to 3
        decimal places for the wire, trailing zeros and a trailing dot are
        stripped, and the result is clamped to "0.001".."3600" so rounding can
        never produce 0 or exceed the maximum. ws3270 4.5 accepts both
        integer ("1") and decimal ("1.5") forms; this helper is the single
        place to change the notation.
        """
        t = min(max(float(t), 0.001), 3600.0)
        text = format(t, ".3f").rstrip("0").rstrip(".")
        return text or "0.001"

    def _wait(self, wait_type: str, timeout: float | None) -> Response:
        t = self._resolve_timeout(timeout)
        action = f"Wait({self._format_seconds(t)},{wait_type})"
        try:
            return self._send_with_deadline(action, t + self.WAIT_GRACE_SECONDS)
        except S3270Error as exc:
            text = " ".join(exc.data_lines)
            lowered = text.lower()
            if "timed out" in lowered or "timeout" in lowered:
                raise ConnectorTimeoutError(
                    f"Wait({wait_type}) timed out after {self._format_seconds(t)}s: {text}",
                    operation=f"Wait({wait_type})",
                    deadline=t,
                ) from exc
            if text and text not in str(exc):
                raise S3270Error(
                    f"{exc}: {text}",
                    action=exc.action,
                    data_lines=exc.data_lines,
                    status_line=exc.status_line,
                    exit_code=exc.exit_code,
                ) from exc
            raise

    def wait_for_output(self, timeout: float | None = None) -> Response:
        """Wait(N,Output). Returns on the FIRST screen update, which may be partial;
        use wait_for_text to wait for specific content."""
        return self._wait("Output", timeout)

    def wait_for_field(self, timeout: float | None = None) -> Response:
        """Wait(N,InputField)."""
        return self._wait("InputField", timeout)

    def wait_for_unlock(self, timeout: float | None = None) -> Response:
        """Wait(N,Unlock)."""
        return self._wait("Unlock", timeout)

    # ── Screen capture ───────────────────────────────────────────────────
    def read_screen(self) -> Screen:
        """Send only ReadBuffer(Ascii) and parse it into a Screen."""
        return ScreenParser().parse_readbuffer(self.send("ReadBuffer(Ascii)"))

    def ascii(self) -> Response:
        """Send Ascii(); data_lines are the screen text rows."""
        return self.send("Ascii()")

    @staticmethod
    def _visible_text(screen: Screen) -> str:
        """Screen text with hidden-field cells blanked, rows joined by newline."""
        grid = [list(row) for row in screen.text_grid]
        total = screen.rows * screen.columns
        for f in screen.fields:
            if not f.hidden:
                continue
            start = f.start_row * screen.columns + f.start_col
            for offset in range(1, f.byte_length + 1):
                r, c = divmod((start + offset) % total, screen.columns)
                grid[r][c] = " "
        return "\n".join("".join(row) for row in grid)

    def wait_for_text(
        self,
        text: str,
        timeout: float | None = None,
        poll_interval: float = 0.25,
    ) -> Screen:
        """Poll read_screen() until `text` appears, then return that Screen.

        Rows are joined with "\\n", so a match cannot span rows unless `text`
        itself contains newlines; match within a row for row-local text.
        Cells of hidden fields (passwords) are blanked before matching and
        never appear in errors or logs. Callers must not pass secrets as
        `text`. Always polls at least once, with a final poll at the deadline.
        A ParseError from read_screen() propagates.
        Raises ConnectorTimeoutError (operation="wait_for_text") on expiry.
        """
        if not text:
            raise ValueError("text must be non-empty")
        if poll_interval <= 0:
            raise ValueError(f"poll_interval must be positive, got {poll_interval!r}")
        t = self._resolve_timeout(timeout)
        end = time.monotonic() + t
        while True:
            screen = self.read_screen()
            if text in self._visible_text(screen):
                return screen
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise ConnectorTimeoutError(
                    f"Timed out after {t}s waiting for text {text!r}",
                    operation="wait_for_text",
                    deadline=t,
                )
            time.sleep(min(poll_interval, remaining))

    def _write(self, action: str) -> None:
        logger.debug("direction=sent action=%s raw=%s", action, action)
        try:
            self._proc.stdin.write((action + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except OSError as exc:  # includes BrokenPipeError
            raise S3270Error(
                f"s3270 subprocess is not accepting input for {action!r}",
                action=action,
                exit_code=self._exit_code(),
            ) from exc

    def _read_response(self, action: str, timeout: float) -> Response:
        reader = self._reader
        assert reader is not None
        data_lines: list[str] = []
        lines: list[str] = []
        while True:
            try:
                raw = reader.readline(timeout)
            except S3270Error as exc:
                if exc.exit_code is None:
                    raise S3270Error(
                        f"s3270 subprocess exited during {action!r}",
                        action=action,
                        exit_code=self._exit_code(),
                    ) from exc
                raise
            line = raw.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                data_lines.append(line[len("data: "):])
                continue
            if line == "data:":
                data_lines.append("")
                continue
            if line in ("ok", "error"):
                break
            lines.append(line)

        status_raw = lines[-1] if lines else ""
        logger.debug(
            "direction=received action=%s raw=%s",
            action,
            "\n".join(data_lines + lines + [line]),
        )
        status = ScreenParser().parse_status_line(status_raw)
        if line == "ok":
            return Response(success=True, data_lines=data_lines, status=status)
        raise S3270Error(
            f"s3270 returned error for {action!r}",
            action=action,
            data_lines=data_lines,
            status_line=status,
        )

    # ── Helpers ──────────────────────────────────────────────────────────
    def _exit_code(self) -> int | None:
        try:
            return self._proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return None

    def _terminate_proc(self) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warning("s3270 did not terminate; killed")
