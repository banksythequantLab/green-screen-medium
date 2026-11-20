# Feature: polish, Property 4: The example buttons follow the listing
"""Properties of the console's example questions (spec polish, tasks 7.3 to 7.5).

Property 4 (task 7.3): the example buttons follow the listing.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**

The real ``parseListing`` (cut out of ``console.js``) and the real ``askExamples`` (from
``snippets.js``) run under Node through ``tests.console_node_extract.run_listing``. One
example is one ``node`` process over one to four generated documents that share a limit
and a question length. The oracle below is a Python model of Requirement 9, written apart
from the code under test: a Flow gets a button only when its name is valid, none of its
inputs is secret and its ``x-ask-example`` is a non-empty string of printable ASCII that
fits the question length; there is never a generic text; the cap is 12.

Tasks 7.4 and 7.5 append their properties to this file.
"""
from __future__ import annotations

import re
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.console_node_extract import needs_node, run_listing

pytestmark = needs_node

ASK_EXAMPLE_MAX = 12
NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}")
PRINTABLE = re.compile(r"[\x20-\x7E]+")

VALID_NAME = st.from_regex(r"[a-zA-Z0-9_-]{1,64}", fullmatch=True)
INVALID_NAME = st.one_of(
    st.just("a b"),
    st.just("caf\u00e9"),
    st.just("x" * 65),
    st.just("a.b"),
    st.just("tab\there"),
    st.just("a/b"),
    st.just(""),
)
NAMES = st.one_of(VALID_NAME, VALID_NAME, INVALID_NAME)

PRINTABLE_TEXT = st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), min_size=1, max_size=80)
BAD_TEXT = st.one_of(
    st.just(""),
    st.just("tab\tinside"),
    st.just("line\nbreak"),
    st.just("caf\u00e9 question"),
    st.just("\u2603 snowman"),
    st.text(max_size=20),
)
MISSING = object()
EXAMPLE = st.one_of(
    PRINTABLE_TEXT,
    PRINTABLE_TEXT,
    BAD_TEXT,
    st.integers(),
    st.none(),
    st.lists(st.text(max_size=5), max_size=2),
    st.just(MISSING),
)

PROPERTY_NAMES = st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=6)


@st.composite
def request_body(draw):
    kind = draw(st.sampled_from(["none", "empty", "props"]))
    if kind == "none":
        return None
    if kind == "empty":
        return {"content": {"application/json": {"schema": {"type": "object"}}}}
    names = draw(st.lists(PROPERTY_NAMES, max_size=4, unique=True))
    properties = {}
    for name in names:
        prop = {"type": draw(st.sampled_from(["string", "integer"]))}
        mode = draw(st.sampled_from(["plain", "plain", "secret", "not-secret"]))
        if mode == "secret":
            prop["writeOnly"] = True
        elif mode == "not-secret":
            prop["writeOnly"] = False
        properties[name] = prop
    required = draw(st.lists(st.sampled_from(names), max_size=len(names))) if names else []
    schema = {"type": "object", "properties": properties, "required": required}
    return {"content": {"application/json": {"schema": schema}}}


@st.composite
def operation(draw):
    op = {"summary": draw(st.one_of(st.text(max_size=60), st.none(), st.integers()))}
    body = draw(request_body())
    if body is not None:
        op["requestBody"] = body
    example = draw(EXAMPLE)
    if example is not MISSING:
        op["x-ask-example"] = example
    return op


@st.composite
def document(draw):
    names = draw(st.lists(NAMES, max_size=30, unique=True))
    paths = {}
    for name in names:
        paths["/flows/" + name] = {"post": draw(operation())}
    if draw(st.booleans()):
        paths["/health"] = {"get": {"summary": "health"}}
    return {"openapi": "3.1.0", "paths": paths}


def is_secret_input(op) -> bool:
    body = op.get("requestBody")
    if body is None:
        return False
    schema = body["content"]["application/json"]["schema"]
    return any(prop.get("writeOnly") is True for prop in schema.get("properties", {}).values())


def model(doc, limit, max_question):
    """Requirement 9: (flow name, example text) for each button, in listing order."""
    cap = min(max(limit, 0), ASK_EXAMPLE_MAX)
    found = []
    for path, item in doc["paths"].items():
        match = re.fullmatch(r"/flows/([^/]+)", path)
        if not match or "post" not in item:
            continue
        name = match.group(1)
        op = item["post"]
        example = op.get("x-ask-example")
        if not NAME.fullmatch(name) or is_secret_input(op):
            continue
        if not isinstance(example, str) or not PRINTABLE.fullmatch(example):
            continue
        if max_question is not None and len(example) > max_question:
            continue
        found.append((name, example))
    return found[:cap]


