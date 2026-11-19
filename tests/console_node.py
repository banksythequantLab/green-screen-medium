"""Run the console's Snippets_Module under Node (Requirement 14.3 and 14.4).

One `node` process serves a whole batch of cases. The module source and the cases go in
through standard input as JSON, the module is imported from a `data:` URL, and the
results come back on standard output. No file is written.

Nothing here prints a case value: failures name the process outcome, never the input.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import pytest

from tests.console_support import ASSET_DIR

NODE = shutil.which("node")

needs_node = pytest.mark.skipif(
    NODE is None,
    reason="node is not on PATH; the Snippets_Module was not executed",
)

RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.source,'utf8').toString('base64'));"
    "process.stdout.write(JSON.stringify(p.cases.map(c=>({curl:m.buildCurl(c.origin,c.name,c.inputs),"
    "mcp:m.buildMcpConfig(c.origin),claude:m.buildClaudeCodeCommand(c.origin)}))));});"
)


def snippets_source() -> str:
    return (ASSET_DIR / "snippets.js").read_text(encoding="utf-8")


def run_snippets(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Run every case through the three builders in one `node` process.

    Each case is `{"origin", "name", "inputs"}`; each result is `{"curl", "mcp", "claude"}`.
    """
    assert NODE is not None, "run_snippets needs node"
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", RUNNER],
        input=json.dumps({"source": snippets_source(), "cases": cases}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        # Neither stream is echoed: stderr could carry a fragment of an input value.
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    if len(results) != len(cases):
        raise RuntimeError("node returned a different number of results than cases")
    return results
