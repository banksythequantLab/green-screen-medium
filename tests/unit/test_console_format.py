"""auditLine and retryAfterText of the Snippets_Module, run under Node (task 6.3).

One `node` process serves a whole batch, with the same data: URL import and standard-input
pattern as `run_snippets` in tests/console_node.py. No file is written.

Requirements: 7.3, 7.11, 8.4, 14.8
"""

from __future__ import annotations

import json
import math
import subprocess
from typing import Any

import pytest

from tests.console_node import NODE, needs_node, snippets_source

pytestmark = needs_node

RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.source,'utf8').toString('base64'));"
    "process.stdout.write(JSON.stringify(p.cases.map(c=>c.fn==='audit'?m.auditLine(c.arg):m.retryAfterText(c.arg))));});"
)


def run_format(cases: list[dict[str, Any]]) -> list[Any]:
    """Run `{"fn": "audit" | "retry", "arg": ...}` cases in one node process."""
    assert NODE is not None
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", RUNNER],
        input=json.dumps({"source": snippets_source(), "cases": cases}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    assert len(results) == len(cases)
    return results


def row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "step_index": 12,
        "kind": "expect",
        "phase": "main",
        "iteration": None,
        "signature": "tso-password-prompt",
        "status": "ok",
        "duration_seconds": 0,
    }
    base.update(over)
    return base


def ref_audit(r: dict[str, Any]) -> str:
    """Small reference of the design's "Audit list"."""

    def whole(v: Any) -> str:
        ok = isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 2**53 - 1
        return str(v) if ok else "?"

    words = [whole(r["step_index"]), str(r["kind"])[:40]]
    if r["signature"] is not None:
        words.append(str(r["signature"])[:80])
    words.append({"ok": "OK", "skipped": "SKIPPED", "failed": "FAILED"}.get(r["status"], "UNKNOWN"))
    d = r["duration_seconds"]
    if isinstance(d, (int, float)) and math.isfinite(d) and float(f"{d:.2f}") > 0:
        words.append(f"{d:.2f}s")
    if r["phase"] == "finally":
        words.append("finally")
    if r["iteration"] is not None:
        words.append("pass " + whole(r["iteration"]))
    return " ".join(words)


def ref_retry(v: Any) -> str | None:
    if not isinstance(v, str) or not (1 <= len(v) <= 6 and v.isascii() and v.isdigit()):
        return None
    n = int(v)
    return f"Retry after: {n} second" + ("" if n == 1 else "s")


AUDIT_EXAMPLES = [
    (row(), "12 expect tso-password-prompt OK"),
    (row(duration_seconds=0.4), "12 expect tso-password-prompt OK 0.40s"),
    (row(duration_seconds=0), "12 expect tso-password-prompt OK"),
    (row(duration_seconds=0.004), "12 expect tso-password-prompt OK"),
    (row(duration_seconds=-0.5), "12 expect tso-password-prompt OK"),
    (row(duration_seconds=0.006), "12 expect tso-password-prompt OK 0.01s"),
    (row(duration_seconds=1.234), "12 expect tso-password-prompt OK 1.23s"),
    (row(phase="finally", iteration=3), "12 expect tso-password-prompt OK finally pass 3"),
    (row(signature=None, kind="extract"), "12 extract OK"),
    (row(status="weird"), "12 expect tso-password-prompt UNKNOWN"),
    (row(status="skipped"), "12 expect tso-password-prompt SKIPPED"),
    (row(status="failed"), "12 expect tso-password-prompt FAILED"),
    (row(step_index="x"), "? expect tso-password-prompt OK"),
    (row(kind="k" * 500), "12 " + "k" * 40 + " tso-password-prompt OK"),
    (row(signature="s" * 500), "12 expect " + "s" * 80 + " OK"),
]

RETRY_EXAMPLES = [
    ("1", "Retry after: 1 second"),
    ("01", "Retry after: 1 second"),
    ("0", "Retry after: 0 seconds"),
    ("007", "Retry after: 7 seconds"),
    ("120", "Retry after: 120 seconds"),
    (None, None),
    ("", None),
    ("1.5", None),
    ("-1", None),
    ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    (" 3", None),
    ("1234567", None),
]


def test_audit_line_matches_the_design_examples():
    got = run_format([{"fn": "audit", "arg": r} for r, _ in AUDIT_EXAMPLES])
    for i, ((_, want), have) in enumerate(zip(AUDIT_EXAMPLES, got)):
        assert have == want, f"audit example {i} differs"


def test_audit_line_matches_the_reference():
    rows = [r for r, _ in AUDIT_EXAMPLES] + [
        row(step_index=2**53, iteration=2**53),
        row(step_index=1.5, iteration=0),
        row(duration_seconds=100.0, phase="finally", iteration=1),
    ]
    got = run_format([{"fn": "audit", "arg": r} for r in rows])
    for i, (r, have) in enumerate(zip(rows, got)):
        assert have == ref_audit(r), f"audit reference case {i} differs"


def test_retry_after_matches_the_design_examples():
    got = run_format([{"fn": "retry", "arg": v} for v, _ in RETRY_EXAMPLES])
    for i, ((_, want), have) in enumerate(zip(RETRY_EXAMPLES, got)):
        assert have == want, f"retry example {i} differs"


def test_retry_after_matches_the_reference():
    values = [v for v, _ in RETRY_EXAMPLES] + ["999999", "000000", "0000001", "12a", "١٢"]
    got = run_format([{"fn": "retry", "arg": v} for v in values])
    for i, (v, have) in enumerate(zip(values, got)):
        assert have == ref_retry(v), f"retry reference case {i} differs"
