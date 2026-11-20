# Feature: polish, Property 8: Count_Output validation agrees with its mutations
"""Property 8 of the polish spec (task 4.3).

A valid Flow with a Rows_Output and a Count_Output is accepted. Each mutation from a
fixed list is rejected with the rule that the table below defines. The message names
the output and the rule, and holds none of the generated text. Static: no host, no
screens.
"""
from __future__ import annotations

import dataclasses

from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import (
    CollectStep,
    ExpectStep,
    ExtractStep,
    Flow,
    OutputSpec,
)
from greenscreen.flow.validate import check_flow, structural_violations
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

_SIGS = [
    ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),)),
    ScreenSignature("more", (TextAtMatcher(0, 0, "MORE"),)),
]

# mutation -> the rules it must produce. A max_rows or next_row on an int output also
# breaks the more-flows rule that belongs to that member, so those two list it.
_EXPECTED: dict[str, frozenset[str]] = {
    "type_str": frozenset({"counts_requires_int"}),
    "add_max_rows": frozenset({"counts_excludes_extras", "rows_requires_str"}),
    "add_next_row": frozenset({"counts_excludes_extras", "next_row_requires_rows"}),
    "add_equals": frozenset({"counts_excludes_extras"}),
    "unknown": frozenset({"counts_unknown_output"}),
    "self": frozenset({"counts_unknown_output"}),
    "target_not_rows": frozenset({"counts_target_not_rows"}),
    "region_signature": frozenset({"counts_region_mismatch"}),
    "region_row": frozenset({"counts_region_mismatch"}),
    "region_col": frozenset({"counts_region_mismatch"}),
    "region_length": frozenset({"counts_region_mismatch"}),
    "extract_count": frozenset({"counts_not_readable"}),
    "collect_count": frozenset({"counts_not_readable"}),
}
_STEP_LEVEL = {"extract_count", "collect_count"}
_COUNTS_RULES = frozenset(r for rules in _EXPECTED.values() for r in rules if r.startswith("counts_"))

_NAME = st.builds(
    lambda head, tail: head + tail,
    st.sampled_from("ABCDEFGHJKLMNPQRSTUVWXYZ"),
    st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", min_size=5, max_size=11),
)


@st.composite
def _cases(draw):
    rows_name, count_name, extra_name, unknown = draw(
        st.lists(_NAME, min_size=4, max_size=4, unique=True).filter(
            lambda n: n[3] not in n[0] + n[1] + n[2]
        )
    )
    row = draw(st.integers(1, 23))
    col = draw(st.integers(0, 60))
    length = draw(st.integers(2, 20))
    max_rows = draw(st.integers(1, 500))
    read = draw(st.sampled_from(("extract", "collect")))
    mutation = draw(st.sampled_from(sorted(_EXPECTED)))
    equals = draw(st.text(alphabet="~^`|", min_size=1, max_size=2))
    delta = draw(st.integers(1, 5))
    return (rows_name, count_name, extra_name, unknown, row, col, length, max_rows, read,
            mutation, equals, delta)


def _other(value: int, delta: int, lo: int, hi: int) -> int:
    """A value in [lo, hi] that differs from ``value`` (the range is wider than ``delta``)."""
    span = hi - lo + 1
    assert span > delta
    return lo + (value - lo + delta) % span


def _unchecked(flow: Flow, **changes) -> Flow:
    """``flow`` with ``changes`` applied and no validation, to list every violation."""
    raw = object.__new__(Flow)
    for f in dataclasses.fields(Flow):
        object.__setattr__(raw, f.name, changes.get(f.name, getattr(flow, f.name)))
    return raw


def _base(case) -> Flow:
    rows_name, count_name, _x, _u, row, col, length, max_rows, read, *_ = case
    rows = OutputSpec(rows_name, "str", "tiny", row, col, length, None, max_rows)
    count = OutputSpec(count_name, "int", "tiny", row, col, length, counts=rows_name)
    reader = (
        ExtractStep(rows_name) if read == "extract" else CollectStep(rows_name, "more", 3)
    )
    return Flow(
        "counts-flow",
        (ExpectStep(("tiny", "more")), reader),
        outputs=(rows, count),
    )


def _mutate(flow: Flow, case) -> tuple[Flow, tuple[str, ...]]:
    rows_name, count_name, extra_name, unknown, row, col, length, _m, _r, mutation, equals, delta = case
    rows, count = flow.outputs
    secrets: tuple[str, ...] = ()

    def with_count(**changes) -> Flow:
        return _unchecked(flow, outputs=(rows, dataclasses.replace(count, **changes)))

    if mutation == "type_str":
        return with_count(type="str"), secrets
    if mutation == "add_max_rows":
        return with_count(max_rows=5), secrets
    if mutation == "add_next_row":
        return with_count(next_row=2), secrets
    if mutation == "add_equals":
        return with_count(equals=equals), (equals,)
    if mutation == "unknown":
        return with_count(counts=unknown), (unknown,)
    if mutation == "self":
        return with_count(counts=count_name), secrets
    if mutation == "target_not_rows":
        plain = OutputSpec(extra_name, "str", "tiny", row, col, length)
        steps = flow.steps + (ExtractStep(extra_name),)
        return (
            _unchecked(flow, steps=steps, outputs=(rows, dataclasses.replace(count, counts=extra_name), plain)),
            secrets,
        )
    if mutation == "region_signature":
        return with_count(signature="more"), secrets
    if mutation == "region_row":
        return with_count(row=_other(row, delta, 0, 23)), secrets
    if mutation == "region_col":
        return with_count(col=_other(col, delta, 0, 80 - length)), secrets
    if mutation == "region_length":
        return with_count(length=_other(length, delta, 1, 80 - col)), secrets
    if mutation == "extract_count":
        return _unchecked(flow, steps=flow.steps + (ExtractStep(count_name),)), secrets
    if mutation == "collect_count":
        return _unchecked(flow, steps=flow.steps + (CollectStep(count_name, "more", 3),)), secrets
    raise AssertionError(mutation)


