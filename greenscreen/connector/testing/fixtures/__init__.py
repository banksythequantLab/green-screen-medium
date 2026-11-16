"""Fixture loader for tn3270-connector unit tests (Task 9.2).

Requirements: 8.3, 8.4
"""
from __future__ import annotations

import importlib.resources
import pathlib
from dataclasses import dataclass

import yaml


@dataclass
class FixtureFrame:
    """One recorded s3270 response (data lines + status line + result token)."""
    data_lines: list[str]
    status_line: str
    result: str   # "ok" or "error"


def load_fixture(path: str) -> list[FixtureFrame]:
    """Load a YAML fixture file and return frames in file order.

    Each frame must have exactly: data_lines (list[str]), status_line (str),
    result ("ok" or "error").
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, list):
        raise ValueError(f"Fixture file {path!r} must contain a YAML list")
    frames = []
    for i, item in enumerate(raw):
        frames.append(FixtureFrame(
            data_lines  = item["data_lines"],
            status_line = item["status_line"],
            result      = item["result"],
        ))
    return frames


def load_bundled_fixture(name: str) -> list[FixtureFrame]:
    """Load a fixture by short name from the installed package.

    name: 'tk5-logo' or 'tk5-logon'
    Works both from source tree and from an installed wheel via importlib.resources.
    """
    pkg = importlib.resources.files("greenscreen.connector.testing.fixtures")
    data = (pkg / f"{name}.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(data)
    return [
        FixtureFrame(
            data_lines  = item["data_lines"],
            status_line = item["status_line"],
            result      = item["result"],
        )
        for item in raw
    ]
