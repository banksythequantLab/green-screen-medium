"""Unit tests for greenscreen.publisher.vault (task 1.2)."""

from __future__ import annotations

import copy
import pickle

import pytest

from greenscreen.publisher.vault import BoundValues, SecretBox

PROBE = "zq7-PROBE-value"
PROBE_INT = 987654321


def _box() -> tuple[SecretBox, dict[str, object]]:
    items: dict[str, object] = {"password": PROBE, "count": PROBE_INT}
    return SecretBox.adopt(items), items


def test_adopt_takes_ownership_and_clear_empties_it() -> None:
    box, items = _box()
    assert box.mapping() is items
    box.clear()
    assert items == {}
    assert box.mapping() == {}


def test_merged_is_fresh_and_cleared_too() -> None:
    box, items = _box()
    merged = box.merged({"userid": "bound-USER", "password": "bound-wins"})
    assert merged is not items
    assert merged["userid"] == "bound-USER" and merged["count"] == PROBE_INT
    assert merged["password"] == "bound-wins"
    assert set(items) == {"password", "count"}  # supplied dict untouched by merge
    box.clear()
    assert merged == {} and items == {}


def test_merged_twice_empties_the_first_result() -> None:
    box, _ = _box()
    first = box.merged({"a": "x"})
    second = box.merged({"b": "y"})
    assert first == {}  # a new merge empties the previous merged dict
    assert second is not first
    assert second["b"] == "y"
    box.clear()
    assert second == {}


def test_box_repr_and_str_show_names_only() -> None:
    box, _ = _box()
    box.merged({"userid": "bound-USER"})
    for text in (repr(box), str(box), f"{box}", "%s" % (box,)):
        assert PROBE not in text and str(PROBE_INT) not in text and "bound-USER" not in text
        assert "password" in text and "count" in text


def test_box_is_not_iterable_or_hashable_or_picklable() -> None:
    box, _ = _box()
    with pytest.raises(TypeError):
        iter(box)
    with pytest.raises(TypeError):
        list(box)
    with pytest.raises(TypeError):
        _ = "password" in box
    with pytest.raises(TypeError):
        hash(box)
    with pytest.raises(TypeError):
        pickle.dumps(box)
    with pytest.raises(TypeError):
        copy.copy(box)


def test_bound_values_for_flow_and_names() -> None:
    store = BoundValues({"flow-a": {"userid": "bound-USER", "n": 42}, "flow-b": {}})
    assert dict(store.for_flow("flow-a")) == {"userid": "bound-USER", "n": 42}
    assert store.names_for("flow-a") == frozenset({"userid", "n"})
    assert dict(store.for_flow("flow-b")) == {}
    assert store.names_for("missing") == frozenset()
    assert len(store.for_flow("missing")) == 0
    assert repr(store) == "BoundValues(flows=1)"


def test_bound_values_copies_its_input_and_view_is_read_only() -> None:
    src = {"userid": "bound-USER"}
    store = BoundValues({"f": src})
    src.clear()
    view = store.for_flow("f")
    assert view["userid"] == "bound-USER"
    with pytest.raises(TypeError):
        view["userid"] = "x"  # type: ignore[index]


def test_bound_values_show_no_value_anywhere() -> None:
    store = BoundValues({"f": {"userid": "bound-USER", "n": 424242}})
    view = store.for_flow("f")
    for text in (repr(store), str(store), repr(view), str(view), f"{store}", f"{view}"):
        assert "bound-USER" not in text and "424242" not in text
    with pytest.raises(TypeError):
        list(store)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        hash(store)
    with pytest.raises(TypeError):
        pickle.dumps(store)
    with pytest.raises(TypeError):
        pickle.dumps(view)
