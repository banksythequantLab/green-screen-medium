"""Tests that keep README.md true (polish Requirement 2).

Every list is derived from the code or the repository, not typed in here.
Messages name the rule and the line number, never a matched value.
"""
from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest

from greenscreen.flow.model import Flow
from greenscreen.recognizer import load_bundled_signatures
from tests.unit.test_publisher_static import _ASSIGN as PUBLISHER_ASSIGN

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
GS_NAME = re.compile(r"GS_[A-Z0-9]+(?:_[A-Z0-9]+)*")
GS_WORD = re.compile(r"GS_[A-Za-z0-9_]*")
FORBIDDEN_WORDS = ("recorder", "5250", "as/400", "web terminal", "write flow", "flows that write")
FORBIDDEN_PHRASES = ("early build", "will land here")
NOT_BUILT = "Not built yet"
CHECK_HEADING = "Check a Flow file"
CHECK_COMMAND = "python -m greenscreen.flow.check"
SECRET_ASSIGN = re.compile(
    r"^\s*(?:export\s+|set\s+|\$env:)?(?:GS_API_KEY|GS_LLM_API_KEY|GS_BIND_[A-Za-z0-9_]*|TK5_[A-Za-z0-9_]*)"
    r"\s*[=:]\s*\S"
)
IPV4 = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")
LONG_TOKEN = re.compile(r"(?<![\w/.\\:-])[A-Za-z0-9_-]{24,}(?![\w/.\\-])")
PLACEHOLDER = re.compile(r"<([^<>\n]+)>")
PLACEHOLDER_OK = re.compile(r"YOUR_API_KEY|[A-Za-z][A-Za-z0-9 .\-]*")
URL = re.compile(r"https?://\S+")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# ---------------------------------------------------------------- derived facts


