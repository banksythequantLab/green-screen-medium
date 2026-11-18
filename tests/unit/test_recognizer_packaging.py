"""Packaging checks for the screen recognizer (Requirements 8.12, 12.4, 12.8)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]

BUNDLED = [
    "ispf-primary-menu.yaml",
    "tk5-logo.yaml",
    "tk5-logon.yaml",
    "tso-input-not-recognized.yaml",
    "tso-password-prompt.yaml",
    "tso-pause.yaml",
    "tso-ready.yaml",
    "tso-reconnect-ok.yaml",
    "tso-reconnect-password-prompt.yaml",
    "tso-userid-in-use.yaml",
]


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_runtime_dependencies_exact() -> None:
    assert _pyproject()["project"]["dependencies"] == ["pyyaml>=6.0.3"]


def test_dev_extra_unchanged() -> None:
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    # The extra `greenscreen-connector[publish]` entry is allowed by publisher Requirement 18.3.
    assert dev == [
        "greenscreen-connector[publish]",
        "hypothesis>=6.170.15",
        "pytest>=8.0",
        "pyyaml>=6.0.3",
        "setuptools>=70.1",
    ]


def test_package_data_entries() -> None:
    pkg_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert pkg_data["greenscreen.recognizer.signatures"] == ["*.yaml"]
    assert pkg_data["greenscreen.connector.testing"] == ["fixtures/*.yaml"]


def test_ten_bundled_yaml_files_exist() -> None:
    sig_dir = ROOT / "greenscreen" / "recognizer" / "signatures"
    for name in BUNDLED:
        assert (sig_dir / name).is_file(), name
    assert len(BUNDLED) == 10
