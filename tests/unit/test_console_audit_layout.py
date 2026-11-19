"""Audit list layout numbers in console.css (task 6.2 and 6.3, no browser).

These pin the figures of the design's "Audit line width"; whether the lines fit is
manual checklist step 16.

Requirements: 7.12
"""

from __future__ import annotations

import re
from importlib import resources

CSS = (
    resources.files("greenscreen.publisher.console")
    .joinpath("console.css")
    .read_text(encoding="utf-8")
)


def _block(selector: str) -> str:
    """Body of the top-level rule whose selector is exactly `selector`."""
    top = re.sub(r"@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", CSS)
    found = re.findall(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", top)
    assert len(found) == 1, f"console.css: expected one '{selector}' rule, found {len(found)}"
    return found[0]


def _rem(block: str, prop: str) -> float:
    m = re.search(r"(?<![\w-])" + re.escape(prop) + r"\s*:\s*([^;]+);", block)
    assert m, f"console.css: '{prop}' is missing"
    value = m.group(1).strip()
    n = re.fullmatch(r"(\d+(?:\.\d+)?)rem", value)
    assert n, f"console.css: '{prop}' is not written in rem"
    return float(n.group(1))


def test_audit_column_width_is_22_to_28_rem():
    assert 22 <= _rem(_block(".audit"), "column-width") <= 28


def test_audit_column_gap_is_at_most_1_5_rem():
    assert _rem(_block(".audit"), "column-gap") <= 1.5


def test_audit_has_no_list_marker():
    assert re.search(r"list-style\s*:\s*none\s*;", _block(".audit"))


def test_audit_item_left_padding_is_at_most_1_25_rem():
    body = _block(".audit > li")
    m = re.search(r"(?<![\w-])padding\s*:\s*([^;]+);", body)
    if m:
        parts = m.group(1).split()
        left = {1: parts[0], 2: parts[1], 3: parts[1], 4: parts[3]}[len(parts)]
    else:
        m = re.search(r"padding-left\s*:\s*([^;]+);", body)
        assert m, "console.css: '.audit > li' has no left padding"
        left = m.group(1).strip()
    n = re.fullmatch(r"(\d+(?:\.\d+)?)(rem)?", left)
    assert n and (n.group(2) or float(n.group(1)) == 0), "left padding is not in rem"
    assert float(n.group(1)) <= 1.25
