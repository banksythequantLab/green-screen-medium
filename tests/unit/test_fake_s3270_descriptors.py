"""Descriptor count over many FakeS3270 cycles (POSIX only; skipped on Windows).

**Validates: Requirements 1.6**

200 cycles alternate between closing the fake through ``Connector.close()``
and through ``FakeS3270.close()``. The descriptor count of the test process
must end where it started. The counting needs ``/proc/self/fd`` or
``/dev/fd``; without either the test skips with the platform name.
"""
from __future__ import annotations

import gc
import os
import re
import sys
from typing import Callable

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse

HOST = "host.example"
PORT = 3270
STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"
CYCLES = 200


def _fd_count() -> int:
    for path in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(path):
            return len(os.listdir(path))
    pytest.skip(
        "descriptor counting needs /proc/self/fd or /dev/fd; "
        f"platform {sys.platform}"
    )


def _script() -> list[ScriptedResponse]:
    def entry(command: str) -> ScriptedResponse:
        return ScriptedResponse(re.escape(command), [], STATUS, "ok")

    return [entry(f"Connect({HOST}:{PORT})"), entry("Disconnect()"), entry("Quit()")]


def _cycle(index: int) -> None:
    """Even index: Connector.open()/close(). Odd index: FakeS3270.close() directly."""
    fake = FakeS3270(_script())
    try:
        if index % 2 == 0:
            conn = Connector(
                ConnectorConfig(binary="s3270", host=HOST, port=PORT),
                process_factory=lambda cmd, **kw: fake,
            )
            conn.open()
            conn.close()
        else:
            fake.terminate()
    finally:
        fake.close()


def _measure(count: Callable[[], int], cycle: Callable[[int], None], cycles: int = CYCLES):
    """Return (start, end) counts around ``cycles`` cycles after one warm-up."""
    gc.collect()
    cycle(0)
    gc.collect()
    start = count()
    for i in range(cycles):
        cycle(i)
    gc.collect()
    return start, count()


def test_descriptor_count_is_flat_over_200_fake_cycles():
    start, end = _measure(_fd_count, _cycle)
    assert end == start, f"descriptor count went from {start} to {end} over {CYCLES} cycles"


def test_measure_runs_warmup_plus_all_cycles_and_reports_both_counts():
    """Windows-safe check of the counting helper, with a fake counter."""
    seen: list[int] = []
    counter = iter([7, 7])
    start, end = _measure(lambda: next(counter), seen.append, cycles=5)
    assert (start, end) == (7, 7)
    assert seen == [0, 0, 1, 2, 3, 4]  # warm-up, then every cycle index in order
