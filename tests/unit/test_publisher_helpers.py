"""Tests of the shared publisher test helpers (task 7.1).

Covers ``tests/publisher_support.py`` (LogCapture, frame scanner, clients) and
``tests/property/_publisher_strategies.py``. The Fake_Host has its own test file
(``test_publisher_fake_host.py``). Values are made up here; none is a credential.
"""
from __future__ import annotations

import asyncio
import logging
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.flow.errors import REASON_CODES
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow import load_bundled_flows
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.auth import extract_key
from greenscreen.publisher.calls import HTTP_STATUS, MESSAGES
from greenscreen.publisher.vault import BoundValues, SecretBox
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock
from tests.property import _publisher_strategies as ps
from tests.publisher_support import (
    MCP_MODES,
    MINI,
    FakeHost,
    LogCapture,
    formatted_traceback,
    mcp_client,
    rest_client,
    scan_frames,
    system_info_states,
)

COVER = settings(max_examples=600, deadline=None, derandomize=True)  # deterministic coverage checks
FEW = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# --------------------------------------------------------------------------
# Leak_Forms, spelled out
# --------------------------------------------------------------------------

def test_leak_forms_of_a_value_with_space_and_quote():
    assert set(ps.leak_forms('a b"')) == {
        'a b"',          # plain
        'a b\\"',        # JSON-escaped, without the outer quotes
        "a%20b%22",      # quote(safe="")
        "a+b%22",        # quote_plus
        "61206222",      # hex, lower, no spaces (upper case is the same string)
        "61 20 62 22",   # hex with spaces
        "YSBiIg==",      # base64 (URL-safe is the same string for these bytes)
        "YSBiIg",        # base64 without padding
    }


def test_leak_forms_distinguish_upper_hex_and_url_safe_base64():
    forms = set(ps.leak_forms("~~~?"))
    assert {"7e7e7e3f", "7E7E7E3F", "7e 7e 7e 3f", "7E 7E 7E 3F"} <= forms
    assert {"fn5+Pw==", "fn5+Pw", "fn5-Pw==", "fn5-Pw"} <= forms
    assert "~~~%3F" in forms  # quote and quote_plus give the same text here


def test_leak_forms_of_an_int_use_str():
    assert set(ps.leak_forms(4711)) == {"4711", "34373131", "34 37 31 31", "NDcxMQ==", "NDcxMQ"}


def test_leak_forms_covers_every_form_with_a_value_that_changes_all_of_them():
    # Backslash needs JSON escaping, space needs quote/quote_plus to differ, the byte values
    # give distinct lower and upper hex and distinct base64 alphabets.
    forms = ps.leak_forms("\\ ~~~?x")
    assert len(forms) == len(set(forms))
    assert len(forms) == 12  # plain, json, quote, quote_plus, 2 hex x 2 spacing, 2 b64 x 2 padding


def test_find_leaks_reports_the_forms_found():
    assert ps.find_leaks("nothing here", ["AB~^"]) == []
    assert "41427e5e" in ps.find_leaks("x 41427e5e y", ["AB~^"])


# --------------------------------------------------------------------------
# Probe_Value alphabet is disjoint from fixed text
# --------------------------------------------------------------------------

def _fixed_text() -> list[str]:
    texts = list(MESSAGES.values()) + list(HTTP_STATUS) + list(REASON_CODES)
    texts += [s.name for s in load_bundled_signatures()]
    for flow in load_bundled_flows().values():
        texts += [flow.name, flow.description]
        texts += [i.name for i in flow.inputs] + [i.description for i in flow.inputs]
        texts += [o.name for o in flow.outputs]
    texts += [MINI.name, MINI.description]
    texts += [i.name for i in MINI.inputs] + [o.name for o in MINI.outputs]
    texts += ["error", "code", "message", "flow", "outputs", "audit", "step_index", "kind", "expected",
              "summary", "status", "detail", "no-store", "application/json"]
    return texts


def test_probe_alphabet_is_absent_from_every_fixed_text():
    blob = "\n".join(_fixed_text())
    assert not set(ps.PROBE_ALPHABET) & set(blob)
    assert not re.search(r"\d{4}", "\n".join(MESSAGES.values()))


def test_name_alphabet_shares_no_character_with_probes():
    assert not set(ps.NAME_ALPHABET) & set(ps.PROBE_ALPHABET)
    assert not set(ps.NAME_ALPHABET) & set("0123456789")


