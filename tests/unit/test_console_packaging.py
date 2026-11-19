"""Packaging tests for the console assets (task 2.13).

The wheel is built in a temporary copy of the repository (reusing the helper
of the flow packaging test) so nothing is left behind in the repo.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
import zipfile

from tests.unit.test_flow_packaging import REPO, _wheel_workspace

PREFIX = "greenscreen/publisher/console/"
EXPECTED_FILES = {
    PREFIX + name
    for name in (
        "__init__.py",
        "index.html",
        "console.css",
        "console.js",
        "snippets.js",
        "codes.json",
        "favicon.svg",
    )
}

CONSOLE_PATTERNS = ["*.html", "*.css", "*.js", "*.json", "*.svg"]
OTHER_PACKAGE_DATA = {
    "greenscreen.connector.testing": ["fixtures/*.yaml"],
    "greenscreen.recognizer.signatures": ["*.yaml"],
    "greenscreen.flow.flows": ["*.yaml"],
}


def test_package_data_has_the_console_key_and_the_others_are_unchanged() -> None:
    with (REPO / "pyproject.toml").open("rb") as handle:
        package_data = tomllib.load(handle)["tool"]["setuptools"]["package-data"]
    assert package_data == {
        **OTHER_PACKAGE_DATA,
        "greenscreen.publisher.console": CONSOLE_PATTERNS,
    }


def test_wheel_contains_exactly_the_console_assets() -> None:
    with _wheel_workspace() as (work, out):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("TK5_")}
        # No network: no index, and proxies that point nowhere.
        env["PIP_NO_INDEX"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env[name] = "http://127.0.0.1:9"
            env[name.lower()] = "http://127.0.0.1:9"

        proc = subprocess.run(
            [
                sys.executable, "-m", "pip", "wheel", ".",
                "--no-deps", "--no-build-isolation", "--no-index",
                "-w", str(out),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        wheels = sorted(out.glob("*.whl"))
        assert proc.returncode == 0 and wheels, (
            "wheel build failed (exit "
            f"{proc.returncode}):\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
        )

        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())

    found = {n for n in names if n.startswith(PREFIX)}
    missing = sorted(EXPECTED_FILES - found)
    assert not missing, f"wheel is missing: {', '.join(missing)}"
    assert found == EXPECTED_FILES, f"unexpected files in wheel: {sorted(found - EXPECTED_FILES)}"


def test_importing_the_console_package_loads_no_web_framework() -> None:
    code = (
        "import sys, json\n"
        "import greenscreen.publisher.console\n"
        "banned = ('mcp', 'fastapi', 'starlette', 'uvicorn')\n"
        "print(json.dumps(sorted(m for m in sys.modules "
        "if m.split('.')[0] in banned)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []
