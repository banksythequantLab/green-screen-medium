"""Shared Hypothesis strategies for the publisher property tests (task 7.1).

Everything here is cheap: the alphabets, pools and strategy objects are built once at
import, and a draw is a few integers or one short text mapped through a pure function.
Nothing here starts an app, a thread or a session, and no value is a credential.

Probe_Values (Requirements Glossary, 20.10)
    A ``str`` probe has at least 4 characters, all from ``PROBE_ALPHABET``. That alphabet
    holds symbols only, and none of them occurs in any fixed response text (the fixed
    ``MESSAGES``, Flow, Input, Output and Signature names, the Reason_Codes), so a hit of
    a probe in a response or a log record is always a leak. An ``int`` probe has at least
    4 digits. Undeclared Input names come from ``NAME_ALPHABET``, which shares no
    character with ``PROBE_ALPHABET``, because an ``input_invalid`` message may name an
    undeclared Input by design.

Hypothesis conventions
    The repo has no Hypothesis profile and no ``pyproject`` settings. Each property test
    carries ``@settings(max_examples=100, deadline=None)``; ``SETTINGS`` is that value.
"""
from __future__ import annotations

import base64
import functools
import json
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypothesis import settings
from hypothesis import strategies as st

from greenscreen.flow.model import Flow, InputSpec
from greenscreen.connector import (
    ConfigurationError,
    ConnectorTimeoutError,
    ParseError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.flow.errors import FlowDefinitionError
from tests.publisher_support import (
    FAILURE_POINTS,
    MINI,
    Failure,
    FakeHost,
    mini_states,
)

SETTINGS = settings(max_examples=100, deadline=None)

# Symbols only; `"` is left out (it is JSON structure in every response) but the
# backslash is in, so the JSON-escaped form differs from the plain form for some probes.
PROBE_ALPHABET = "~^!#%&*+=|;?@\\"
NAME_ALPHABET = "qxzjkw"
DIGITS = "0123456789"
assert not set(PROBE_ALPHABET) & set(NAME_ALPHABET)
assert not set(PROBE_ALPHABET) & set(DIGITS)

# --------------------------------------------------------------------------
# Probe_Values and Leak_Forms
# --------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _str_probes(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    return st.text(alphabet=PROBE_ALPHABET, min_size=min_size, max_size=max_size)


@functools.lru_cache(maxsize=None)
def _int_probes(min_digits: int, max_digits: int) -> st.SearchStrategy[int]:
    return st.integers(10 ** (min_digits - 1), 10**max_digits - 1)


def probes(
    kind: str = "str", *, min_size: int = 4, max_size: int = 8
) -> st.SearchStrategy[Any]:
    """A Probe_Value: ``"str"`` (4 or more symbol characters), ``"int"`` (4 or more digits,
    no sign, no leading zero) or ``"any"`` (either)."""
    if min_size < 4:
        raise ValueError("a Probe_Value has at least 4 characters")
    if max_size < min_size:
        raise ValueError("max_size must be at least min_size")
    if kind == "str":
        return _str_probes(min_size, max_size)
    if kind == "int":
        return _int_probes(min_size, max_size)
    if kind == "any":
        return st.one_of(_str_probes(min_size, max_size), _int_probes(min_size, max_size))
    raise ValueError(f"unknown probe kind {kind!r}")


def undeclared_names() -> st.SearchStrategy[str]:
    """Input names no Flow declares, from an alphabet disjoint from every Probe_Value."""
    return st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=8)


def leak_forms(value: Any) -> tuple[str, ...]:
    """Every Leak_Form of ``value`` (rendered with ``str()``), without duplicates.

    Plain; JSON-escaped (``json.dumps`` without the quotes); URL-quoted
    (``quote(v, safe="")``) and quote-plus; the UTF-8 bytes in hex, lower and upper case,
    each with and without a space between bytes; the UTF-8 bytes in base64 and in
    URL-safe base64, each with and without padding. Empty forms are dropped.
    """
    text = str(value)
    raw = text.encode("utf-8")
    forms: list[str] = [
        text,
        json.dumps(text)[1:-1],
        urllib.parse.quote(text, safe=""),
        urllib.parse.quote_plus(text),
    ]
    for upper in (False, True):
        pairs = [f"{b:02X}" if upper else f"{b:02x}" for b in raw]
        forms += ["".join(pairs), " ".join(pairs)]
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        padded = encode(raw).decode("ascii")
        forms += [padded, padded.rstrip("=")]
    return tuple(dict.fromkeys(f for f in forms if f))


