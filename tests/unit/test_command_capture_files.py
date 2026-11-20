"""The 18 promoted command captures (36 files): hashes, forms, secrecy.

Needs no live host. A failure message names a file and a fact, never screen
content. The password scan reads TK5_PASSWORD only to compute booleans; the
value is never printed, stored or put into a message.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from tests.connector_support import forms_of_run, hidden_runs
from tests.screen_support import load_capture_screen

_CAPTURES_DIR = Path(__file__).parents[2] / "captures"

SHA256: dict[str, str] = {
    "tso-cleared.ascii.txt": "1432df6c4713e473f437387f9ac43384f2d3bfb98e39e98ef11c83aa1472bffc",
    "tso-cleared.readbuffer.txt": "cfb52107c1b6ea64ee0142ba74edaa86d4073f487b13420ef2b3af21359d3412",
    "tso-listcat-level-page2.ascii.txt": "a43b87b6205b3040b3fbbf5a2285d7e1689a57efb96df94391d3a88f78f647a3",
    "tso-listcat-level-page2.readbuffer.txt": "051bf764fc1d8ea249c0e9775e1fb6a18244693174901be510843b526a4092b3",
    "tso-listcat-level-page3.ascii.txt": "52751e0efe085b5c976da069b7724b8477689e85dfa2e863e2d87e544c96ceeb",
    "tso-listcat-level-page3.readbuffer.txt": "a3c6b7e84299156d35eaa188b9241baa64b0a43275b238c05cbcb9adf744699d",
    "tso-listcat-level.ascii.txt": "9f274d737e97cd286d096dcba5682b15c0cd186c370d88167b0b2f1a2533ed42",
    "tso-listcat-level.readbuffer.txt": "826f6b5df8b64a2a55b8f3c6abefc828fdb7c96d7c4e3aa41fad6f2236a01e6a",
    "tso-listcat-output.ascii.txt": "6668faadbd7f807e3546d794d4789f72a582ee24af652a029e15947a3969b944",
    "tso-listcat-output.readbuffer.txt": "9a17e10d7e14d0a89dd9e3ce47143a45d1a782040c4fa60a1668345810f30b7b",
    "tso-listds-members-page2.ascii.txt": "918891c570434137779a5387e93cf071bac75c645e2aeb131f9af1c6427258be",
    "tso-listds-members-page2.readbuffer.txt": "934d691455335653dfd5f6f2157d6df9d3acacbf4b0a145b8e54c322ae04c2c0",
    "tso-listds-members-page3.ascii.txt": "fb21f523166375280816ec5f0a7144cc81c3add68f4fba0d83c6297b4de12501",
    "tso-listds-members-page3.readbuffer.txt": "c87e9071695abfe8d0a5a529850a3559562427210f22b5e90489e9a07051afeb",
    "tso-listds-members-page4.ascii.txt": "310dfa9bcbb02ff34f6d64bc1a8d93cd3510a5767998fcc871d6602ed568981f",
    "tso-listds-members-page4.readbuffer.txt": "ca5971ee0f4fbbb68fc53457069885ae7f6fb8111477b6c7974b7152061a63be",
    "tso-listds-members-page5.ascii.txt": "4f76d58620c78b2db4676828beee40bac5a1cad2b83a1df4e9ad7f21cb0eae00",
    "tso-listds-members-page5.readbuffer.txt": "ee1ce60e93c362779c3139ca4c163211373c3a069e2e52417bd6d790164b19a2",
    "tso-listds-members-page6.ascii.txt": "3691fca5832ec211e7b945f3e727f246a3e9730d03aaf02929a3e8fa7a6f02d5",
    "tso-listds-members-page6.readbuffer.txt": "cddf94ef67f5e266b5423e87894e4ce9a18d41cd37255090ce185e8bb0daf46a",
    "tso-listds-members-page7.ascii.txt": "660d6a5777a1d139288c67eccef5cf0040120dbeebb8e88f915c51b94240143a",
    "tso-listds-members-page7.readbuffer.txt": "1d18ad7a7a19687e7942c7d162f9ae4efbca0778901d885028a63001c3120191",
    "tso-listds-members.ascii.txt": "f3292e57c9229f9b85b04ba7cf4cee457c1a3017f9e20dd2c59d87dc54117baa",
    "tso-listds-members.readbuffer.txt": "ec269c35c2abc07d4b57b564ca73677c431d7259d221e41dc49f567e51fe14b8",
    "tso-listds-not-in-catalog.ascii.txt": "658856ff06f5881790592c4024d2a1f048fef22b70cedbe0e57c4dd2bfde74d2",
    "tso-listds-not-in-catalog.readbuffer.txt": "22520f3dde77bae04cdc62d2e9956e9f4f14cba3456ca336dbf89059d3e28c32",
    "tso-listds-output.ascii.txt": "29cd27597a3f9a30f083309d7a435402fa4e265b33e53a034743095e64970207",
    "tso-listds-output.readbuffer.txt": "de56ff7b94591056b87cbf218c35f267b6b31a76fc13fece3317b661d9de228b",
    "tso-listds-reenter-after-pa1.ascii.txt": "dc79a5b00183b8824f3826f03bc3955278d4e671864683345ce4b9107793a37f",
    "tso-listds-reenter-after-pa1.readbuffer.txt": "0d88ed4d96bc7c1a50e533bec4326ca7101fdd1470113444fa812cb66a91dc7f",
    "tso-listds-reenter.ascii.txt": "b4e653ff84882ec2044043e9a781819d8c5dd542bb54d44ec8d48326c84eda31",
    "tso-listds-reenter.readbuffer.txt": "61cddc0eefd13317bd2c5f3cd2b6191e3fac8f29ec09bfe0eef31729845f200e",
    "tso-status-output.ascii.txt": "70fe29e8d5e04716f975eb795264a2c29d82c1af992ad3f18dc9455964eb86cb",
    "tso-status-output.readbuffer.txt": "68629e1e27226476345a3c1a384050b0e169b2f17325d6615ce7a50c313d0ebe",
    "tso-time-output.ascii.txt": "6d61df9c056ca1ba17fe27c116c8bf98a38640f02275bef65132412ca5452449",
    "tso-time-output.readbuffer.txt": "60b1d1bcd78894efd52ca9a719e9cf207786c04ec55f7fae15ff68a9ccae32e1",
}

_STEMS = sorted({name.split(".")[0] for name in SHA256})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ascii_rows(stem: str) -> list[str]:
    """Rows of the last Ascii() block in ``<stem>.ascii.txt`` (no prefix)."""
    rows: list[str] = []
    block: list[str] = []
    path = _CAPTURES_DIR / f"{stem}.ascii.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("data: "):
            block.append(line[len("data: "):])
        elif line == "ok" and block:
            rows, block = block, []
    return rows


def test_there_are_36_hashes_for_18_captures():
    assert len(SHA256) == 36
    assert len(_STEMS) == 18
    assert all(
        f"{stem}{suffix}" in SHA256
        for stem in _STEMS
        for suffix in (".ascii.txt", ".readbuffer.txt")
    )


@pytest.mark.parametrize("file_name", sorted(SHA256))
def test_file_is_present_with_the_recorded_sha256(file_name):
    path = _CAPTURES_DIR / file_name
    assert path.is_file(), f"{file_name} is missing"
    assert _sha256(path) == SHA256[file_name], f"{file_name} has another SHA-256"


@pytest.mark.parametrize("stem", _STEMS)
def test_readbuffer_is_24_by_80(stem):
    screen = load_capture_screen(stem)
    assert (screen.rows, screen.columns) == (24, 80), f"{stem} is not 24 by 80"
    assert len(screen.cell_grid) == 24
    assert all(len(row) == 80 for row in screen.cell_grid), f"{stem} has a short row"


@pytest.mark.parametrize("stem", _STEMS)
def test_ascii_rows_equal_text_grid_of_the_readbuffer_form(stem):
    rows = _ascii_rows(stem)
    grid = load_capture_screen(stem).text_grid
    assert len(rows) == 24, f"{stem}.ascii.txt does not hold 24 rows"
    mismatched = [r for r, (a, b) in enumerate(zip(rows, grid)) if a != b]
    assert mismatched == [], f"{stem}: Ascii() and ReadBuffer forms differ in {len(mismatched)} row(s)"


@pytest.mark.parametrize("stem", _STEMS)
def test_no_hidden_field_holds_a_non_blank_cell(stem):
    screen = load_capture_screen(stem)
    non_blank = [
        value
        for whole, _ in hidden_runs(screen)
        for value in whole
        if value not in (0, 0x40, 0x20)
    ]
    assert non_blank == [], f"{stem} holds a non-blank hidden cell"
    assert not any(f.hidden for f in screen.fields), f"{stem} has a hidden field"


def test_no_capture_file_holds_the_password_in_any_form():
    password = os.environ.get("TK5_PASSWORD", "")
    if not password:
        pytest.skip("TK5_PASSWORD is unset or empty, so the password scan cannot run")
    forms = forms_of_run(list(password.encode("utf-8")))
    forms |= {f.lower() for f in forms} | {f.upper() for f in forms}
    offenders = []
    for path in sorted(_CAPTURES_DIR.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(form in text for form in forms):
            offenders.append(path.name)
    assert offenders == [], f"capture file(s) contain the password: {offenders}"
