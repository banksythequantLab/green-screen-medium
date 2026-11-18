"""Unit tests for greenscreen.publisher.registry."""
from __future__ import annotations

import json
from importlib import resources

import pytest
from jsonschema import Draft202012Validator

from greenscreen.flow.errors import FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.publisher import registry as reg
from greenscreen.publisher.config import StartupError
from greenscreen.publisher.registry import (
    build_registry,
    build_schemas,
    check_inputs,
    load_flows,
    load_startup_signatures,
    select_published,
)
from greenscreen.publisher.vault import BoundValues, SecretBox

BUNDLED = ("tk5-logon", "tk5-logoff", "tk5-system-info")
FORBIDDEN_KEYS = {"default", "examples", "example", "const", "enum"}


def _yaml_text(name: str) -> str:
    return (
        resources.files("greenscreen.flow.flows")
        .joinpath(f"{name}.yaml")
        .read_text(encoding="utf-8")
    )


def _renamed(src: str, new: str) -> str:
    return _yaml_text(src).replace(f"name: {src}\n", f"name: {new}\n", 1)


def _keys(obj: object) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _keys(v)
    return found


def _fails(fn, *args) -> str:
    with pytest.raises(StartupError) as info:
        fn(*args)
    return str(info.value)


# --- load_flows ---------------------------------------------------------------


def test_bundled_flows_load_in_manifest_order() -> None:
    loaded = load_flows(None)
    assert tuple(loaded) == BUNDLED
    assert {src for _, src in loaded.values()} == {"bundled"}


