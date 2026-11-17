"""Static source rules for ``greenscreen/flow`` (task 10.20), checked with ``ast``.

Validates: Requirements 6.2, 7.7, 8.19, 10.7, 12.4, 16.3, 16.5, 16.6, 17.19.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "greenscreen" / "flow"

SCREEN_READ_ATTRS = frozenset({"text_grid", "fields", "find_field", "text"})
TIME_MODULES = frozenset({"datetime", "random"})
TIME_ATTRS = frozenset({"monotonic", "sleep"})
RUNNER_MODULES = frozenset({"subprocess", "socket"})
YAML_ALLOWED = frozenset({"safe_load", "safe_dump", "YAMLError"})
# "secret" is the schema's boolean Input flag, not a credential value.
CREDENTIAL_KEYS = ("password", "passwd", "pwd", "credential", "token")


def _modules() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def _where(path: Path, node: ast.AST) -> str:
    return f"{path.name}:{getattr(node, 'lineno', '?')}"


def _is_step_text(node: ast.AST) -> bool:
    """``step.text``: the TypeStep literal (a Flow definition field), not Field.text."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "text"
        and isinstance(node.value, ast.Name)
        and node.value.id == "step"
    )


def screen_read_violations(
    tree: ast.AST, name: str = "<src>", allow_step_text: bool = False
) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if allow_step_text and _is_step_text(node):
            continue
        if isinstance(node, ast.Attribute) and node.attr in SCREEN_READ_ATTRS:
            out.append(f"{name}:{node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in SCREEN_READ_ATTRS - {"text", "fields"}:
            out.append(f"{name}:{node.lineno}: {node.id}")
        elif isinstance(node, ast.ImportFrom):
            out.extend(
                f"{name}:{node.lineno}: import {a.name}"
                for a in node.names
                if a.name in SCREEN_READ_ATTRS
            )
    return out


def environ_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "environb"}:
            out.append(f"{name}:{node.lineno}: {node.attr}")
        elif isinstance(node, ast.Name) and node.id in {"environ", "getenv", "environb"}:
            out.append(f"{name}:{node.lineno}: {node.id}")
        elif isinstance(node, ast.ImportFrom):
            out.extend(
                f"{name}:{node.lineno}: import {a.name}"
                for a in node.names
                if a.name in {"environ", "getenv", "environb"}
            )
    return out


def yaml_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(
                f"{name}:{node.lineno}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "yaml" and a.name != "yaml"
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if (node.module or "").split(".")[0] == "yaml":
                out.extend(
                    f"{name}:{node.lineno}: from yaml import {a.name}"
                    for a in node.names
                    if a.name not in YAML_ALLOWED
                )
        elif isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "yaml"
                and node.attr not in YAML_ALLOWED
            ):
                out.append(f"{name}:{node.lineno}: yaml.{node.attr}")
    return out


def clock_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out = []
    for mod in sorted(_imported_modules(tree) & (TIME_MODULES | {"time"})):
        out.append(f"{name}: import {mod}")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "time":
            out.append(f"{name}:{node.lineno}: from time import")
        if isinstance(node, ast.Attribute) and (
            node.attr in TIME_ATTRS - {"sleep", "monotonic"}
            or (isinstance(node.value, ast.Name) and node.value.id in {"time", "datetime", "random"})
        ):
            out.append(f"{name}:{node.lineno}: {ast.unparse(node)}")
    return out


def runner_io_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out = [f"{name}: import {m}" for m in sorted(_imported_modules(tree) & RUNNER_MODULES)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if fname == "open":
                out.append(f"{name}:{node.lineno}: open(")
    return out


# --- the real package ---------------------------------------------------------


def test_package_modules_found():
    names = {p.name for p in _modules()}
    assert {"screens.py", "runner.py", "clock.py", "yamlio.py"} <= names


@pytest.mark.parametrize("fname", ["screens.py", "runner.py"])
def test_screen_modules_do_not_read_text_fields(fname: str):
    path = PACKAGE_DIR / fname
    # Only runner.py may read ``step.text`` (TypeStep literal); screens.py gets none.
    allow = fname == "runner.py"
    assert screen_read_violations(_tree(path), fname, allow_step_text=allow) == []


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_environment_access(path: Path):
    assert environ_violations(_tree(path), path.name) == []


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_yaml_entry_points_are_safe_only(path: Path):
    assert yaml_violations(_tree(path), path.name) == []


def test_yaml_is_used_through_safe_entry_points():
    used = set()
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "yaml"
            ):
                used.add(node.attr)
    assert {"safe_load", "safe_dump"} <= used
    assert used <= YAML_ALLOWED