def listed_examples(doc):
    """What parseListing must carry as ``example`` per listed Flow name."""
    found = {}
    for path, item in doc["paths"].items():
        match = re.fullmatch(r"/flows/([^/]+)", path)
        if match and "post" in item:
            value = item["post"].get("x-ask-example")
            found[match.group(1)] = value if isinstance(value, str) else ""
    return found


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    docs=st.lists(document(), min_size=1, max_size=4),
    limit=st.integers(min_value=-1, max_value=20),
    max_question=st.one_of(st.none(), st.integers(min_value=1, max_value=600)),
)
def test_example_buttons_follow_the_listing(docs, limit, max_question):
    results = run_listing(docs, limit, max_question)
    assert len(results) == len(docs)
    for index, (doc, result) in enumerate(zip(docs, results)):
        assert "threw" not in result, f"case {index}: the code threw"

        # parseListing: one item per operation under /flows/<name>, example is a string or "".
        wanted = listed_examples(doc)
        assert [i["name"] for i in result["items"]] == list(wanted), f"case {index}: listing names"
        for item in result["items"]:
            assert item["example"] == wanted[item["name"]], f"case {index}: example member"

        # askExamples: equal to the model, in listing order, text only from the document.
        expected = model(doc, limit, max_question)
        got = result["examples"]
        assert [e["text"] for e in got] == [text for _, text in expected], f"case {index}: texts"
        assert len(got) <= min(max(limit, 0), ASK_EXAMPLE_MAX), f"case {index}: cap"
        offered = {text for _, text in expected}
        for entry in got:
            assert entry["text"] in offered, f"case {index}: a text that no Flow offers"
            assert isinstance(entry["hint"], str), f"case {index}: hint type"
            assert len(entry["hint"]) <= 100, f"case {index}: hint length"
            assert entry["hint"] == "" or PRINTABLE.fullmatch(entry["hint"]), f"case {index}: hint charset"
        if not any(isinstance(i["post"].get("x-ask-example"), str) for i in doc["paths"].values() if "post" in i):
            assert got == [], f"case {index}: items without any example"


@pytest.mark.parametrize("count,limit", [(12, 12), (13, 12), (13, 13), (13, 99)])
def test_cap_is_twelve(count, limit):
    paths = {
        f"/flows/f{n}": {"post": {"summary": "s", "x-ask-example": f"What is f{n}?"}}
        for n in range(count)
    }
    result = run_listing([{"paths": paths}], limit, 500)[0]
    assert [e["text"] for e in result["examples"]] == [f"What is f{n}?" for n in range(min(count, 12))]


# Feature: polish, Property 5: A hint ends at a whole word
#
# Property 5 (task 7.4): for any string, ``hintText`` returns at most 100 printable ASCII
# characters, equal to the Python model of Requirement 10, and when the result ends with
# ``...`` the text before the dots is a prefix of the normalised input that ends at a word
# boundary of the input.
#
# **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**

import json
import subprocess

from tests.console_node import NODE, snippets_source

_HINT_RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.snippets,'utf8').toString('base64'));"
    "process.stdout.write(JSON.stringify(p.texts.map(t=>m.hintText(t))));});"
)

HINT_MAX = 100
TRAILING = " .!?,;:"