def all_leak_forms(values: Iterable[Any]) -> tuple[str, ...]:
    """The Leak_Forms of several values, without duplicates."""
    return tuple(dict.fromkeys(f for v in values for f in leak_forms(v)))


def find_leaks(haystack: str, values: Iterable[Any]) -> list[str]:
    """The Leak_Forms of ``values`` that occur in ``haystack`` (empty when clean)."""
    return [f for f in all_leak_forms(values) if f in haystack]


# --------------------------------------------------------------------------
# bound_sets: which Inputs are bound, supplied or left out
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundSet:
    """One split of a Flow's Inputs. ``bound`` becomes ``GS_BIND_*`` values, ``supplied``
    becomes the values of the Call. Both hold Probe_Values (``str`` or ``int``)."""

    bound: Mapping[str, Any]
    supplied: Mapping[str, Any]

    def env(self, flow_name: str) -> dict[str, str]:
        """The Binding_Variables of ``bound`` (names as Requirement 22 spells them)."""
        prefix = f"GS_BIND_{flow_name.upper().replace('-', '_')}__"
        return {prefix + n.upper().replace("-", "_"): str(v) for n, v in self.bound.items()}

    @property
    def values(self) -> tuple[Any, ...]:
        return tuple(self.bound.values()) + tuple(self.supplied.values())


def _probe_for(spec: InputSpec) -> st.SearchStrategy[Any]:
    if spec.regex is not None:
        raise ValueError(f"input {spec.name!r} has a regex; no probe is guaranteed to match")
    if spec.max_length < 4:
        raise ValueError(f"input {spec.name!r} cannot hold a Probe_Value (max_length < 4)")
    kind = "int" if spec.type == "int" else "str"
    return probes(kind, max_size=min(spec.max_length, 12))


def bound_sets(flow: Flow = MINI) -> st.SearchStrategy[BoundSet]:
    """Every Input of ``flow`` is bound, supplied or (when optional) left out.

    Required Inputs are never left out, so a Call with ``supplied`` and the bound values
    satisfies the Input_Validator. Secret and non-secret Inputs both occur, so the
    property covers a bound Input marked secret and one that is not (``MINI``: the
    secret ``password``, the plain ``userid`` and ``count``). The Flow must have no
    regex and at least 4 characters per Input.
    """
    specs = flow.inputs
    states = [("bound", "supplied") if s.required else ("bound", "supplied", "absent") for s in specs]
    parts = [st.tuples(st.sampled_from(states[i]), _probe_for(s)) for i, s in enumerate(specs)]
    names = [s.name for s in specs]

    def build(drawn: Sequence[tuple[str, Any]]) -> BoundSet:
        bound = {n: v for n, (state, v) in zip(names, drawn) if state == "bound"}
        supplied = {n: v for n, (state, v) in zip(names, drawn) if state == "supplied"}
        return BoundSet(bound, supplied)

    return st.tuples(*parts).map(build)


# --------------------------------------------------------------------------
# fake_host_plans
# --------------------------------------------------------------------------


class ArbitraryError(Exception):
    """An arbitrary ``Exception`` subclass (Requirement 20.5)."""


class InjectedBase(BaseException):
    """A ``BaseException`` that is not an ``Exception``."""


_EXCEPTIONS: tuple[type[BaseException], ...] = (
    FlowDefinitionError,
    S3270Error,
    ConnectorTimeoutError,
    ParseError,
    ConfigurationError,
    SessionClosedError,
    OSError,
    RuntimeError,
    ArbitraryError,
)


@dataclass(frozen=True)
class HostPlan:
    """A Fake_Host behaviour for the ``MINI`` Flow: the right screens or the wrong order
    (the Flow stops), plus an optional injected failure."""

    wrong_screens: bool = False
    failure: Failure | None = None

    def build(self) -> FakeHost:
        states = mini_states()
        return FakeHost(list(reversed(states)) if self.wrong_screens else states,
                        failures=(self.failure,) if self.failure else ())


@functools.lru_cache(maxsize=None)
def _failures(message: str, allow_base: bool) -> tuple[Failure | None, ...]:
    excs = _EXCEPTIONS + ((InjectedBase,) if allow_base else ())
    pool: list[Failure | None] = [None] * 6  # success stays common
    for at in FAILURE_POINTS:
        for exc in excs:
            for n in (1, 2):
                pool.append(Failure(at, exc, n, None, message))
    return tuple(pool)


