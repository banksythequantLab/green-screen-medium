"""Test-only child entry: ``tests.publisher_cli_entry`` plus a self-delivered SIGTERM.

Launched as ``python -m tests.publisher_sigterm_entry <report.json>`` by
``tests/unit/test_publisher_stdio_sigterm_portable.py``. A timer thread waits until
``cli._on_sigterm`` is the installed SIGTERM handler, waits one more second (as the
POSIX test does), then delivers SIGTERM to its own process. The call differs by platform:

* POSIX: ``os.kill(os.getpid(), SIGTERM)``. The signal goes through the kernel and
  Python runs ``cli._on_sigterm`` in the main thread.
* Elsewhere (Windows): ``signal.raise_signal(SIGTERM)``. On Windows ``os.kill`` with
  SIGTERM terminates the process without running the Python handler, and a parent
  cannot send a real SIGTERM, so the signal is raised in-process instead.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time


def _arm() -> None:
    from greenscreen.publisher import cli

    deadline = time.monotonic() + 60
    while signal.getsignal(signal.SIGTERM) is not cli._on_sigterm:
        if time.monotonic() > deadline:
            return
        time.sleep(0.01)
    time.sleep(1.0)
    if os.name == "posix":
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        signal.raise_signal(signal.SIGTERM)


if __name__ == "__main__":
    from tests.publisher_cli_entry import run

    threading.Thread(target=_arm, name="sigterm-timer", daemon=True).start()
    sys.exit(run(sys.argv[1]))
