"""Property 7: The fragment reader matches its model (spec polish, task 9.2).

**Validates: Requirements 12.2, 12.3, 12.4, 12.5, 12.9**

``takeKeyFromFragment`` runs under Node over stub ``window`` objects. The oracle is a Python
model: after ``#key=`` valid percent escapes decode as UTF-8, otherwise the text stays raw.
A failure names the case index and the rule only, never the key text.
"""
from __future__ import annotations

import re
from urllib.parse import unquote_to_bytes

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.console_node_extract import needs_node, run_fragment

pytestmark = needs_node

PREFIXES = ["", "#", "#key=", "#KEY=", "#key", "#key=#key=", "#other="]

LETTERS = st.text("abcXYZ019-_.", min_size=1, max_size=8)
VALID_ESCAPE = st.sampled_from(["%41", "%42", "%20", "%C3%A9", "%E2%82%AC", "%F0%9F%98%80", "%2f", "%25"])
INVALID_ESCAPE = st.sampled_from(["%E0%A4%A", "%FF", "%C3", "%80", "%ZZ", "%4", "%E0%A4"])
NON_ASCII = st.text(
    st.characters(min_codepoint=0xA0, blacklist_categories=("Cs",)), min_size=1, max_size=4
)
PIECE = st.one_of(LETTERS, VALID_ESCAPE, INVALID_ESCAPE, st.just("%"), NON_ASCII)

PATHS = st.text("/abc-_.", min_size=0, max_size=10)
SEARCHES = st.one_of(st.just(""), st.text("?&=abc19", min_size=1, max_size=10))


@st.composite
def cases(draw):
    return {
        "hash": draw(st.sampled_from(PREFIXES)) + "".join(draw(st.lists(PIECE, max_size=5))),
        "pathname": draw(PATHS),
        "search": draw(SEARCHES),
    }


def model_text(raw: str) -> str:
    """decodeURIComponent: strict UTF-8 over the percent escapes, or the raw text."""
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        return raw
    try:
        return unquote_to_bytes(raw.encode("utf-8")).decode("utf-8")
    except UnicodeDecodeError:
        return raw


def check(ok: bool, index: int, rule: str) -> None:
    if not ok:
        pytest.fail(f"case {index}: rule broken: {rule}")


@given(st.lists(cases(), min_size=1, max_size=25))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
def test_fragment_reader_matches_its_model(batch):
    results = run_fragment(batch)
    for index, (case, result) in enumerate(zip(batch, results)):
        check("threw" not in result, index, "the reader does not throw")
        has_prefix = case["hash"].startswith("#key=")
        text = model_text(case["hash"][len("#key="):]) if has_prefix else ""
        taken = has_prefix and text != ""
        check(result["taken"] is taken, index, "taken is true only for a non-empty key after #key=")
        check(result["keyHeld"] is taken, index, "the key is held exactly when it is taken")
        check(result["apiKey"] == (text if taken else None), index, "the key is the decoded text or raw text")
        expected = [[None, "", case["pathname"] + case["search"]]] if has_prefix else []
        check(result["calls"] == expected, index, "one replaceState with the address, only after #key=")
        if taken:
            check(
                not any(text in str(arg) for call in result["calls"] for arg in call if arg is not None)
                or text in case["pathname"] + case["search"],
                index,
                "no replaceState argument contains the key",
            )
