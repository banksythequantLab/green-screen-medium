"""Property 11: The check command agrees with the Flow reader.

**Property 11: The check command agrees with the Flow reader**
**Validates: Requirements 6.2, 6.3, 6.6, 6.8, 6.10, 6.11**

For file contents drawn from valid Flows, mutated Flows, arbitrary YAML, malformed
YAML and arbitrary bytes, ``main([path])`` exits 0 exactly when ``Flow.from_yaml``
accepts the text, 4 when the bytes are not UTF-8, do not parse as YAML or are not a
mapping, and 1 otherwise. Every printed line is printable ASCII of at most 200
characters and none contains the generated free text.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import tempfile
from pathlib import Path

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.flow.check import main
from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.model import Flow
from greenscreen.recognizer import load_bundled_signatures

_SIGNATURES = list(load_bundled_signatures())
_BASE: Flow = load_bundled_flows(_SIGNATURES)["tk5-time"]

# Free text uses characters that no fixed message line contains, so a hit in the
# output means the text leaked.
_TEXT = st.text(alphabet="~^!%&*|", min_size=4, max_size=60)

_MUTATIONS = (
    ("tso-ready", "zz-no-such-signature"),
    ("step: 10.0", "step: 99999.0"),
    ("step: 10.0", "step: -3"),
    ("max_count: 1\n", "max_count: 0\n"),
    ("version: 1\n", ""),
    ("name: tk5-time\n", ""),
    ("steps:\n", "stepz:\n"),
    ("outputs:\n", "outputz:\n"),
)


@st.composite
def _flow_texts(draw: st.DrawFn) -> tuple[str, str, str]:
    description = draw(_TEXT)
    example = draw(_TEXT)
    flow = dataclasses.replace(_BASE, description=description, example=example)
    text = flow.to_yaml()
    mutation = draw(st.integers(min_value=-1, max_value=len(_MUTATIONS) - 1))
    if mutation >= 0:
        old, new = _MUTATIONS[mutation]
        text = text.replace(old, new, 1)
    return text, description, example


_YAML_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10**6, max_value=10**6),
    st.text(alphabet="abc xyz", max_size=8),
)
_YAML_VALUES = st.recursive(
    _YAML_SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.dictionaries(st.text(alphabet="abcxyz", min_size=1, max_size=5), inner, max_size=3),
    ),
    max_leaves=8,
)
_ARBITRARY_YAML = _YAML_VALUES.map(lambda v: yaml.safe_dump(v).encode("utf-8"))
_MALFORMED = st.text(alphabet="[]{}:,-'\"#&*!|>%@` \nab", max_size=40).map(
    lambda s: s.encode("utf-8")
)

_CONTENT = st.one_of(
    _flow_texts().map(lambda t: (t[0].encode("utf-8"), (t[1], t[2]))),
    _ARBITRARY_YAML.map(lambda b: (b, ())),
    _MALFORMED.map(lambda b: (b, ())),
    st.binary(max_size=64).map(lambda b: (b, ())),
)


def _oracle(data: bytes) -> int:
    try:
        text = data.decode("utf-8")
        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - any parse failure is exit 4
        return 4
    if not isinstance(doc, dict):
        return 4
    try:
        Flow.from_yaml(text, _SIGNATURES)
    except FlowDefinitionError:
        return 1
    return 0


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(case=_CONTENT)
def test_check_agrees_with_flow_reader(case: tuple[bytes, tuple[str, ...]]) -> None:
    data, free_texts = case
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "flow.yaml"
        path.write_bytes(data)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(path)])
        assert path.read_bytes() == data

    assert code == _oracle(data)

    lines = (out.getvalue() + err.getvalue()).splitlines()
    for line in lines:
        assert len(line) <= 200
        assert all(" " <= c <= "~" for c in line)
        for text in free_texts:
            assert text not in line
