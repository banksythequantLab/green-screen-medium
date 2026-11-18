"""Test-only entry point: the real ``greenscreen.publisher.cli.main`` on the Fake_Host.

Launched by ``tests/unit/test_publisher_cli.py`` in a subprocess, from the repository
root, as ``python -m tests.publisher_cli_entry <report.json>``. It lives under
``tests/`` and is not part of the package, so the production code has no way to
select a Session_Factory from the environment (Requirement 19.1). It does one
thing: replace ``greenscreen.publisher.app.build_app`` (which ``cli.main`` calls)
with a version that passes the Fake_Host, then run ``main()`` unchanged. The
configuration comes from the process environment as in production.

The Fake_Host sessions are noisy on purpose: ``open`` (which runs on the worker
thread, inside a tool call) prints, writes to descriptor 1 and writes to
``sys.__stdout__``. Requirement 14.11 says none of it may reach the protocol stream.

When ``main`` returns, a JSON report with the exit code and the session counters
is written to the path in ``argv[1]``. Nothing is printed to stdout here.
"""
from __future__ import annotations

import json
import os
import sys

from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, system_info_states

STRAY_MARKERS = ("STRAY-PRINT", "STRAY-FD1", "STRAY-DUNDER")


def _noisy(host: FakeHost):
    def factory():
        session = host()
        real_open = session.open

        def open_() -> None:
            print(STRAY_MARKERS[0])
            os.write(1, (STRAY_MARKERS[1] + "\n").encode())
            sys.__stdout__.write(STRAY_MARKERS[2] + "\n")
            sys.__stdout__.flush()
            real_open()

        session.open = open_  # type: ignore[method-assign]
        return session

    return factory


def run(report_path: str) -> int:
    from greenscreen.publisher import app as app_module
    from greenscreen.publisher import cli

    real_build_app = app_module.build_app
    host = FakeHost(lambda _n: system_info_states())
    factory = _noisy(host)

    def build_app(prepared, **kwargs):
        return real_build_app(
            prepared, session_factory=factory, clock=FakeClock(), poll_interval=0.01
        )

    app_module.build_app = build_app  # main() imports the name at call time
    code = cli.main()
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "rc": code,
                "created": host.created,
                "opened": host.opened,
                "closed": host.closed,
                "aborted": host.aborted,
                "live": host.live,
            },
            fh,
        )
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