def test_flows_dir_files_follow_bundled_in_file_order(tmp_path) -> None:
    (tmp_path / "b.yaml").write_text(_renamed("tk5-logoff", "zeta"), encoding="utf-8")
    (tmp_path / "a.yaml").write_text(_renamed("tk5-logoff", "alpha"), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.yaml").write_text(_renamed("tk5-logoff", "nested"), encoding="utf-8")
    loaded = load_flows(tmp_path)
    assert tuple(loaded) == BUNDLED + ("alpha", "zeta")
    assert loaded["alpha"][1] == "a.yaml"


def test_missing_directory_and_non_directory_stop_startup(tmp_path) -> None:
    assert "GS_FLOWS_DIR" in _fails(load_flows, tmp_path / "nope")
    f = tmp_path / "file.yaml"
    f.write_text("x", encoding="utf-8")
    assert "GS_FLOWS_DIR" in _fails(load_flows, f)


def test_invalid_file_names_the_file(tmp_path) -> None:
    (tmp_path / "broken.yaml").write_text("version: 1\nname: [\n", encoding="utf-8")
    assert "broken.yaml" in _fails(load_flows, tmp_path)


def test_duplicate_name_names_both_sources(tmp_path) -> None:
    (tmp_path / "dup.yaml").write_text(_yaml_text("tk5-logoff"), encoding="utf-8")
    msg = _fails(load_flows, tmp_path)
    assert "tk5-logoff" in msg and "bundled" in msg and "dup.yaml" in msg
    (tmp_path / "dup.yaml").unlink()
    (tmp_path / "a.yaml").write_text(_renamed("tk5-logoff", "same"), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_renamed("tk5-logoff", "same"), encoding="utf-8")
    msg = _fails(load_flows, tmp_path)
    assert "same" in msg and "a.yaml" in msg and "b.yaml" in msg


def test_invalid_file_stops_startup_even_if_allow_list_would_skip_it(tmp_path) -> None:
    (tmp_path / "broken.yaml").write_text("not: [valid", encoding="utf-8")
    with pytest.raises(StartupError):
        select_published(load_flows(tmp_path), ("tk5-system-info",))


# --- select_published ---------------------------------------------------------


def test_select_none_returns_all() -> None:
    loaded = load_flows(None)
    assert select_published(loaded, None) == loaded


def test_select_keeps_loading_order_not_list_order() -> None:
    loaded = load_flows(None)
    chosen = select_published(loaded, ("tk5-system-info", "tk5-logon"))
    assert tuple(chosen) == ("tk5-logon", "tk5-system-info")


def test_select_unknown_names_first_unknown_in_list_order() -> None:
    loaded = load_flows(None)
    msg = _fails(select_published, loaded, ("tk5-logon", "ghost", "phantom"))
    assert msg == "GS_PUBLISH_FLOWS: unknown_flow (ghost)"
    # names match case-sensitively
    assert "TK5-LOGON" in _fails(select_published, loaded, ("TK5-LOGON",))


def test_registry_holds_only_selected_flows() -> None:
    chosen = select_published(load_flows(None), ("tk5-system-info",))
    registry = build_registry(chosen, BoundValues(), 180.0)
    assert tuple(registry) == ("tk5-system-info",)
    with pytest.raises(TypeError):
        registry["x"] = None  # type: ignore[index]


# --- signatures ---------------------------------------------------------------


def test_startup_signatures_load_and_failure_has_no_cause(monkeypatch) -> None:
    assert len(load_startup_signatures()) > 0

    def boom():
        raise RuntimeError("secret-looking detail")

    monkeypatch.setattr(reg, "load_bundled_signatures", boom)
    with pytest.raises(StartupError) as info:
        load_startup_signatures()
    assert str(info.value) == "signatures: load_failed"
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert "secret" not in str(info.value)


# --- schemas ------------------------------------------------------------------


def test_prepare_inputs_accepts_decl() -> None:
    flow = load_flows(None)["tk5-system-info"][0]
    registry = build_registry({"tk5-system-info": (flow, "bundled")}, BoundValues(), 180.0)
    decl = registry["tk5-system-info"].decl
    prepared = prepare_inputs(decl, {"userid": "ABC", "password": "pwplace1"})  # type: ignore[arg-type]
    assert prepared.values == {"userid": "ABC"}


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_schemas_are_valid_and_deterministic(name) -> None:
    flow = load_flows(None)[name][0]
    first = build_schemas(flow, frozenset())
    assert first == build_schemas(flow, frozenset())
    assert first[0] is not build_schemas(flow, frozenset())[0]
    for schema in first:
        Draft202012Validator.check_schema(schema)
        assert not (_keys(schema) & FORBIDDEN_KEYS)
        json.dumps(schema)


def test_system_info_input_schema_rules() -> None:
    flow = load_flows(None)["tk5-system-info"][0]
    inp, out, suc = build_schemas(flow, frozenset())
    assert inp["type"] == "object" and inp["additionalProperties"] is False
    assert list(inp["properties"]) == ["userid", "password"]
    assert inp["required"] == ["userid", "password"]
    assert inp["properties"]["userid"]["pattern"] == "^(?:[A-Za-z0-9@#$]{1,8})$"
    assert inp["properties"]["userid"]["maxLength"] == 8
    assert "writeOnly" not in inp["properties"]["userid"]
    assert inp["properties"]["password"]["writeOnly"] is True
    assert "pattern" not in inp["properties"]["password"]
    assert inp["properties"]["userid"]["description"] == "TSO user id."
    assert list(out["properties"]) == ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]
    assert out["required"] == list(out["properties"])
    assert "password" not in json.dumps(out) and "password" not in json.dumps(suc)
    assert suc["properties"]["outputs"] == out
    assert set(suc["properties"]["audit"]["items"]["properties"]) == {
        "step_index",
        "kind",
        "phase",
        "iteration",
        "signature",
        "status",
        "duration_seconds",
    }


def test_logon_flow_without_outputs_has_empty_output_schema() -> None:
    flow = load_flows(None)["tk5-logoff"][0]
    inp, out, _ = build_schemas(flow, frozenset())
    assert inp["properties"] == {} and "required" not in inp
    assert out["properties"] == {} and out["required"] == []


def test_bound_name_is_absent_from_schema_and_required() -> None:
    flow = load_flows(None)["tk5-system-info"][0]
    inp, _, _ = build_schemas(flow, frozenset({"userid"}))
    assert list(inp["properties"]) == ["password"]
    assert inp["required"] == ["password"]
    inp_all, _, _ = build_schemas(flow, frozenset({"userid", "password"}))
    assert inp_all["properties"] == {} and "required" not in inp_all


