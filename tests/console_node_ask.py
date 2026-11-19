"""Run the Ask functions of the Snippets_Module under Node (spec ask, task 4.3).

One `node` process serves a whole batch of calls. The module source and the calls go in
through standard input as JSON, the module is imported from a `data:` URL, and the
results come back on standard output. No file is written. The helpers of
`tests/console_node.py` are imported, not edited.
Nothing here prints a call argument: failures name the process outcome only.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from tests.console_node import NODE, needs_node, snippets_source

__all__ = ["NODE", "needs_node", "run_ask_calls", "snippets_source"]

# Each call is {"fn": <export name>, "args": [...]}. A call that throws returns
# {"threw": true} (the error text is dropped on purpose: it could hold an argument).
RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.source,'utf8').toString('base64'));"
    "const out=p.calls.map(c=>{try{const f=m[c.fn];"
    "const v=typeof f==='function'?f(...c.args):f;"
    "return {value:v===undefined?null:v};}catch(e){return {threw:true};}});"
    "process.stdout.write(JSON.stringify(out));});"
)


def run_ask_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run every call in one `node` process; each result is `{"value": ...}` or `{"threw": true}`."""
    assert NODE is not None, "run_ask_calls needs node"
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", RUNNER],
        input=json.dumps({"source": snippets_source(), "calls": calls}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        # Neither stream is echoed: stderr could carry a fragment of an argument.
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    if len(results) != len(calls):
        raise RuntimeError("node returned a different number of results than calls")
    return results


def summarise_run(audit: Any) -> dict[str, int]:
    """Python reference for `summariseRun` (design: console spec, Decision on counts).

    A step counts when it is an object whose `status` is not "skipped"; a screen counts
    for each distinct non-empty string `signature` among those steps.
    """
    if not isinstance(audit, list):
        return {"steps": 0, "screens": 0}
    steps = 0
    screens: set[str] = set()
    for entry in audit:
        if isinstance(entry, dict) and entry.get("status") != "skipped":
            steps += 1
            sig = entry.get("signature")
            if isinstance(sig, str) and sig != "":
                screens.add(sig)
    return {"steps": steps, "screens": len(screens)}


def call_one(fn: str, *args: Any) -> Any:
    """Run one call and return its value; a throw raises `AssertionError`."""
    result = run_ask_calls([{"fn": fn, "args": list(args)}])[0]
    assert "threw" not in result, f"{fn} threw"
    return result["value"]
