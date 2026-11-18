"""parse_bindings (publisher Requirement 22): one example per rule, plus a no-leak property.

All values are fake strings made in this file. No test reads a credential.
"""
from __future__ import annotations

import gc
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.model import ExpectStep, Flow, InputSpec
from greenscreen.publisher.config import StartupError, parse_bindings
from greenscreen.publisher.vault import BoundValues

FAKE = "fake-" + "value-" + "0001"  # 15 chars, printable ASCII


def _flow(name: str, *inputs: InputSpec) -> Flow:
    return Flow(name, (ExpectStep(signatures=("tk5-logon",)),), inputs=tuple(inputs))


def _str(name: str, **kw) -> InputSpec:
    kw.setdefault("required", True)
    kw.setdefault("max_length", 20)
    return InputSpec(name, "str", **kw)


def _int(name: str, max_length: int = 6) -> InputSpec:
    return InputSpec(name, "int", False, max_length)


DEMO = _flow("demo-flow", _str("user_id"), _str("pw", secret=True), _int("count"))
OTHER = _flow("other", _str("x"))


def _parse(env: dict[str, str], loaded=None, published=None) -> BoundValues:
    loaded = loaded or {"demo-flow": DEMO, "other": OTHER}
    published = list(loaded) if published is None else published
    return parse_bindings(env, loaded, published)


def _fails(env: dict[str, str], rule: str, *needles: str, **kw) -> str:
    with pytest.raises(StartupError) as info:
        _parse(env, **kw)
    message = str(info.value)
    assert rule in message
    for needle in needles:
        assert needle in message
    assert FAKE not in message
    assert info.value.__cause__ is None and info.value.__suppress_context__ is True
    return message


def test_no_binding_variables_gives_empty_store():
    store = _parse({"GS_HOST": "h", "OTHER": FAKE})
    assert store.for_flow("demo-flow") == {} and repr(store) == "BoundValues(flows=0)"


def test_valid_bindings_normalise_names_and_parse_types():
    store = _parse(
        {
            "GS_BIND_DEMO_FLOW__USER_ID": FAKE,
            "GS_BIND_DEMO_FLOW__COUNT": "-42",  # '-' in the Flow name matches '_' in the variable
            "GS_BIND_OTHER__X": "ab",
        }
    )
    assert dict(store.for_flow("demo-flow")) == {"user_id": FAKE, "count": -42}
    assert store.names_for("other") == frozenset({"x"})
    assert FAKE not in repr(store) and FAKE not in str(store)


def test_prefix_is_case_sensitive_so_lowercase_prefix_is_ignored():
    assert repr(_parse({"gs_bind_demo_flow__user_id": FAKE})) == "BoundValues(flows=0)"


def test_empty_value_is_unset_and_does_not_bind():
    store = _parse({"GS_BIND_DEMO_FLOW__USER_ID": "", "GS_BIND_NOSUCH": ""})
    assert store.names_for("demo-flow") == frozenset()


@pytest.mark.parametrize("suffix", ["NOSEPARATOR", "__USER_ID", "DEMO_FLOW__", "DEMO_FLOW"])
def test_name_format(suffix):
    _fails({"GS_BIND_" + suffix: FAKE}, "name_format", "GS_BIND_" + suffix)


def test_unknown_flow():
    _fails({"GS_BIND_NOPE__X": FAKE}, "unknown_flow", "GS_BIND_NOPE__X")


def test_loaded_flow_left_out_by_publish_list_is_flow_not_published():
    _fails(
        {"GS_BIND_OTHER__X": FAKE},
        "flow_not_published",
        "GS_BIND_OTHER__X",
        published=["demo-flow"],
    )


def test_flow_not_published_is_checked_before_the_input_match():
    _fails({"GS_BIND_OTHER__NOINPUT": FAKE}, "flow_not_published", published=["demo-flow"])


def test_unknown_input():
    _fails({"GS_BIND_DEMO_FLOW__NOPE": FAKE}, "unknown_input", "GS_BIND_DEMO_FLOW__NOPE")


def test_ambiguous_flow_name_between_two_loaded_flows():
    loaded = {"a-b": _flow("a-b", _str("x")), "a_b": _flow("a_b", _str("x"))}
    _fails({"GS_BIND_A_B__X": FAKE}, "ambiguous_name", "GS_BIND_A_B__", loaded=loaded)


def test_ambiguous_input_name_in_one_flow():
    loaded = {"f": _flow("f", _str("user"), _str("USER"))}
    _fails({"GS_BIND_F__USER": FAKE}, "ambiguous_name", "GS_BIND_F__USER", loaded=loaded)


@pytest.mark.parametrize("name", ["bad__name", "trail_"])
def test_published_flow_name_that_hides_the_separator(name):
    loaded = {name: _flow(name, _str("x"))}
    _fails({"GS_BIND_X__X": FAKE}, "ambiguous_name", name, loaded=loaded)


def test_hidden_separator_check_only_applies_when_a_binding_exists():
    loaded = {"bad__name": _flow("bad__name", _str("x"))}
    assert repr(_parse({}, loaded=loaded)) == "BoundValues(flows=0)"


def test_hidden_separator_check_ignores_unpublished_flows():
    loaded = {"bad__name": _flow("bad__name", _str("x")), "other": OTHER}
    store = _parse({"GS_BIND_OTHER__X": "ab"}, loaded=loaded, published=["other"])
    assert store.names_for("other") == frozenset({"x"})


@pytest.mark.parametrize("text", ["12a", "+5", "1.5", " 5", "٣", "0x10", "-", "--5"])
def test_int_text_rules(text):
    _fails({"GS_BIND_DEMO_FLOW__COUNT": text}, "value_invalid", "GS_BIND_DEMO_FLOW__COUNT")


