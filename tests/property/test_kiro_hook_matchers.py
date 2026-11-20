# Feature: polish, Property 10: Hook matchers accept exactly their paths
"""Property 10 of spec polish (task 10.3). Requirements 3.2, 4.2, 5.2.

The matchers are read from the real files under .kiro/hooks. No live host.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

_HOOKS = Path(__file__).resolve().parents[2] / ".kiro" / "hooks"


def _matchers(file_name: str) -> list[str]:
    data = json.loads((_HOOKS / file_name).read_text(encoding="utf-8"))
    return [h["matcher"] for h in data["hooks"]]


_FLOW = _matchers("flow-yaml-check.json")
_CAPTURES = _matchers("captures-check.json")
_FLOW_DIR = ("greenscreen", "flow", "flows")
_OTHER_DIRS = [
    ("greenscreen", "flow"),
    ("greenscreen", "flow", "flows", "sub"),
    ("greenscreen", "flows"),
    ("flow", "flows"),
    ("flows",),
    ("captures", "sub"),
    ("capture",),
    ("captures2",),
    ("xcaptures",),
    ("greenscreen", "flow", "flowz"),
    ("tests", "fixtures"),
    (),
]
_PREFIXES = st.sampled_from(
    ["", "a/", "tests/unit/", "..\\", ".\\", "C:\\", "C:/", "D:\\work\\repo\\", "/", "/home/u/repo/", "src/x/"]
)
_NAMES = st.text(alphabet="abcXYZ019-_.", min_size=1, max_size=20)
_YAML = st.text(alphabet="abcXYZ019-_.", min_size=0, max_size=12).map(lambda s: s + ".yaml")


def _path(prefix: str, parts: tuple[str, ...], name: str, sep: str) -> str:
    p = prefix.replace("\\", sep).replace("/", sep)
    return p + "".join(part + sep for part in parts) + name


def _agree(matcher: str, path: str) -> bool:
    s = re.search(matcher, path) is not None
    f = re.fullmatch(matcher, path) is not None
    assert s == f, (matcher, path)
    return s


@settings(max_examples=100, deadline=None)
@given(
    prefix=_PREFIXES,
    sep=st.sampled_from(["/", "\\"]),
    name=st.one_of(_NAMES, _YAML),
    other=st.sampled_from(_OTHER_DIRS),
)
def test_hook_matchers_accept_exactly_their_paths(prefix, sep, name, other):
    want_flow = name.endswith(".yaml") and name != ".yaml"
    for m in _FLOW:
        assert _agree(m, _path(prefix, _FLOW_DIR, name, sep)) is want_flow
        assert _agree(m, _path(prefix, other, name, sep)) is False
    for m in _CAPTURES:
        assert _agree(m, _path(prefix, ("captures",), name, sep)) is True
        assert _agree(m, _path(prefix, other, name, sep)) is False


def test_hook_files_hold_the_expected_matcher_counts():
    assert len(_FLOW) == 1
    assert len(_CAPTURES) == 2
