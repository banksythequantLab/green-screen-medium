"""Property 10 (task 8.6): no traceback frame of the publisher holds a value.

One generated scenario per example. Each scenario makes an exception leave a function of
``greenscreen.publisher`` and then scans the traceback and its chain:

* ``cancel``: the Call is cancelled while the read is blocked (also with an ``abort()``
  that raises a ``BaseException``);
* ``base``: a ``BaseException`` from the Session at the factory, ``open``, ``read_screen``,
  ``string``, ``enter`` or ``close`` (the six points the ``MINI`` Flow reaches);
* ``seam``: a ``BaseException`` injected into the ``run_flow`` seam;
* ``start``: a ``BaseException`` from ``Thread.start`` of the worker, and a failed start
  followed by a ``BaseException`` from ``close``;
* ``timeout``: the Call deadline expires and the ``abort()`` of the teardown raises a
  ``BaseException`` (the ``call_timeout`` teardown);
* ``drain``: ``drain`` tears down a blocked Call and ``abort()`` raises a ``BaseException``;
* ``bindings``: ``parse_bindings`` fails at startup with Probe_Values in the environment.

The frame scanner of ``tests/publisher_support.py`` checks every ``greenscreen.publisher``
frame (the objects of the ``BoundValues`` and ``PublishedFlow`` classes are opaque, as the
requirements permit) for a Probe_Value, a ``Screen`` and the merged mapping handed to
``run_flow`` (by identity). ``traceback.format_exception`` with chain is searched for every
Leak_Form of every Probe_Value.

The probes are made-up values, never credentials. A failure message names the path, the
frame function, the local and the kind of hit, never a value, and the example data is
hidden from Hypothesis's report for the same reason.

Two decorations of a formatted traceback cannot carry a value and collide with the probe
alphabet, so they are normalised before the Leak_Form search: the ``~~~^^^`` marker lines
(the probes use ``~`` and ``^``) and the line numbers of the ``File ..., line N`` headers
(an ``int`` probe of four digits can equal one).
"""
from __future__ import annotations

import asyncio
import functools
import re
import threading
from dataclasses import dataclass, field
from unittest import mock

from hypothesis import example, given, settings
from hypothesis import strategies as st

from greenscreen.publisher import calls
from greenscreen.publisher.app import prepare
from greenscreen.publisher.calls import CallService, Limiter
from greenscreen.publisher.config import parse_bindings
from greenscreen.publisher.registry import build_registry, load_flows
from greenscreen.publisher.vault import BoundValues, SecretBox
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import BoundSet, InjectedBase, bound_sets, find_leaks, probes
from tests.publisher_support import (
    MINI,
    Failure,
    FakeHost,
    formatted_traceback,
    mini_states,
    scan_frames,
)

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": "tk5-logon",
}
_HARD = 3.0  # anything a scenario waits for; a hang fails here
_WHOLE = 30.0  # one whole scenario
_BASE_POINTS = ("factory", "open", "read_screen", "string", "enter", "close")


@dataclass(frozen=True)
class _Hidden:
    """Example data. The repr shows nothing, so a failure report holds no value."""

    bs: BoundSet = field(repr=False)
    p1: str = field(repr=False)
    p2: str = field(repr=False)

    @property
    def values(self) -> tuple:
        return (*self.bs.values, self.p1, self.p2)


UNIVERSE: tuple[tuple[str, str], ...] = (
    ("cancel", ""),
    ("cancel", "abort_base"),
    *(("base", at) for at in _BASE_POINTS),
    ("seam", ""),
    ("start", "base"),
    ("start", "close_base"),
    ("timeout", ""),
    ("drain", ""),
    ("bindings", "regex"),
    ("bindings", "unknown_input"),
)
SCENARIOS = st.sampled_from(UNIVERSE)
HIDDEN = st.builds(
    _Hidden, bound_sets(MINI), probes("str", max_size=8), probes("str", max_size=8)
)

# Fixed example data (made-up Probe_Values). A mixes bound and supplied Inputs, B binds all.
_A = _Hidden(BoundSet({"password": "*+=|;?"}, {"userid": "~^!#%&", "count": 4821}), "#@!%&~", "^;?@=+")
_B = _Hidden(BoundSet({"userid": "&*+=|;", "password": "!#%@~^", "count": 7305}, {}), "|;?@&*", "+=~^!#")


@functools.lru_cache(maxsize=1)
def _prepared():
    return prepare(ENV)


@functools.lru_cache(maxsize=1)
def _loaded():
    return {n: f for n, (f, _src) in load_flows(None).items()}


async def _result(task: asyncio.Future, what: str) -> BaseException | None:
    """The exception that left ``task`` (the stored one, with its traceback), or ``None``."""
    done, _ = await asyncio.wait({task}, timeout=_HARD)
    assert done, f"hang: {what}"
    try:
        task.result()
    except BaseException as err:  # noqa: BLE001 - this is what the test collects
        return err
    return None


async def _until(predicate, what: str) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + _HARD
    while not predicate():
        assert loop.time() < end, f"hang: {what}"
        await asyncio.sleep(0)