@pytest.mark.parametrize(
    "path", [p for p in _modules() if p.name != "clock.py"], ids=lambda p: p.name
)
def test_time_and_randomness_only_in_clock(path: Path):
    assert clock_violations(_tree(path), path.name) == []


def test_runner_has_no_subprocess_socket_or_open():
    assert runner_io_violations(_tree(PACKAGE_DIR / "runner.py"), "runner.py") == []


def _shipped_yaml() -> list[Path]:
    roots = [REPO_ROOT / "greenscreen"]
    return sorted(p for r in roots for p in r.rglob("*.yaml"))


def _walk(value, keys: list[str], strings: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            keys.append(str(k))
            _walk(v, keys, strings)
    elif isinstance(value, list):
        for v in value:
            _walk(v, keys, strings)
    elif isinstance(value, str):
        strings.append(value)


def test_shipped_yaml_files_found():
    assert {p.name for p in _shipped_yaml()} >= {"tk5-logon.yaml", "tk5-logoff.yaml"}


@pytest.mark.parametrize("path", _shipped_yaml(), ids=lambda p: p.name)
def test_shipped_yaml_holds_no_credential(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    keys: list[str] = []
    strings: list[str] = []
    _walk(doc, keys, strings)
    bad_keys = [k for k in keys if any(w in k.lower() for w in CREDENTIAL_KEYS)]
    assert bad_keys == []
    secrets = [
        v for v in (os.environ.get("TK5_USERNAME"), os.environ.get("TK5_PASSWORD")) if v
    ]
    # Report only that a match exists, never the value.
    assert not any(s == v for s in strings for v in secrets), "credential value in YAML"


# --- scanner self-tests -----------------------------------------------------


@pytest.mark.parametrize(
    "scan, source",
    [
        (screen_read_violations, "x = screen.text_grid"),
        (screen_read_violations, "x = screen.fields"),
        (screen_read_violations, "x = screen.find_field(1, 2)"),
        (screen_read_violations, "x = field.text"),
        (environ_violations, "import os\nx = os.environ['A']"),
        (environ_violations, "import os\nx = os.getenv('A')"),
        (environ_violations, "from os import environ"),
        (yaml_violations, "import yaml\nyaml.load(t)"),
        (yaml_violations, "from yaml import load"),
        (clock_violations, "import time\nx = time.monotonic()"),
        (clock_violations, "import random"),
        (clock_violations, "from datetime import datetime"),
        (runner_io_violations, "import subprocess"),
        (runner_io_violations, "import socket"),
        (runner_io_violations, "f = open('x')"),
    ],
)
def test_scanners_flag_violations(scan, source: str):
    assert scan(ast.parse(source))


def test_runner_step_text_is_allowed():
    tree = ast.parse("literal = step.text")
    assert screen_read_violations(tree, allow_step_text=True) == []
    assert screen_read_violations(tree)  # screens.py has no allowance


@pytest.mark.parametrize(
    "source",
    [
        "x = field.text",
        "x = screen.fields",
        "x = x.text",
        "x = self.step.text",
        "x = steps.text",
        "x = screen.text_grid",
        "x = screen.find_field(1, 2)",
    ],
)
def test_runner_like_source_still_flags_other_reads(source: str):
    assert screen_read_violations(ast.parse(source), allow_step_text=True)


def test_scanners_accept_clean_source():
    tree = ast.parse("import yaml\nyaml.safe_load('a')\nx = self.clock.monotonic()")
    assert yaml_violations(tree) == []
    assert environ_violations(tree) == []
    assert runner_io_violations(tree) == []
    assert screen_read_violations(tree) == []