def code_gs_names() -> set[str]:
    """GS_* string constants of every module under greenscreen/ (AST scan)."""
    found: set[str] = set()
    for path in sorted((REPO / "greenscreen").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if GS_NAME.fullmatch(node.value):
                    found.add(node.value)
    return found


def env_example_names() -> set[str]:
    names: set[str] = set()
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*#?\s*(GS_[A-Z0-9_]+)\s*=", line)
        if m:
            names.add(m.group(1))
    return names


def bundled_flow_names() -> set[str]:
    return {p.stem for p in (REPO / "greenscreen" / "flow" / "flows").glob("*.yaml")}


def spec_dirs() -> set[str]:
    return {p.name for p in (REPO / ".kiro" / "specs").iterdir() if p.is_dir()}


def hook_files() -> set[str]:
    return {p.name for p in (REPO / ".kiro" / "hooks").glob("*.json")}


# ---------------------------------------------------------------- text helpers


def section(text: str, heading: str) -> str:
    """Body of the section with this exact heading, up to the next heading of the same or higher level."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.fullmatch(r"(#{1,6}) (.+?)\s*", line)
        if m and m.group(2) == heading:
            level = len(m.group(1))
            body: list[str] = []
            for nxt in lines[i + 1:]:
                n = re.match(r"(#{1,6}) ", nxt)
                if n and len(n.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body)
    return ""


def table_first_column(body: str) -> set[str]:
    out: set[str] = set()
    for line in body.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if m:
            out.add(m.group(1))
    return out


# ---------------------------------------------------------------- scanners


def forbidden_claim_findings(text: str) -> list[str]:
    """Rule `forbidden-claim` with line numbers; the allowed place is the section 'Not built yet'."""
    out: list[str] = []
    in_allowed = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_allowed = line[3:].strip() == NOT_BUILT
        lower = line.lower()
        if any(p in lower for p in FORBIDDEN_PHRASES):
            out.append(f"forbidden-phrase:{number}")
        if not in_allowed and any(w in lower for w in FORBIDDEN_WORDS):
            out.append(f"forbidden-claim-outside-{NOT_BUILT.replace(' ', '-')}:{number}")
    return out


def secret_findings(text: str, known_gs: frozenset[str] = frozenset()) -> list[str]:
    out: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if SECRET_ASSIGN.match(line):
            out.append(f"assignment-line:{number}")
        for m in IPV4.finditer(line):
            if m.group(0) != "127.0.0.1":
                out.append(f"ipv4-address:{number}")
        bare = URL.sub(" ", line)
        for m in LONG_TOKEN.finditer(bare):
            token = m.group(0)
            if token in known_gs or token.startswith("GS_BIND_"):
                continue
            out.append(f"long-token:{number}")
        for m in PLACEHOLDER.finditer(bare):
            if not PLACEHOLDER_OK.fullmatch(m.group(1)):
                out.append(f"placeholder:{number}")
    return out


def documentation_problems(text: str) -> list[str]:
    """Requirement 2, criterion 11, on a README text."""
    out: list[str] = []
    if CHECK_COMMAND not in text:
        out.append("check-command-text-missing")
    body = section(text, CHECK_HEADING)
    if not body:
        out.append("check-section-missing")
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^\|\s*(\d)\s*\|\s*(\S[^|]*?)\s*\|", body, re.M)
    }
    for code in "012345":
        if not rows.get(code):
            out.append(f"exit-code-{code}-not-documented")
    return out


# ---------------------------------------------------------------- README tests


def test_every_gs_variable_of_the_code_is_in_the_readme():
    text = _readme()
    in_code = code_gs_names()
    assert len(in_code) >= 25, "AST scan found too few GS_ names"
    missing = sorted(n for n in in_code if not re.search(rf"\b{n}\b", text))
    assert missing == [], f"README does not mention: {missing}"
    env_names = env_example_names()
    assert env_names, ".env.example holds no GS_ names"
    missing_env = sorted(n for n in env_names if not re.search(rf"\b{n}\b", text))
    assert missing_env == [], f"README does not mention (.env.example): {missing_env}"


def test_the_readme_names_no_unknown_gs_variable():
    known = code_gs_names() | env_example_names()
    unknown: list[str] = []
    for word in sorted(set(GS_WORD.findall(_readme()))):
        if word in known or word.startswith("GS_BIND_"):
            continue
        unknown.append(word)
    assert unknown == [], f"README mentions unknown GS_ names: {unknown}"


def test_tool_list_is_the_bundled_flows_minus_logon_and_logoff():
    listed = table_first_column(section(_readme(), "Published tools"))
    assert listed == bundled_flow_names() - {"tk5-logon", "tk5-logoff"}
    assert len(listed) == 6


def test_spec_list_is_the_spec_directories():
    text = _readme()
    listed = table_first_column(section(text, "How Kiro built it")) & spec_dirs()
    assert listed == spec_dirs()
    assert len(spec_dirs()) == 10
    for path in re.findall(r"\.kiro/specs/([A-Za-z0-9_-]+)", text):
        assert path in spec_dirs(), f"README names a spec path that does not exist: {path}"
    spec_rows = {r for r in table_first_column(section(text, "How Kiro built it")) if "/" not in r and "." not in r}
    assert spec_rows == spec_dirs()


def test_every_hook_file_is_documented_and_exists():
    text = _readme()
    files = hook_files()
    assert files == {"flow-yaml-check.json", "captures-check.json"}
    for name in sorted(files):
        assert name in text, f"README does not name {name}"
    for rel in re.findall(r"\.kiro/hooks/([A-Za-z0-9_.-]+)", text):
        assert (REPO / ".kiro" / "hooks" / rel).is_file(), f"README names a hook path that does not exist: {rel}"


def test_the_check_command_is_documented():
    assert documentation_problems(_readme()) == []
    check = REPO / "greenscreen" / "flow" / "check.py"
    assert check.is_file()
    tree = ast.parse(check.read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body)


def test_forbidden_claims_only_in_not_built_yet():
    assert forbidden_claim_findings(_readme()) == []
    body = section(_readme(), NOT_BUILT)
    assert "recorder" in body.lower() and "5250" in body and "AS/400" in body


def test_no_secret_looking_values():
    known = frozenset(code_gs_names() | env_example_names())
    assert secret_findings(_readme(), known) == []


def test_script_and_extra_exist_and_links_resolve():
    text = _readme()
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if "greenscreen-publish" in text:
        assert "greenscreen-publish" in project["scripts"]
    if "[publish]" in text:
        assert "publish" in project["optional-dependencies"]
    links = re.findall(r"\]\(([^)\s]+)\)", text)
    assert links, "README has no link to check"
    for target in links:
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        assert (REPO / target.split("#")[0]).exists(), f"link target does not exist: {target}"


def test_yaml_and_json_blocks_parse():
    text = _readme()
    signatures = list(load_bundled_signatures())
    yaml_blocks = [b for b in re.findall(r"```yaml\n(.*?)```", text, re.S) if b.lstrip().startswith("version:")]
    json_blocks = re.findall(r"```json\n(.*?)```", text, re.S)
    assert yaml_blocks and json_blocks
    for block in yaml_blocks:
        Flow.from_yaml(block, signatures)
    for block in json_blocks:
        json.loads(block)


def test_static_secret_scan_is_green_with_the_readme():
    hits = []
    for number, line in enumerate(_readme().splitlines(), 1):
        m = PUBLISHER_ASSIGN.match(line)
        if m and not m.group(2).lstrip().startswith("#"):
            hits.append(f"assignment-line:{number}")
    assert hits == []


# ---------------------------------------------------------------- scanner self-tests

CLEAN = f"""# T

## What it is

Fine text.

## {NOT_BUILT}

- A Flow recorder.
- 5250 (AS/400) support.
- Flows that write to the host.
"""


def test_self_clean_text_is_not_flagged():
    assert forbidden_claim_findings(CLEAN) == []
    assert secret_findings(CLEAN) == []


def test_self_recorder_claim_outside_the_section_is_flagged():
    text = CLEAN.replace("Fine text.", "A recorder builds Flows.")
    findings = forbidden_claim_findings(text)
    assert findings == ["forbidden-claim-outside-Not-built-yet:5"]


def test_self_early_build_phrase_is_flagged_anywhere():
    text = CLEAN + "\nEarly build.\n"
    assert any(f.startswith("forbidden-phrase:") for f in forbidden_claim_findings(text))


def test_self_assignment_line_is_flagged():
    for line in ("GS_API_KEY=abc", "export GS_LLM_API_KEY=abc", "$env:GS_BIND_X__Y = abc", "TK5_USERNAME: abc"):
        assert secret_findings(CLEAN + "\n" + line + "\n") == ["assignment-line:13"], line
    assert secret_findings(CLEAN + '\nSet-Item -Path Env:GS_API_KEY -Value (Read-Host "k")\n') == []


def test_self_ipv4_address_is_flagged_but_loopback_is_not():
    assert secret_findings(CLEAN + "\nhost 10.1.2.3 here\n") == ["ipv4-address:13"]
    assert secret_findings(CLEAN + "\nhost 127.0.0.1 here\n") == []


def test_self_long_token_and_bad_placeholder_are_flagged():
    assert secret_findings(CLEAN + "\nkey abcdefghijklmnopqrstuvwxyz0123\n") == ["long-token:13"]
    assert secret_findings(CLEAN + "\nsee https://example.org/abcdefghijklmnopqrstuvwxyz0123\n") == []
    assert secret_findings(CLEAN + "\nvalue <abc=1>\n") == ["placeholder:13"]
    assert secret_findings(CLEAN + "\nkey <YOUR_API_KEY> and <mainframe host>\n") == []


def test_self_readme_without_the_check_command_fails_the_documentation_test():
    text = _readme().replace(CHECK_COMMAND, "python -m something.else")
    assert "check-command-text-missing" in documentation_problems(text)
    no_table = _readme().replace("| 3 |", "| x |")
    assert "exit-code-3-not-documented" in documentation_problems(no_table)
    assert documentation_problems("# T\n") != []


@pytest.mark.parametrize("name", ["GS_BIND_", "GS_X_"])
def test_self_names_with_a_trailing_underscore_are_not_variables(name):
    assert GS_NAME.fullmatch(name) is None