def run_hints(texts):
    """``hintText`` from the packaged ``snippets.js`` over each text, one node process."""
    done = subprocess.run(
        [NODE, "-e", _HINT_RUNNER],
        input=json.dumps({"snippets": snippets_source(), "texts": texts}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    assert len(results) == len(texts)
    return results


def normalise(text):
    """Requirement 10.1: non-printable to blank, runs of blanks to one, trimmed."""
    out = "".join(ch if "\x20" <= ch <= "\x7e" else " " for ch in text)
    return re.sub(" +", " ", out).strip(" ")


def first_sentence(norm):
    for i, ch in enumerate(norm):
        if ch in ".!?" and (i + 1 == len(norm) or norm[i + 1] == " "):
            return norm[: i + 1]
    return norm


def hint_model(text):
    """Requirement 10.2 to 10.5."""
    start = first_sentence(normalise(text))
    if len(start) <= HINT_MAX:
        return start
    cut = start.rfind(" ", 0, 98)  # last blank at index 97 or lower
    if cut <= 0:
        return ""
    kept = start[:cut].rstrip(TRAILING)
    return kept + "..." if kept else ""


_WORD = st.one_of(
    st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=12),
    st.text(alphabet=string.ascii_letters, min_size=60, max_size=130),
    st.text(alphabet=string.ascii_letters + ",;:'-", min_size=1, max_size=15),
)
_GAP = st.sampled_from([" ", " ", " ", "  ", "   ", "\t", "\n", "\r\n", " \n ", "\u00a0", "\u3000"])
_MARK = st.sampled_from([".", "!", "?", ". ", "! ", "? ", "...", ", ", "; ", ": ", "?!", ".x"])
_NONASCII = st.sampled_from(["\u00e9", "caf\u00e9", "\u2603", "\u4e2d\u6587", "\U0001f600", "\x00", "\x7f", "\x1f"])
_PIECE = st.one_of(_WORD, _WORD, _WORD, _GAP, _GAP, _MARK, _NONASCII)
TEXT = st.lists(_PIECE, max_size=90).map(lambda parts: "".join(parts)[:400])


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(texts=st.lists(TEXT, min_size=1, max_size=8))
def test_hint_ends_at_a_whole_word(texts):
    results = run_hints(texts)
    for index, (text, got) in enumerate(zip(texts, results)):
        assert isinstance(got, str), f"case {index}: type"
        assert len(got) <= HINT_MAX, f"case {index}: length {len(got)}"
        assert all("\x20" <= ch <= "\x7e" for ch in got), f"case {index}: charset"
        assert got == hint_model(text), f"case {index}: differs from the model"
        if len(first_sentence(normalise(text))) > HINT_MAX and got != "":
            # A cut: a short text that merely ends in dots is returned unchanged.
            assert got.endswith("..."), f"case {index}: a cut hint has no ellipsis"
            before = got[:-3]
            norm = normalise(text)
            assert before != "", f"case {index}: empty before the dots"
            assert norm.startswith(before), f"case {index}: not a prefix of the normalised input"
            rest = norm[len(before):]
            assert rest != "" and rest[0] in TRAILING, f"case {index}: cut inside a word"
            assert before[-1] not in TRAILING, f"case {index}: trailing mark kept"
            # hintText strips trailing marks from the end of the kept text only, so only the
            # last kept word is compared after the same strip; the others are whole raw words.
            words = set(norm.split(" "))
            stripped = {word.rstrip(TRAILING) for word in words}
            *leading, last = before.split(" ")
            for word in leading:
                assert word in words, f"case {index}: a word that the input does not have"
            assert last in stripped, f"case {index}: a word that the input does not have"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Reads the clock. Second sentence.", "Reads the clock."),
        ("x" * 300, ""),
        (" ".join(["word"] * 30), " ".join(["word"] * 19) + "..."),
        (None, ""),
    ],
)
def test_hint_examples(text, expected):
    assert run_hints([text])[0] == expected


# Feature: polish, Property 6: outputClass marks exactly the multi-line values
#
# Property 6 (task 7.5): for any value, ``outputClass`` returns ``"multiline"`` when the
# value is a string that contains LF (alone or in CR LF), and ``null`` for every other
# value: strings without LF (including a lone CR and other whitespace), numbers, null and
# lists (even a list of strings that contain LF).
#
# **Validates: Requirements 11.1**

_CLASS_RUNNER = (
    "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);"
    "process.stdin.on('end',async()=>{const p=JSON.parse(s);"
    "const m=await import('data:text/javascript;base64,'+Buffer.from(p.snippets,'utf8').toString('base64'));"
    "process.stdout.write(JSON.stringify(p.values.map(v=>m.outputClass(v))));});"
)


def run_output_class(values):
    """``outputClass`` from the packaged ``snippets.js`` over each value, one node process."""
    done = subprocess.run(
        [NODE, "-e", _CLASS_RUNNER],
        input=json.dumps({"snippets": snippets_source(), "values": values}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if done.returncode != 0:
        raise RuntimeError(f"node exited with code {done.returncode}")
    results = json.loads(done.stdout)
    assert len(results) == len(values)
    return results


def output_class_model(value):
    return "multiline" if isinstance(value, str) and "\n" in value else None


_LINE_GAP = st.sampled_from(["\n", "\r\n", "\n\n", " \n", "\n "])
_OTHER_GAP = st.sampled_from([" ", "\t", "\r", "\x0b", "\x0c", "\u00a0", "\u2028", "\u3000"])
_CLASS_PIECE = st.one_of(
    st.text(alphabet=string.ascii_letters + string.digits, max_size=10),
    _LINE_GAP,
    _OTHER_GAP,
    _OTHER_GAP,
)
_CLASS_TEXT = st.lists(_CLASS_PIECE, max_size=12).map("".join)
_CLASS_VALUE = st.one_of(
    _CLASS_TEXT,
    _CLASS_TEXT,
    _CLASS_TEXT,
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
    st.lists(_CLASS_TEXT, max_size=3),
    st.just(["a\nb"]),
)


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(values=st.lists(_CLASS_VALUE, min_size=1, max_size=12))
def test_output_class_marks_exactly_the_multiline_values(values):
    results = run_output_class(values)
    for index, (value, got) in enumerate(zip(values, results)):
        assert got == output_class_model(value), f"case {index}: {value!r} gave {got!r}"


@pytest.mark.parametrize(
    "value,expected",
    [("a\nb", "multiline"), ("a\r\nb", "multiline"), ("a\rb", None), ("a", None), ("", None), ("a b", None), (136, None), (None, None), (["a\nb"], None)],
)
def test_output_class_examples(value, expected):
    assert run_output_class([value])[0] == expected