@functools.lru_cache(maxsize=None)
def _plans(message: str, allow_base: bool) -> st.SearchStrategy[HostPlan]:
    return st.builds(
        HostPlan,
        wrong_screens=st.booleans(),
        failure=st.sampled_from(_failures(message, allow_base)),
    )


def fake_host_plans(
    *, message: str = "injected", allow_base: bool = False
) -> st.SearchStrategy[HostPlan]:
    """Fake_Host behaviours: success, a stop on the wrong screens, and a failure at the
    factory, ``open``, any Session call or ``close`` with one of nine exception classes.
    ``message`` is the exception text (a marker for Property 7). ``allow_base`` adds a
    ``BaseException`` that is not an ``Exception``. ``FlowError`` and ``FlowInputError``
    need constructor arguments; pass an instance in a ``Failure`` yourself."""
    return _plans(message, allow_base)


# --------------------------------------------------------------------------
# bad_requests
# --------------------------------------------------------------------------

REST_KINDS = (
    "wrong_type", "too_long", "undeclared", "missing", "malformed", "duplicate",
    "duplicate_nested", "nan", "infinity", "non_object", "oversize", "media_type",
)
MCP_KINDS = ("wrong_type", "too_long", "undeclared", "missing")


@dataclass(frozen=True)
class BadRequest:
    """A request that fails validation. ``body`` and ``content_type`` are for REST.
    ``arguments`` is the MCP argument mapping, ``None`` when the kind has no MCP form
    (malformed JSON, duplicate key, non-finite number, non-object, size, media type).
    ``values`` are the submitted probes (leak-check every one)."""

    kind: str
    body: bytes
    content_type: str
    arguments: dict[str, Any] | None
    values: tuple[Any, ...]
    names: tuple[str, ...] = field(default=())  # undeclared names sent (not secrets)


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _bad(kind: str, args: dict[str, Any], values: tuple[Any, ...], names: tuple[str, ...] = ()) -> BadRequest:
    return BadRequest(kind, _dumps(args), "application/json", args, values, names)


def _raw(kind: str, text: str, values: tuple[Any, ...], content_type: str = "application/json") -> BadRequest:
    return BadRequest(kind, text.encode("utf-8"), content_type, None, values)


@functools.lru_cache(maxsize=None)
def _bad_requests(max_body: int, bound_input: str | None) -> st.SearchStrategy[BadRequest]:
    p, q, r = probes("str"), probes("str"), probes("str")
    n = probes("int")
    long_ = probes("str", min_size=9, max_size=40)
    kinds = REST_KINDS + (("bound_name",) if bound_input else ())

    def build(kind: str, sub: int, a: str, b: str, c: str, num: int, longer: str, name: str) -> BadRequest:
        j = json.dumps
        if kind == "wrong_type":
            args: dict[str, Any]
            if sub == 0:
                args = {"userid": num}
                return _bad(kind, args, (num,))
            if sub == 1:
                args = {"userid": a, "count": b}
                return _bad(kind, args, (a, b))
            args = {"userid": [a]}
            return _bad(kind, args, (a,))
        if kind == "too_long":
            return _bad(kind, {"userid": longer}, (longer,))
        if kind == "undeclared":
            return _bad(kind, {"userid": a, name: b}, (a, b), (name,))
        if kind == "missing":
            return _bad(kind, {"password": a}, (a,))
        if kind == "bound_name":
            return _bad(kind, {"userid": a, bound_input or "": b}, (a, b))
        if kind == "malformed":
            return _raw(kind, '{"userid": ' + j(a)[:-1], (a,))
        if kind == "duplicate":
            return _raw(kind, '{"userid": ' + j(a) + ', "userid": ' + j(b) + "}", (a, b))
        if kind == "duplicate_nested":
            return _raw(
                kind, '{"userid": ' + j(a) + ', "password": {"k": ' + j(b) + ', "k": ' + j(c) + "}}",
                (a, b, c),
            )
        if kind in ("nan", "infinity"):
            bad = "NaN" if kind == "nan" else "Infinity"
            return _raw(kind, '{"userid": ' + j(a) + ', "count": ' + bad + "}", (a,))
        if kind == "non_object":
            return _raw(kind, "[" + j(a) + "]", (a,))
        if kind == "oversize":
            pad = "A" * (max_body + 16)
            return _raw(kind, '{"userid": ' + j(a) + ', "password": "' + pad + '"}', (a,))
        if kind == "media_type":
            return BadRequest(kind, _dumps({"userid": a}), "text/plain", None, (a,))
        raise AssertionError(kind)

    return st.builds(
        build, st.sampled_from(kinds), st.integers(0, 2), p, q, r, n, long_, undeclared_names()
    )