def test_int_bounds() -> None:
    from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep

    flow = Flow(
        name="ints",
        steps=(ExpectStep(signatures=("tk5-logon",)), TypeStep(text="x"), KeyStep(key="enter")),
        inputs=(
            InputSpec("one", "int", False, 1),
            InputSpec("four", "int", True, 4),
        ),
    )
    inp, _, _ = build_schemas(flow, frozenset())
    assert (inp["properties"]["one"]["minimum"], inp["properties"]["one"]["maximum"]) == (0, 9)
    assert (inp["properties"]["four"]["minimum"], inp["properties"]["four"]["maximum"]) == (
        -999,
        9999,
    )
    assert inp["required"] == ["four"]


@pytest.mark.parametrize(
    "regex,safe",
    [
        (r"[A-Za-z0-9@#$]{1,8}", True),
        (r"\d+\.\d*", True),
        (r"\++", True),
        (r"(?:ab)+", True),
        (r"a++", False),
        (r"a*+", False),
        (r"(?i)abc", False),
        (r"(?P<x>a)", False),
        (r"(a)\1", False),
        (r"[[:alpha:]]", False),
        (r"\p{L}", False),
        ("abc\\", False),
    ],
)
def test_ecma_safe_rule(regex, safe) -> None:
    assert reg._ecma_safe(regex) is safe


def test_unsafe_regex_omits_pattern() -> None:
    from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep

    flow = Flow(
        name="rx",
        steps=(ExpectStep(signatures=("tk5-logon",)), TypeStep(text="x"), KeyStep(key="enter")),
        inputs=(InputSpec("v", "str", True, 8, regex=r"a++"),),
    )
    inp, _, _ = build_schemas(flow, frozenset())
    assert "pattern" not in inp["properties"]["v"]


# --- check_inputs -------------------------------------------------------------


def _published(bound: dict | None = None):
    flow = load_flows(None)["tk5-system-info"][0]
    registry = build_registry(
        {"tk5-system-info": (flow, "bundled")}, BoundValues(bound), 180.0
    )
    return registry["tk5-system-info"]


def test_check_inputs_accepts_valid_and_reports_rule_names() -> None:
    pub = _published()
    ok = SecretBox.adopt({"userid": "ABC", "password": "pwplace1"})
    assert check_inputs(pub, ok) is None

    missing = SecretBox.adopt({"userid": "ABC"})
    msg = check_inputs(pub, missing)
    assert msg == str(FlowInputError("password", "required"))

    wrong = SecretBox.adopt({"userid": 5, "password": "pwplace1"})
    assert check_inputs(pub, wrong) == str(FlowInputError("userid", "type"))


def test_check_inputs_message_holds_no_value() -> None:
    pub = _published()
    value = "zz-leak-probe-zz"
    msg = check_inputs(pub, SecretBox.adopt({"userid": value, "password": "pwplace1"}))
    assert msg is not None and value not in msg and "pwplace1" not in msg


def test_bound_name_supplied_by_caller_is_undeclared() -> None:
    pub = _published({"tk5-system-info": {"userid": "ABC"}})
    assert pub.bound_names == frozenset({"userid"})
    msg = check_inputs(pub, SecretBox.adopt({"userid": "ABC", "password": "pwplace1"}))
    assert msg == str(FlowInputError("userid", "undeclared"))
    # without it the call is valid: the bound value fills the Input later
    assert check_inputs(pub, SecretBox.adopt({"password": "pwplace1"})) is None


def test_deadline_is_smaller_of_config_and_flow_budget() -> None:
    flow = load_flows(None)["tk5-system-info"][0]  # run 120 + finally 30 + 30
    one = {"tk5-system-info": (flow, "bundled")}
    assert build_registry(one, BoundValues(), 900.0)["tk5-system-info"].deadline == 180.0
    assert build_registry(one, BoundValues(), 60.0)["tk5-system-info"].deadline == 60.0
