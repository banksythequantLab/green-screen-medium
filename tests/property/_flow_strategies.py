"""Shared Hypothesis strategies for the flow-runtime property tests.

Strategies draw small integers and indexes into module-level pools built once at
import, so the Hypothesis health checks stay quiet and a draw is cheap. Screens
come from ``tests/flow_support.py`` (cached prototypes, all in memory). This module
does not import the runner.

``flows()`` is ``PARTS.map(build_from_parts)``: about 14 integers and one short text
per draw, at most 6 top-level Steps, 2 Inputs, 2 Outputs, handle bodies of 1 to 2
Steps and 2 ``finally`` Steps (task 18.1, design "Trimmed flows()").

Timings of task 18.1 (100 draws, best of three, ``time.perf_counter``, dev machine):
    before: 2.769 s for 100 draws, 3.293 s for 100 draws with the YAML round trip
    after:  0.163 s for 100 draws, 1.030 s for 100 draws with the YAML round trip
"""
from __future__ import annotations

from dataclasses import dataclass

from hypothesis import strategies as st

from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import (
    ScriptedState,
    blank_screen,
    capture,
    partial_repaint,
    pause_variant,
)

SIGNATURE_NAMES: tuple[str, ...] = tuple(s.name for s in load_bundled_signatures())

# Alphabet of generated Secret_Values. No other generated text (literals,
# descriptions, regexes, names) and no capture file contains these characters.
SECRET_ALPHABET = "~^!"

# Captures whose cursor sits in an unprotected field (a Type_Step can target it).
TYPEABLE: tuple[str, ...] = (
    "tk5-logon",
    "tso-password-prompt",
    "ispf-primary-menu",
    "tso-ready",
)

_LITERAL_ALPHABET = st.characters(
    min_codepoint=0x20, max_codepoint=0x7E, exclude_characters="$" + SECRET_ALPHABET
)
# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------

def secrets() -> st.SearchStrategy[str]:
    """A Secret_Value of 1 to 8 characters from an alphabet used in no other generated text."""
    return st.text(alphabet=SECRET_ALPHABET, min_size=1, max_size=8)


# --------------------------------------------------------------------------
# flows()
# --------------------------------------------------------------------------
#
# Every strategy object and every reusable value is built once, here at import.
# A draw is one ``PARTS`` draw (about 14 integers and one short text) mapped
# through the pure ``build_from_parts``; nothing below the ``def`` of a strategy
# runs a regex, builds a ``Timeouts`` or an ``InputSpec``, or calls the recognizer.

_SIGS = SIGNATURE_NAMES
_NSIG = len(_SIGS)

FLOW_NAMES: tuple[str, ...] = (
    "a", "tk5-flow", "flow_1", "-", "_", "0", "null", "true", "123", "no",
    "a" * 64, "z9-_x" * 12,
)

# Texts for Type_Steps (1 to 255 printable ASCII, no "${", none of SECRET_ALPHABET).
TEXT_POOL: tuple[str, ...] = (
    "A", "x y", "null", "true", "yes", "no", "123", "1.5", "0x1F", "a: b", "# x",
    "- y", "'q'", '"q"', "  pad  ", " lead", "trail ", "{a}", "[b]", "&c", "*d",
    "x\\y", "%z", "@w", "key: [1, 2]", "a,b", "q'\"r", "100%", "tab-free text",
    "Z" * 255,
)
_N_TEXT = len(TEXT_POOL)

# Descriptions (at most 200 characters). Includes the empty string and non-ASCII text.
DESC_POOL: tuple[str, ...] = (
    "", "", "Look up an account", "a: b", "# not a comment", "  padded  ", "'q' and \"q\"",
    "back\\slash", "caf\u00e9 \u2603", "yes", "null", "1", "line one. line two", "D" * 200,
)

_TIMEOUT_VALUES = (None, 0.1, 5.0, 60.0)

TIMEOUT_SETS: tuple[Timeouts, ...] = (
    Timeouts(),
    Timeouts(0.1, 1, 1),
    Timeouts(60, 600, 120),
    Timeouts(2.5, 45, 15),
)

