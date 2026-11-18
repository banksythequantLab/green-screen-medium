"""Cost of ``recognize`` on the bundled Signatures (publisher Requirement 17.4).

Opt-in: set GS_RUN_PERF=1. Each capture is recognized 200 times and the median of one
call must stay at or under 5 ms. Failure messages hold capture names and timings only.
"""
from __future__ import annotations

import os
import statistics
import time

import pytest

from greenscreen.recognizer import load_bundled_signatures, recognize
from tests.screen_support import load_capture_screen

CAPTURES = ("tk5-logon", "tso-password-prompt", "ispf-primary-menu", "tso-ready")
CALLS = 200
BUDGET_MS = 5.0


@pytest.mark.perf
@pytest.mark.skipif(
    os.environ.get("GS_RUN_PERF") != "1",
    reason="perf test is opt-in: set GS_RUN_PERF=1 to run it",
)
def test_recognize_median_under_budget() -> None:
    signatures = load_bundled_signatures()
    medians: dict[str, float] = {}
    for name in CAPTURES:
        screen = load_capture_screen(name)
        recognize(screen, signatures)  # warm-up
        samples: list[float] = []
        for _ in range(CALLS):
            start = time.perf_counter()
            recognize(screen, signatures)
            samples.append((time.perf_counter() - start) * 1000.0)
        medians[name] = statistics.median(samples)
    print("recognize median ms:", {k: round(v, 3) for k, v in medians.items()})
    slow = {k: v for k, v in medians.items() if v > BUDGET_MS}
    assert not slow, (
        f"median over {BUDGET_MS} ms: "
        + ", ".join(f"{k}={v:.3f} ms" for k, v in slow.items())
        + "; all: "
        + ", ".join(f"{k}={v:.3f} ms" for k, v in medians.items())
    )