async def _drive(kind: str, opt: str, hid: _Hidden, captured: list, inj: BaseException):
    """Run one Call scenario. Returns the exceptions that left the publisher."""
    bs = hid.bs
    abort_base = kind in ("timeout", "drain") or (kind == "cancel" and opt == "abort_base")
    failures: tuple[Failure, ...] = ()
    if kind == "base":
        failures = (Failure(opt, inj, 1, None),)
    elif kind == "start" and opt == "close_base":
        failures = (Failure("close", inj, 1, None),)
    block = 1 if kind in ("cancel", "timeout", "drain") else None
    host = FakeHost(mini_states(), failures=failures, block_read=block)
    sessions: list = []

    def factory():
        session = host()
        if abort_base:
            real = session.abort

            def abort() -> None:
                real()  # release a blocked read first, like the real abort
                raise inj

            session.abort = abort
        sessions.append(session)
        return session

    bound = BoundValues({"mini": dict(bs.bound)})
    deadline = 0.05 if kind == "timeout" else 30.0
    registry = build_registry({"mini": (MINI, "test")}, bound, deadline)
    service = CallService(
        registry, bound, _prepared().signatures, Limiter(1), factory,
        clock=FakeClock(), poll_interval=0.01,
    )
    real_run_flow = calls.run_flow

    def spy(flow, session, inputs, **kwargs):
        captured.append(inputs)  # the object handed to run_flow, for the identity check
        if kind == "seam":
            raise inj
        return real_run_flow(flow, session, inputs, **kwargs)

    errs: list[BaseException] = []
    try:
        with mock.patch.object(calls, "run_flow", spy):
            task = asyncio.ensure_future(
                service.execute(registry.get("mini"), SecretBox.adopt(dict(bs.supplied)), "rest")
            )
            if kind in ("cancel", "drain"):
                await _until(lambda: sessions and sessions[-1].blocked.is_set(), "read did not block")
                if kind == "cancel":
                    task.cancel()
                else:
                    drain = asyncio.ensure_future(service.drain(0.0))
                    err = await _result(drain, "drain did not end")
                    if err is not None:
                        errs.append(err)
            err = await _result(task, "call did not end")
            if err is not None:
                errs.append(err)
    finally:
        host.release_all()
    assert errs, "the scenario did not make an exception leave the publisher"
    if kind == "cancel":
        assert any(isinstance(e, asyncio.CancelledError) for e in errs)
    else:
        assert any(e is inj for e in errs), "the injected BaseException did not propagate unchanged"
    assert service._limiter.in_flight == 0
    assert all(s.close_calls == 1 for s in host.sessions)
    return errs


class _StartFails(threading.Thread):
    """A Thread whose ``start`` raises for the worker only (``inj_start`` is set per run)."""

    inj_start: BaseException | None = None

    def start(self) -> None:
        if self._target is calls._worker and type(self).inj_start is not None:
            raise type(self).inj_start
        super().start()


_MARKERS = re.compile(r"^[ \t]*[~^]+[ \t]*$", re.M)
_LINENO = re.compile(r", line \d+,")


def _normalised(text: str) -> str:
    return _LINENO.sub(", line N,", _MARKERS.sub("", text))


def _check(errs: list[BaseException], values: tuple, mappings: list) -> None:
    findings: list[str] = []
    leak_count = 0
    for err in errs:
        findings += scan_frames(err, values, mappings=mappings)
        leak_count += len(find_leaks(_normalised(formatted_traceback(err)), values))
    findings = sorted(set(findings))
    assert not findings, "frames hold values: " + "; ".join(findings)
    assert leak_count == 0, f"{leak_count} Leak_Form(s) in the formatted traceback"


def _bindings_error(opt: str, hid: _Hidden) -> BaseException:
    prefix = "GS_BIND_TK5_SYSTEM_INFO__"
    if opt == "regex":
        # PASSWORD is accepted and stored first (names are sorted), USERID violates its regex
        env = {prefix + "PASSWORD": hid.p1, prefix + "USERID": hid.p2}
    else:
        env = {prefix + "NOPE": hid.p1}
    loaded = _loaded()
    try:
        parse_bindings(env, loaded, tuple(loaded))
    except BaseException as err:  # noqa: BLE001
        return err
    raise AssertionError("parse_bindings accepted a bad environment")


@settings(max_examples=100, deadline=None)
# One example per path, so every run covers each of them.
@example(("cancel", ""), _A)
@example(("cancel", "abort_base"), _B)
@example(("base", "factory"), _A)
@example(("base", "open"), _B)
@example(("base", "read_screen"), _A)
@example(("base", "string"), _B)
@example(("base", "enter"), _A)
@example(("base", "close"), _B)
@example(("seam", ""), _A)
@example(("start", "base"), _B)
@example(("start", "close_base"), _A)
@example(("timeout", ""), _B)
@example(("drain", ""), _A)
@example(("bindings", "regex"), _A)
@example(("bindings", "unknown_input"), _B)
@given(SCENARIOS, HIDDEN)
def test_no_traceback_frame_holds_a_value(scn, hid):
    # Feature: publisher, Property 10: No traceback frame of the publisher holds a value
    kind, opt = scn
    if kind == "bindings":
        _check([_bindings_error(opt, hid)], hid.values, [])
        return
    captured: list = []
    inj = InjectedBase("injected base")
    if kind == "start":
        _StartFails.inj_start = inj if opt == "base" else RuntimeError("cannot start")
        patch = mock.patch.object(threading, "Thread", _StartFails)
    else:
        patch = mock.patch.object(threading, "Thread", threading.Thread)
    try:
        with patch:
            errs = asyncio.run(asyncio.wait_for(_drive(kind, opt, hid, captured, inj), _WHOLE))
    finally:
        _StartFails.inj_start = None
    _check(errs, hid.values, captured)