_IN_NAMES = ("userid", "password", "acct", "Code", "n1", "amount", "ref_no", "Q")
_IN_VARIANTS = (
    # (type, required, max_length, regex, secret, description)
    ("str", True, 8, "[A-Z]+", False, ""),
    ("str", False, 255, None, True, "A secret"),
)
_IN_INT_VARIANT = ("int", True, 1, "[0-9]{1,4}", False, "caf\u00e9")


def _input_pool() -> tuple[InputSpec, ...]:
    pool: list[InputSpec] = []
    for i, name in enumerate(_IN_NAMES):
        for v in range(2):
            # Half of the names get an int variant, so every option combination occurs.
            t, req, ml, rx, sec, desc = (
                _IN_INT_VARIANT if (i + v) % 4 == 3 else _IN_VARIANTS[v]
            )
            if i % 2:
                req = not req
            pool.append(InputSpec(name, t, req, ml, rx, sec, desc))
    return tuple(pool)


INPUT_POOL: tuple[InputSpec, ...] = _input_pool()


def _subsets(pool: tuple, limit: int = 2) -> tuple[tuple, ...]:
    out: list[tuple] = [()]
    out += [(a,) for a in pool]
    if limit >= 2:
        out += [(a, b) for i, a in enumerate(pool) for b in pool[i + 1 :] if a.name != b.name]
    return tuple(out)


INPUT_SETS: tuple[tuple[InputSpec, ...], ...] = _subsets(INPUT_POOL)

_OUT_NAMES = ("USERID", "SYSTEMID", "RELEASE", "TERMINAL", "total", "Status", "x1")


def _output_pool() -> tuple[OutputSpec, ...]:
    pool: list[OutputSpec] = []
    for i, name in enumerate(_OUT_NAMES):
        for v in range(2):
            col = (i * 11 + v * 40) % 70
            pool.append(
                OutputSpec(
                    name,
                    "str" if v == 0 else "int",
                    _SIGS[(i + v * 3) % _NSIG],
                    (i * 3 + v * 7) % 24,
                    col,
                    1 + (i + v * 5) % (80 - col) if v == 0 else min(18, 80 - col),
                )
            )
    return tuple(pool)


OUTPUT_POOL: tuple[OutputSpec, ...] = _output_pool()
OUTPUT_SETS: tuple[tuple[OutputSpec, ...], ...] = _subsets(OUTPUT_POOL)


def _expect_shapes() -> tuple[ExpectStep, ...]:
    shapes: list[ExpectStep] = []
    for i, name in enumerate(_SIGS):
        for v in range(8):
            sigs = (name,) if v % 2 == 0 else (name, _SIGS[(i + 1 + v % 3) % _NSIG])
            tolerate: tuple[str, ...] = ()
            if v & 2:
                tolerate = next((s,) for s in _SIGS[(i + 3) :] + _SIGS[: i + 3] if s not in sigs)
            shapes.append(ExpectStep(sigs, tolerate, _TIMEOUT_VALUES[(v + i) % 4]))
    return tuple(shapes)


EXPECT_SHAPES: tuple[ExpectStep, ...] = _expect_shapes()
EXPECT_FOR: dict[str, tuple[ExpectStep, ...]] = {
    name: tuple(e for e in EXPECT_SHAPES if name in e.signatures) for name in _SIGS
}

KEYS: tuple[KeyStep, ...] = (
    KeyStep("enter"), KeyStep("clear"), KeyStep("pf", 1), KeyStep("pf", 24),
    KeyStep("pa", 1), KeyStep("pa", 3),
)

_TYPE_LITERALS: tuple[TypeStep, ...] = tuple(TypeStep(text=t) for t in TEXT_POOL)
_TYPE_INPUTS: dict[str, TypeStep] = {s.name: TypeStep(input=s.name) for s in INPUT_POOL}

# Handle bodies: 1 to 2 Steps, a Key_Step last.
HANDLE_BODIES: tuple[tuple, ...] = (
    (KEYS[0],),
    (KEYS[2],),
    (KEYS[1],),
    (_TYPE_LITERALS[0], KEYS[0]),
    (_TYPE_LITERALS[2], KEYS[3]),
)
_HANDLE_SHAPES = ((1, 0.0), (3, 0.5), (20, 0.0), (5, 10.0))
HANDLE_STEPS: tuple[HandleStep, ...] = tuple(
    HandleStep(sig, mc, body, settle)
    for sig in _SIGS
    for body in HANDLE_BODIES
    for mc, settle in _HANDLE_SHAPES
)

