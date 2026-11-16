"""Static source scan of ``greenscreen/recognizer`` (task 12.3).

Enforces, with ``ast``:

* Req 3.7: no code path may read ``Field.text`` or use the screen's raw
  ``text_grid`` / ``find_field`` / ``fields`` (everything goes through the
  hidden-field-blanking ``ScreenView``).
* Req 4.4 / 12.3: YAML only via ``yaml.safe_load`` / ``yaml.safe_dump``.
* Req 13.2: imports only from the standard library, ``yaml`` and ``greenscreen``.

Allow-lists are per file and name the exact base expression. ``m.text`` is the
``text`` dataclass field of the matcher classes (TextAtMatcher etc.), not
``Field.text``. ``view`` / ``self`` ``.fields`` is ``ScreenView.fields`` (a tuple
of ``FieldGeom`` geometry records that carry no text), not ``Screen.fields``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "greenscreen" / "recognizer"

ALWAYS_FORBIDDEN_ATTRS = frozenset({"text_grid", "find_field"})
ALLOWED_YAML_ATTRS = frozenset({"safe_load", "safe_dump", "YAMLError"})
ALLOWED_TOP_LEVEL = frozenset({"yaml", "greenscreen"})
# Attribute names guarded by the per-file allow-lists below.
GUARDED_ATTRS = frozenset({"text", "fields"})
# Calls that fetch an attribute by string, or import dynamically.
DYNAMIC_ATTR_CALLS = frozenset({"getattr", "hasattr", "setattr", "attrgetter"})
DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})

# {file name: {attribute: {allowed base expressions}}}. Narrow on purpose.
ALLOW = {
    "signature.py": {"text": {"m"}, "getattr": {"self"}},  # matcher field; dataclass copy
    "matching.py": {"text": {"m"}},  # matcher dataclass field
    "yamlio.py": {"getattr": {"m"}},  # getattr(matcher, <schema key>)
    "view.py": {"fields": {"self"}},  # ScreenView.fields
    "summary.py": {"fields": {"self", "view"}},  # RedactedSummary / ScreenView
    "suggest.py": {"fields": {"view"}},  # ScreenView.fields
}


def scan_source(source: str, filename: str = "<synthetic>") -> list[str]:
    """Return a list of violation descriptions found in ``source``."""
    tree = ast.parse(source, filename=filename)
    allow = ALLOW.get(Path(filename).name, {})
    out: list[str] = []

    def flag(node: ast.AST, msg: str) -> None:
        out.append(f"{filename}:{getattr(node, 'lineno', '?')}: {msg}")

    yaml_names: set[str] = set()  # local names bound to the yaml module

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top == "yaml":
                    if a.name != "yaml":
                        flag(node, f"import of yaml submodule {a.name}")
                    yaml_names.add(a.asname or "yaml")
                if not _import_ok(top):
                    flag(node, f"disallowed import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                top = (node.module or "").split(".")[0]
                if not _import_ok(top):
                    flag(node, f"disallowed import from {node.module}")
                if top == "yaml":
                    for a in node.names:
                        if a.name not in ALLOWED_YAML_ATTRS:
                            flag(node, f"from yaml import {a.name}")
            for a in node.names:
                if a.name in ALWAYS_FORBIDDEN_ATTRS:
                    flag(node, f"import of {a.name}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            base = ast.unparse(node.value)
            if node.attr in ALWAYS_FORBIDDEN_ATTRS:
                flag(node, f"access to .{node.attr}")
            elif node.attr in GUARDED_ATTRS:
                if base not in allow.get(node.attr, set()):
                    flag(node, f"access to {base}.{node.attr} (not allow-listed)")
            if (
                isinstance(node.value, ast.Name)
                and (node.value.id in yaml_names or node.value.id == "yaml")
                and node.attr not in ALLOWED_YAML_ATTRS
            ):
                flag(node, f"disallowed yaml.{node.attr}")
        elif isinstance(node, ast.Name) and node.id in ALWAYS_FORBIDDEN_ATTRS:
            flag(node, f"name {node.id}")
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None
            )
            if fname in DYNAMIC_IMPORT_CALLS:
                flag(node, f"dynamic import via {fname}")
            if fname in DYNAMIC_ATTR_CALLS and len(node.args) >= 2:
                target, arg = node.args[0], node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value in ALWAYS_FORBIDDEN_ATTRS | GUARDED_ATTRS:
                        flag(node, f"{fname} of '{arg.value}'")
                elif ast.unparse(target) not in allow.get("getattr", set()):
                    flag(node, f"{fname} with non-literal attribute name")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in ALWAYS_FORBIDDEN_ATTRS:
                flag(node, f"string literal '{node.value}'")

    return out


def _import_ok(top: str) -> bool:
    return top in sys.stdlib_module_names or top in ALLOWED_TOP_LEVEL


def _modules() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def test_package_modules_found():
    names = {p.name for p in _modules()}
    assert {"view.py", "matching.py", "yamlio.py", "signature.py"} <= names


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_recognizer_module_has_no_violations(path: Path):
    source = path.read_text(encoding="utf-8")
    violations = scan_source(source, str(path.relative_to(REPO_ROOT)))
    assert violations == [], "\n".join(violations)


# --- negative self-tests: the scanner must flag these -----------------------


@pytest.mark.parametrize(
    "source",
    [
        "x = screen.text_grid()",
        "f = screen.find_field(1, 2)",
        "import yaml\ndata = yaml.load(t)",
        "import yaml as y\ndata = y.unsafe_load(t)",
        "from yaml import load",
        "import requests",
        "from requests import get",
        "import numpy.linalg",
        "x = field.text",
        "x = screen.fields",
        "x = getattr(screen, 'text_grid')",
        "x = getattr(field, 'text')",
        "x = getattr(field, name)",
        "m = __import__('requests')",
        "import importlib\nm = importlib.import_module('requests')",
        "text_grid = 1",
    ],
)
def test_scanner_flags_violations(source: str):
    assert scan_source(source), source


@pytest.mark.parametrize(
    "source",
    [
        "import yaml\nyaml.safe_load('a')\nyaml.safe_dump({})\nexcept_ = yaml.YAMLError",
        "import os, logging\nfrom collections.abc import Callable",
        "from greenscreen.connector.models import Screen\nfrom . import x",
        "from __future__ import annotations",
    ],
)
def test_scanner_accepts_clean_source(source: str):
    assert scan_source(source) == []


def test_allow_list_is_per_file():
    assert scan_source("x = m.text", "matching.py") == []
    assert scan_source("x = m.text", "yamlio.py")
    assert scan_source("x = view.fields", "suggest.py") == []
    assert scan_source("x = view.fields", "matching.py")
    assert scan_source("x = screen.fields", "summary.py")
