"""Packaging tests for the bundled Flow YAML files (task 10.18).

This is the only flow test that starts a subprocess. The wheel is built in a
temporary copy of the repository so that nothing is left behind in the repo.

Requirements: 21.2, 21.5, 21.6
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

EXPECTED_YAML = {
    "greenscreen/flow/flows/tk5-logoff.yaml",
    "greenscreen/flow/flows/tk5-logon.yaml",
    "greenscreen/flow/flows/tk5-system-info.yaml",
}

EXPECTED_DEPENDENCIES = ["pyyaml>=6.0.3"]
EXPECTED_OPTIONAL = {
    "publish": ["mcp>=2.3,<3", "fastapi>=0.163,<1"],
    "dev": [
        "greenscreen-connector[publish]",
        "hypothesis>=6.170.15",
        "pytest>=8.0",
        "pyyaml>=6.0.3",
    ],
}

_IGNORE = shutil.ignore_patterns(
    ".git",
    ".hypothesis",
    ".pytest_cache",
    ".kiro",
    "__pycache__",
    "build",
    "dist",
    "*.egg-info",
    "*.pyc",
)


def _pyproject() -> dict:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_declares_flow_package_data() -> None:
    data = _pyproject()
    package_data = data["tool"]["setuptools"]["package-data"]
    assert package_data["greenscreen.flow.flows"] == ["*.yaml"]


def test_pyproject_dependencies_are_unchanged() -> None:
    # The `publish` extra and the dev entry for it are allowed by publisher Requirement 18.3.
    project = _pyproject()["project"]
    assert project["dependencies"] == EXPECTED_DEPENDENCIES
    assert project["optional-dependencies"] == EXPECTED_OPTIONAL


def test_wheel_contains_exactly_the_three_flow_yaml_files() -> None:
    import os

    with tempfile.TemporaryDirectory(prefix="gs-wheel-") as tmp:
        work = Path(tmp) / "repo"
        out = Path(tmp) / "out"
        out.mkdir()
        shutil.copytree(REPO, work, ignore=_IGNORE)

        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("TK5_")
        }
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

        found = {n for n in names if n.startswith("greenscreen/flow/flows/") and n.endswith(".yaml")}
        missing = sorted(EXPECTED_YAML - names)
        assert not missing, f"wheel is missing: {', '.join(missing)}"
        assert found == EXPECTED_YAML, f"unexpected YAML files in wheel: {sorted(found - EXPECTED_YAML)}"
