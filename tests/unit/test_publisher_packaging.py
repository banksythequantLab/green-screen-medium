"""Packaging checks for the publisher (task 1.1)."""
from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ("mcp", "fastapi", "starlette", "uvicorn")


@pytest.fixture(scope="module")
def project() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]


def _names(requirements: list[str]) -> set[str]:
    return {re.split(r"[<>=!~\[ ;]", r, maxsplit=1)[0].lower() for r in requirements}


def test_publish_extra_holds_the_approved_dependencies(project: dict) -> None:
    assert sorted(project["optional-dependencies"]["publish"]) == [
        "fastapi>=0.163,<1",
        "mcp>=2.3,<3",
    ]


def test_web_packages_appear_only_under_publish(project: dict) -> None:
    assert _names(project["dependencies"]).isdisjoint(WEB)
    for extra, reqs in project["optional-dependencies"].items():
        if extra != "publish":
            assert _names(reqs).isdisjoint(WEB), extra


def test_dependencies_unchanged(project: dict) -> None:
    assert project["dependencies"] == ["pyyaml>=6.0.3"]


def test_dev_extra_pulls_publish(project: dict) -> None:
    assert "greenscreen-connector[publish]" in project["optional-dependencies"]["dev"]


def test_console_script_declared(project: dict) -> None:
    assert project["scripts"] == {"greenscreen-publish": "greenscreen.publisher.cli:main"}


def test_core_packages_do_not_import_web_packages() -> None:
    code = (
        "import sys\n"
        "import greenscreen.flow, greenscreen.connector, greenscreen.recognizer\n"
        "import greenscreen.publisher\n"
        f"bad = [m for m in {WEB!r} if m in sys.modules]\n"
        "print(','.join(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
