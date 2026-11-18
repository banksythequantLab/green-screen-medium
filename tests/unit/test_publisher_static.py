"""Static rules for ``greenscreen.publisher`` and the repository (task 10.3).

File reads only: ``ast``, ``re`` and ``Path.read_text``. No import of the package, no
subprocess, no git.

**Validates: Requirements 7.7, 7.10, 8.4, 15.6, 15.7, 17.1, 18.6, 22.11**
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "greenscreen" / "publisher"
RECOGNIZER_DIR = REPO_ROOT / "greenscreen" / "recognizer"

ENV_READERS = frozenset({"cli.py", "config.py"})
ENV_ATTRS = frozenset({"environ", "environb", "getenv", "getenvb", "putenv", "unsetenv"})
TRACEBACK_PRINT = frozenset({"print_exc", "print_exception", "print_tb", "print_stack", "print_last"})
CREDENTIAL_WORDS = ("PASSWORD", "PASSWD", "USERNAME", "SECRET", "TOKEN", "CREDENTIAL")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
SKIP_DIRS = frozenset({".git", ".hypothesis", ".venv", "venv", "node_modules", "__pycache__",
                       ".pytest_cache", "dist", "build"})
TEXT_SUFFIXES = frozenset({"", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
                           ".env", ".example", ".sh", ".ps1", ".bat", ".cmd"})


def _modules(directory: Path = PACKAGE_DIR) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _where(name: str, node: ast.AST) -> str:
    return f"{name}:{getattr(node, 'lineno', '?')}"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _string_constants(tree: ast.AST) -> list[ast.Constant]:
    skip = _docstring_nodes(tree)
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


# -- scanners (each returns "file:line: what") ---------------------------------


def environ_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ENV_ATTRS:
            out.append(f"{_where(name, node)}: .{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            out += [f"{_where(name, node)}: from os import {a.name}"
                    for a in node.names if a.name in ENV_ATTRS or a.name == "*"]
    return out


def credential_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out: list[str] = []
    for node in _string_constants(tree):
        text = node.value
        if "TK5_" in text:
            out.append(f"{_where(name, node)}: a TK5_ variable name")
        elif ENV_NAME.match(text) and any(w in text for w in CREDENTIAL_WORDS):
            out.append(f"{_where(name, node)}: a credential-looking variable name")
    return out


def _is_sys_stderr(value: ast.AST) -> bool:
    return (isinstance(value, ast.Attribute) and value.attr == "stderr"
            and isinstance(value.value, ast.Name) and value.value.id == "sys")


def output_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "print":
            if not any(kw.arg == "file" and _is_sys_stderr(kw.value) for kw in node.keywords):
                out.append(f"{_where(name, node)}: print( without file=sys.stderr")
        elif isinstance(func, ast.Attribute):
            if func.attr == "exception":
                out.append(f"{_where(name, node)}: .exception(")
            elif func.attr in TRACEBACK_PRINT or (
                isinstance(func.value, ast.Name) and func.value.id == "traceback"
                and func.attr.startswith("print")
            ):
                out.append(f"{_where(name, node)}: traceback.{func.attr}(")
        out += [f"{_where(name, kw.value)}: exc_info=" for kw in node.keywords if kw.arg == "exc_info"]
    return out


def cache_violations(tree: ast.AST, name: str = "<src>") -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            names += [ast.unparse(d) for d in node.decorator_list]
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, ast.alias):
            names.append(node.name)
        out += [f"{_where(name, node)}: {n}" for n in names if "cache" in n.lower()]
    return out


# -- package rules -------------------------------------------------------------


def test_package_modules_found():
    names = {p.name for p in _modules()}
    assert {"app.py", "calls.py", "cli.py", "config.py", "rest.py", "mcp_server.py"} <= names


@pytest.mark.parametrize("path", [p for p in _modules() if p.name not in ENV_READERS], ids=lambda p: p.name)
def test_environment_read_only_in_cli_and_config(path: Path):
    """Requirement 22.11 (and 7.10): ``os.environ`` is read only by cli.py and config.py."""
    assert environ_violations(_tree(path), path.name) == []


def test_config_py_does_not_touch_os_environ():
    # config.py takes a mapping; only cli.py hands it ``os.environ``.
    assert environ_violations(_tree(PACKAGE_DIR / "config.py"), "config.py") == []


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_credential_variable_named(path: Path):
    """Requirement 7.10: no TK5_USERNAME, TK5_PASSWORD or other credential variable."""
    assert credential_violations(_tree(path), path.name) == []


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_print_traceback_print_logger_exception_or_exc_info(path: Path):
    """Requirements 7.7, 8.4."""
    assert output_violations(_tree(path), path.name) == []


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_publisher_has_no_cache_of_screen_views_or_recognize(path: Path):
    """Requirement 17.1."""
    assert cache_violations(_tree(path), path.name) == []


def test_recognizer_is_unchanged_for_caching():
    """Requirement 17.1: no cache and no cache key in the recognizer package."""
    found: list[str] = []
    for path in _modules(RECOGNIZER_DIR):
        found += cache_violations(_tree(path), f"recognizer/{path.name}")
    assert found == []


def test_cancelled_only_in_calls_py_and_only_as_log_outcome():
    """Requirement 23 / 7.7: ``cancelled`` is a log-only outcome; no message, status or table."""
    elsewhere = [f"{p.name}: {_where(p.name, n)}" for p in _modules() if p.name != "calls.py"
                 for n in _string_constants(_tree(p)) if "cancelled" in n.value.lower()]
    elsewhere += [p.name for p in _modules()
                  if p.name != "calls.py" and re.search(r"\bcancelled\b", p.read_text(encoding="utf-8"), re.I)]
    assert elsewhere == []

    tree = _tree(PACKAGE_DIR / "calls.py")
    allowed: set[int] = set()
    for node in ast.walk(tree):
        # LOG_ONLY_OUTCOMES = frozenset({"cancelled"}) and ``rec.outcome = ... else "cancelled"``
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if (isinstance(t, ast.Name) and t.id == "LOG_ONLY_OUTCOMES") or (
                    isinstance(t, ast.Attribute) and t.attr == "outcome"
                ):
                    allowed.update(id(n) for n in ast.walk(node.value or node))
    stray = [_where("calls.py", n) for n in _string_constants(tree)
             if "cancelled" in n.value.lower() and id(n) not in allowed]
    assert stray == []


# -- repository rules ----------------------------------------------------------


def test_gitignore_does_not_hide_kiro():
    """Requirement 18.6."""
    lines = [ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    active = [ln for ln in lines if ln and not ln.startswith("#")]
    hiding = [ln for ln in active
              if not ln.startswith("!") and re.fullmatch(r"/?(\*\*/)?(\.kiro|\.\*|\*|\.kiro/.*|\.kiro\*?)/?", ln)]
    assert hiding == []
    assert not [ln for ln in active if ".kiro" in ln and not ln.startswith("!")]


_ASSIGN = re.compile(
    r"^\s*(?:export\s+|set\s+|\$env:)?(GS_API_KEY|GS_BIND_[A-Za-z0-9_]*)\s*[=:]\s*(\S.*)$"
)


def _repo_text_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts) or not path.is_file():
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue  # git-ignored private env files
        if path.suffix in TEXT_SUFFIXES or path.name == ".env.example":
            out.append(path)
    return out


def test_no_file_holds_a_nonempty_api_key_or_binding_value():
    """Requirements 15.7, 22 (names only): KEY=VALUE lines with a value are findings."""
    files = _repo_text_files()
    assert any(p.name == ".env.example" for p in files)
    hits: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            m = _ASSIGN.match(line)
            if m and not m.group(2).lstrip().startswith("#"):
                hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {m.group(1)}")
    assert hits == []


def test_env_example_has_names_only():
    """Requirement 15.7: empty values; ``GS_PUBLISH_FLOWS`` is empty or ``tk5-system-info``."""
    values: dict[str, str] = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, value = stripped.partition("=")
        assert sep == "=", f"not NAME=VALUE: {name}"
        values[name.strip()] = value.strip()
    assert "GS_API_KEY" in values and "GS_PUBLISH_FLOWS" in values
    assert not [n for n in values if n.startswith("GS_BIND_")]
    assert values["GS_PUBLISH_FLOWS"] in ("", "tk5-system-info")
    assert [n for n, v in values.items() if v != "" and n != "GS_PUBLISH_FLOWS"] == []


# -- the scanners themselves ---------------------------------------------------


@pytest.mark.parametrize(
    "scan, source",
    [
        (environ_violations, "import os\nx = os.environ['A']"),
        (environ_violations, "import os\nx = os.getenv('A')"),
        (environ_violations, "from os import environ"),
        (credential_violations, "x = 'TK5_PASSWORD'"),
        (credential_violations, "x = 'DB_PASSWORD'"),
        (output_violations, "print('x')"),
        (output_violations, "import traceback\ntraceback.print_exc()"),
        (output_violations, "log.exception('x')"),
        (output_violations, "log.error('x', exc_info=True)"),
        (cache_violations, "import functools\n@functools.lru_cache\ndef f(): pass"),
        (cache_violations, "view_cache = {}"),
    ],
)
def test_scanners_flag_violations(scan, source):
    assert scan(ast.parse(source))


@pytest.mark.parametrize(
    "source, flagged",
    [
        ("print(x)", True),
        ("import sys\nprint(x, file=sys.stdout)", True),
        ("print(x, file=stderr)", True),
        ("print(x, file=other.stderr)", True),
        ("import sys\nprint(x, file=sys.stderr)", False),
    ],
)
def test_print_allowed_only_with_file_sys_stderr(source, flagged):
    assert bool(output_violations(ast.parse(source))) is flagged


def test_scanners_accept_clean_source():
    src = "import logging\nlog = logging.getLogger('x')\nlog.info('ok')\nx = 'GS_API_KEY'\n"
    tree = ast.parse(src)
    for scan in (environ_violations, credential_violations, output_violations, cache_violations):
        assert scan(tree) == []
