"""Stale text stays corrected (polish spec, Requirement 16.8).

Messages name the file and the rule only.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / ".kiro" / "specs"
TESTS = ROOT / "tests"

# Built from two parts so that this file does not match itself.
STALE_LOG = "publishing 1 " + "of 3"
STALE_NAME = "test_exactly_" + "three_entries"
DIAGNOSTIC = "sigterm-diagnostic.txt"

FOLDERS = ("linux-readiness", "console", "ask")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def scan(folder: Path, needle: str, excluded_names: tuple[str, ...] = ()) -> list[Path]:
    """Files under folder (all levels) that hold needle, skipping excluded names."""
    return [
        p
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name not in excluded_names and needle in _read(p)
    ]


def _excluded(folder_name: str) -> tuple[str, ...]:
    return (DIAGNOSTIC,) if folder_name == "linux-readiness" else ()


def test_spec_folders_exist():
    for name in FOLDERS:
        assert (SPECS / name).is_dir(), f"{name}: spec folder missing"


def test_spec_folders_free_of_stale_log_line():
    for name in FOLDERS:
        stale = scan(SPECS / name, STALE_LOG, _excluded(name))
        assert not stale, f"{[str(p.relative_to(ROOT)) for p in stale]}: stale log line rule"


def test_diagnostic_record_is_kept():
    path = SPECS / "linux-readiness" / DIAGNOSTIC
    assert path.is_file(), f"{DIAGNOSTIC}: record missing"
    assert STALE_LOG in _read(path), f"{DIAGNOSTIC}: record must keep the old text"


def test_no_test_file_uses_old_test_name():
    stale = [
        p
        for p in sorted(TESTS.rglob("*"))
        if p.is_file() and p.suffix != ".pyc" and STALE_NAME in _read(p)
    ]
    assert not stale, f"{[str(p.relative_to(ROOT)) for p in stale]}: old test name rule"


def _docstring(path: Path) -> str:
    return ast.get_docstring(ast.parse(_read(path))) or ""


def test_bundled_test_renamed():
    path = TESTS / "unit" / "test_flow_bundled.py"
    tree = ast.parse(_read(path))
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "test_exactly_eight_entries_with_expected_keys" in names, f"{path.name}: rename rule"


def test_sync_docstring_names_system_info():
    path = TESTS / "unit" / "test_flow_sync.py"
    assert "tk5-system-info" in _docstring(path), f"{path.name}: docstring rule"


def test_bindings_docstring_says_eight():
    path = TESTS / "property" / "test_publisher_bindings.py"
    assert "eight bundled" in _docstring(path), f"{path.name}: docstring rule"


def test_scanner_is_not_vacuous(tmp_path):
    linux = tmp_path / "linux-readiness"
    other = tmp_path / "console"
    (linux / "sub").mkdir(parents=True)
    other.mkdir()
    (linux / "sub" / "stale.md").write_text(f"x {STALE_LOG} y", encoding="utf-8")
    (linux / DIAGNOSTIC).write_text(STALE_LOG, encoding="utf-8")
    (other / DIAGNOSTIC).write_text(STALE_LOG, encoding="utf-8")

    found = scan(linux, STALE_LOG, _excluded("linux-readiness"))
    assert [p.name for p in found] == ["stale.md"], "scanner: stale file or exclusion rule"

    found = scan(other, STALE_LOG, _excluded("console"))
    assert [p.name for p in found] == [DIAGNOSTIC], "scanner: exclusion applies to linux-readiness only"
