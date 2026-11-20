"""Run single functions of the console's ``console.js`` under Node (spec polish, task 7.2).

``console.js`` is not a module a test can import: it touches ``document`` at load. So the
source of one function is cut out of the text by brace matching and run with
``vm.runInNewContext`` against stubs. One ``node`` process serves a whole batch, the input
goes in through standard input as JSON, and no file is written. The helpers of
``tests/console_node.py`` are imported, not edited.

    ``function_source(text, name)``    source of ``function name(...) {...}`` (or ``async function``)
    ``console_source()``               the text of the packaged ``console.js``
    ``run_listing(documents, ...)``    ``parseListing`` over OpenAPI-like documents; with ``limit``
                                       also ``askExamples(items, limit, max_question)``
    ``run_fragment(cases)``            ``takeKeyFromFragment`` over stub ``window`` objects (task 9.2)

Nothing here prints a case value: a failure names the process outcome only. Results of
``run_fragment`` hold the key text of the case because it is test data.
"""
from __future__ import annotations

import json
import re
import subprocess
from importlib import resources
from typing import Any

from tests.console_node import NODE, needs_node, snippets_source

__all__ = [
    "NODE",
    "console_source",
    "function_source",
    "needs_node",
    "run_fragment",
    "run_listing",
]


def console_source() -> str:
    """The text of ``console.js`` as installed in the package."""
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath("console.js")
        .read_text(encoding="utf-8")
    )


def function_source(text: str, name: str) -> str:
    """The source of ``function name(...) {...}`` or ``async function name(...) {...}``.

    The end is found by brace matching; braces inside ``"``, ``'`` and backquote strings and
    inside ``//`` and ``/* */`` comments are skipped. A regular expression literal that holds
    a quote or a brace is not handled (none of the extracted functions has one).
    """
    header = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", text)
    if header is None:
        raise AssertionError(f"function {name} not found")
    start = header.start()
    open_at = text.index("{", text.index(")", header.end()))
    depth = 0
    i = open_at
    while i < len(text):
        ch = text[i]
        if text.startswith("//", i):
            i = text.index("\n", i) if "\n" in text[i:] else len(text)
            continue
        if text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        if ch in "\"'`":
            i += 1
            while text[i] != ch:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces in {name}")


_LISTING_RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const vm=require('node:vm');const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.snippets,'utf8').toString('base64'));"
    "const out=p.documents.map(d=>{try{"
    "const items=JSON.parse(JSON.stringify(vm.runInNewContext(p.source+';parseListing(doc)',{doc:d})));"
    "const r={items};"
    "if(p.limit!==null){r.examples=m.askExamples(items,p.limit,p.maxQuestion);}"
    "return r;}catch(e){return {threw:true};}});"
    "process.stdout.write(JSON.stringify(out));});"
)

_FRAGMENT_RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',()=>{const vm=require('node:vm');const p=JSON.parse(s);"
    "const out=p.cases.map(c=>{try{const calls=[];"
    "const ctx={window:{location:{hash:c.hash,pathname:c.pathname,search:c.search},"
    "history:{replaceState:(...a)=>calls.push(a)}}};"
    "const r=vm.runInNewContext('let apiKey = null; let keyHeld = false;'+p.source+"
    "';({taken: takeKeyFromFragment(), apiKey, keyHeld})',ctx);"
    "return JSON.parse(JSON.stringify({taken:r.taken,apiKey:r.apiKey,keyHeld:r.keyHeld,calls}));"
    "}catch(e){return {threw:true};}});"
    "process.stdout.write(JSON.stringify(out));});"
)


def _node(runner: str, payload: dict[str, Any], count: int) -> list[dict[str, Any]]:
    assert NODE is not None, "the extraction harness needs node"
    done = subprocess.run(
        [NODE, "-e", runner],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        # Neither stream is echoed: stderr could carry a fragment of a case value.
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    if len(results) != count:
        raise RuntimeError("node returned a different number of results than cases")
    return results


def run_listing(
    documents: list[Any],
    limit: int | None = None,
    max_question: int | None = None,
) -> list[dict[str, Any]]:
    """Run ``parseListing`` over each document; each result is ``{"items": [...]}``.

    With ``limit`` the result also has ``"examples"``: ``askExamples(items, limit, max_question)``
    from the packaged ``snippets.js``. ``max_question=None`` is passed as ``null``. A document
    on which the code throws gives ``{"threw": true}``.
    """
    payload = {
        "source": function_source(console_source(), "parseListing"),
        "snippets": snippets_source(),
        "documents": documents,
        "limit": limit,
        "maxQuestion": max_question,
    }
    return _node(_LISTING_RUNNER, payload, len(documents))


def run_fragment(cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Run ``takeKeyFromFragment`` once per case, each in a new context.

    A case is ``{"hash", "pathname", "search"}`` (the three members of the stub
    ``window.location``; a missing member is the empty string). The prelude is
    ``let apiKey = null; let keyHeld = false;`` and ``window.history.replaceState`` records
    its argument lists. Each result is ``{"taken", "apiKey", "keyHeld", "calls"}`` where
    ``calls`` is the list of argument lists, or ``{"threw": true}``.
    """
    full = [{"hash": "", "pathname": "", "search": "", **case} for case in cases]
    payload = {
        "source": function_source(console_source(), "takeKeyFromFragment"),
        "cases": full,
    }
    return _node(_FRAGMENT_RUNNER, payload, len(cases))
