"""Consistency checks between the flow-runtime and tn3270-connector specs and the code.

Task 17.1 of ``.kiro/specs/flow-runtime/tasks.md``. The module reads files as
text (and parses source with ``ast``); it uses no network and no subprocess.
Each failure names the file and the missing item.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLOW_REQ = ROOT / ".kiro" / "specs" / "flow-runtime" / "requirements.md"
FLOW_DESIGN = ROOT / ".kiro" / "specs" / "flow-runtime" / "design.md"
CONN_REQ = ROOT / ".kiro" / "specs" / "tn3270-connector" / "requirements.md"
CONN_DESIGN = ROOT / ".kiro" / "specs" / "tn3270-connector" / "design.md"
RUNNER = ROOT / "greenscreen" / "flow" / "runner.py"
SCREENS = ROOT / "greenscreen" / "flow" / "screens.py"
CONNECTOR = ROOT / "greenscreen" / "connector" / "connector.py"
UNIT = ROOT / "tests" / "unit"


def _read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)}: file is missing"
    return path.read_text(encoding="utf-8")


def _criterion(path: Path, requirement: int, number: int) -> str:
    """Text of acceptance criterion ``number`` of ``### Requirement N:``."""
    text = _read(path)
    start = re.search(rf"^### Requirement {requirement}:", text, re.M)
    assert start, f"{path.relative_to(ROOT)}: no heading for Requirement {requirement}"
    rest = text[start.end() :]
    end = re.search(r"^### Requirement \d+:", rest, re.M)
    section = rest[: end.start()] if end else rest
    found = re.search(rf"^{number}\. (.*)$", section, re.M)
    assert found, (
        f"{path.relative_to(ROOT)}: Requirement {requirement} has no criterion {number}"
    )
    return found.group(1)


def _mentions(design: str, requirement: int, criterion: int) -> bool:
    """True when the design cites ``requirement.criterion``, alone or inside a range."""
    if re.search(rf"\b{requirement}\.{criterion}\b", design):
        return True
    for m in re.finditer(rf"\b{requirement}\.(\d+) to (?:{requirement}\.)?(\d+)\b", design):
        if int(m.group(1)) <= criterion <= int(m.group(2)):
            return True
    return False


