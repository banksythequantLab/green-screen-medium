"""Property 18: load errors never echo YAML scalars."""

from __future__ import annotations

import copy

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.yamlio import from_yaml

SENTINEL = "QZX_SENTINEL_7f3a91"
UNKNOWN_KEY = "bogus_extra_key"

_STR_KEYS = {"name", "description", "kind", "text", "pattern"}

VALID_DOC = {
    "version": 1,
    "name": "valid-screen",
    "description": "a description",
    "matchers": [
        {"kind": "text_at", "row": 0, "col": 1, "text": "HELLO"},
        {"kind": "row_contains", "row": 2, "text": "WORLD"},
        {"kind": "field_layout", "count": 2,
         "positions": [{"row": 1, "col": 2}, {"row": 3, "col": 4}]},
        {"kind": "cursor_field", "row": 1, "col": 1, "hidden": False},
        {"kind": "region_regex", "row": 0, "col": 0, "length": 5, "pattern": "A.*"},
        {"kind": "last_row", "text": "READY"},
        {"kind": "before_cursor", "text": "==>"},
    ],
    "volatile": [{"row": 0, "col": 70, "length": 8}, {"row": 1, "col": 0, "length": 3}],
}


def _mappings(node, path=()):
    """Yield (path, mapping) for every mapping in the document."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _mappings(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _mappings(v, path + (i,))


def _walk(doc, path):
    node = doc
    for p in path:
        node = node[p]
    return node


def _mutations():
    out = []
    for path, m in _mappings(VALID_DOC):
        for key in m:
            if path == () and key == "version":
                continue  # version is the documented truncated-echo exception
            out.append(("wrong_type", path, key))
            if not (path == () and key in ("description", "volatile")):  # optional
                out.append(("missing", path, key))
        out.append(("unknown", path, UNKNOWN_KEY))
    return out


MUTATIONS = _mutations()


def _expected_tokens(path, key):
    """Key name plus every list index context the message must mention."""
    tokens = [key]
    for i, p in enumerate(path):
        if isinstance(p, int):
            tokens.append(f"{path[i - 1]}[{p}]")
    return tokens


@settings(max_examples=150, deadline=None)
@given(st.one_of(
    st.tuples(st.just("yaml"), st.sampled_from(MUTATIONS)),
    st.tuples(st.just("malformed"), st.sampled_from(
        ["{", "a: [", "key: 'unclosed", "- - {a: ]", "a: b: c", "\t- x"])),
))
def test_load_errors_never_echo_scalars(case):
    # Feature: screen-recognizer, Property 18: Load errors never echo scalars
    kind, payload = case
    if kind == "malformed":
        text = f"{payload} {SENTINEL}"
        try:
            from_yaml(text)
        except SignatureError as exc:
            msg = str(exc)
            assert SENTINEL not in msg
            assert payload not in msg
        else:
            raise AssertionError("malformed YAML was accepted")
        return

    mode, path, key = payload
    doc = copy.deepcopy(VALID_DOC)
    target = _walk(doc, path)
    if mode == "wrong_type":
        # A str-typed key gets a list; any other key gets the sentinel string.
        target[key] = [SENTINEL] if key in _STR_KEYS else SENTINEL
    elif mode == "missing":
        del target[key]
    else:
        target[key] = SENTINEL
    text = yaml.safe_dump(doc, sort_keys=False)
    assert SENTINEL in text or mode == "missing"

    try:
        from_yaml(text)
    except SignatureError as exc:
        msg = str(exc)
    else:
        raise AssertionError(f"{mode} mutation at {path}/{key} was accepted")

    assert SENTINEL not in msg
    # "kind" mutations report "'kind'"; "positions"/"matchers" keep their names.
    for token in _expected_tokens(path, key):
        assert token in msg, (token, msg)
