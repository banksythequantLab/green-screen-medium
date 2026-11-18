"""Tests of the publisher Fake_Host (tests/publisher_support.py). No live host."""
from __future__ import annotations

import threading

import pytest

from greenscreen.connector import ConnectorTimeoutError, SessionClosedError
from greenscreen.flow import run_flow
from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock
from tests.publisher_support import (
    MINI,
    CallEvent,
    Failure,
    FakeHost,
    mini_states,
    system_info_states,
)

SIGS = load_bundled_signatures()
INPUTS = {"userid": "USER1"}


def _run_mini(host: FakeHost):
    session = host()
    session.open()
    try:
        return run_flow(MINI, session, INPUTS, signatures=SIGS, clock=FakeClock())
    finally:
        session.close()


def test_mini_flow_runs_and_counters_balance():
    host = FakeHost(mini_states())
    assert host.created == 0 and host.live == 0
    result = _run_mini(host)
    assert list(result.outputs) == ["RELEASE"]
    assert (host.created, host.opened, host.closed, host.aborted) == (1, 1, 1, 0)
    assert host.live == 0 and host.close_calls == 1
    assert ("string", "USER1") in host.sessions[0].calls


def test_script_callable_gets_session_number():
    seen: list[int] = []

    def script(n: int):
        seen.append(n)
        return mini_states()

    host = FakeHost(script)
    _run_mini(host)
    _run_mini(host)
    assert seen == [1, 2] and host.created == 2


def test_system_info_chain_runs_to_logoff():
    flow = load_bundled_flows(SIGS)["tk5-system-info"]
    host = FakeHost(system_info_states())
    session = host()
    session.open()
    result = run_flow(
        flow, session, {"userid": "USER1", "password": "DUMMYPW1"}, signatures=SIGS, clock=FakeClock()
    )
    session.close()
    assert set(result.outputs) == {"USERID", "SYSTEMID", "RELEASE", "TERMINAL"}
    assert session.calls.count(("enter",)) == 5
    assert host.live == 0


def test_events_have_increasing_sequence_and_thread_ids():
    host = FakeHost(mini_states())
    _run_mini(host)
    seqs = [e.seq for e in host.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert host.events[0] == CallEvent(1, None, "factory", (), threading.get_ident())
    assert {e.thread for e in host.events} == {threading.get_ident()}
    assert [e.method for e in host.events_for(1)][:2] == ["open", "read_screen"]


def test_events_record_the_calling_thread():
    host = FakeHost(mini_states())
    ids: list[int] = []

    def work():
        ids.append(threading.get_ident())
        _run_mini(host)

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert {e.thread for e in host.events} == set(ids)
    assert threading.get_ident() not in ids


# -- failure injection --

def test_failure_at_factory_creates_no_session():
    host = FakeHost(mini_states(), failures=[Failure("factory", OSError)])
    with pytest.raises(OSError):
        host()
    assert host.created == 0 and host.factory_calls == 1
    assert host().number == 1  # only the first factory call fails


def test_failure_at_open_leaves_session_unopened():
    host = FakeHost(mini_states(), failures=[Failure("open", ConnectorTimeoutError)])
    session = host()
    with pytest.raises(ConnectorTimeoutError):
        session.open()
    assert host.created == 1 and host.opened == 0 and host.live == 1
    session.close()
    assert host.live == 0


def test_failure_at_nth_call_of_a_method():
    host = FakeHost(mini_states(), failures=[Failure("read_screen", ValueError, n=2)])
    session = host()
    session.open()
    session.read_screen()
    with pytest.raises(ValueError):
        session.read_screen()
    session.read_screen()  # only the second call fails


def test_failure_targets_one_session_only():
    host = FakeHost(mini_states(), failures=[Failure("enter", RuntimeError, session=2)])
    for number in (1, 2):
        s = host()
        s.open()
        s.read_screen()
        s.string("USER1")
        if number == 2:
            with pytest.raises(RuntimeError):
                s.enter()
        else:
            s.enter()


def test_failure_at_close_still_counts_the_session_closed():
    host = FakeHost(mini_states(), failures=[Failure("close", RuntimeError)])
    session = host()
    session.open()
    with pytest.raises(RuntimeError):
        session.close()
    assert host.closed == 1 and host.live == 0


def test_base_exception_and_instance_are_raised_as_given():
    marker = KeyboardInterrupt("stop")
    host = FakeHost(mini_states(), failures=[Failure("string", marker)])
    session = host()
    session.open()
    with pytest.raises(KeyboardInterrupt) as info:
        session.string("x")
    assert info.value is marker


def test_failure_rejects_unknown_point_and_bad_n():
    with pytest.raises(ValueError):
        Failure("nope")
    with pytest.raises(ValueError):
        Failure("enter", n=0)


def test_calls_before_open_and_after_close_raise():
    host = FakeHost(mini_states())
    session = host()
    with pytest.raises(RuntimeError):
        session.read_screen()
    session.open()
    session.close()
    with pytest.raises(SessionClosedError):
        session.read_screen()


# -- abort (Requirement 19.9) --

def test_abort_unblocks_a_blocked_read_and_poisons_the_session():
    host = FakeHost(mini_states(), block_read=2)
    session = host()
    session.open()
    session.read_screen()
    outcome: list[BaseException | None] = []

    def blocked():
        try:
            session.read_screen()
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001 - the test records any raise
            outcome.append(exc)

    t = threading.Thread(target=blocked)
    t.start()
    assert session.blocked.wait(5)
    abort_thread = threading.Thread(target=session.abort)
    abort_thread.start()
    abort_thread.join(5)
    t.join(5)
    assert not t.is_alive()
    assert isinstance(outcome[0], SessionClosedError)

    abort_seq = next(e.seq for e in host.events if e.method == "abort")
    for call in (session.read_screen, session.enter, session.clear, lambda: session.pf(3),
                 lambda: session.pa(1), lambda: session.string("x")):
        with pytest.raises(SessionClosedError):
            call()
    # Calls recorded after the abort all failed; the scripted session saw nothing new.
    assert all(c in (("read",),) for c in session.calls)
    assert len(session.calls) == 1
    assert any(e.seq > abort_seq and e.method == "enter" for e in host.events)

    session.abort()  # a second abort acts as one
    assert session.abort_calls == 2 and host.aborted == 1 and host.abort_calls == 2
    session.close()  # close after abort returns
    assert host.closed == 1 and host.live == 0


def test_abort_before_open_makes_open_raise():
    host = FakeHost(mini_states())
    session = host()
    session.abort()
    with pytest.raises(SessionClosedError):
        session.open()
    assert host.opened == 0


def test_release_lets_a_blocked_read_continue():
    host = FakeHost(mini_states(), block_read=1)
    session = host()
    session.open()
    got: list[object] = []
    t = threading.Thread(target=lambda: got.append(session.read_screen()))
    t.start()
    assert session.blocked.wait(5)
    host.release_all()
    t.join(5)
    assert len(got) == 1 and not session.is_aborted
