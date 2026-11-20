"""Checks of the Kiro hook files (polish Requirement 5)."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".kiro" / "hooks"
FLOWS = REPO / "greenscreen" / "flow" / "flows"

BUNDLED = sorted(p.name for p in FLOWS.glob("*.yaml"))
CAPTURE_SAMPLE = ["tk5-logon.ascii.txt", "tso-ready.readbuffer.txt", "x"]
NOT_MATCHED = [
    "greenscreen/recognizer/signatures/tso-ready.yaml",
    "greenscreen/flow/flows/__init__.py",
    "captures-notes.txt",
    "tests/unit/test_flow_bundled.py",
]
TRIGGERS = {"PostFileSave", "PostFileCreate"}


def _hook_files(folder: Path = HOOKS) -> list[Path]:
    return sorted(folder.glob("*.json"))


def _load_hooks(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError(f"hook file {path.name} does not parse: {exc}") from exc
    assert doc.get("version") == "v1", path.name
    hooks = doc.get("hooks")
    assert isinstance(hooks, list) and hooks, f"{path.name}: hooks empty"
    return hooks


def _all_hooks() -> list[tuple[str, dict]]:
    return [(p.name, h) for p in _hook_files() for h in _load_hooks(p)]


def _forms(rel: str) -> list[str]:
    root = r"D:\greenMachine"
    return [
        rel,
        rel.replace("/", "\\"),
        root.replace("\\", "/") + "/" + rel,
        root + "\\" + rel.replace("/", "\\"),
    ]


def _matches(pattern: str, text: str) -> bool:
    searched = re.search(pattern, text) is not None
    full = re.fullmatch(pattern, text) is not None
    assert searched == full, f"search and fullmatch differ for {text!r}"
    return searched


def _hooks_of(file_name: str) -> list[dict]:
    return _load_hooks(HOOKS / file_name)


def test_every_hook_file_parses_and_has_the_v1_shape():
    files = _hook_files()
    assert files
    for path in files:
        for hook in _load_hooks(path):
            where = path.name
            assert isinstance(hook.get("name"), str) and hook["name"].strip(), where
            assert isinstance(hook.get("description"), str) and hook["description"].strip(), where
            assert hook.get("trigger") in TRIGGERS, where
            re.compile(hook["matcher"])
            assert hook["action"]["type"] == "command", where
            assert isinstance(hook["action"]["command"], str), where
            timeout = hook["timeout"]
            assert isinstance(timeout, int) and not isinstance(timeout, bool), where
            assert 1 <= timeout <= 300, where
            assert hook.get("enabled") is True, where


def test_a_broken_hook_file_fails_and_names_the_file(tmp_path):
    broken = tmp_path / "broken-hook.json"
    broken.write_text('{"version": "v1", "hooks": [', encoding="utf-8")
    with pytest.raises(AssertionError, match="broken-hook.json"):
        _load_hooks(broken)


def test_the_two_hook_files_are_exactly_these():
    assert {p.name for p in _hook_files()} == {"flow-yaml-check.json", "captures-check.json"}
    assert [h["trigger"] for h in _hooks_of("flow-yaml-check.json")] == ["PostFileSave"]
    assert sorted(h["trigger"] for h in _hooks_of("captures-check.json")) == [
        "PostFileCreate",
        "PostFileSave",
    ]


def test_flow_hook_matcher_matches_the_bundled_flows_in_all_path_forms():
    assert len(BUNDLED) == 8
    (hook,) = _hooks_of("flow-yaml-check.json")
    pattern = hook["matcher"]
    for name in BUNDLED:
        for form in _forms(f"greenscreen/flow/flows/{name}"):
            assert _matches(pattern, form), form
    for rel in NOT_MATCHED:
        for form in _forms(rel):
            assert not _matches(pattern, form), form


def test_capture_hook_matcher_matches_capture_names_in_all_path_forms():
    hooks = _hooks_of("captures-check.json")
    for hook in hooks:
        pattern = hook["matcher"]
        for name in CAPTURE_SAMPLE:
            for form in _forms(f"captures/{name}"):
                assert _matches(pattern, form), form
        for rel in NOT_MATCHED:
            for form in _forms(rel):
                assert not _matches(pattern, form), form


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_commands_name_existing_paths_and_node_ids():
    fixed = {"python", "tests/hook_pytest.py", "-p", "no:cacheprovider"}
    checked = 0
    for name, hook in _all_hooks():
        for token in hook["action"]["command"].split():
            if token in fixed:
                continue
            path_part, _, func = token.partition("::")
            target = REPO / path_part
            assert target.is_file(), f"{name}: missing path {path_part}"
            if func:
                assert func in _functions(target), f"{name}: {path_part} has no {func}"
            checked += 1
    assert checked > 0


def test_commands_have_the_fixed_shape():
    for name, hook in _all_hooks():
        command = hook["action"]["command"]
        assert command.startswith("python tests/hook_pytest.py "), name
        assert command.endswith(" -p no:cacheprovider"), name
        assert "1>&2" not in command, name
        assert "-m pytest" not in command, name
        tokens = command.split()
        assert "-q" not in tokens and "-x" not in tokens, name
        assert "greenscreen.flow.check" not in command, name


def test_hook_files_hold_no_secret_names_or_hosts():
    for path in _hook_files():
        text = path.read_text(encoding="utf-8")
        assert "GS_" not in text, path.name
        assert "TK5_" not in text, path.name
        assert "http" not in text.lower(), path.name
        assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text), path.name


def test_hooks_are_documented_and_not_ignored():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for path in _hook_files():
        assert path.name in readme, f"README.md does not name {path.name}"
    for raw in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        stripped = line.strip("/")
        assert stripped not in {".kiro", ".kiro/hooks", "hooks", "*.json"}, line
        assert not line.startswith(".kiro"), line
