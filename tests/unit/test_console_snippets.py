"""The Snippets_Module run by a real Node process (console spec, Requirements 9 and 14.5)."""
from __future__ import annotations

import json
import shlex

import pytest

from tests.console_node import needs_node, run_snippets

pytestmark = needs_node

ORIGIN = "https://seance.example"
KEY = "<YOUR_API_KEY>"
FLOW = "tk5-system-info"
CLAUDE_ARGS = [
    "claude", "mcp", "add", "--transport", "http", "greenscreen",
    f"{ORIGIN}/mcp", "--header", f"X-API-Key: {KEY}",
]


def _one(inputs, origin=ORIGIN, name=FLOW):
    return run_snippets([{"origin": origin, "name": name, "inputs": inputs}])[0]


def _field(name, value, *, type="string", secret=False, required=True):
    return {"name": name, "type": type, "secret": secret, "required": required, "value": value}


def _body(curl: str) -> dict:
    args = shlex.split(curl)
    return json.loads(args[args.index("-d") + 1])


def test_no_inputs_gives_the_exact_curl_shape():
    out = _one([])
    assert out["curl"] == (
        f"curl -sS -X POST '{ORIGIN}/flows/{FLOW}' -H 'Content-Type: application/json' "
        f"-H 'X-API-Key: {KEY}' -d '{{}}'"
    )


@pytest.mark.parametrize(
    "value",
    ["it's", 'say "hi"', "back\\slash", "line1\nline2", "$(x)", "tick`tick", "all ' \" \\ \n $(x) `"],
)
def test_awkward_string_values_survive_shlex_and_json(value):
    out = _one([_field("note", value)])
    if _body(out["curl"]) != {"note": value}:
        pytest.fail("a string value did not round-trip through shlex and JSON")


def test_secret_is_masked_and_typed_text_appears_nowhere():
    typed = "SECRET-0123456789abcdef"
    out = _one([_field("password", typed, secret=True)])
    if _body(out["curl"]) != {"password": "<SECRET>"}:
        pytest.fail("the secret was not written as <SECRET>")
    for part in ("curl", "mcp", "claude"):
        if typed in out[part]:
            pytest.fail(f"the typed secret text appears in the {part} output")


def test_integer_is_a_json_number():
    out = _one([_field("count", "42", type="integer"), _field("neg", "-7", type="integer")])
    assert out["curl"].endswith("-d '{\"count\":42,\"neg\":-7}'")
    body = _body(out["curl"])
    assert body == {"count": 42, "neg": -7}
    assert type(body["count"]) is int


def test_integer_junk_stays_a_string():
    out = _one([_field("count", "007", type="integer"), _field("other", "1.5", type="integer")])
    assert _body(out["curl"]) == {"count": "007", "other": "1.5"}


def test_empty_optional_value_is_omitted_and_empty_required_is_kept():
    out = _one([_field("a", "", required=False), _field("b", "", required=True)])
    assert _body(out["curl"]) == {"b": ""}


def test_mcp_text_parses_with_placeholder_key_and_origin():
    out = _one([])
    parsed = json.loads(out["mcp"])
    assert parsed == {
        "mcpServers": {
            "greenscreen": {"url": f"{ORIGIN}/mcp", "headers": {"X-API-Key": KEY}},
        }
    }


def test_claude_command_splits_into_the_fixed_argument_list():
    typed = "SECRET-feedfacecafebeef"
    out = _one([_field("password", typed, secret=True)])
    if shlex.split(out["claude"]) != CLAUDE_ARGS:
        pytest.fail("the Claude Code command is not the fixed argument list")
    if typed in out["claude"]:
        pytest.fail("the typed secret text appears in the claude output")