@FEW
@given(v=ps.probes("str", max_size=12), n=ps.probes("int", max_size=6), a=ps.probes("any"))
def test_probes_follow_the_glossary(v, n, a):
    assert 4 <= len(v) <= 12 and set(v) <= set(ps.PROBE_ALPHABET)
    assert type(n) is int and 4 <= len(str(n)) <= 6 and n > 0
    assert (isinstance(a, str) and len(a) >= 4) or (type(a) is int and a >= 1000)


@FEW
@given(name=ps.undeclared_names(), v=ps.probes())
def test_undeclared_names_never_overlap_a_probe(name, v):
    assert not set(name) & set(v)


def test_probes_reject_a_size_below_four():
    with pytest.raises(ValueError):
        ps.probes("str", min_size=3)


# --------------------------------------------------------------------------
# The other strategies
# --------------------------------------------------------------------------

@FEW
@given(split=ps.bound_sets())
def test_bound_sets_split_inputs_and_satisfy_the_validator(split):
    assert not set(split.bound) & set(split.supplied)
    merged = {**split.supplied, **split.bound}
    assert "userid" in merged  # required, so never left out
    prepare_inputs(MINI, merged)  # raises FlowInputError when a draw breaks a rule
    env = split.env("mini")
    assert all(k.startswith("GS_BIND_MINI__") for k in env)
    assert set(env.values()) == {str(v) for v in split.bound.values()}


def test_bound_sets_cover_secret_and_plain_bound_inputs():
    seen: set[str] = set()

    @COVER
    @given(split=ps.bound_sets())
    def collect(split):
        seen.update(split.bound)

    collect()
    assert {"userid", "password", "count"} <= seen


def test_bound_sets_reject_a_flow_it_cannot_probe():
    from greenscreen.flow.model import ExpectStep, Flow, InputSpec

    flow = Flow("x", (ExpectStep(("tk5-logon",)),), inputs=(InputSpec("a", "str", True, 8, "[A-Z]+"),))
    with pytest.raises(ValueError):
        ps.bound_sets(flow)


@FEW
@given(plan=ps.fake_host_plans(message="MARK"), base=ps.fake_host_plans(allow_base=True))
def test_fake_host_plans_build_a_fresh_host(plan, base):
    host = plan.build()
    assert isinstance(host, FakeHost) and host.created == 0
    if plan.failure is not None:
        assert plan.failure.message == "MARK" and plan.failure.at in ("factory", "open", "close", "read_screen",
                                                                      "string", "enter", "clear", "pf", "pa")
    assert base.failure is None or isinstance(base.failure.build(), BaseException)


def test_fake_host_plans_reach_every_failure_point_and_a_base_exception():
    points: set[str] = set()
    bases: list[bool] = []

    @COVER
    @given(plan=ps.fake_host_plans(allow_base=True))
    def collect(plan):
        if plan.failure:
            points.add(plan.failure.at)
            bases.append(not isinstance(plan.failure.build(), Exception))

    collect()
    assert points == set(ps.FAILURE_POINTS) and any(bases)


@FEW
@given(req=ps.bad_requests(max_body=512, bound_input="password"))
def test_bad_requests_are_well_formed(req):
    assert req.kind in ps.REST_KINDS + ("bound_name",)
    assert req.values
    for v in req.values:
        assert any(f in req.body.decode("utf-8") for f in ps.leak_forms(v)) or req.kind in ()
    if req.kind == "oversize":
        assert len(req.body) > 512
    else:
        assert len(req.body) < 512
    if req.arguments is not None:
        assert req.kind in ps.MCP_KINDS + ("bound_name",)
    if req.kind == "media_type":
        assert req.content_type == "text/plain"
    if req.kind == "undeclared":
        assert req.names and not set(req.names[0]) & set(ps.PROBE_ALPHABET)


def test_bad_requests_cover_every_kind():
    kinds: set[str] = set()

    @COVER
    @given(req=ps.bad_requests(bound_input="password"))
    def collect(req):
        kinds.add(req.kind)

    collect()
    assert kinds == set(ps.REST_KINDS) | {"bound_name"}


def test_bad_request_bodies_hold_the_malformation():
    import json

    @settings(max_examples=60, deadline=None)
    @given(req=ps.bad_requests())
    def check(req):
        text = req.body.decode("utf-8")
        if req.kind == "malformed":
            with pytest.raises(ValueError):
                json.loads(text)
        elif req.kind == "duplicate":
            assert text.count('"userid"') == 2
        elif req.kind == "duplicate_nested":
            assert text.count('"k"') == 2
        elif req.kind in ("nan", "infinity"):
            assert ("NaN" if req.kind == "nan" else "Infinity") in text
        elif req.kind == "non_object":
            assert isinstance(json.loads(text), list)

    check()


