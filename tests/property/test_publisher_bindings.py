"""Property 14: the publish list and the binding variables either start cleanly or stop.

One example is one startup: generated extra Flows are written to a temporary ``GS_FLOWS_DIR``
(after the three bundled Flows, in file order), the generated ``GS_PUBLISH_FLOWS`` and
``GS_BIND_*`` variables go into an injected environment, and ``prepare`` runs in process.
``MODEL`` below is a small independent model of Requirements 1.9 to 1.15 and 22 that decides
the expected outcome from the Flow declarations and the environment alone.

* Accepted run: the registry holds exactly the selected Flows in loading order, the bound
  values equal the model's, every bound value passes the Input_Validator over the full spec,
  and no bound name is in any schema, ``tools/list`` entry or OpenAPI path. The app is then
  built and run in the Fake_Host seam: ``/health`` counts the published Flows, no session is
  created.
* Stopped run: the ``StartupError`` message holds the tokens the model expects (the variable,
  Flow or family, and the rule).
* Both: no Leak_Form of any binding value in the message, its repr or traceback, in stdout
  and stderr, in any log record of startup and shutdown (all loggers at DEBUG), in
  ``/health``, in the OpenAPI document or in ``tools/list``; no session process is started.

Binding values are made-up symbols and letters, not credentials. No loader is patched.
Failure messages are fixed text and the generated case has a repr without values, so a failing
run prints no bound value.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import io
import logging
import re
import subprocess
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greenscreen.flow import FlowInputError, load_bundled_flows
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep
from greenscreen.publisher.app import _THIRD_PARTY_LOGGERS, build_app, prepare
from greenscreen.publisher.config import StartupError
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import SETTINGS, all_leak_forms, binding_envs
from tests.publisher_support import FakeHost, LogCapture, mcp_client, mini_states, rest_client

API_KEY = "Kq" * 10
BASE_ENV = {"GS_S3270_BINARY": "s3270", "GS_HOST": "host.invalid", "GS_API_KEY": API_KEY}


# --------------------------------------------------------------------------
# Generated Flows: a pool of small Flows, a random unique subset is written to disk
# --------------------------------------------------------------------------

def _flow(name: str, *inputs: InputSpec) -> Flow:
    return Flow(name=name, steps=(ExpectStep(("tk5-logon",)), KeyStep("enter")), inputs=inputs)


POOL: dict[str, Flow] = {
    f.name: f
    for f in (
        _flow("alpha", InputSpec("user", "str", True, 8), InputSpec("pw", "str", False, 8, None, True),
              InputSpec("amt", "int", False, 6)),
        _flow("beta", InputSpec("Code", "str", True, 8, "[A-Z]+"), InputSpec("n_1", "int", True, 6)),
        _flow("a-b", InputSpec("user", "str", True, 8), InputSpec("User", "str", False, 8)),
        _flow("a_b", InputSpec("a__b", "str", False, 8), InputSpec("x", "str", False, 8)),  # collides with a-b
        _flow("x__y", InputSpec("user", "str", True, 8)),   # '__' in the normalised name
        _flow("x_", InputSpec("user", "str", True, 8)),     # trailing '_'
        _flow("tk5_logon", InputSpec("userid", "str", True, 8)),  # collides with the bundled tk5-logon
        _flow("w-1"),                                        # no Inputs
    )
}


@functools.lru_cache(maxsize=1)
def _bundled() -> dict[str, Flow]:
    return load_bundled_flows()


# --------------------------------------------------------------------------
# The independent model of Requirements 1.9 to 1.15 and 22
# --------------------------------------------------------------------------

def _norm(name: str) -> str:
    return name.upper().replace("-", "_")


def _model_value(text: str, spec: InputSpec):
    """The parsed value, or the rule that rejects ``text`` (Requirement 22, criteria 4 and 5)."""
    if spec.type == "int":
        if re.fullmatch(r"-?[0-9]+", text) is None or len(text) > spec.max_length:
            return None, "value_invalid"
        value: str | int = int(text)
    else:
        value = text
    rendered = str(value)
    if len(rendered) > spec.max_length:
        return None, "max_length"
    if any(not 0x20 <= ord(c) <= 0x7E for c in rendered):
        return None, "printable_ascii"
    if spec.regex is not None and re.fullmatch(spec.regex, rendered) is None:
        return None, "regex"
    return value, None


def MODEL(loaded: dict[str, Flow], env: dict[str, str]):
    """``("ok", selected_names, {flow: {input: value}})`` or ``("stop", tokens)``.

    ``tokens`` are the names a message must hold: the variable, Flow or family, and the rule.
    """
    order = list(loaded)  # loading order

    # Requirements 1.9 to 1.14: the Publish_List.
    text = env.get("GS_PUBLISH_FLOWS")
    selected = order
    if text:
        items = [i.strip() for i in text.split(",")]
        if "" in items:
            return ("stop", ("GS_PUBLISH_FLOWS", "empty_item"))
        for k, item in enumerate(items):
            if item in items[:k]:
                return ("stop", ("GS_PUBLISH_FLOWS", item, "duplicate_name"))
        for item in items:
            if item not in loaded:
                return ("stop", ("GS_PUBLISH_FLOWS", item, "unknown_flow"))
        selected = [n for n in order if n in items]

    # Requirement 22: the Binding_Variables, in ascending name order.
    binds = sorted((n, v) for n, v in env.items() if n.startswith("GS_BIND_") and v != "")
    bound: dict[str, dict[str, object]] = {}
    if not binds:
        return ("ok", selected, bound)

    split = []
    for name, _ in binds:
        rest = name[len("GS_BIND_"):]
        i = rest.find("__")
        if i <= 0 or rest[i + 2:] == "":
            return ("stop", (name, "name_format"))
        split.append((name, rest[:i], rest[i + 2:]))

    for fname in selected:
        if "__" in _norm(fname) or _norm(fname).endswith("_"):
            return ("stop", (fname, "ambiguous_name"))

    for name, flow_part, input_part in split:
        matches = [f for f in order if _norm(f) == flow_part]
        if not matches:
            return ("stop", (name, "unknown_flow"))
        if len(matches) > 1:
            return ("stop", (f"GS_BIND_{flow_part}__", "ambiguous_name"))
        fname = matches[0]
        if fname not in selected:
            return ("stop", (name, "flow_not_published"))
        specs = [s for s in loaded[fname].inputs if _norm(s.name) == input_part]
        if not specs:
            return ("stop", (name, "unknown_input"))
        if len(specs) > 1:
            return ("stop", (f"GS_BIND_{flow_part}__{input_part}", "ambiguous_name"))
        value, rule = _model_value(env[name], specs[0])
        if rule is not None:
            return ("stop", (name, rule))
        bound.setdefault(fname, {})[specs[0].name] = value
    return ("ok", selected, bound)


# --------------------------------------------------------------------------
# Generated cases
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Case:
    extra: tuple[str, ...]
    env: dict[str, str]
    mode: str

    def __repr__(self) -> str:  # names and rules only: a failure prints no binding value
        return (f"Case(extra={self.extra}, mode={self.mode}, "
                f"publish={self.env.get('GS_PUBLISH_FLOWS')!r}, variables={sorted(k for k in self.env if k != 'GS_PUBLISH_FLOWS')})")


_CLEAN_TEXT = st.text(alphabet="QWXZ", min_size=4, max_size=8)
_CLEAN_INT = st.integers(100000, 899999)


def _clean_env(flows: dict[str, Flow]) -> st.SearchStrategy[dict[str, str]]:
    """Valid variables for generated pairs, plus a valid or unset Publish_List."""
    pairs = [(fn, s) for fn, f in flows.items() for s in f.inputs]

    @st.composite
    def build(draw):
        picks = draw(st.lists(st.integers(0, len(pairs) - 1), unique=True, max_size=4))
        env: dict[str, str] = {}
        for k in picks:
            fn, spec = pairs[k]
            value = draw(_CLEAN_INT if spec.type == "int" else _CLEAN_TEXT)
            env[f"GS_BIND_{_norm(fn)}__{_norm(spec.name)}"] = str(value)
        shape = draw(st.integers(0, 3))
        if shape == 0:
            return env
        if shape == 1:
            env["GS_PUBLISH_FLOWS"] = ""
            return env
        chosen = {pairs[k][0] for k in picks}
        more = draw(st.lists(st.sampled_from(sorted(flows)), unique=True, max_size=3))
        names = draw(st.permutations(sorted(chosen | set(more)))) or [sorted(flows)[0]]
        env["GS_PUBLISH_FLOWS"] = (", " if shape == 3 else ",").join(names)
        return env

    return build()


@st.composite
def cases(draw) -> Case:
    extra = tuple(draw(st.lists(st.sampled_from(sorted(POOL)), unique=True, max_size=4)))
    flows = {**_bundled(), **{n: POOL[n] for n in extra}}
    if draw(st.booleans()):
        env = draw(binding_envs(flows, publish_list=True))
    else:
        env = draw(_clean_env(flows))
    return Case(extra, env, draw(st.sampled_from(("legacy", "auto"))))


# --------------------------------------------------------------------------
# One startup
# --------------------------------------------------------------------------

def _require(ok: bool, message: str) -> None:
    """A check with fixed-text failure: no operand (so no binding value) is ever printed."""
    if not ok:
        raise AssertionError(message)


@pytest.fixture(scope="module", autouse=True)
def _restore_logger_levels():
    names = ("",) + tuple(_THIRD_PARTY_LOGGERS)
    saved = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


def _spec_for(flow: Flow, name: str) -> InputSpec:
    return next(s for s in flow.inputs if s.name == name)


async def _run_app(prepared, mode: str, host: FakeHost) -> tuple[int, str, str, dict[str, set[str]], dict[str, set[str]]]:
    """Start the app, read /health, /openapi.json and tools/list, shut it down."""
    app = build_app(prepared, session_factory=host, clock=FakeClock(), poll_interval=1.0)
    async with contextlib.AsyncExitStack() as stack:
        rest = await stack.enter_async_context(rest_client(app, headers={"X-API-Key": API_KEY}))
        mcp = await stack.enter_async_context(mcp_client(app, mode))
        health = await rest.get("/health")
        doc = await rest.get("/openapi.json")
        listing = await mcp.list_tools()
    props_api = {
        p[len("/flows/"):]: set(op["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"])
        for p, op in doc.json()["paths"].items() if p.startswith("/flows/")
    }
    props_mcp = {t.name: set(t.input_schema["properties"]) for t in listing.tools}
    texts = health.text + "\n" + doc.text + "\n" + "\n".join(t.model_dump_json() for t in listing.tools)
    health_flows = health.json()["flows"] if health.status_code == 200 else -1
    return health_flows, health.text, texts, props_api, props_mcp


def _scan(texts: list[str], forms: tuple[str, ...]) -> bool:
    return any(f in t for t in texts for f in forms)


# Feature: publisher, Property 14: Publish list and binding variables either start cleanly or stop the startup
@SETTINGS
@given(cases())
def test_publish_list_and_bindings_start_cleanly_or_stop(case):
    """**Validates: Requirements 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 22.1, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8, 22.9, 22.10, 22.12, 7.8**"""
    loaded = {**_bundled(), **{n: POOL[n] for n in case.extra}}
    forms = all_leak_forms([v for k, v in case.env.items() if k.startswith("GS_BIND_")])
    expected = MODEL(loaded, case.env)

    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)  # build_app applies the clamp again
    out, err = io.StringIO(), io.StringIO()
    host = FakeHost(mini_states())

    with tempfile.TemporaryDirectory() as tmp, LogCapture() as cap, \
            mock.patch.object(subprocess.Popen, "__init__", side_effect=AssertionError("a process was started")), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        for i, name in enumerate(case.extra):  # file order = draw order = loading order
            (Path(tmp) / f"f{i:02d}.yaml").write_text(POOL[name].to_yaml(), encoding="utf-8")
        environ = {**BASE_ENV, "GS_FLOWS_DIR": tmp, **case.env}

        stopped: StartupError | None = None
        prepared = None
        try:
            prepared = prepare(environ)
        except StartupError as exc:
            stopped = exc
        cap.refresh()

        app_result = None
        if prepared is not None:
            app_result = asyncio.run(_run_app(prepared, case.mode, host))
        cap.refresh()
        records = cap.records

    # --- the outcome equals the model's -----------------------------------------------
    if expected[0] == "stop":
        _require(stopped is not None, "the model stops the startup but prepare returned")
        message = str(stopped)
        _require(all(t in message for t in expected[1]), "stop message lacks the variable, Flow or family, or the rule")
        _require(not _scan([message, repr(stopped), "".join(traceback.format_exception(stopped)),
                            *map(str, stopped.args)], forms), "a Leak_Form is in the StartupError")
    else:
        _require(stopped is None, "the model accepts the startup but prepare stopped")
        _, selected, bound = expected
        reg = prepared.registry
        _require(list(reg) == selected, "the registry is not the selected Flows in loading order")
        for fname in selected:
            actual = dict(prepared.bound.for_flow(fname))
            want = bound.get(fname, {})
            _require(actual == want and all(type(actual[k]) is type(want[k]) for k in want),
                     "bound values differ from the model")
            _require(set(reg[fname].bound_names) == set(want), "bound names differ from the model")
            for iname, value in actual.items():  # accepted by the Input_Validator, full spec
                decl = SimpleNamespace(inputs=(dataclasses.replace(_spec_for(loaded[fname], iname), required=True),))
                try:
                    prepare_inputs(decl, {iname: value})  # type: ignore[arg-type]
                except FlowInputError:
                    raise AssertionError("a bound value fails the Input_Validator") from None
            declared = [s.name for s in loaded[fname].inputs]
            schema = reg[fname].input_schema
            _require(list(schema["properties"]) == [n for n in declared if n not in want],
                     "the schema does not hold exactly the unbound Inputs")
            _require(not set(schema.get("required", ())) & set(want), "a bound name is in required")
        health_flows, health_text, texts, props_api, props_mcp = app_result
        _require(health_flows == len(selected), "/health does not count the published Flows")
        _require(set(props_api) == set(selected) == set(props_mcp), "OpenAPI or tools/list lists other Flows")
        for fname in selected:
            gone = set(bound.get(fname, {}))
            keep = {s.name for s in loaded[fname].inputs} - gone
            _require(props_api[fname] == keep and props_mcp[fname] == keep,
                     "a bound name is in the OpenAPI schema or tools/list, or an unbound Input is missing")
        _require(not _scan([texts], forms), "a Leak_Form is in /health, the OpenAPI document or tools/list")
        _require(host.factory_calls == 0 and host.created == 0, "a session was created")

    # --- both: no Leak_Form in stdout, stderr or any log record --------------------------
    _require(not _scan([out.getvalue(), err.getvalue()], forms), "a Leak_Form is in stdout or stderr")
    leaks = [r.logger for r in records if any(f in t for t in r.texts() for f in forms)]
    _require(not leaks, "a Leak_Form is in a log record")