# Finally plans of at most 2 top-level Steps (none of them an Extract_Step).
_LOGON = EXPECT_FOR["tk5-logon"][0]
_READY = EXPECT_FOR["tso-ready"][0]
FINALLY_PLANS: tuple[tuple, ...] = (
    (),
    (_LOGON,),
    (_READY, KeyStep("enter")),
    (_READY, TypeStep(text="LOGOFF")),
    (EXPECT_FOR["ispf-primary-menu"][1], KEYS[3]),
    (HANDLE_STEPS[0],),
    (HANDLE_STEPS[len(HANDLE_STEPS) // 2],),
    (_LOGON, KEYS[1]),
)

MAX_TOP_STEPS = 6
_BLOCK_SPAN = 3 * len(EXPECT_SHAPES) * len(KEYS) * (_N_TEXT + 1) * 4


@dataclass(frozen=True)
class FlowParts:
    """Small integers (and one short text) that ``build_from_parts`` turns into a Flow."""

    name: int
    description: int
    inputs: int
    outputs: int
    timeouts: int
    finally_plan: int
    n_blocks: int
    block0: int
    block1: int
    block2: int
    out_pos0: int
    out_pos1: int
    text: str


_RANDOM_TEXT = st.text(alphabet=_LITERAL_ALPHABET, min_size=1, max_size=8)

PARTS: st.SearchStrategy[FlowParts] = st.builds(
    FlowParts,
    name=st.integers(0, len(FLOW_NAMES) - 1),
    description=st.integers(0, len(DESC_POOL) - 1),
    inputs=st.integers(0, len(INPUT_SETS) - 1),
    outputs=st.integers(0, len(OUTPUT_SETS) - 1),
    timeouts=st.integers(0, len(TIMEOUT_SETS) - 1),
    finally_plan=st.integers(0, len(FINALLY_PLANS) - 1),
    n_blocks=st.integers(0, 3),
    block0=st.integers(0, _BLOCK_SPAN - 1),
    block1=st.integers(0, _BLOCK_SPAN - 1),
    block2=st.integers(0, _BLOCK_SPAN - 1),
    out_pos0=st.integers(0, 3),
    out_pos1=st.integers(0, 3),
    text=_RANDOM_TEXT,
)


def _action_block(code: int, first: bool, input_names: tuple[str, ...], text: str) -> tuple:
    """One action block: Expect + Key, Expect + Type + Key, or one Handle_Step.

    The first block is never a Handle_Step, so a Flow with any action block has an
    Expect-armed block for ``unarm`` to strip.
    """
    code, kind = divmod(code, 3)
    code, shape = divmod(code, len(EXPECT_SHAPES))
    code, key = divmod(code, len(KEYS))
    code, ti = divmod(code, _N_TEXT + 1)
    ref = code  # 0 to 3
    if kind == 2 and not first:
        return (HANDLE_STEPS[(shape * len(KEYS) + key) % len(HANDLE_STEPS)],)
    expect = EXPECT_SHAPES[shape]
    if kind == 1 or kind == 2:
        if input_names and ref % 2 == 0:
            typed = _TYPE_INPUTS[input_names[ref // 2 % len(input_names)]]
        elif ti == _N_TEXT:
            typed = TypeStep(text=text)
        else:
            typed = _TYPE_LITERALS[ti]
        return (expect, typed, KEYS[key])
    return (expect, KEYS[key])


def build_from_parts(parts: FlowParts, *, unarm: int | None = None) -> Flow:
    """Build one valid Flow from ``parts`` (pure; the Flow is constructed once).

    Every Key_Step and Type_Step is armed by construction. Output blocks (an
    Expect_Step from ``EXPECT_FOR[output.signature]`` plus the Extract_Step) are
    never dropped; whole action blocks are cut from the end until the top-level
    Steps number at most 6.

    ``unarm=k`` removes the Expect_Step of the ``k``-th (modulo) Expect-armed action
    block, and Output blocks are then placed after all action blocks, so the first
    violation is that block's Type_Step or Key_Step. The ``Flow`` constructor then
    raises ``FlowDefinitionError`` (Requirement 5.6 to 5.8). It raises
    ``ValueError`` when the parts hold no action block.
    """
    inputs = INPUT_SETS[parts.inputs]
    outputs = OUTPUT_SETS[parts.outputs]
    input_names = tuple(s.name for s in inputs)

    n = parts.n_blocks
    if n == 0 and not outputs:
        n = 1  # a Flow needs at least one Step
    codes = (parts.block0, parts.block1, parts.block2)
    blocks = [_action_block(codes[i], i == 0, input_names, parts.text) for i in range(n)]

    out_blocks = [
        (EXPECT_FOR[o.signature][(o.row + o.col) % len(EXPECT_FOR[o.signature])], ExtractStep(o.name))
        for o in outputs
    ]
    reserved = 2 * len(out_blocks)
    keep = 1 if unarm is not None else 0
    while len(blocks) > keep and sum(map(len, blocks)) + reserved > MAX_TOP_STEPS:
        blocks.pop()

    if unarm is not None:
        armed = [i for i, b in enumerate(blocks) if isinstance(b[0], ExpectStep)]
        if not armed:
            raise ValueError("parts hold no Expect-armed action block to unarm")
        target = armed[unarm % len(armed)]
        blocks[target] = blocks[target][1:]
        blocks.extend(out_blocks)
    else:
        for ob, pos in zip(out_blocks, (parts.out_pos0, parts.out_pos1)):
            blocks.insert(pos % (len(blocks) + 1), ob)

    return Flow(
        name=FLOW_NAMES[parts.name],
        steps=tuple(s for b in blocks for s in b),
        description=DESC_POOL[parts.description],
        inputs=inputs,
        outputs=outputs,
        finally_steps=FINALLY_PLANS[parts.finally_plan],
        timeouts=TIMEOUT_SETS[parts.timeouts],
    )


_FLOWS: st.SearchStrategy[Flow] = PARTS.map(build_from_parts)


def flows() -> st.SearchStrategy[Flow]:
    """A valid Flow: all five Step kinds, Inputs with every option, Outputs.

    At most 6 top-level Steps, 2 Inputs, 2 Outputs, handle bodies of 1 to 2 Steps
    and 2 ``finally`` Steps. Every Key_Step and Type_Step is armed by construction
    and every Output has one Extract_Step right after an Expect_Step that lists its
    Signature_Name.
    """
    return _FLOWS


# --------------------------------------------------------------------------
# chain_scripts()
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainStep:
    """One screen of a chain. Indexes and small numbers only, no Screen."""

    name: str
    literal: str | None  # typed before the key; None on the last screen
    key: tuple  # ("enter",), ("clear",), ("pf", n) or ("pa", n); unused on the last screen
    stale_reads: int  # 0 to 10 stale reads after the key that leads to this screen
    repaints: tuple[int, ...]  # 0 is a blank screen, k > 0 is partial_repaint(previous, k - 1)


@dataclass(frozen=True)
class ChainScript:
    steps: tuple[ChainStep, ...]
    flow: Flow

    def states(self, *, fail_at: int | None = None) -> list[ScriptedState]:
        """Build the ScriptedStates. ``fail_at`` swaps that state's own Screen for a blank one."""
        out: list[ScriptedState] = []
        for i, step in enumerate(self.steps):
            if fail_at == i:
                screen = blank_screen()
            elif step.name == "tso-pause":
                screen = pause_variant(i)
            else:
                screen = capture(step.name)
            repaints = ()
            if i > 0:
                prev = self.steps[i - 1].name
                repaints = tuple(
                    blank_screen() if code == 0 else partial_repaint(prev, code - 1)
                    for code in step.repaints
                )
            out.append(
                ScriptedState(screen, stale_reads=step.stale_reads if i else 0, repaints=repaints)
            )
        return out

    def expected_calls(self) -> list[tuple]:
        """The typing and key calls a correct run sends, in order."""
        calls: list[tuple] = []
        for step in self.steps[:-1]:
            if step.literal is not None:
                calls.append(("string", step.literal))
            calls.append(step.key)
        return calls


_CHAIN_KEYS = (("enter",), ("enter",), ("enter",), ("clear",), ("pf", 3), ("pa", 2))


def _chain_flow(steps: tuple[ChainStep, ...], step_timeout: float | None = None) -> Flow:
    flow_steps: list = []
    for i, step in enumerate(steps):
        flow_steps.append(ExpectStep((step.name,)))
        if i == len(steps) - 1:
            if step.name != "tso-password-prompt":  # its row 1 holds the hidden field
                flow_steps.append(ExtractStep("TEXT"))
            break
        if step.literal is not None:
            flow_steps.append(TypeStep(text=step.literal))
        flow_steps.append(KeyStep(*step.key))
    last = steps[-1].name
    outputs = ()
    if last != "tso-password-prompt":
        outputs = (OutputSpec("TEXT", "str", last, 0, 0, 8),)
    timeouts = Timeouts() if step_timeout is None else Timeouts(step=step_timeout)
    return Flow(name="chain", steps=tuple(flow_steps), outputs=outputs, timeouts=timeouts)


@st.composite
def chain_scripts(
    draw, max_screens: int = 6, max_stale: int = 5, step_timeout: float | None = None
) -> ChainScript:
    """A chain of 2 to 6 screens (adjacent names differ), the matching Flow and the script variations.

    ``step_timeout`` (seconds) overrides the Flow's default step timeout; None keeps it.
    """
    n = draw(st.integers(2, max_screens))
    count = len(SIGNATURE_NAMES)
    idx = draw(st.integers(0, count - 1))
    steps: list[ChainStep] = []
    for i in range(n):
        if i:
            idx = (idx + draw(st.integers(1, count - 1))) % count  # never equal to the previous
        name = SIGNATURE_NAMES[idx]
        last = i == n - 1
        literal = None
        if not last and name in TYPEABLE and draw(st.booleans()):
            literal = draw(st.text(alphabet=_LITERAL_ALPHABET, min_size=1, max_size=8))
        steps.append(
            ChainStep(
                name=name,
                literal=literal,
                key=draw(st.sampled_from(_CHAIN_KEYS)),
                stale_reads=draw(st.integers(0, max_stale)),
                repaints=tuple(draw(st.lists(st.integers(0, 3), max_size=3))),
            )
        )
    frozen = tuple(steps)
    return ChainScript(frozen, _chain_flow(frozen, step_timeout))


# --------------------------------------------------------------------------
# handle_counts()
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class HandleCount:
    max_count: int  # N, 1 to 20
    shown: int  # k, 0 to 20: how many times the handled screen is shown
    forever: bool  # the handled screen never goes away


def handle_counts() -> st.SearchStrategy[HandleCount]:
    return st.builds(
        HandleCount,
        max_count=st.integers(1, 20),
        shown=st.integers(0, 20),
        forever=st.booleans(),
    )


# --------------------------------------------------------------------------
# typed_cases()
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TypedCase:
    name: str
    text: str
    mdt: bool


def _cells_to_field_end(name: str) -> int:
    """Data cells from the cursor to the end of the cursor field (the cursor cell included)."""
    s = capture(name)
    f = s.find_field(s.cursor_row, s.cursor_col)
    assert f is not None, name
    total = s.rows * s.columns
    ls = f.start_row * s.columns + f.start_col
    lc = s.cursor_row * s.columns + s.cursor_col
    return f.byte_length - ((lc - ls) % total) + 1


# Property 8 bounds: one cell short for the three screens whose Signature has a
# cursor_field matcher, the whole run to the end for tso-ready.
_TYPED_MAX: dict[str, int] = {
    name: min(255, _cells_to_field_end(name) - (0 if name == "tso-ready" else 1))
    for name in TYPEABLE
}
assert all(v >= 1 for v in _TYPED_MAX.values()), _TYPED_MAX


@st.composite
def typed_cases(draw) -> TypedCase:
    name = draw(st.sampled_from(TYPEABLE))
    text = draw(
        st.text(
            alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
            min_size=1,
            max_size=_TYPED_MAX[name],
        )
    )
    return TypedCase(name, text, draw(st.booleans()))
