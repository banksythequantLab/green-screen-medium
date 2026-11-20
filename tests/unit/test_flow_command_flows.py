"""Scripted runs of the five Command_Flows (more-flows, task 8).

Task 8.2: ``tk5-time``. The Flow is read from its file by path, so the manifest
is not needed. Screens come from the captures; user id and password are fake.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import Flow
from greenscreen.flow.runner import run_flow
from greenscreen.flow.validate import check_flow
from greenscreen.recognizer.bundled import load_bundled_signatures

from tests.command_flow_support import (
    INPUTS,
    POLL,
    SENTINEL,
    command_session,
    flow_path,
    keys,
    keys_after_menu,
    load_shipped_flow,
    typed_after_menu,
)
from tests.flow_support import FakeClock, capture, pause_variant

AFTER_MENU = [
    ("string", "X"), ("enter",), ("clear",),
    ("string", "TIME"), ("enter",),
    ("clear",), ("string", "LOGOFF"), ("enter",),
]


def _run(flow, session):
    return run_flow(flow, session, INPUTS, clock=FakeClock(), poll_interval=POLL)


def _final_name(session):
    from tests.flow_support import _recognized

    return _recognized(session.read_screen())


# ---------------------------------------------------------------- tk5-time

def test_time_returns_row_one_of_the_capture():
    flow = load_shipped_flow("tk5-time")
    session = command_session(["tso-time-output"])
    result = _run(flow, session)

    expected = "".join(
        chr(c) if isinstance(c, int) else " "
        for c in capture("tso-time-output").cell_grid[1][1:80]
    ).replace("\x00", " ").strip()
    assert result.outputs["TIME_TEXT"] == expected
    assert expected.startswith("TIME-")
    assert keys_after_menu(session) == AFTER_MENU
    assert _final_name(session) == "tk5-logon"

    extracts = [a for a in result.audit if a.kind == "extract"]
    assert [(a.step_index, a.status) for a in extracts] == [(35, "ok")]
    fin = [a for a in result.audit if a.phase == "finally"]
    assert len(fin) == 13
    assert sum(a.status == "ok" for a in fin) == 6
    assert sum(a.status == "skipped" for a in fin) == 7
    assert SENTINEL not in repr(result)


def test_time_finally_sends_no_key_on_the_normal_path():
    flow = load_shipped_flow("tk5-time")
    session = command_session(["tso-time-output"])
    _run(flow, session)
    # the whole call list is the logon keys plus AFTER_MENU: nothing from finally
    assert len(keys(session)) == 6 + len(AFTER_MENU)


def test_time_pause_after_command_stops_and_finally_logs_off():
    flow = load_shipped_flow("tk5-time")
    # Command Enter shows a pause; finally: Enter, then READY, Clear, LOGOFF.
    session = command_session([pause_variant(0), "tso-ready"])
    # command_session appends closing states (cleared, logon) after the screens
    with pytest.raises(FlowError) as info:
        _run(flow, session)
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 35
    assert err.expected == ("tso-ready",)
    assert keys_after_menu(session) == [
        ("string", "X"), ("enter",), ("clear",),
        ("string", "TIME"), ("enter",),
        ("enter",), ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    assert _final_name(session) == "tk5-logon"
    fin = [a for a in err.audit if a.phase == "finally"]
    assert len(fin) == 13
    assert sum(a.status == "ok" for a in fin) == 10
    assert sum(a.status == "skipped" for a in fin) == 3


# ------------------------------------------------------ static checks

def test_time_check_flow_and_yaml_round_trip():
    flow = load_shipped_flow("tk5-time")
    signatures = load_bundled_signatures()
    assert len(signatures) == 12
    check_flow(flow, signatures)
    assert Flow.from_yaml(flow.to_yaml()) == flow
    assert flow_path("tk5-time").read_text(encoding="utf-8") == flow.to_yaml()


def test_time_description_and_timeouts():
    flow = load_shipped_flow("tk5-time")
    assert len(flow.description) == 271
    assert not any(c in flow.description for c in ";#@")
    assert (flow.timeouts.step, flow.timeouts.run, flow.timeouts.finally_) == (
        10.0, 20.0, 6.0,
    )


# ------------------------------------------------- tk5-list-datasets (8.3)

from tests.screen_support import make_screen  # noqa: E402

LISTCAT_AFTER_MENU = [
    ("string", "X"), ("enter",), ("clear",),
    ("string", "LISTCAT"), ("enter",),
    ("clear",), ("string", "LOGOFF"), ("enter",),
]


def _row_text(screen, row):
    return "".join(
        chr(c) if isinstance(c, int) and c else " " for c in screen.cell_grid[row]
    ).rstrip()


def test_list_datasets_real_capture_gives_seven_names_in_order():
    flow = load_shipped_flow("tk5-list-datasets")
    session = command_session(["tso-listcat-output"])
    result = _run(flow, session)

    names = result.outputs["DATASETS"].split("\n")
    screen = capture("tso-listcat-output")
    assert names == [_row_text(screen, r).strip() for r in range(2, 9)]
    assert len(names) == 7
    assert all(names) and all(len(n) <= 44 for n in names)
    assert "IN CATALOG" not in result.outputs["DATASETS"]
    assert keys_after_menu(session) == LISTCAT_AFTER_MENU
    assert _final_name(session) == "tk5-logon"
    assert SENTINEL not in repr(result)


def _two_screen_listcat():
    page1_names = [f"U.PAGE1.N{i:02d}" for i in range(21)]
    page2_names = [f"U.PAGE2.N{i}" for i in range(5)]
    text1 = {(0, 0): "LISTCAT", (1, 1): "IN CATALOG:SYS1.UCAT.TSO", (23, 1): "***"}
    text1.update({(2 + i, 1): n for i, n in enumerate(page1_names)})
    screen1 = make_screen(24, 80, text1, [(0, 0, 0xC8)], (23, 5))
    text2 = {(i, 1): n for i, n in enumerate(page2_names)}
    text2[(5, 1)] = "READY"
    screen2 = make_screen(24, 80, text2, [(0, 0, 0xC8)], (6, 0))
    return screen1, screen2, page1_names + page2_names


def test_list_datasets_two_screens_join_in_order_without_heading():
    flow = load_shipped_flow("tk5-list-datasets")
    screen1, screen2, expected = _two_screen_listcat()
    session = command_session([screen1, screen2])
    result = _run(flow, session)

    assert result.outputs["DATASETS"].split("\n") == expected
    assert "IN CATALOG" not in result.outputs["DATASETS"]
    assert keys_after_menu(session) == [
        ("string", "X"), ("enter",), ("clear",),
        ("string", "LISTCAT"), ("enter",), ("enter",),
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    collects = [a for a in result.audit if a.kind == "collect"]
    assert [(a.step_index, a.status) for a in collects] == [(35, "ok")]
    assert _final_name(session) == "tk5-logon"


def test_list_datasets_check_flow_and_yaml_round_trip():
    flow = load_shipped_flow("tk5-list-datasets")
    check_flow(flow, load_bundled_signatures())
    assert Flow.from_yaml(flow.to_yaml()) == flow
    assert flow_path("tk5-list-datasets").read_text(encoding="utf-8") == flow.to_yaml()
    assert len(flow.description) == 272
    assert not any(c in flow.description for c in ";#@")
    assert (flow.timeouts.step, flow.timeouts.run, flow.timeouts.finally_) == (
        10.0, 20.0, 6.0,
    )
    out = flow.outputs[-1]
    assert (out.name, out.row, out.col, out.length, out.next_row, out.max_rows) == (
        "DATASETS", 2, 1, 44, 0, 60,
    )


# ------------------------------------------------- tk5-dataset-info (8.4)

from tests.dsname_support import DSNAME_SPEC  # noqa: E402

DSN = "SYS2.JCLLIB"


def _run_dsn(flow, session, name=DSN):
    return run_flow(
        flow, session, {**INPUTS, "dsname": name}, clock=FakeClock(), poll_interval=POLL
    )


def _info_after_menu(name=DSN):
    return [
        ("string", "X"), ("enter",), ("clear",),
        ("string", "LISTDS '"), ("string", name), ("string", "'"), ("enter",),
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]


def test_dataset_info_found_gives_details_in_lines():
    flow = load_shipped_flow("tk5-dataset-info")
    session = command_session(["tso-listds-output"])
    result = _run_dsn(flow, session)

    assert result.outputs["FOUND"] == 1
    assert result.outputs["DETAILS"] == "\n".join(
        ["FB    80    27920   PO", "--VOLUMES--", "TSO001"]
    )
    assert keys_after_menu(session) == _info_after_menu()
    assert typed_after_menu(session) == ["X", "LISTDS '", DSN, "'", "LOGOFF"]
    assert _final_name(session) == "tk5-logon"
    assert SENTINEL not in repr(result)


def test_dataset_info_not_in_catalog_is_success_with_found_zero():
    flow = load_shipped_flow("tk5-dataset-info")
    session = command_session(["tso-listds-not-in-catalog"])
    result = _run_dsn(flow, session, "NO.SUCH.DSN")

    assert result.outputs["FOUND"] == 0
    assert result.outputs["DETAILS"] == ""
    assert keys_after_menu(session) == _info_after_menu("NO.SUCH.DSN")
    assert _final_name(session) == "tk5-logon"


def test_dataset_info_reenter_stops_and_finally_leaves_with_pa1():
    flow = load_shipped_flow("tk5-dataset-info")
    session = command_session(
        ["tso-listds-reenter", "tso-listds-reenter-after-pa1"]
    )
    with pytest.raises(FlowError) as info:
        _run_dsn(flow, session)
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 37
    assert err.kind == "extract"
    assert err.expected == ("tso-ready",)
    assert keys_after_menu(session)[7:] == [
        ("pa", 1), ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    assert _final_name(session) == "tk5-logon"
    fin = [a for a in err.audit if a.phase == "finally"]
    assert len(fin) == 13
    assert sum(a.status == "ok" for a in fin) == 10
    assert sum(a.status == "skipped" for a in fin) == 3
    assert SENTINEL not in repr(err)


def test_dataset_info_bad_name_is_input_invalid_with_no_session_calls():
    flow = load_shipped_flow("tk5-dataset-info")
    session = command_session(["tso-listds-output"])
    with pytest.raises(FlowError) as info:
        _run_dsn(flow, session, "A..B")
    err = info.value
    assert err.reason == "input_invalid"
    assert "dsname" in str(err) and "regex" in str(err)
    assert "A..B" not in str(err)
    assert session.calls == []


def test_dataset_info_dsname_input_equals_the_shared_constant():
    flow = load_shipped_flow("tk5-dataset-info")
    shipped = {spec.name: spec for spec in flow.inputs}["dsname"]
    assert shipped == DSNAME_SPEC
    assert [s.name for s in flow.inputs] == ["userid", "password", "dsname"]


def test_dataset_info_check_flow_and_yaml_round_trip():
    flow = load_shipped_flow("tk5-dataset-info")
    check_flow(flow, load_bundled_signatures())
    assert Flow.from_yaml(flow.to_yaml()) == flow
    assert flow_path("tk5-dataset-info").read_text(encoding="utf-8") == flow.to_yaml()
    assert len(flow.description) == 336
    assert not any(c in flow.description for c in ";#@")
    assert (flow.timeouts.step, flow.timeouts.run, flow.timeouts.finally_) == (
        10.0, 20.0, 6.0,
    )
    found, details = flow.outputs
    assert (found.name, found.type, found.row, found.col, found.length, found.equals) == (
        "FOUND", "int", 2, 1, 27, "--RECFM-LRECL-BLKSIZE-DSORG",
    )
    assert (details.name, details.type, details.row, details.col, details.length,
            details.max_rows) == ("DETAILS", "str", 3, 1, 79, 20)
    assert len(flow.steps) == 32 and len(flow.finally_steps) == 6


# ------------------------------------------------ tk5-library-members (8.5)

import dataclasses  # noqa: E402

from greenscreen.flow.model import CollectStep  # noqa: E402
from tests.flow_support import ScriptedSession, ScriptedState  # noqa: E402
from tests.screen_support import reconnect_pause_screen  # noqa: E402

MEMBER_PAGES = ["tso-listds-members"] + [
    f"tso-listds-members-page{i}" for i in range(2, 8)
]
MEMBERS_TYPED = ["X", "LISTDS '", DSN, "' MEMBERS", "LOGOFF"]


def _members_after_menu(pages=7, name=DSN):
    return [
        ("string", "X"), ("enter",), ("clear",),
        ("string", "LISTDS '"), ("string", name), ("string", "' MEMBERS"), ("enter",),
        *[("enter",)] * (pages - 1),
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]


def _page_member_names():
    """Member names read straight from the seven captures, independent of the Flow."""
    names: list[str] = []
    for i, page in enumerate(MEMBER_PAGES):
        screen = capture(page)
        for row in range(7 if i == 0 else 0, 24):
            text = _row_text(screen, row)
            if text.startswith("   ") and text.strip():
                names.append(text.strip())
    return names


def test_library_members_seven_real_pages_give_136_names_in_order():
    flow = load_shipped_flow("tk5-library-members")
    session = command_session(MEMBER_PAGES)
    result = _run_dsn(flow, session)

    members = result.outputs["MEMBERS"]
    names = members.split("\n")
    assert names == _page_member_names()
    assert len(names) == 136
    assert names[:3] == ["$$$INDEX", "$HISTORY", "ADDALIAS"]
    assert names[-1] == "ZAPDSCB"
    assert len(members) == 1145
    assert keys_after_menu(session) == _members_after_menu()
    assert sum(c == ("enter",) for c in keys_after_menu(session)[6:]) == 8
    assert typed_after_menu(session) == MEMBERS_TYPED
    assert _final_name(session) == "tk5-logon"
    collects = [a for a in result.audit if a.kind == "collect"]
    assert [(a.step_index, a.status) for a in collects] == [(37, "ok")]
    assert SENTINEL not in repr(result)


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_library_members_stale_reads_do_not_change_the_result(stale):
    flow = load_shipped_flow("tk5-library-members")
    base = _run_dsn(flow, command_session(MEMBER_PAGES)).outputs["MEMBERS"]
    session = command_session(MEMBER_PAGES, stale=stale)
    result = _run_dsn(flow, session)
    assert result.outputs["MEMBERS"] == base
    assert keys_after_menu(session) == _members_after_menu()


def test_library_members_not_in_catalog_gives_empty_string():
    flow = load_shipped_flow("tk5-library-members")
    session = command_session(["tso-listds-not-in-catalog"])
    result = _run_dsn(flow, session, "NO.SUCH.DSN")
    assert result.outputs["MEMBERS"] == ""
    assert keys_after_menu(session) == _members_after_menu(1, "NO.SUCH.DSN")
    assert _final_name(session) == "tk5-logon"


def test_library_members_reenter_stops_at_collect_and_finally_uses_pa1():
    flow = load_shipped_flow("tk5-library-members")
    session = command_session(["tso-listds-reenter", "tso-listds-reenter-after-pa1"])
    with pytest.raises(FlowError) as info:
        _run_dsn(flow, session)
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 37
    assert err.kind == "collect"
    assert sorted(err.expected) == ["tso-pause", "tso-ready"]
    assert keys_after_menu(session)[7:] == [
        ("pa", 1), ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    assert _final_name(session) == "tk5-logon"
    assert SENTINEL not in repr(err)


def _with_max_screens(flow, n):
    steps = tuple(
        dataclasses.replace(s, max_screens=n) if isinstance(s, CollectStep) else s
        for s in flow.steps
    )
    return dataclasses.replace(flow, steps=steps)


def test_library_members_max_screens_three_gives_loop_limit_and_finally_drains():
    flow = _with_max_screens(load_shipped_flow("tk5-library-members"), 3)
    session = command_session(MEMBER_PAGES)
    with pytest.raises(FlowError) as info:
        _run_dsn(flow, session)
    err = info.value
    assert err.reason == "loop_limit"
    assert err.step_index == 37
    assert keys_after_menu(session)[7:] == [
        ("enter",), ("enter",),  # collect: pages 2 and 3
        ("enter",), ("enter",), ("enter",), ("enter",),  # finally drains 4 pauses
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    assert _final_name(session) == "tk5-logon"
    fin = [a for a in err.audit if a.phase == "finally"]
    # all 13 plan indices (43 to 55) report; the pause Handle body ran 4 times
    assert sorted({a.step_index for a in fin}) == list(range(43, 56))
    assert [a.iteration for a in fin if a.step_index == 47] == [1, 2, 3, 4]
    assert not any(a.status == "failed" for a in fin)
    assert [a.status for a in fin].count("skipped") == 3


def test_library_members_unrecognized_page_three_is_unknown_screen_and_skips_finally():
    flow = load_shipped_flow("tk5-library-members")
    garbage = make_screen(24, 80, {(3, 1): "NOT A KNOWN SCREEN"}, [(0, 0, 0xC8)], (4, 0))
    pages = MEMBER_PAGES[:2] + [garbage] + MEMBER_PAGES[3:]
    session = command_session(pages)
    with pytest.raises(FlowError) as info:
        _run_dsn(flow, session)
    err = info.value
    assert err.reason == "unknown_screen"
    fin = [a for a in err.audit if a.phase == "finally"]
    assert len(fin) == 13
    assert all(a.status == "skipped" for a in fin)
    assert keys_after_menu(session)[7:] == [("enter",), ("enter",)]


def test_library_members_dsname_input_equals_the_shared_constant():
    flow = load_shipped_flow("tk5-library-members")
    shipped = {spec.name: spec for spec in flow.inputs}["dsname"]
    assert shipped == DSNAME_SPEC
    assert [s.name for s in flow.inputs] == ["userid", "password", "dsname"]


def test_library_members_check_flow_and_yaml_round_trip():
    flow = load_shipped_flow("tk5-library-members")
    check_flow(flow, load_bundled_signatures())
    assert Flow.from_yaml(flow.to_yaml()) == flow
    assert flow_path("tk5-library-members").read_text(encoding="utf-8") == flow.to_yaml()
    assert len(flow.description) == 381
    assert not any(c in flow.description for c in ";#@")
    assert (flow.timeouts.step, flow.timeouts.run, flow.timeouts.finally_) == (
        10.0, 20.0, 6.0,
    )
    (out, count) = flow.outputs
    assert (out.name, out.type, out.signature, out.row, out.col, out.length,
            out.next_row, out.max_rows) == (
        "MEMBERS", "str", "tso-ready", 7, 3, 8, 0, 200,
    )
    assert (count.name, count.type, count.counts) == ("MEMBER_COUNT", "int", "MEMBERS")
    assert (count.signature, count.row, count.col, count.length) == (out.signature, out.row, out.col, out.length)
    collect = next(s for s in flow.steps if isinstance(s, CollectStep))
    assert (collect.more, collect.max_screens) == ("tso-pause", 10)
    pause = next(s for s in flow.steps if getattr(s, "signature", None) == "tso-pause")
    assert pause.max_count == 10
    assert len(flow.steps) == 31 and len(flow.finally_steps) == 6


# ----- deep pauses (task 6.10 amendment, Requirement 25.6)

ENTER = ("enter",)
CLEAR = ("clear",)
LOGOFF_KEYS = [("string", "LOGOFF"), ENTER]
CALLS_TO_PASSWORD = [
    ("string", "FAKEUSR"), ENTER,
    ("string", "LOGON "), ("string", "FAKEUSR"), ("string", " RECONNECT"), ENTER,
    ("string", SENTINEL), ENTER,
]
DEEP_POLL = 0.1


def _reconnect_states(stale, further, *tail):
    screens = [
        capture("tk5-logon"),
        capture("tso-userid-in-use"),
        capture("tso-reconnect-password-prompt"),
        capture("tso-reconnect-ok"),
        reconnect_pause_screen(),
        *[pause_variant(i) for i in range(further)],
        *tail,
    ]
    return [ScriptedState(s, stale_reads=stale) for s in screens]


def _deep_run(states, clock):
    flow = load_shipped_flow("tk5-library-members")
    session = ScriptedSession(states, echo_typing=True)
    try:
        run_flow(flow, session, {**INPUTS, "dsname": DSN}, clock=clock,
                 poll_interval=DEEP_POLL)
    except FlowError as exc:
        return exc, session
    raise AssertionError("the reconnect call must stop with a FlowError")


def _nonread(session):
    return [c for c in session.calls if c[0] != "read"]


def test_library_members_nine_further_pauses_release_then_next_call_is_normal():
    clock = FakeClock()
    states = _reconnect_states(
        1, 9, capture("tso-ready"), capture("tso-cleared"), capture("tk5-logon")
    )
    err, session = _deep_run(states, clock)
    assert err.reason == "unexpected_screen"
    assert err.step_index == 26
    assert err.reason != "run_timeout"
    assert clock.now < load_shipped_flow("tk5-library-members").timeouts.run
    assert _nonread(session) == (
        CALLS_TO_PASSWORD + [ENTER] * 11 + [CLEAR, *LOGOFF_KEYS]
    )
    assert _final_name(session) == "tk5-logon"
    assert SENTINEL not in repr(err)

    # Second call: a new Session at the logon screen, the normal path.
    flow = load_shipped_flow("tk5-library-members")
    session2 = command_session(MEMBER_PAGES, stale=1)
    result = _run_dsn(flow, session2)
    assert len(result.outputs["MEMBERS"].split("\n")) == 136
    assert keys_after_menu(session2) == _members_after_menu()
    assert _final_name(session2) == "tk5-logon"


def test_library_members_ten_further_pauses_loop_limit_then_finally_drains():
    clock = FakeClock()
    behind = [pause_variant(10 + i) for i in range(3)]
    states = _reconnect_states(
        1, 10, *behind, capture("tso-ready"), capture("tso-cleared"),
        capture("tk5-logon"),
    )
    err, session = _deep_run(states, clock)
    assert err.reason == "loop_limit"
    assert err.step_index == 17
    # 12 Enters from the password Enter on; the finally Handle presses Enter at
    # the 11th pause and the 3 behind it, then Clear, LOGOFF, Enter.
    assert _nonread(session) == (
        CALLS_TO_PASSWORD + [ENTER] * 11 + [ENTER] * 4 + [CLEAR, *LOGOFF_KEYS]
    )
    assert _final_name(session) == "tk5-logon"
    fin = [a for a in err.audit if a.phase == "finally"]
    assert sorted({a.step_index for a in fin}) == list(range(43, 56))
    assert not any(a.status == "failed" for a in fin)
    assert SENTINEL not in repr(err)


# ------------------------------------------------- tk5-job-status (8.6)

STATUS_AFTER_MENU = [
    ("string", "X"), ("enter",), ("clear",),
    ("string", "STATUS"), ("enter",),
    ("clear",), ("string", "LOGOFF"), ("enter",),
]


def test_job_status_real_capture_gives_the_one_job_line():
    flow = load_shipped_flow("tk5-job-status")
    session = command_session(["tso-status-output"])
    result = _run(flow, session)

    line = _row_text(capture("tso-status-output"), 1).strip()
    assert result.outputs["JOBS"] == line
    assert line.startswith("JOB ") and line.endswith("EXECUTING")
    assert keys_after_menu(session) == STATUS_AFTER_MENU
    assert _final_name(session) == "tk5-logon"
    collects = [a for a in result.audit if a.kind == "collect"]
    assert [(a.step_index, a.status) for a in collects] == [(35, "ok")]
    fin = [a for a in result.audit if a.phase == "finally"]
    assert len(fin) == 13 and sum(a.status == "skipped" for a in fin) == 7
    assert SENTINEL not in repr(result)


def test_job_status_several_job_lines_on_one_screen_in_order():
    # Synthetic: shapes beyond one job are not captured (open item 3).
    flow = load_shipped_flow("tk5-job-status")
    jobs = [
        " JOB FAKEUSR(TSU00012) EXECUTING",
        " JOB PAYROLL(JOB00041) ON OUTPUT QUEUE",
        " JOB NIGHTLY(JOB00042) HELD",
    ]
    text = {(0, 0): "STATUS"}
    text.update({(1 + i, 0): j for i, j in enumerate(jobs)})
    text[(4, 1)] = "READY"
    screen = make_screen(24, 80, text, [(0, 0, 0xC8)], (5, 0))
    session = command_session([screen])
    result = _run(flow, session)

    assert result.outputs["JOBS"].split("\n") == [j.strip() for j in jobs]
    assert keys_after_menu(session) == STATUS_AFTER_MENU
    assert _final_name(session) == "tk5-logon"


def test_job_status_two_screens_return_all_lines_in_order():
    flow = load_shipped_flow("tk5-job-status")
    page1 = [f"JOB BATCH{i:02d}(JOB{i:05d}) ON OUTPUT QUEUE" for i in range(22)]
    page2 = [f"JOB LATE{i}(JOB9000{i}) HELD" for i in range(3)]
    text1 = {(0, 0): "STATUS", (23, 1): "***"}
    text1.update({(1 + i, 1): j for i, j in enumerate(page1)})
    screen1 = make_screen(24, 80, text1, [(0, 0, 0xC8)], (23, 5))
    text2 = {(i, 1): j for i, j in enumerate(page2)}
    text2[(3, 1)] = "READY"
    screen2 = make_screen(24, 80, text2, [(0, 0, 0xC8)], (4, 0))
    session = command_session([screen1, screen2])
    result = _run(flow, session)

    assert result.outputs["JOBS"].split("\n") == page1 + page2
    assert keys_after_menu(session) == [
        ("string", "X"), ("enter",), ("clear",),
        ("string", "STATUS"), ("enter",), ("enter",),
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    collects = [a for a in result.audit if a.kind == "collect"]
    assert [(a.step_index, a.status) for a in collects] == [(35, "ok")]
    assert _final_name(session) == "tk5-logon"


def test_job_status_check_flow_and_yaml_round_trip():
    flow = load_shipped_flow("tk5-job-status")
    check_flow(flow, load_bundled_signatures())
    assert Flow.from_yaml(flow.to_yaml()) == flow
    assert flow_path("tk5-job-status").read_text(encoding="utf-8") == flow.to_yaml()
    assert len(flow.description) == 237
    assert not any(c in flow.description for c in ";#@")
    assert (flow.timeouts.step, flow.timeouts.run, flow.timeouts.finally_) == (
        10.0, 20.0, 6.0,
    )
    (out,) = flow.outputs
    assert (out.name, out.type, out.signature, out.row, out.col, out.length,
            out.next_row, out.max_rows) == ("JOBS", "str", "tso-ready", 1, 1, 79, 0, 40)
    collect = next(s for s in flow.steps if isinstance(s, CollectStep))
    assert (collect.more, collect.max_screens) == ("tso-pause", 3)
    assert [s.name for s in flow.inputs] == ["userid", "password"]
    assert len(flow.steps) == 29 and len(flow.finally_steps) == 6


# ------------------------------------------- manifest and descriptions (8.7)

from greenscreen.flow.bundled import load_bundled_flows  # noqa: E402
from greenscreen.publisher.registry import build_registry  # noqa: E402
from greenscreen.publisher.vault import BoundValues  # noqa: E402
from tests.property._publisher_strategies import PROBE_ALPHABET  # noqa: E402

EIGHT = (
    "tk5-logon", "tk5-logoff", "tk5-system-info", "tk5-time", "tk5-list-datasets",
    "tk5-dataset-info", "tk5-library-members", "tk5-job-status",
)
FIVE = EIGHT[3:]


def test_manifest_holds_the_eight_names_in_order():
    assert tuple(load_bundled_flows()) == EIGHT


@pytest.mark.parametrize("name", FIVE)
def test_shipped_file_text_equals_to_yaml_of_the_loaded_flow(name):
    flow = load_bundled_flows()[name]
    assert flow_path(name).read_text(encoding="utf-8") == flow.to_yaml()


@pytest.mark.parametrize("name", EIGHT)
def test_every_bundled_flow_passes_check_flow_and_round_trips(name):
    sigs = load_bundled_signatures()
    flow = load_bundled_flows(sigs)[name]
    check_flow(flow, sigs)
    assert Flow.from_yaml(flow.to_yaml(), sigs) == flow


@pytest.mark.parametrize("name", EIGHT)
def test_descriptions_are_short_and_name_every_output(name):
    flow = load_bundled_flows()[name]
    assert len(flow.description) <= 500
    if name in FIVE:  # the three older descriptions are unchanged and use words, not names
        for out in flow.outputs:
            assert out.name in flow.description, out.name
    for spec in flow.inputs:
        assert len(spec.description) <= 200


@pytest.mark.parametrize("name", EIGHT)
def test_no_probe_alphabet_character_in_any_fixed_text_of_a_flow(name):
    flow = load_bundled_flows()[name]
    texts = [flow.name, flow.description]
    texts += [i.name for i in flow.inputs] + [i.description for i in flow.inputs]
    texts += [o.name for o in flow.outputs]
    assert not set(PROBE_ALPHABET) & set("\n".join(texts))


def test_the_five_flows_get_a_registry_deadline_of_run_plus_finally_plus_30():
    flows = {n: (f, "bundled") for n, f in load_bundled_flows().items()}
    registry = build_registry(flows, BoundValues(), 900.0)
    assert tuple(registry) == EIGHT
    for name in FIVE:
        assert registry[name].deadline == 56.0
