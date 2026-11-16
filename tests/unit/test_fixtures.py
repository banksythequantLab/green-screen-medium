"""Unit tests for fixture loading (Task 10.4).

Validates: Requirements 8.3, 8.4
"""
from __future__ import annotations

import importlib.resources
import os
import tomllib
from pathlib import Path

import pytest

from greenscreen.connector.testing.fixtures import (
    FixtureFrame,
    load_bundled_fixture,
    load_fixture,
)

NAMES = ["tk5-logo", "tk5-logon"]
REPO = Path(__file__).parents[2]


def _fixture_path(name: str) -> Path:
    pkg = importlib.resources.files("greenscreen.connector.testing.fixtures")
    return Path(str(pkg / f"{name}.yaml"))


@pytest.mark.parametrize("name", NAMES)
def test_load_fixture_by_path(name):
    frames = load_fixture(str(_fixture_path(name)))
    assert frames
    for f in frames:
        assert isinstance(f, FixtureFrame)
        assert len(f.data_lines) == 24
        assert f.status_line
        assert f.result == "ok"


@pytest.mark.parametrize("name", NAMES)
def test_bundled_fixture_independent_of_cwd(name, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    frames = load_bundled_fixture(name)
    assert frames and len(frames[0].data_lines) == 24


def test_pyproject_declares_package_data():
    with open(REPO / "pyproject.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    patterns = cfg["tool"]["setuptools"]["package-data"]["greenscreen.connector.testing"]
    assert "fixtures/*.yaml" in patterns


@pytest.mark.parametrize("name", NAMES)
def test_yaml_files_inside_package(name):
    import greenscreen.connector.testing as testing_pkg

    pkg_dir = Path(testing_pkg.__file__).parent
    assert (pkg_dir / "fixtures" / f"{name}.yaml").is_file()
    assert _fixture_path(name).is_file()


@pytest.mark.parametrize("name", NAMES)
def test_fixture_data_matches_captures(name):
    capture = REPO / "captures" / f"{name}.readbuffer.txt"
    if not capture.is_file():
        pytest.skip("captures/ not available")
    capture_lines = set(capture.read_text(encoding="utf-8").splitlines())
    for frame in load_bundled_fixture(name):
        for line in frame.data_lines:
            assert f"data: {line}" in capture_lines


def test_load_fixture_not_a_list(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("key: value\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(str(p))


def test_load_fixture_missing_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- data_lines: ['00']\n  result: ok\n", encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        load_fixture(str(p))


@pytest.mark.parametrize("name", NAMES)
def test_no_secrets_in_fixtures(name):
    text = _fixture_path(name).read_text(encoding="utf-8")
    assert "ENTER CURRENT PASSWORD" not in text
    frames = load_bundled_fixture(name)
    for f in frames:
        assert not any("ENTER CURRENT PASSWORD" in ln for ln in f.data_lines)
    secrets = [os.environ.get(k) for k in ("TK5_USERNAME", "TK5_PASSWORD")]
    secrets = [s for s in secrets if s]
    if not secrets:
        pytest.skip("TK5_USERNAME/TK5_PASSWORD not set")
    for s in secrets:
        assert s not in text
