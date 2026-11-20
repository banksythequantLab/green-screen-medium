"""Run pytest for a Kiro hook with the report on standard error.

Spec: polish (requirements 12.x). A hook shows standard output to the agent
only on success, so the report must never go there. This runner works the same
in cmd, sh and PowerShell, which a `1>&2` suffix does not.

Usage: python tests/hook_pytest.py <pytest arguments>
Exit code: the one pytest returns.
"""

from __future__ import annotations

import contextlib
import sys

import pytest


def main(args: list[str]) -> int:
    with contextlib.redirect_stdout(sys.stderr):
        return int(pytest.main(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