def bad_requests(
    max_body: int = 2048, *, bound_input: str | None = None
) -> st.SearchStrategy[BadRequest]:
    """Requests that fail validation, for the ``MINI`` Flow (``userid`` required string of
    at most 8, optional secret ``password`` string, optional ``count`` int of at most 4
    digits): wrong type, too long, undeclared name (from the disjoint alphabet), missing
    Input, malformed JSON, duplicate key (also nested), ``NaN``, ``Infinity``, non-object
    body, oversize body (more than ``max_body`` bytes) and wrong media type. With
    ``bound_input`` set, a request that also supplies that Input (the caller must have
    bound it). ``MINI`` has no regex, so a regex violation is not generated."""
    return _bad_requests(max_body, bound_input)


# --------------------------------------------------------------------------
# key_headers
# --------------------------------------------------------------------------

_KEY_CHARS = st.characters(min_codepoint=0x21, max_codepoint=0x7E)

KEY_KINDS: tuple[tuple[str, bool], ...] = (
    # (kind, accepted)
    ("valid_api", True), ("valid_bearer", True), ("valid_bearer_case", True),
    ("valid_both", True), ("valid_bearer_spaces", True),
    ("wrong_api", False), ("wrong_bearer", False), ("both_differ", False),
    ("api_valid_bearer_wrong", False), ("api_wrong_bearer_valid", False),
    ("both_equal_wrong", False), ("other_scheme", False), ("bearer_no_credentials", False),
    ("bearer_inner_space", False), ("bearer_non_ascii", False), ("auth_repeated", False),
    ("api_repeated", False), ("empty_api", False), ("empty_api_valid_bearer", False),
    ("no_key", False),
)


@dataclass(frozen=True)
class KeyCase:
    """Raw ASGI request headers and whether the Auth_Guard must accept them."""

    kind: str
    headers: tuple[tuple[bytes, bytes], ...]
    accepted: bool


def key_headers(api_key: str) -> st.SearchStrategy[KeyCase]:
    """Key headers around ``api_key`` (printable ASCII without spaces): the valid key in
    either Key_Carrier or in both, wrong keys in either or both, differing pairs, every
    malformed ``Authorization`` form, repeated headers and an empty ``X-API-Key`` with and
    without a valid Bearer header. ``extract_key`` is the oracle of the first part; this
    strategy states the expected outcome of Requirement 13, criterion 11 on its own."""
    good = api_key.encode("utf-8")
    wrong = st.text(alphabet=_KEY_CHARS, min_size=1, max_size=40).filter(lambda s: s != api_key)
    spaces = st.integers(1, 4)

    def build(idx: int, w1: str, w2: str, n: int) -> KeyCase:
        kind, accepted = KEY_KINDS[idx]
        bad1, bad2 = w1.encode(), w2.encode()
        if bad1 == bad2:
            bad2 = bad1 + b"x"
        api, auth = b"x-api-key", b"authorization"
        bearer = lambda k: b"Bearer " + k  # noqa: E731
        table: dict[str, list[tuple[bytes, bytes]]] = {
            "valid_api": [(api, good)],
            "valid_bearer": [(auth, bearer(good))],
            "valid_bearer_case": [(auth, b"bEaReR " + good)],
            "valid_bearer_spaces": [(auth, b"Bearer" + b" " * (n + 1) + good)],
            "valid_both": [(api, good), (auth, bearer(good))],
            "wrong_api": [(api, bad1)],
            "wrong_bearer": [(auth, bearer(bad1))],
            "both_differ": [(api, bad1), (auth, bearer(bad2))],
            "api_valid_bearer_wrong": [(api, good), (auth, bearer(bad1))],
            "api_wrong_bearer_valid": [(api, bad1), (auth, bearer(good))],
            "both_equal_wrong": [(api, bad1), (auth, bearer(bad1))],
            "other_scheme": [(auth, b"Basic " + good)],
            "bearer_no_credentials": [(auth, b"Bearer" + b" " * (n - 1))],
            "bearer_inner_space": [(auth, b"Bearer " + bad1 + b" " + bad2)],
            "bearer_non_ascii": [(auth, b"Bearer \xc3\xa9\xc3\xa9\xc3\xa9")],
            "auth_repeated": [(auth, bearer(good)), (auth, bearer(good))],
            "api_repeated": [(api, good), (api, good)],
            "empty_api": [(api, b"")],
            "empty_api_valid_bearer": [(api, b""), (auth, bearer(good))],
            "no_key": [],
        }
        return KeyCase(kind, tuple(table[kind]), accepted)

    return st.builds(build, st.integers(0, len(KEY_KINDS) - 1), wrong, wrong, spaces)