def test_int_longer_than_max_length_is_value_invalid():
    _fails({"GS_BIND_DEMO_FLOW__COUNT": "1234567"}, "value_invalid")


def test_int_leading_zeros_and_sign_count_toward_length():
    store = _parse({"GS_BIND_DEMO_FLOW__COUNT": "000123"})
    assert dict(store.for_flow("demo-flow")) == {"count": 123}
    _fails({"GS_BIND_DEMO_FLOW__COUNT": "-000123"}, "value_invalid")  # 7 characters


def test_str_longer_than_max_length():
    _fails({"GS_BIND_DEMO_FLOW__USER_ID": "x" * 21}, "max_length", "GS_BIND_DEMO_FLOW__USER_ID")


@pytest.mark.parametrize("text", ["tab\there", "caf\u00e9", "line\nbreak"])
def test_printable_ascii(text):
    _fails({"GS_BIND_DEMO_FLOW__USER_ID": text}, "printable_ascii")


def test_regex_is_applied_against_the_full_spec():
    loaded = {"f": _flow("f", _str("code", regex="[a-z]{3}"))}
    assert _parse({"GS_BIND_F__CODE": "abc"}, loaded=loaded).names_for("f") == {"code"}
    _fails({"GS_BIND_F__CODE": "ABC"}, "regex", "GS_BIND_F__CODE", loaded=loaded)


def test_secret_flag_does_not_change_validation_or_storage():
    store = _parse({"GS_BIND_DEMO_FLOW__PW": FAKE})
    assert store.for_flow("demo-flow")["pw"] == FAKE


def test_variable_parts_are_matched_against_the_upper_case_normal_form():
    # Requirement 22.4: the normalised name (upper case) must EQUAL the part, so a
    # lower-case part matches nothing. Two spellings of one Input cannot both match.
    _fails({"GS_BIND_demo_flow__USER_ID": FAKE}, "unknown_flow", "GS_BIND_demo_flow__USER_ID")
    _fails({"GS_BIND_DEMO_FLOW__user_id": FAKE}, "unknown_input", "GS_BIND_DEMO_FLOW__user_id")


def test_lower_case_variable_for_an_upper_case_binding_is_unknown_flow():
    # The duplicate-binding guard was removed as unreachable: the variable name is fully
    # determined by the matched Flow and Input, and the match is case-sensitive.
    loaded = {"a": _flow("a", _str("u"))}
    _fails({"GS_BIND_a__u": FAKE}, "unknown_flow", "GS_BIND_a__u", loaded=loaded)
    assert _parse({"GS_BIND_A__U": FAKE}, loaded=loaded).names_for("a") == {"u"}


def test_first_error_is_deterministic_in_ascending_name_order():
    message = _fails({"GS_BIND_ZZZ__X": FAKE, "GS_BIND_AAA__X": FAKE}, "unknown_flow")
    assert "GS_BIND_AAA__X" in message


def test_error_leaves_no_value_in_traceback_frames():
    env = {"GS_BIND_DEMO_FLOW__USER_ID": FAKE, "GS_BIND_DEMO_FLOW__NOPE": FAKE}
    try:
        _parse(env)
    except StartupError as exc:
        tb = exc.__traceback__
    else:  # pragma: no cover
        raise AssertionError("expected StartupError")
    frames = []
    while tb is not None:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    own = [f for f in frames if f.f_globals.get("__name__") == "greenscreen.publisher.config"]
    assert own
    for frame in own:
        for local in frame.f_locals.values():
            if local is env:  # the caller's own mapping (the process environment)
                continue
            if isinstance(local, dict) and local is not frame.f_locals:
                assert FAKE not in local.values()
                assert all(not v for v in local.values() if isinstance(v, dict))
            assert local != FAKE
    del frames, own, tb
    gc.collect()
    assert sys.getrefcount(FAKE) > 0


_NAMES = st.sampled_from(
    [
        "GS_BIND_DEMO_FLOW__USER_ID",
        "GS_BIND_DEMO_FLOW__COUNT",
        "GS_BIND_DEMO_FLOW__NOPE",
        "GS_BIND_OTHER__X",
        "GS_BIND_NOPE__X",
        "GS_BIND_BADNAME",
    ]
)
_VALUES = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=4, max_size=30)


@settings(max_examples=100, deadline=None)
@given(env=st.dictionaries(_NAMES, _VALUES, max_size=6), published=st.sampled_from([["demo-flow"], ["demo-flow", "other"]]))
def test_property_message_never_holds_a_value(env, published):
    # Feature: publisher, Property 14 (message part): startup errors hold no value
    loaded = {"demo-flow": DEMO, "other": OTHER}
    try:
        parse_bindings(env, loaded, published)
    except StartupError as exc:
        message = str(exc)
        for name, value in env.items():
            # a value may coincide with fixed text only by chance; names are in the message by design
            if value not in name and value not in "name_format unknown_flow unknown_input value_invalid":
                assert value not in message.replace(name, "")


def test_parse_bindings_frame_does_not_keep_the_environment_mapping():
    env = {"GS_BIND_DEMO_FLOW__USER_ID": FAKE, "GS_BIND_DEMO_FLOW__NOPE": FAKE}
    loaded = {"demo-flow": DEMO, "other": OTHER}
    try:
        parse_bindings(env, loaded, list(loaded))
    except StartupError as exc:
        tb = exc.__traceback__
    else:  # pragma: no cover
        raise AssertionError("expected StartupError")
    seen = 0
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code.co_name == "parse_bindings":
            seen += 1
            local = frame.f_locals.get("environ")
            assert local is not env
            assert not local  # absent or emptied
        tb = tb.tb_next
    assert seen == 1