@settings(max_examples=200, deadline=None)
@given(_cases())
def test_count_output_validation_agrees_with_its_mutations(case):
    """**Validates: Requirements 13.3, 13.4, 13.5, 13.6, 13.7, 13.9**"""
    base = _base(case)
    assert structural_violations(base) == []
    check_flow(base, _SIGS)  # accepted

    mutation = case[9]
    count_name = case[1]
    event(f"mutation={mutation}")
    mutant, generated = _mutate(base, case)

    found = structural_violations(mutant)
    assert found, mutation
    assert {v.rule for v in found} == _EXPECTED[mutation]
    for v in found:
        if v.rule in _COUNTS_RULES and mutation not in _STEP_LEVEL:
            assert v.step_index is None
            assert v.field == f"output {count_name}.counts"
        if mutation in _STEP_LEVEL:
            assert v.step_index == 2 and v.field == "output"

    # The Flow constructor runs the structural rules itself; check_flow adds the
    # signature references. Both must refuse, with the same first violation.
    for refuse in (
        lambda: Flow(mutant.name, mutant.steps, outputs=mutant.outputs),
        lambda: check_flow(mutant, _SIGS),
    ):
        try:
            refuse()
        except FlowDefinitionError as exc:
            message = str(exc)
        else:
            raise AssertionError(f"{mutation} was accepted")
        _check_message(message, mutation, count_name, generated, found)


def _check_message(message, mutation, count_name, generated, found) -> None:
    first = min(found, key=lambda v: (v.step_index is None, v.step_index or 0,
                                      v.requirement, v.criterion, v.field))
    assert first.rule in message
    assert first.rule in _EXPECTED[mutation]
    if mutation in _STEP_LEVEL:
        # A step violation names the step and its kind; the output name is not in it.
        assert "step 2" in message
    else:
        assert count_name in message
    for text in generated:
        assert text not in message


# Feature: polish, Property 9: The count equals the number of rows read
"""Property 9 of the polish spec (task 4.4).

Over any listing of 0 to 10 pages of 0 to 22 lines, a Flow with a Rows_Output and a
Count_Output returns the count as an ``int`` (not a ``bool``) equal to the number of
lines on the pages, outputs in declaration order, and the keys sent and the audit equal
those of the same Flow without the Count_Output. No host: a ScriptedSession.
"""
from greenscreen.flow.model import Timeouts
from greenscreen.flow.runner import run_flow
from tests.flow_support import FakeClock, ScriptedSession
from tests.property._collect_support import page_sequence

_T = Timeouts(step=2.0, run=60.0, finally_=30.0)
_ARMING = ("tso-ready", "tso-pause")
_ROWS = OutputSpec("LINES", "str", "tso-ready", 1, 1, 79, next_row=0, max_rows=300)
_COUNT = OutputSpec("N", "int", "tso-ready", 1, 1, 79, counts="LINES")


def _listing_flow(*outputs: OutputSpec) -> Flow:
    return Flow(
        "counts-run",
        (ExpectStep(_ARMING), CollectStep("LINES", "tso-pause", 12)),
        outputs=outputs,
        timeouts=_T,
    )


def _run(flow: Flow, seq):
    session = ScriptedSession(seq.states())
    result = run_flow(flow, session, {}, clock=FakeClock())
    return result, session.calls


@st.composite
def _page_counts(draw):
    """1 to 10 pages of 0 to 22 lines. One page of 0 lines is the empty listing. A middle
    page is never empty (it would equal the page before it, which the runner reads as no
    answer yet), and a lone page ends in READY at row 1, so it holds 21 lines at most."""
    n = draw(st.integers(1, 10))
    counts = [draw(st.integers(0, 21 if n == 1 else 22))]
    counts += [draw(st.integers(1, 22)) for _ in range(n - 2)]
    if n > 1:
        counts.append(draw(st.integers(0, 22)))
    return counts


@settings(max_examples=100, deadline=None)
@given(_page_counts(), st.booleans())
def test_count_equals_the_number_of_rows_read(lines_per_page, count_first):
    """**Validates: Requirements 14.1, 14.2, 14.3, 14.5, 14.6**"""
    seq = page_sequence(lines_per_page)
    total = len(seq.all_tokens)
    event(f"empty={total == 0}")
    outputs = (_COUNT, _ROWS) if count_first else (_ROWS, _COUNT)

    result, calls = _run(_listing_flow(*outputs), seq)
    plain, plain_calls = _run(_listing_flow(_ROWS), page_sequence(lines_per_page))

    count = result.outputs["N"]
    value = result.outputs["LINES"]
    assert type(count) is int
    assert count == total
    assert count == (len(value.split("\n")) if value else 0)
    assert value.split("\n") == list(seq.all_tokens) if value else total == 0
    assert list(result.outputs) == [o.name for o in outputs]

    assert calls == plain_calls
    assert result.audit == plain.audit
    assert plain.outputs["LINES"] == value