# --------------------------------------------------------------------------
# binding_envs
# --------------------------------------------------------------------------

_NAME_SHAPES = 8
_VALUE_SHAPES = 6


def _norm(name: str) -> str:
    return name.upper().replace("-", "_")


def _binding_name(shape: int, flow: str, name: str) -> str:
    f, i = _norm(flow), _norm(name)
    return {
        0: f"GS_BIND_{f}__{i}",          # valid
        1: f"GS_BIND_{f.lower()}__{i}",  # lower-case Flow part
        2: f"GS_BIND_{f}__{i.lower()}",  # lower-case Input part
        3: f"GS_BIND_{f}__",             # missing Input part
        4: f"GS_BIND___{i}",             # missing Flow part
        5: f"GS_BIND_{f}_{i}",           # no separator
        6: f"GS_BIND_NOFLOW__{i}",       # unknown Flow
        7: f"GS_BIND_{f}__NOINPUT",      # unknown Input
    }[shape]


def _binding_value(shape: int, spec: InputSpec, probe: str) -> str:
    if shape == 0:
        return probe if spec.type == "str" else probe_digits(probe, spec.max_length)
    if shape == 1:
        return ""                                   # empty: unset
    if shape == 2:
        return (probe * 40)[: spec.max_length + 1]  # too long
    if shape == 3:
        return "\t" + probe                         # not printable ASCII
    if shape == 4:
        return "12a" + probe                        # bad int text, odd str
    return probe                                    # as drawn (bad int text for int Inputs)


def probe_digits(seed: str, max_length: int) -> str:
    """A digit string of at most ``max_length`` (and 8) digits made from ``seed``."""
    n = max(1, min(max_length, 8))
    digits = "".join(str(ord(c) % 10) for c in (seed * 4)[:n])
    return ("1" + digits)[:n]


_PUBLISH_SHAPES = 7


def _publish_list(shape: int, names: Sequence[str], picks: Sequence[int]) -> str | None:
    chosen = [names[i % len(names)] for i in picks] or [names[0]]
    unique = list(dict.fromkeys(chosen))
    return {
        0: None,
        1: "",
        2: ",".join(unique),
        3: " , ".join(unique),
        4: ",".join(unique) + ",",
        5: ",".join(unique + unique[:1]),
        6: ",".join(unique) + ",no-such-flow",
    }[shape]


def binding_envs(
    flows: Mapping[str, Flow], *, publish_list: bool = False
) -> st.SearchStrategy[dict[str, str]]:
    """Environment fragments with Binding_Variables for the given Flows (name -> Flow).

    A fragment holds up to 4 variables. Names are valid, or in the wrong case, or lack a
    part, or name an unknown Flow or Input; values are valid probes, empty, too long, not
    printable, or bad int text. Two draws can name the same variable, and different
    spellings of one name can collide after normalisation. With ``publish_list`` the
    fragment may also hold ``GS_PUBLISH_FLOWS`` (unset, empty, valid, spaced, with an empty
    item, with a duplicate, with an unknown name). The outcome is decided by the test's
    own model of Requirement 22; this strategy only draws the environment."""
    names = tuple(flows)
    if not names:
        raise ValueError("binding_envs needs at least one Flow")
    with_inputs = tuple((fn, s) for fn, f in flows.items() for s in f.inputs)
    if not with_inputs:
        raise ValueError("binding_envs needs a Flow with at least one Input")
    entry = st.tuples(
        st.integers(0, len(with_inputs) - 1), st.integers(0, _NAME_SHAPES - 1),
        st.integers(0, _VALUE_SHAPES - 1), probes("str"),
    )
    base = st.lists(entry, max_size=4)

    def build(entries, shape: int, picks: Sequence[int]) -> dict[str, str]:
        env: dict[str, str] = {}
        for idx, name_shape, value_shape, probe in entries:
            flow_name, spec = with_inputs[idx]
            env[_binding_name(name_shape, flow_name, spec.name)] = _binding_value(value_shape, spec, probe)
        if publish_list:
            text = _publish_list(shape, names, picks)
            if text is not None:
                env["GS_PUBLISH_FLOWS"] = text
        return env

    return st.builds(build, base, st.integers(0, _PUBLISH_SHAPES - 1), st.lists(st.integers(0, 7), max_size=3))