def _code_only(path: Path) -> str:
    """Source with comments and docstrings removed (names and strings of real code stay)."""
    tree = ast.parse(_read(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body[0].value.value = ""
    return ast.unparse(tree)


# --- Requirement 10.1 -------------------------------------------------------------


def test_requirement_10_1_names_containing_field_and_code_uses_it() -> None:
    crit = _criterion(FLOW_REQ, 10, 1)
    assert "Type_Step" in crit, (
        f"{FLOW_REQ.relative_to(ROOT)}: Requirement 10.1 does not mention the Type_Step"
    )
    assert "`ScreenView.containing_field`" in crit, (
        f"{FLOW_REQ.relative_to(ROOT)}: Requirement 10.1 lacks `ScreenView.containing_field`"
    )
    assert "Current_Screen cursor" in crit, (
        f"{FLOW_REQ.relative_to(ROOT)}: Requirement 10.1 lacks 'Current_Screen cursor'"
    )
    assert ".containing_field(" in _read(RUNNER), (
        f"{RUNNER.relative_to(ROOT)}: no call to containing_field"
    )


def test_runner_and_screens_hold_no_find_field() -> None:
    for path in (RUNNER, SCREENS):
        assert "find_field" not in _code_only(path), (
            f"{path.relative_to(ROOT)}: code refers to find_field "
            "(comments and docstrings were ignored)"
        )


# --- Requirement 13.3 `definition` ------------------------------------------------


def test_requirement_13_3_lists_definition_error_among_skip_reasons() -> None:
    crit = _criterion(FLOW_REQ, 13, 3)
    assert "FlowDefinitionError is raised during the run" in crit, (
        f"{FLOW_REQ.relative_to(ROOT)}: Requirement 13.3 does not list a "
        "FlowDefinitionError during the run among the skip reasons"
    )
    assert "skip all Finally_Steps" in crit, (
        f"{FLOW_REQ.relative_to(ROOT)}: Requirement 13.3 does not skip all Finally_Steps"
    )


def test_design_says_definition_skips_finally_steps() -> None:
    design = _read(FLOW_DESIGN)
    assert re.search(r"`definition`[^\n]*skipped \(Requirement 13\.3\)", design), (
        f"{FLOW_DESIGN.relative_to(ROOT)}: failure table row for `definition` "
        "lacks 'skipped (Requirement 13.3)'"
    )
    assert re.search(r"_FINALLY_SKIP_REASONS`? in the runner holds `definition`", design), (
        f"{FLOW_DESIGN.relative_to(ROOT)}: no statement that _FINALLY_SKIP_REASONS holds `definition`"
    )


def test_runner_skips_finally_after_definition_error() -> None:
    src = _read(RUNNER)
    m = re.search(r"_FINALLY_SKIP_REASONS\s*=\s*frozenset\((.*?)\n\)", src, re.S)
    assert m, f"{RUNNER.relative_to(ROOT)}: _FINALLY_SKIP_REASONS is missing"
    assert '"definition"' in m.group(1), (
        f"{RUNNER.relative_to(ROOT)}: _FINALLY_SKIP_REASONS lacks \"definition\""
    )
    assert re.search(r'final\.reason == "definition"[\s\S]{0,200}raise FlowDefinitionError', src), (
        f"{RUNNER.relative_to(ROOT)}: no raise of FlowDefinitionError for reason \"definition\""
    )


# --- tn3270-connector 7.8 and Requirement 12 criteria 34 to 37 --------------------


def test_connector_7_8_states_received_record_without_data_lines() -> None:
    crit = _criterion(CONN_REQ, 7, 8)
    assert "response received" in crit and "Requirement 12" in crit, (
        f"{CONN_REQ.relative_to(ROOT)}: Requirement 7.8 does not say the received "
        "record has the format of Requirement 12"
    )
    assert "carries no response data lines" in crit, (
        f"{CONN_REQ.relative_to(ROOT)}: Requirement 7.8 does not say the received "
        "record carries no response data lines"
    )


def test_connector_requirement_12_forbids_response_text_in_exception_messages() -> None:
    for number in (34, 35, 36, 37):
        crit = _criterion(CONN_REQ, 12, number)
        assert "exception" in crit or "ParseError" in crit, (
            f"{CONN_REQ.relative_to(ROOT)}: Requirement 12.{number} does not concern "
            "exceptions"
        )
    assert "SHALL NOT include any data line" in _criterion(CONN_REQ, 12, 34), (
        f"{CONN_REQ.relative_to(ROOT)}: Requirement 12.34 does not forbid response "
        "text in exception messages"
    )
    assert "no data line" in _criterion(CONN_REQ, 12, 37), (
        f"{CONN_REQ.relative_to(ROOT)}: Requirement 12.37 does not keep data lines "
        "out of str(), repr() and args"
    )

def test_connector_puts_no_data_lines_join_in_a_message() -> None:
    tree = ast.parse(_read(CONNECTOR))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            for sub in ast.walk(node.exc):
                if isinstance(sub, ast.Attribute) and sub.attr == "data_lines":
                    offenders.append(node.lineno)
    assert not offenders, (
        f"{CONNECTOR.relative_to(ROOT)}: raise at line(s) {offenders} uses data_lines "
        "in an exception"
    )


# --- Requirements 13.10 to 13.14 and 14.9 to 14.11 --------------------------------


def test_design_covers_requirements_13_10_to_14_11() -> None:
    design = _read(FLOW_DESIGN)
    missing = [
        f"{r}.{c}"
        for r, cs in ((13, range(10, 15)), (14, range(9, 12)))
        for c in cs
        if not _mentions(design, r, c)
    ]
    assert not missing, f"{FLOW_DESIGN.relative_to(ROOT)}: no mention of Requirement(s) {missing}"


def test_requirements_exist_in_requirements_document() -> None:
    for r, cs in ((13, range(10, 15)), (14, range(9, 12))):
        for c in cs:
            assert _criterion(FLOW_REQ, r, c), f"{FLOW_REQ.relative_to(ROOT)}: empty {r}.{c}"


def test_test_files_for_tasks_16_1_16_2_16_4_exist() -> None:
    for name in (
        "test_flow_runner_fixes_skipped.py",
        "test_flow_runner_fixes_session_error.py",
        "test_flow_runner_fixes_extract_mismatch.py",
    ):
        path = UNIT / name
        assert "def test_" in _read(path), f"{path.relative_to(ROOT)}: holds no test function"


def test_connector_documents_are_readable() -> None:
    assert _read(CONN_DESIGN).strip(), f"{CONN_DESIGN.relative_to(ROOT)}: file is empty"
