"""The key on ``hashchange`` (spec polish, task 9.2, Requirement 12).

Static checks over the packaged ``console.js`` and Node examples through
``tests/console_node_extract.py``.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from tests.console_node_extract import (
    NODE,
    console_source,
    function_source,
    needs_node,
    run_fragment,
)


def test_start_registers_hashchange_after_load_codes():
    body = function_source(console_source(), "start")
    load = body.index("await loadCodes()")
    listen = body.index('window.addEventListener("hashchange", onHashChange)')
    first_call = body.index("onHashChange();", listen)
    assert load < listen < first_call


def test_on_hash_change_reloads_the_listing_only_when_not_running():
    body = function_source(console_source(), "onHashChange")
    take = body.index("takeKeyFromFragment()")
    panel = body.index("showKeyPanel(false)")
    guard = body.index("if (!running)")
    load = body.index("loadListing()")
    assert take < panel < guard < load
    assert body.count("loadListing()") == 1


def test_first_replace_state_precedes_first_fetch():
    text = console_source()
    assert text.index("history.replaceState") < text.index("fetch(")


def _one(hash_text, pathname="/p", search="?x=1"):
    [result] = run_fragment([{"hash": hash_text, "pathname": pathname, "search": search}])
    assert "threw" not in result
    return result


@needs_node
def test_key_is_taken_and_removed_from_the_address():
    r = _one("#key=abc")
    assert r["taken"] is True
    assert (r["apiKey"], r["keyHeld"]) == ("abc", True)
    assert r["calls"] == [[None, "", "/p?x=1"]]


@needs_node
def test_empty_key_is_not_taken_but_is_removed():
    r = _one("#key=")
    assert r["taken"] is False
    assert (r["apiKey"], r["keyHeld"]) == (None, False)
    assert r["calls"] == [[None, "", "/p?x=1"]]


@needs_node
def test_other_fragment_does_nothing():
    r = _one("#other")
    assert r["taken"] is False
    assert (r["apiKey"], r["keyHeld"]) == (None, False)
    assert r["calls"] == []


@needs_node
@pytest.mark.parametrize(
    ("fragment", "key"),
    [
        ("#key=%41%42", "AB"),
        ("#key=%E0%A4%A", "%E0%A4%A"),
        ("#key=%", "%"),
    ],
)
def test_percent_escapes_decode_or_stay_raw(fragment, key):
    r = _one(fragment)
    assert r["taken"] is True
    assert (r["apiKey"], r["keyHeld"]) == (key, True)
    assert len(r["calls"]) == 1


@needs_node
def test_a_second_call_with_a_new_fragment_replaces_the_key():
    # run_fragment gives each case a fresh context, so this one shares a context.
    runner = (
        "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
        "process.stdin.on('end',()=>{const vm=require('node:vm');const p=JSON.parse(s);"
        "const calls=[];const ctx={window:{location:{hash:'#key=first',pathname:'/p',search:''},"
        "history:{replaceState:(...a)=>calls.push(a)}}};"
        "const r=vm.runInNewContext('let apiKey = null; let keyHeld = false;'+p.source+"
        "';const a=takeKeyFromFragment();const k1=apiKey;window.location.hash=\"#key=second\";"
        "const b=takeKeyFromFragment();({a,k1,b,k2:apiKey,keyHeld})',ctx);"
        "process.stdout.write(JSON.stringify({r,n:calls.length}));});"
    )
    done = subprocess.run(
        [NODE, "-e", runner],
        input=json.dumps({"source": function_source(console_source(), "takeKeyFromFragment")}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert done.returncode == 0
    out = json.loads(done.stdout)
    assert out["r"] == {"a": True, "k1": "first", "b": True, "k2": "second", "keyHeld": True}
    assert out["n"] == 2
