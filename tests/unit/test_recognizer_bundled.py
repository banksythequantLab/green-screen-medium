"""Unit tests for the bundled screen signatures (Requirements 8, 10.3)."""
from __future__ import annotations

import os
import re
from importlib import resources
from pathlib import Path

import pytest

from greenscreen.recognizer import bundled
from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import (
    CursorFieldMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    RegionRegexMatcher,
    TextAtMatcher,
)
from tests.screen_support import load_capture_screen

SIGNATURES_DIR = Path(__file__).parents[2] / "greenscreen" / "recognizer" / "signatures"

# Signature name -> capture it must recognize.
OWN_CAPTURES = {
    "tk5-logo": "tk5-logo",
    "tk5-logon": "tk5-logon",
    "tso-password-prompt": "tso-password-prompt",
    "ispf-primary-menu": "ispf-primary-menu",
    "tso-input-not-recognized": "tso-input-not-recognized",
    "tso-ready": "tso-ready",
    "tso-pause": "tso-pause-2",
    "tso-userid-in-use": "tso-userid-in-use",
    "tso-reconnect-password-prompt": "tso-reconnect-password-prompt",
    "tso-reconnect-ok": "tso-reconnect-ok",
    "tso-cleared": "tso-cleared",
    "tso-reenter": "tso-listds-reenter",
}

_DATE_TIME = re.compile(
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"|(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    r"|(?:0[1-9]|[12][0-9]|3[01])\.[0-9]{2}\.[0-9]{2}",
    re.ASCII,
)


@pytest.fixture(scope="module")
def sigs():
    return {s.name: s for s in load_bundled_signatures()}


def test_exactly_ten_signatures_bundled():
    loaded = load_bundled_signatures()
    assert len(loaded) == 12
    assert {s.name for s in loaded} == set(OWN_CAPTURES)
    assert len(list(SIGNATURES_DIR.glob("*.yaml"))) == 12


@pytest.mark.parametrize("name,capture", sorted(OWN_CAPTURES.items()))
def test_each_bundled_signature_recognizes_its_capture(name, capture):
    screen = load_capture_screen(capture)
    assert recognize(screen, load_bundled_signatures()) == name


def test_bundled_matchers_match_capture_cells(sigs):
    for name, capture in OWN_CAPTURES.items():
        sig = sigs[name]
        screen = load_capture_screen(capture)
        grid = screen.text_grid
        fields = screen.fields
        unprotected = [f for f in fields if not f.protected]

        for v in sig.volatile:
            value = grid[v.row][v.col : v.col + v.length]
            assert len(value) == v.length, name
            assert _DATE_TIME.fullmatch(value), (name, v)

        for m in sig.matchers:
            if isinstance(m, TextAtMatcher):
                got = grid[m.row][m.col : m.col + len(m.text)]
                assert got == m.text, (name, m.row, m.col)
            elif isinstance(m, FieldLayoutMatcher):
                assert m.count == len(unprotected), name
                assert list(m.positions) == [
                    (f.start_row, f.start_col) for f in unprotected
                ], name
            elif isinstance(m, CursorFieldMatcher):
                f = screen.find_field(screen.cursor_row, screen.cursor_col)
                assert f is not None, name
                assert not f.protected, name
                assert (f.start_row, f.start_col) == (m.row, m.col), name
                assert f.hidden is m.hidden, name
            elif isinstance(m, RegionRegexMatcher):
                region = grid[m.row][m.col : m.col + m.length]
                assert len(region) == m.length, (name, m.row, m.col)
                assert re.search(m.pattern, region), (name, m.row, m.col)
            elif isinstance(m, LastRowMatcher):
                non_blank = [r.rstrip(" ") for r in grid if r.strip(" ")]
                assert non_blank[-1] == m.text, name


def test_load_is_independent_of_working_directory(monkeypatch, tmp_path):
    expected = load_bundled_signatures()
    monkeypatch.chdir(tmp_path)
    assert load_bundled_signatures() == expected


NEW_SIGNATURES = ("tso-userid-in-use", "tso-reconnect-password-prompt", "tso-reconnect-ok")


def test_no_bundled_yaml_contains_user_id():
    files = list(SIGNATURES_DIR.glob("*.yaml"))
    assert files
    for path in files:
        assert "herc01" not in path.read_text(encoding="utf-8").lower(), path.name
    assert {p.stem for p in files} >= set(NEW_SIGNATURES)


def test_new_signature_files_hold_no_credentials_or_host():
    values = {
        name: os.environ.get(name, "") for name in ("TK5_USERNAME", "TK5_PASSWORD", "GS_HOST")
    }
    present = {n: v for n, v in values.items() if v}
    if not present:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(values))
    for stem in NEW_SIGNATURES:
        text = (SIGNATURES_DIR / f"{stem}.yaml").read_text(encoding="utf-8").lower()
        hits = [n for n, v in present.items() if v.lower() in text]
        assert not hits, f"{stem}.yaml contains the value of {hits}"


class _Node:
    """Traversable stand-in that replaces one file's behaviour."""

    def __init__(self, real, target, behaviour):
        self._real, self._target, self._behaviour = real, target, behaviour

    def joinpath(self, name):
        node = self._real.joinpath(name)
        if name == self._target:
            return _File(node, self._behaviour)
        return node


class _File:
    def __init__(self, real, behaviour):
        self._real, self._behaviour = real, behaviour

    def read_text(self, encoding="utf-8"):
        if callable(self._behaviour):
            return self._behaviour(self._real, encoding)
        return self._behaviour


def _patch_file(monkeypatch, filename, behaviour):
    real_root = resources.files("greenscreen.recognizer.signatures")
    node = _Node(real_root, filename, behaviour)
    monkeypatch.setattr(bundled.resources, "files", lambda _pkg: node)


def _raise(exc):
    def inner(_real, _enc):
        raise exc

    return inner


@pytest.mark.parametrize("name", sorted(OWN_CAPTURES))
def test_missing_bundled_file_raises_naming_file(monkeypatch, name):
    _patch_file(monkeypatch, f"{name}.yaml", _raise(FileNotFoundError()))
    with pytest.raises(SignatureError, match=re.escape(f"{name}.yaml")):
        load_bundled_signatures()


@pytest.mark.parametrize(
    "behaviour",
    [
        "version: 1\nname: [unclosed\n",
        "version: 2\nname: tso-ready\n",
        "",
        _raise(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")),
    ],
    ids=["malformed", "wrong-version", "empty", "bad-utf8"],
)
def test_invalid_bundled_file_raises_naming_file(monkeypatch, behaviour):
    # Earlier manifest entries loaded before the error;
    # no partial list may be returned.
    _patch_file(monkeypatch, "tso-pause.yaml", behaviour)
    with pytest.raises(SignatureError, match=re.escape("tso-pause.yaml")):
        load_bundled_signatures()


def test_name_differing_from_file_name_raises(monkeypatch):
    other = (SIGNATURES_DIR / "tso-ready.yaml").read_text(encoding="utf-8")
    _patch_file(monkeypatch, "tso-pause.yaml", other)
    with pytest.raises(SignatureError, match=re.escape("tso-pause.yaml")):
        load_bundled_signatures()


def test_loader_keeps_no_state_after_failure(monkeypatch):
    with monkeypatch.context() as mp:
        _patch_file(mp, "tso-ready.yaml", _raise(FileNotFoundError()))
        with pytest.raises(SignatureError):
            load_bundled_signatures()
    assert len(load_bundled_signatures()) == 12
