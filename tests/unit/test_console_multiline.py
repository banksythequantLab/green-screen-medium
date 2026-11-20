"""Multi-line output values in the console (spec polish, task 8.1, Requirement 11).

CSS and script text checks, plus `outputClass` run under Node when it is on PATH.
"""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from tests.console_node import NODE, needs_node
from tests.console_support import ASSET_DIR
from tests.unit.test_console_css import _rule_declarations, _strip_comments

CSS_TEXT = _strip_comments((ASSET_DIR / "console.css").read_text(encoding="utf-8"))
CONSOLE_JS = (ASSET_DIR / "console.js").read_text(encoding="utf-8")


def _rem(value: str) -> float:
    match = re.fullmatch(r"([0-9.]+)rem", value)
    assert match, "not a rem value"
    return float(match.group(1))


def test_single_value_rule_is_unchanged():
    rule = _rule_declarations(CSS_TEXT, ".outputs dd")
    assert rule.get("font-size") == "2rem"
    assert rule.get("max-height") == "24rem"


def test_multiline_rule_fits_twenty_lines_in_the_box():
    base = _rule_declarations(CSS_TEXT, ".outputs dd")
    rule = _rule_declarations(CSS_TEXT, ".outputs dd.multiline")
    assert rule, "no .outputs dd.multiline rule"
    size = _rem(rule["font-size"])
    assert 0.8 <= size <= 1
    line_height = float(rule["line-height"])
    assert 24 / (size * line_height) >= 20
    assert _rem(base["max-height"]) == 24


def test_multiline_rule_adds_nothing_forbidden():
    rule = _rule_declarations(CSS_TEXT, ".outputs dd.multiline")
    joined = " ".join(f"{k}: {v}" for k, v in rule.items())
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb|hsl|url\(|var\(", joined)
    assert not any(k.startswith(("animation", "transition")) for k in rule)
    assert "@font-face" not in CSS_TEXT


def test_show_success_passes_the_class_to_the_dd_only():
    assert 'el("dd", { class: outputClass(text) }, text)' in CONSOLE_JS
    assert len(re.findall(r"outputClass\(", CONSOLE_JS)) == 1
    assert re.search(r"^\s*outputClass,$", CONSOLE_JS, re.M)


@needs_node
def test_output_class_under_node():
    source = (ASSET_DIR / "snippets.js").read_text(encoding="utf-8")
    runner = (
        "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
        "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
        "const m=await import('data:text/javascript;base64,'+Buffer.from(p.source,'utf8').toString('base64'));"
        "process.stdout.write(JSON.stringify(p.cases.map(c=>m.outputClass(c))));});"
    )
    cases = ["a\nb", "a", "", "a b", 136]
    done = subprocess.run(
        [NODE, "-e", runner],
        input=json.dumps({"source": source, "cases": cases}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0
    assert json.loads(done.stdout) == ["multiline", None, None, None, None]
