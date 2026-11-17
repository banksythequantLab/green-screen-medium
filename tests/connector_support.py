"""Shared test doubles and collectors for connector redaction tests.

ScriptedProc and RecordingFake are copied from tests/unit/test_connector.py,
which stays unchanged. This module does not import greenscreen.connector._redact.
"""
from __future__ import annotations

import io
import logging

from greenscreen.connector.models import SFToken
from greenscreen.connector.testing.fake import FakeS3270


class RecordingFake(FakeS3270):
    """FakeS3270 that records commands and stays silent once the script runs out."""

    def __init__(self, script):
        self.commands: list[str] = []
        super().__init__(script)

    def _dispatch(self, command: str) -> None:
        self.commands.append(command)
        if self._index >= len(self._script):
            return  # simulate a hung process: no answer
        super()._dispatch(command)


class ScriptedProc:
    """Minimal Popen-like object backed by in-memory pipes."""

    def __init__(self, stdout: bytes, wait_exc=None, wait_value=0):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(b"")
        self.calls: list[str] = []
        self._wait_exc = wait_exc
        self._wait_value = wait_value

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self._wait_exc is not None:
            raise self._wait_exc
        return self._wait_value

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def poll(self):
        return None


class _BrokenPipeStdin:
    """First write succeeds; later writes record the bytes and raise BrokenPipeError."""

    def __init__(self, attempted: list[bytes]):
        self._attempted = attempted
        self._writes = 0
        self.written = io.BytesIO()

    def write(self, data: bytes):
        self._attempted.append(bytes(data))
        self._writes += 1
        if self._writes == 1:
            return self.written.write(data)
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class BrokenPipeProc(ScriptedProc):
    """ScriptedProc whose stdin accepts the first write (Connect) then breaks."""

    def __init__(self, stdout: bytes, wait_exc=None, wait_value=0):
        super().__init__(stdout, wait_exc=wait_exc, wait_value=wait_value)
        self.attempted: list[bytes] = []
        self.stdin = _BrokenPipeStdin(self.attempted)


class LogCapture(logging.Handler):
    """Handler that keeps every LogRecord it receives, at every level."""

    def __init__(self, level: int = logging.NOTSET):
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _args_items(args) -> list:
    if args is None:
        return []
    if isinstance(args, dict):
        return list(args.values())
    if isinstance(args, (tuple, list)):
        return list(args)
    return [args]


def collect_record_text(record: logging.LogRecord) -> list[str]:
    """Every text that a log record can carry: msg, each args element, getMessage()."""
    texts = [str(record.msg)]
    for item in _args_items(record.args):
        texts.append(str(item))
        texts.append(repr(item))
    try:
        texts.append(record.getMessage())
    except Exception as exc:  # a bad format string is itself a finding
        texts.append(f"<getMessage failed: {type(exc).__name__}>")
    return texts


def hidden_runs(screen) -> list[tuple[list[int], list[list[int]]]]:
    """Hidden_Cells found by a linear scan of screen.cell_grid, independent of
    Screen.fields and Field.hidden. Returns (whole_run, per_row_runs) per hidden
    SFToken; the run wraps modulo rows*columns and ends before the next SFToken."""
    columns = screen.columns
    grid = screen.cell_grid
    total = len(grid) * columns
    sf_positions = [
        (r * columns + c, cell)
        for r, row in enumerate(grid)
        for c, cell in enumerate(row)
        if isinstance(cell, SFToken)
    ]
    result = []
    for i, (pos, tok) in enumerate(sf_positions):
        if (tok.c0 & 0x0C) != 0x0C:
            continue
        nxt = sf_positions[(i + 1) % len(sf_positions)][0]
        length = (nxt - pos - 1) % total if nxt != pos else total - 1
        whole: list[int] = []
        per_row: list[list[int]] = []
        for off in range(1, length + 1):
            lin = (pos + off) % total
            row_i, col_i = divmod(lin, columns)
            value = grid[row_i][col_i]
            whole.append(int(value))
            if not per_row or row_i != prev_row:
                per_row.append([])
            per_row[-1].append(int(value))
            prev_row = row_i
        result.append((whole, per_row))
    return result


def forms_of_run(run: list[int]) -> set[str]:
    """Plain_Form (nulls dropped, omitted when empty) and the four Hex_Forms."""
    forms: set[str] = set()
    plain = "".join(chr(b) for b in run if b != 0)
    if plain:
        forms.add(plain)
    for fmt in ("{:02x}", "{:02X}"):
        for sep in ("", " "):
            forms.add(sep.join(fmt.format(b) for b in run))
    return forms


def forbidden_forms(screen, min_len: int = 4) -> set[str]:
    """Union of forms_of_run over every whole run and every per-row piece of at
    least min_len bytes."""
    forms: set[str] = set()
    for whole, per_row in hidden_runs(screen):
        for run in [whole, *per_row]:
            if len(run) >= min_len:
                forms |= forms_of_run(run)
    return forms


def collect_exception_text(
    exc: BaseException, exclude_attrs=frozenset()
) -> list[str]:
    """str, repr, every args item and every vars() value of exc and of its
    __cause__ / __context__ chain (visited set ends cycles). Names in
    exclude_attrs are skipped in vars() at every level."""
    texts: list[str] = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        texts.append(str(cur))
        texts.append(repr(cur))
        for a in cur.args:
            texts.append(str(a))
            texts.append(repr(a))
        try:
            attrs = vars(cur)
        except TypeError:
            attrs = {}
        for name, value in attrs.items():
            if name in exclude_attrs:
                continue
            texts.append(str(value))
            texts.append(repr(value))
        for linked in (cur.__cause__, cur.__context__):
            if linked is not None:
                stack.append(linked)
    return texts
