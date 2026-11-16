"""Unit tests for recognizer YAML loading and emission (Requirement 4)."""

from __future__ import annotations

import pytest
import yaml

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.yamlio import load_signatures
from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    ScreenSignature,
    TextAtMatcher,
)


def _doc(name: str = "a", extra: str = "", version: str = "1") -> str:
    return (
        f"version: {version}\nname: {name}\n"
        "matchers:\n- kind: last_row\n  text: ' READY'\n" + extra
    )


def _list_doc(*names: str) -> str:
    out = []
    for n in names:
        out.append(f"- version: 1\n  name: {n}\n  matchers:\n  - kind: last_row\n    text: X\n")
    return "".join(out)


def _write(tmp_path, text: str, name: str = "sigs.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- load_signatures


def test_load_single_mapping_returns_list_of_one(tmp_path):
    sigs = load_signatures(_write(tmp_path, _doc("one")))
    assert [s.name for s in sigs] == ["one"]


def test_load_list_preserves_file_order(tmp_path):
    sigs = load_signatures(_write(tmp_path, _list_doc("c", "a", "b")))
    assert [s.name for s in sigs] == ["c", "a", "b"]


def test_load_empty_list_returns_empty_list(tmp_path):
    assert load_signatures(_write(tmp_path, "[]\n")) == []


def test_load_accepts_str_path(tmp_path):
    p = _write(tmp_path, _doc("one"))
    assert load_signatures(str(p))[0].name == "one"


def test_load_missing_file(tmp_path):
    with pytest.raises(SignatureError, match="could not be read"):
        load_signatures(tmp_path / "nope.yaml")


def test_load_unreadable_file_directory(tmp_path):
    with pytest.raises(SignatureError, match="could not be read"):
        load_signatures(tmp_path)


def test_load_invalid_utf8(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_bytes(b"version: 1\nname: \xff\xfe\n")
    with pytest.raises(SignatureError, match="could not be read"):
        load_signatures(p)


@pytest.mark.parametrize("text", ["", "null\n", "42\n", "just text\n"])
def test_load_non_mapping_non_list_document(tmp_path, text):
    with pytest.raises(SignatureError, match="document structure is invalid"):
        load_signatures(_write(tmp_path, text))


# ---------------------------------------------------------------------- version


def test_version_2_rejected(tmp_path):
    with pytest.raises(SignatureError, match=r"unsupported version 2 \(type int\)"):
        load_signatures(_write(tmp_path, _doc(version="2")))


def test_version_string_one_rejected(tmp_path):
    with pytest.raises(SignatureError, match=r"unsupported version '1' \(type str\)"):
        load_signatures(_write(tmp_path, _doc(version="'1'")))


def test_version_true_rejected(tmp_path):
    with pytest.raises(SignatureError, match=r"unsupported version True \(type bool\)"):
        ScreenSignature.from_yaml(_doc(version="true"))


def test_version_missing(tmp_path):
    with pytest.raises(SignatureError, match="missing key 'version'"):
        ScreenSignature.from_yaml("name: a\nmatchers:\n- kind: last_row\n  text: X\n")


def test_long_version_is_truncated():
    with pytest.raises(SignatureError) as ei:
        ScreenSignature.from_yaml(_doc(version="'" + "v" * 200 + "'"))
    assert "v" * 40 not in str(ei.value)


# ------------------------------------------------------------- structure errors


def test_malformed_yaml_reports_line_and_column_without_text(tmp_path):
    with pytest.raises(SignatureError, match=r"malformed YAML at line \d+, column \d+") as ei:
        load_signatures(_write(tmp_path, "name: [unclosed SECRETWORD\n"))
    assert "SECRETWORD" not in str(ei.value)


def test_unknown_key_names_key_and_index(tmp_path):
    text = _list_doc("a") + "- version: 1\n  name: b\n  bogus: 1\n  matchers: []\n"
    with pytest.raises(SignatureError) as ei:
        load_signatures(_write(tmp_path, text))
    msg = str(ei.value)
    assert "signature[1]" in msg and "unknown key 'bogus'" in msg


def test_unknown_key_single_document_has_no_index():
    with pytest.raises(SignatureError) as ei:
        ScreenSignature.from_yaml(_doc(extra="bogus: 1\n"))
    assert "unknown key 'bogus'" in str(ei.value)
    assert "signature[" not in str(ei.value)


def test_missing_key_names_key_and_index(tmp_path):
    text = _list_doc("a") + "- version: 1\n  name: b\n"
    with pytest.raises(SignatureError) as ei:
        load_signatures(_write(tmp_path, text))
    msg = str(ei.value)
    assert "signature[1]" in msg and "missing key 'matchers'" in msg


def test_missing_matcher_key_names_key_and_indexes(tmp_path):
    text = (
        "- version: 1\n  name: a\n  matchers:\n  - kind: last_row\n    text: X\n"
        "  - kind: text_at\n    row: 0\n    text: Y\n"
    )
    with pytest.raises(SignatureError) as ei:
        load_signatures(_write(tmp_path, text))
    msg = str(ei.value)
    assert "signature[0]" in msg and "matchers[1] (text_at)" in msg
    assert "missing key 'col'" in msg


def test_wrong_type_names_key_and_index(tmp_path):
    text = _list_doc("a") + (
        "- version: 1\n  name: b\n  matchers:\n"
        "  - kind: text_at\n    row: '0'\n    col: 0\n    text: Y\n"
    )
    with pytest.raises(SignatureError) as ei:
        load_signatures(_write(tmp_path, text))
    msg = str(ei.value)
    assert "signature[1]" in msg and "key 'row' must be an integer" in msg
    assert "'0'" not in msg.replace("key 'row'", "")


def test_bool_is_not_an_integer():
    text = "version: 1\nname: a\nmatchers:\n- kind: text_at\n  row: true\n  col: 0\n  text: Y\n"
    with pytest.raises(SignatureError, match="key 'row' must be an integer"):
        ScreenSignature.from_yaml(text)


def test_unknown_kind_does_not_echo_value():
    text = "version: 1\nname: a\nmatchers:\n- kind: SECRETKIND\n"
    with pytest.raises(SignatureError) as ei:
        ScreenSignature.from_yaml(text)
    assert "SECRETKIND" not in str(ei.value)
    assert "matchers[0]" in str(ei.value)


def test_from_yaml_rejects_list():
    with pytest.raises(SignatureError, match="document structure is invalid"):
        ScreenSignature.from_yaml(_list_doc("a"))


def test_no_partial_result_on_later_item_error(tmp_path):
    text = _list_doc("a") + "- 5\n"
    with pytest.raises(SignatureError, match=r"signature\[1\]"):
        load_signatures(_write(tmp_path, text))


# -------------------------------------------------------------------- duplicates


def test_duplicate_names_report_both_indexes(tmp_path):
    with pytest.raises(SignatureError) as ei:
        load_signatures(_write(tmp_path, _list_doc("a", "b", "a")))
    msg = str(ei.value)
    assert "'a'" in msg and "indexes 0 and 2" in msg


# ------------------------------------------------------------ field_layout count


def test_field_layout_count_mismatch_from_yaml():
    text = (
        "version: 1\nname: a\nmatchers:\n- kind: field_layout\n  count: 2\n"
        "  positions:\n  - row: 1\n    col: 1\n"
    )
    with pytest.raises(SignatureError) as ei:
        ScreenSignature.from_yaml(text)
    msg = str(ei.value)
    assert "matchers[0] (field_layout)" in msg and "'count'" in msg


# ----------------------------------------------------------- representation/emit


def _emitted_matchers(sig: ScreenSignature) -> list[dict]:
    return yaml.safe_load(sig.to_yaml())["matchers"]


def test_last_row_and_before_cursor_representation():
    sig = ScreenSignature(
        name="p",
        matchers=(LastRowMatcher(" ***"), BeforeCursorMatcher(" ***")),
    )
    assert _emitted_matchers(sig) == [
        {"kind": "last_row", "text": " ***"},
        {"kind": "before_cursor", "text": " ***"},
    ]
    assert ScreenSignature.from_yaml(sig.to_yaml()) == sig


def test_field_layout_representation():
    sig = ScreenSignature(
        name="f",
        matchers=(FieldLayoutMatcher(count=2, positions=((1, 13), (5, 0))),),
    )
    assert _emitted_matchers(sig) == [
        {
            "kind": "field_layout",
            "count": 2,
            "positions": [{"row": 1, "col": 13}, {"row": 5, "col": 0}],
        }
    ]
    assert ScreenSignature.from_yaml(sig.to_yaml()) == sig


def test_empty_field_layout_representation():
    sig = ScreenSignature(name="f", matchers=(FieldLayoutMatcher(0, ()),))
    assert ScreenSignature.from_yaml(sig.to_yaml()) == sig


def test_to_yaml_starts_with_version_1():
    sig = ScreenSignature(name="a", matchers=(TextAtMatcher(0, 0, "HI"),))
    assert sig.to_yaml().startswith("version: 1\n")


def test_to_yaml_is_deterministic_for_equal_signatures():
    a = ScreenSignature(name="a", matchers=(TextAtMatcher(0, 0, "HI"),), description="d")
    b = ScreenSignature(name="a", matchers=[TextAtMatcher(0, 0, "HI")], description="d")
    assert a == b
    assert a.to_yaml() == b.to_yaml() == a.to_yaml()


def test_to_yaml_key_order_is_fixed():
    sig = ScreenSignature(name="a", matchers=(TextAtMatcher(0, 0, "HI"),))
    assert list(yaml.safe_load(sig.to_yaml())) == [
        "version",
        "name",
        "description",
        "matchers",
        "volatile",
    ]
