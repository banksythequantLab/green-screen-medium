# Feature: console, Property 3: Snippets survive a POSIX shell
"""Property 3: the snippet texts survive `shlex.split` and `json.loads` (Requirement 14.6).

One Hypothesis example is a batch of up to 20 cases, run by one `node` process. The oracle
below is a separate model of the rules and does not call the module. Failure messages name
the case index and the rule, never a value, and the batch object hides its contents from
Hypothesis's falsifying-example report.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 14.3, 14.4, 14.5, 14.6, 14.7**
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.console_node import needs_node, run_snippets

PLACEHOLDER = "<YOUR_API_KEY>"
INTEGER_TEXT = re.compile(r"^-?(0|[1-9][0-9]*)$")


@dataclass
class Batch:
    cases: list[dict]

    def __repr__(self) -> str:  # keeps typed values out of Hypothesis's report
        return f"<batch of {len(self.cases)} cases>"


_NASTY = list("'\"\\\n$()` \t")
text_values = st.text(
    alphabet=st.one_of(st.sampled_from(_NASTY), st.characters(blacklist_categories=("Cs",))),
    max_size=30,
)
integer_values = st.one_of(
    st.integers(min_value=-(10**30), max_value=10**30).map(str),
    st.sampled_from(["", "007", "-", "1.5", "1e3", " 4", "+5", "abc", "-0", "0"]),
    text_values,
)
secret_values = st.binary(min_size=4, max_size=12).map(lambda b: "SECRET-" + b.hex())
names = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
origins = st.builds(
    lambda scheme, host, port: f"{scheme}://{host}" + (f":{port}" if port else ""),
    st.sampled_from(["http", "https"]),
    st.from_regex(r"[a-z][a-z0-9-]{0,12}(\.[a-z]{2,5}){0,2}", fullmatch=True),
    st.one_of(st.none(), st.integers(min_value=1, max_value=65535)),
)
flow_names = st.from_regex(r"[a-z][a-z0-9]{0,6}(-[a-z0-9]{1,6}){0,3}", fullmatch=True)


@st.composite
def inputs_lists(draw):
    unique = draw(st.lists(names, max_size=5, unique=True))
    result = []
    for name in unique:
        kind = draw(st.sampled_from(["string", "integer", "secret"]))
        required = draw(st.booleans())
        if kind == "secret":
            value = draw(st.one_of(secret_values, st.just("")))
        elif kind == "integer":
            value = draw(integer_values)
        else:
            value = draw(text_values)
        result.append(
            {
                "name": name,
                "type": "integer" if kind == "integer" else "string",
                "secret": kind == "secret",
                "required": required,
                "value": value,
            }
        )
    return result


cases_strategy = st.lists(
    st.fixed_dictionaries({"origin": origins, "name": flow_names, "inputs": inputs_lists()}),
    max_size=20,
).map(Batch)


def expected_body(inputs: list[dict]) -> dict:
    """The oracle: omit empty optional values, mask secrets, digit strings become integers."""
    body: dict = {}
    for item in inputs:
        value = item["value"]
        if value == "" and not item["required"]:
            continue
        if item["secret"]:
            body[item["name"]] = "<SECRET>"
        elif item["type"] == "integer" and INTEGER_TEXT.match(value):
            body[item["name"]] = int(value)
        else:
            body[item["name"]] = value
    return body


def _fail(index: int, rule: str) -> None:
    pytest.fail(f"case {index}: {rule}")


@needs_node
@settings(max_examples=100, deadline=None)
@given(batch=cases_strategy)
def test_snippets_survive_a_posix_shell(batch: Batch) -> None:
    results = run_snippets(batch.cases)
    for index, (case, out) in enumerate(zip(batch.cases, results)):
        origin = case["origin"]
        args = shlex.split(out["curl"])
        fixed = [
            "curl", "-sS", "-X", "POST", f"{origin}/flows/{case['name']}",
            "-H", "Content-Type: application/json",
            "-H", f"X-API-Key: {PLACEHOLDER}",
            "-d",
        ]
        if len(args) != len(fixed) + 1 or args[: len(fixed)] != fixed:
            _fail(index, "the curl argument list is not the fixed one")
        try:
            decoded = json.loads(args[-1])
        except ValueError:
            _fail(index, "the -d argument is not JSON")
        if decoded != expected_body(case["inputs"]):
            _fail(index, "the -d JSON differs from the oracle")
        for item in case["inputs"]:
            if item["type"] == "integer" and not item["secret"] and INTEGER_TEXT.match(item["value"]):
                if type(decoded[item["name"]]) is not int:
                    _fail(index, "an integer is not a JSON number")

        try:
            mcp = json.loads(out["mcp"])
        except ValueError:
            _fail(index, "the MCP text is not JSON")
        want = {"mcpServers": {"greenscreen": {"url": f"{origin}/mcp", "headers": {"X-API-Key": PLACEHOLDER}}}}
        if mcp != want:
            _fail(index, "the MCP config differs from the expected shape")

        claude = [
            "claude", "mcp", "add", "--transport", "http", "greenscreen",
            f"{origin}/mcp", "--header", f"X-API-Key: {PLACEHOLDER}",
        ]
        if shlex.split(out["claude"]) != claude:
            _fail(index, "the Claude Code command is not the fixed argument list")

        for item in case["inputs"]:
            if item["secret"] and item["value"]:
                for part in ("curl", "mcp", "claude"):
                    if item["value"] in out[part]:
                        _fail(index, f"a typed secret appears in the {part} output")