@FEW
@given(case=ps.key_headers("k3y-" + "A" * 20))
def test_key_headers_agree_with_extract_key(case):
    key = "k3y-" + "A" * 20
    presented = extract_key(list(case.headers))
    assert (presented == key) == case.accepted, case.kind


def test_key_headers_reach_every_kind():
    kinds: set[str] = set()

    @COVER
    @given(case=ps.key_headers("k3y-" + "A" * 20))
    def collect(case):
        kinds.add(case.kind)

    collect()
    assert kinds == {k for k, _ in ps.KEY_KINDS}


def _flows():
    return dict(load_bundled_flows())


@FEW
@given(env=ps.binding_envs(_flows(), publish_list=True))
def test_binding_envs_only_hold_binding_and_publish_variables(env):
    assert all(k.startswith("GS_BIND_") or k == "GS_PUBLISH_FLOWS" for k in env)
    assert len(env) <= 5


def test_binding_envs_include_valid_and_broken_names():
    flows = {"mini": MINI}
    names: set[str] = set()
    publish: set[str] = set()

    @COVER
    @given(env=ps.binding_envs(flows, publish_list=True))
    def collect(env):
        names.update(k for k in env if k != "GS_PUBLISH_FLOWS")
        publish.add(env.get("GS_PUBLISH_FLOWS", "<unset>"))

    collect()
    assert "GS_BIND_MINI__USERID" in names and "GS_BIND_mini__USERID" in names
    assert "GS_BIND_MINI__" in names and "GS_BIND_NOFLOW__USERID" in names
    assert {"<unset>", "", "mini", "mini,", "mini,mini", "mini,no-such-flow"} <= publish


def test_binding_envs_need_flows_with_inputs():
    with pytest.raises(ValueError):
        ps.binding_envs({})


# --------------------------------------------------------------------------
# LogCapture
# --------------------------------------------------------------------------

def test_log_capture_sees_a_record_of_a_non_propagating_logger():
    quiet = logging.getLogger("helpers.test.nonpropagating")
    quiet.propagate = False
    quiet.setLevel(logging.DEBUG)
    root_level = logging.getLogger().level
    try:
        with LogCapture() as cap:
            quiet.debug("hello %s", "world")
            logging.getLogger("helpers.test.propagating").debug("up")
        assert [r.message for r in cap.records if r.logger.startswith("helpers.test")] == ["hello world", "up"]
        assert logging.getLogger().level == root_level
        assert not any(isinstance(h, type(cap._handler)) for h in logging.getLogger().handlers)
        assert cap._handler not in quiet.handlers
        quiet.debug("after")  # no longer captured
        assert len(cap.records) == 2
    finally:
        quiet.propagate = True


def test_log_capture_refresh_attaches_to_loggers_created_later():
    with LogCapture() as cap:
        late = logging.getLogger("helpers.test.late")
        late.propagate = False
        late.setLevel(logging.DEBUG)
        try:
            late.info("before refresh")
            cap.refresh()
            late.info("after refresh")
        finally:
            late.propagate = True
        assert [r.message for r in cap.records if r.logger == "helpers.test.late"] == ["after refresh"]


def test_log_capture_records_args_exc_stack_and_fields():
    log = logging.getLogger("helpers.test.fields")
    log.setLevel(logging.DEBUG)
    with LogCapture() as cap:
        try:
            raise ValueError("boom-7")
        except ValueError:
            log.error("oops %s %d", "ARG-1", 42, exc_info=True, stack_info=True, extra={"call_id": "ID-9"})
    (rec,) = [r for r in cap.records if r.logger == "helpers.test.fields"]
    assert rec.message == "oops ARG-1 42"
    assert "ARG-1" in rec.args and "42" in rec.args and "'ARG-1'" in rec.args
    assert "ValueError: boom-7" in rec.exc_info_text
    assert rec.stack_info and rec.stack_info.startswith("Stack")
    assert rec.fields == {"call_id": "ID-9"}
    assert cap.find(["boom-7"]) and cap.find(["ID-9"]) and not cap.find(["absent-text"])
    assert "boom-7" not in " ".join(cap.find(["boom-7"]))  # a finding names no text


