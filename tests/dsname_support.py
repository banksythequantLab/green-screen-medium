"""Shared test support for the ``dsname`` input rule (spec more-flows, task 5.1).

Test support only, no production change. It holds:

* ``DSNAME_SPEC``: the exact ``dsname`` input of design section 5, as an ``InputSpec``;
* ``scanner``: the Reference_Scanner, a character loop over explicit code-point
  sets (no ``re``, no ``str.isalpha`` / ``isdigit`` / ``isalnum``, and no copy of
  the Dsn_Pattern);
* Hypothesis strategies for valid names, names of up to 23 qualifiers, arbitrary
  text and one-character mutations from the hostile set of Property 6;
* ``name_flow``: a test-only Flow that types ``LISTDS '`` + name + ``'`` (or
  ``' MEMBERS``) over a ``ScriptedSession``.
"""
from __future__ import annotations

from hypothesis import strategies as st

from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep

from tests.flow_support import ScriptedSession, capture

# --------------------------------------------------------------------------
# The exact input of design section 5
# --------------------------------------------------------------------------

DSNAME_MAX_LENGTH = 44

DSNAME_REGEX = (
    r"[A-Za-z$#@][A-Za-z0-9$#@]{0,7}"
    r"(?:\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21}"
)

DSNAME_DESCRIPTION = (
    "Data set name, e.g. SYS2.JCLLIB, any case. Up to 44 characters. "
    "Dot-separated qualifiers of 1-8 characters, each starting with a letter, "
    "dollar, number sign or at sign, then letters, digits or those."
)

DSNAME_SPEC = InputSpec(
    name="dsname",
    type="str",
    required=True,
    max_length=DSNAME_MAX_LENGTH,
    regex=DSNAME_REGEX,
    secret=False,
    description=DSNAME_DESCRIPTION,
)

assert len(DSNAME_DESCRIPTION) == 199
assert len(DSNAME_REGEX) == 72

# --------------------------------------------------------------------------
# Reference_Scanner
# --------------------------------------------------------------------------

_UP = frozenset(map(ord, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
_LO = frozenset(map(ord, "abcdefghijklmnopqrstuvwxyz"))
_DIG = frozenset(map(ord, "0123456789"))
_NAT = frozenset(map(ord, "$#@"))
_FIRST = _UP | _LO | _NAT
_REST = _UP | _LO | _DIG | _NAT


def scanner(name: str) -> bool:
    """True when ``name`` obeys the Dsn_Rule (decided character by character)."""
    if not 1 <= len(name) <= DSNAME_MAX_LENGTH:
        return False
    q = 0  # characters in the current qualifier
    for ch in name:
        c = ord(ch)
        if c == 0x2E:  # "."
            if q == 0:
                return False  # leading dot or ".."
            q = 0
            continue
        if q == 0:
            if c not in _FIRST:
                return False
        elif c not in _REST:
            return False
        q += 1
        if q > 8:
            return False
    return q != 0  # no trailing dot


# --------------------------------------------------------------------------
# Name strategies
# --------------------------------------------------------------------------

_FIRST_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz$#@"
_REST_CHARS = _FIRST_CHARS + "0123456789"

# The hostile characters of Property 6 (the dot is covered by the structural cases).
HOSTILE_CHARS: tuple[str, ...] = (
    "'", '"', " ", "\t", "(", ")", ",", "*", "%", "-", "_", "/", "\\",
    "\n", "\r", "\x00", "\x07", "\x1b", "\x7f",
    "\u00e9",  # e acute
    "\uff11",  # full-width digit one
    "\u0661",  # Arabic-Indic digit one
    "\u200f",  # right-to-left mark
    ".",
)


@st.composite
def _qualifier(draw, max_size: int = 8) -> str:
    first = draw(st.sampled_from(_FIRST_CHARS))
    rest = draw(st.text(alphabet=_REST_CHARS, min_size=0, max_size=max_size - 1))
    return first + rest


def _join_within(quals: list[str], limit: int) -> str:
    """Join qualifiers, dropping trailing ones until the name fits ``limit``."""
    while len(quals) > 1 and len(".".join(quals)) > limit:
        quals = quals[:-1]
    return ".".join(quals)


@st.composite
def valid_names(draw) -> str:
    """Names the Dsn_Rule accepts: 1 to 22 qualifiers, at most 44 characters."""
    quals = draw(st.lists(_qualifier(), min_size=1, max_size=22))
    return _join_within(quals, DSNAME_MAX_LENGTH)


@st.composite
def long_names(draw) -> str:
    """Well-formed qualifiers, 1 to 23 of them, with no length cap (may exceed 44)."""
    quals = draw(st.lists(_qualifier(), min_size=1, max_size=23))
    return ".".join(quals)


@st.composite
def structural_names(draw) -> str:
    """Names with a structural fault: dots, a nine-character qualifier, 45+ characters, empty."""
    base = draw(valid_names())
    kind = draw(st.sampled_from(("double_dot", "leading", "trailing", "nine", "long", "empty")))
    if kind == "double_dot":
        i = draw(st.integers(0, len(base)))
        return base[:i] + ".." + base[i:]
    if kind == "leading":
        return "." + base
    if kind == "trailing":
        return base + "."
    if kind == "nine":
        nine = draw(st.sampled_from(_FIRST_CHARS)) + draw(
            st.text(alphabet=_REST_CHARS, min_size=8, max_size=8)
        )
        return ".".join([nine] + base.split(".")[1:])
    if kind == "long":
        # well-formed qualifiers, 45 or more characters in all
        k = draw(st.integers(6, 22))
        return ".".join(["ABCDEFGH"] * k)
    return ""


@st.composite
def mutated_names(draw) -> str:
    """A valid or long name with one character inserted or replaced from the hostile set."""
    base = draw(st.one_of(valid_names(), long_names()))
    ch = draw(st.sampled_from(HOSTILE_CHARS))
    if draw(st.booleans()) and base:
        i = draw(st.integers(0, len(base) - 1))
        return base[:i] + ch + base[i + 1:]
    i = draw(st.integers(0, len(base)))
    return base[:i] + ch + base[i:]


def arbitrary_text():
    """Any text up to 50 characters, plus a printable-ASCII variant."""
    printable = st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=50)
    return st.one_of(st.text(max_size=50), printable)


def dsname_candidates():
    """The full mix of Property 6: valid, long, structural, mutated, arbitrary, empty."""
    return st.one_of(
        valid_names(),
        long_names(),
        structural_names(),
        mutated_names(),
        arbitrary_text(),
        st.just(""),
    )


# --------------------------------------------------------------------------
# Test-only Flow over ScriptedSession
# --------------------------------------------------------------------------

def name_flow(*, members: bool = False) -> Flow:
    """A Flow that types ``LISTDS '`` + dsname + ``'`` (``' MEMBERS`` when ``members``)."""
    closing = "' MEMBERS" if members else "'"
    return Flow(
        "dsname-test",
        (
            ExpectStep(("tso-cleared",)),
            TypeStep(text="LISTDS '"),
            TypeStep(input="dsname"),
            TypeStep(text=closing),
            KeyStep("enter"),
            ExpectStep(("tso-ready",)),
        ),
        inputs=(DSNAME_SPEC,),
    )


def name_session() -> ScriptedSession:
    """A session for ``name_flow``: the cleared screen, then READY after Enter."""
    return ScriptedSession([capture("tso-cleared"), capture("tso-ready")])


def typed_strings(session: ScriptedSession) -> list[str]:
    """The texts the session received through ``string``, in order."""
    return [c[1] for c in session.calls if c[0] == "string"]
