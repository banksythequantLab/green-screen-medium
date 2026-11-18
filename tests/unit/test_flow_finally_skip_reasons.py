"""The runtime's public set of reasons that skip the finally steps (logon-recovery task 6.4)."""
from __future__ import annotations

import greenscreen.flow as flow_pkg
from greenscreen.flow import runner

FIVE = {"unknown_screen", "ambiguous_screen", "timeout", "run_timeout", "session_error"}


def test_public_constant_is_the_private_frozenset() -> None:
    assert isinstance(runner.FINALLY_SKIP_REASONS, frozenset)
    assert runner.FINALLY_SKIP_REASONS is runner._FINALLY_SKIP_REASONS
    assert FIVE <= runner.FINALLY_SKIP_REASONS


def test_constant_is_not_exported_from_the_package() -> None:
    assert "FINALLY_SKIP_REASONS" not in flow_pkg.__all__