def test_log_capture_finds_a_leak_form_in_a_mapping_argument():
    log = logging.getLogger("helpers.test.mapping")
    log.setLevel(logging.DEBUG)
    with LogCapture() as cap:
        log.info("%(a)s", {"a": "VAL~^!"})
    assert cap.find(ps.leak_forms("VAL~^!"))


# --------------------------------------------------------------------------
# Frame scanner
# --------------------------------------------------------------------------

def _raiser(module: str, body: str, *args):
    ns: dict = {"__name__": module}
    exec(f"def f({', '.join(f'a{i}' for i in range(len(args)))}):\n    {body}\n    raise ValueError('x')", ns)
    try:
        ns["f"](*args)
    except ValueError as exc:
        return exc
    raise AssertionError("did not raise")


PUB = "greenscreen.publisher.fake"


def test_scanner_flags_a_planted_probe_in_a_publisher_frame():
    err = _raiser(PUB, "pass", "xx~^!#yy")
    findings = scan_frames(err, ["~^!#"])
    assert len(findings) == 1 and "local a0" in findings[0] and "~^!#" not in findings[0]


def test_scanner_flags_a_probe_inside_containers_and_a_secret_box():
    for planted in ({"k": ["~^!#zz"]}, ("a", {"~^!#zz"}), SecretBox.adopt({"userid": "~^!#zz"}), b"x~^!#zz"):
        assert scan_frames(_raiser(PUB, "pass", planted), ["~^!#"]), planted


def test_scanner_flags_an_int_probe_and_ignores_other_ints_and_bools():
    assert scan_frames(_raiser(PUB, "pass", 4711), [4711])
    assert not scan_frames(_raiser(PUB, "pass", 4712, True), [4711, True])


def test_scanner_flags_the_mapping_handed_to_run_flow_by_identity():
    mapping = {"userid": "clean"}
    assert scan_frames(_raiser(PUB, "pass", mapping), [], mappings=[mapping])
    assert not scan_frames(_raiser(PUB, "pass", dict(mapping)), [], mappings=[mapping])


def test_scanner_flags_a_screen():
    from tests.flow_support import capture

    assert scan_frames(_raiser(PUB, "pass", capture("tk5-logon")), [])


def test_scanner_treats_bound_values_and_published_flow_as_opaque():
    store = BoundValues({"f": {"userid": "~^!#zz"}})

    class PublishedFlow:  # same class name as the registry object; holds a probe
        held = "~^!#zz"

    assert scan_frames(_raiser(PUB, "pass", store), ["~^!#"]) == []
    assert scan_frames(_raiser(PUB, "pass", PublishedFlow()), ["~^!#"]) == []
    assert scan_frames(_raiser(PUB, "pass", {"x": store}), ["~^!#"]) == []


def test_scanner_ignores_frames_outside_the_publisher_and_follows_the_chain():
    assert scan_frames(_raiser("tests.other", "pass", "~^!#zz"), ["~^!#"]) == []
    inner = _raiser(PUB, "pass", "~^!#zz")
    try:
        try:
            raise inner
        except ValueError as exc:
            raise RuntimeError("outer") from exc
    except RuntimeError as outer:
        assert scan_frames(outer, ["~^!#"])
        assert "ValueError" in formatted_traceback(outer) and "RuntimeError" in formatted_traceback(outer)


def test_scanner_is_quiet_on_a_clean_frame():
    assert scan_frames(_raiser(PUB, "pass", "clean", {"a": 1}, [1, 2]), ["~^!#"]) == []


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": "tk5-system-info",
}
ARGS = {"userid": "PRBU7Q2X", "password": "PRBP9Z4K"}


def _app():
    host = FakeHost(system_info_states())
    return build_app(prepare(ENV), session_factory=host, clock=FakeClock(), poll_interval=0.01)


def test_rest_client_runs_inside_the_lifespan():
    async def go():
        async with rest_client(_app(), headers={"X-API-Key": "k" * 16}) as c:
            return await c.post("/flows/tk5-system-info", json=ARGS)

    resp = asyncio.run(go())
    assert resp.status_code == 200 and set(resp.json()) == {"flow", "outputs", "audit"}


@pytest.mark.parametrize("mode", MCP_MODES)
def test_mcp_client_in_both_eras(mode):
    async def go():
        async with mcp_client(_app(), mode) as c:
            return await c.call_tool("tk5-system-info", ARGS)

    res = asyncio.run(go())
    assert res.is_error is False and set(res.structured_content) == {"flow", "outputs", "audit"}
