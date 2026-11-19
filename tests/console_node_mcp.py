"""Run the MCP functions of the console's Snippets_Module under Node (task 8.2).

One `node` process serves a whole batch of calls. The module source and the calls go in
through standard input as JSON, the module is imported from a `data:` URL, and the
results come back on standard output. No file is written.

Nothing here prints a call value: failures name the process outcome, never the input.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from tests.console_node import NODE, needs_node, snippets_source

__all__ = ["NODE", "needs_node", "run_calls"]

# A call is {"fn": <export name>, "args": [...]}. A result is {"value": ...} or {"error": "<message>"}.
# Values that JSON cannot carry (undefined, NaN, Infinity) are passed as {"$": "undefined" | "NaN" | "Infinity" | "-Infinity"}.
RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.source,'utf8').toString('base64'));"
    "const rev=v=>{if(v&&typeof v==='object'){if(!Array.isArray(v)&&Object.keys(v).length===1&&'$' in v){"
    "return {undefined:undefined,NaN:NaN,Infinity:Infinity,'-Infinity':-Infinity}[v.$];}"
    "return Array.isArray(v)?v.map(rev):Object.fromEntries(Object.entries(v).map(([k,x])=>[k,rev(x)]));}return v;};"
    "const out=p.calls.map(c=>{try{const r=m[c.fn](...c.args.map(rev));"
    "return {value:r===undefined?null:r};}catch(e){return {error:String(e&&e.message)};}});"
    "process.stdout.write(JSON.stringify(out));});"
)


def run_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run every call in one `node` process and return one result per call."""
    assert NODE is not None, "run_calls needs node"
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", RUNNER],
        input=json.dumps({"source": snippets_source(), "calls": calls}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        # Neither stream is echoed: stderr could carry a fragment of an input value.
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    if len(results) != len(calls):
        raise RuntimeError("node returned a different number of results than calls")
    return results
