"""Static checks of the seance art (console spec, task 7.3, Requirement 11.10 to 11.18).

Reads index.html and console.css from the installed package. No browser, no
network. The CSS helpers come from tests.unit.test_console_css, unedited.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from importlib import resources

import pytest

from tests.unit.test_console_css import (
    _block_at,
    _colour_problems,
    _contrast,
    _declarations,
    _read_css,
    _reduce_block,
    _seconds,
    _split_root,
    _strip_comments,
    _tokens,
)

LABEL = "A crystal ball on a seance table"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
FOCUS_TAGS = {"a", "button", "input", "select", "textarea"}
SPAN_CLASSES = {"seance-ball", "seance-dim"}
ALLOWED_VARS = {"--fg-dim", "--fg-bright", "--ui-glow"}


def _read_html() -> str:
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )


class _Art(HTMLParser):
    """Collects what the seance checks need from index.html."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, dict[str, str | None], list[tuple[str, str | None]]]] = []
        self.wrappers: list[tuple[dict, bool]] = []  # (attrs, inside main.stage)
        self.pres: list[tuple[list, bool]] = []  # (raw attrs list, parent is wrapper)
        self.spans: list[tuple[list, bool, int]] = []  # (attrs list, nested, line)
        self.stray: list[tuple[str, int]] = []  # text outside spans in the pre
        self.other_tags: list[tuple[str, int]] = []  # non-span tags in the pre
        self.focusable: list[tuple[str, int]] = []
        self.in_wrapper = 0
        self.in_pre = 0
        self.span_depth = 0
        self.pre_text: list[str] = []

    def _names(self) -> list[str]:
        return [t for t, _, _ in self.stack]

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        a = dict(attrs)
        if self.in_wrapper:
            if tag in FOCUS_TAGS or "tabindex" in a or "style" in a:
                self.focusable.append((tag, line))
        if tag == "div" and a.get("class") == "seance-art-wrap" and a.get("role") == "img":
            inside_stage = any(
                t == "main" and (at.get("class") or "").split() == ["stage"]
                for t, at, _ in self.stack
            )
            self.wrappers.append((a, inside_stage))
            self.in_wrapper += 1
        elif tag == "div" and self.in_wrapper:
            self.in_wrapper += 1
        if self.in_pre:
            if tag == "span":
                self.spans.append((attrs, self.span_depth > 0, line))
                self.span_depth += 1
            else:
                self.other_tags.append((tag, line))
        elif tag == "pre" and (a.get("class") or "").split() == ["seance-art"]:
            parent_is_wrapper = bool(self.stack) and self.stack[-1][0] == "div" and self.in_wrapper == 1
            self.pres.append((attrs, parent_is_wrapper))
            self.in_pre = 1
        if tag not in VOID:
            self.stack.append((tag, a, attrs))

    def handle_endtag(self, tag):
        if self.in_pre and tag == "span":
            self.span_depth -= 1
        elif self.in_pre and tag == "pre":
            self.in_pre = 0
        elif tag == "div" and self.in_wrapper:
            self.in_wrapper -= 1
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.in_pre:
            self.pre_text.append(data)
            if self.span_depth == 0 and data.strip(" \n"):
                self.stray.append((data.strip(" \n")[:20], self.getpos()[0]))

    def handle_entityref(self, name):
        if self.in_pre:
            self.pre_text.append("&" + name + ";")
            if self.span_depth == 0:
                self.stray.append(("&" + name + ";", self.getpos()[0]))

    def handle_charref(self, name):
        if self.in_pre:
            self.pre_text.append("&#" + name + ";")


@pytest.fixture(scope="module")
def html() -> str:
    return _read_html()


@pytest.fixture(scope="module")
def art(html) -> _Art:
    parsed = _Art()
    parsed.feed(html)
    parsed.close()
    return parsed


@pytest.fixture(scope="module")
def pre_raw(html) -> str:
    match = re.search(r'<pre class="seance-art"[^>]*>(.*?)</pre>', html, flags=re.S)
    assert match, "index.html: no <pre class=seance-art> found"
    return match.group(1)


@pytest.fixture(scope="module")
def rows(pre_raw) -> list[str]:
    text = re.sub(r"</?span[^>]*>", "", pre_raw)
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


@pytest.fixture(scope="module")
def css() -> str:
    return _strip_comments(_read_css())


@pytest.fixture(scope="module")
def tokens(css) -> dict[str, str]:
    return _tokens(_split_root(css)[0])


def _rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [s.strip() for s in match.group(1).split(",")]
        found.append((selectors, dict(_declarations("{" + match.group(2) + "}"))))
    return found


def _seance_rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    return [(s, d) for s, d in _rules(css) if any(".seance-" in x for x in s)]


def _rule(css: str, selector: str) -> dict[str, str]:
    for selectors, decls in _rules(css):
        if selectors == [selector]:
            return decls
    raise AssertionError(f"console.css: no rule for {selector}")


def _px(value: str) -> float:
    match = re.fullmatch(r"(\d*\.?\d+)(rem|px)", value.strip())
    assert match, f"console.css: cannot read length {value!r}"
    number = float(match.group(1))
    return number * 16 if match.group(2) == "rem" else number


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------


def test_label_occurs_once_on_the_wrapper(html, art):
    assert html.count(LABEL) == 1, "index.html: the art label must occur exactly once"
    assert len(art.wrappers) == 1, "index.html: expected one div.seance-art-wrap[role=img]"
    assert art.wrappers[0][0].get("aria-label") == LABEL


def test_wrapper_is_inside_main_stage_and_holds_one_pre(art):
    assert art.wrappers and art.wrappers[0][1], "index.html: wrapper is not inside main.stage"
    assert len(art.pres) == 1, "index.html: expected exactly one pre.seance-art"
    assert art.pres[0][1], "index.html: pre.seance-art is not a direct child of the wrapper"


def test_pre_has_only_class_and_aria_hidden(art):
    attrs = art.pres[0][0]
    assert dict(attrs) == {"class": "seance-art", "aria-hidden": "true"} and len(attrs) == 2


def test_pre_holds_only_flat_classed_spans(art):
    assert not art.other_tags, f"index.html: non-span tag in the art at line(s) {[n for _, n in art.other_tags]}"
    assert art.spans, "index.html: the art has no spans"
    for attrs, nested, line in art.spans:
        assert not nested, f"index.html line {line}: nested span"
        assert len(attrs) == 1 and attrs[0][0] == "class" and attrs[0][1] in SPAN_CLASSES, (
            f"index.html line {line}: span must have one class of {sorted(SPAN_CLASSES)}"
        )
    used = {dict(attrs)["class"] for attrs, _, _ in art.spans}
    assert used == SPAN_CLASSES, "index.html: both seance-ball and seance-dim must occur"


def test_every_non_space_character_is_inside_a_span(art):
    assert not art.stray, f"index.html: text outside a span at line(s) {[n for _, n in art.stray]}"


def test_art_is_ascii_only(pre_raw, art):
    text = "".join(art.pre_text)
    for number, row in enumerate(text.split("\n")):
        bad = [c for c in row if not 0x20 <= ord(c) <= 0x7E]
        assert not bad, f"art row {number}: character outside 0x20-0x7E"
    for number, row in enumerate(pre_raw.split("\n")):
        assert all(0x20 <= ord(c) <= 0x7E for c in row), f"art source row {number}: not ASCII"


def test_art_size_and_shape(rows):
    assert len(rows) <= 20, f"art has {len(rows)} rows, limit 20"
    for number, row in enumerate(rows):
        assert row.strip(), f"art row {number} is blank"
        assert row == row.rstrip(" "), f"art row {number} ends in a space"
        assert len(row) <= 60, f"art row {number} is {len(row)} columns, limit 60"
    assert len(rows) == 17, f"art has {len(rows)} rows, pinned at 17"
    assert max(len(r) for r in rows) == 56, "widest art row is not 56 columns"


def test_art_has_ball_candles_and_table(rows):
    text = "\n".join(rows)
    assert "( o o )" in text, "art: no ball face"
    assert text.count("(__)") == 2, "art: expected two (__) candle holders"
    assert ".-----" in text, "art: no table top"


def test_nothing_focusable_inside_the_wrapper(art):
    assert not art.focusable, f"index.html: focusable or styled element in the wrapper at line(s) {[n for _, n in art.focusable]}"


# ---------------------------------------------------------------------------
# console.css
# ---------------------------------------------------------------------------


def test_art_is_hidden_after_a_result(css):
    for selectors, decls in _rules(css):
        if selectors == [".has-result .seance-art-wrap"] and decls.get("display") == "none":
            return
    raise AssertionError("console.css: no '.has-result .seance-art-wrap { display: none }' rule")


def test_art_is_hidden_below_a_wide_enough_breakpoint(css):
    for match in re.finditer(r"@media\s*\(\s*max-width\s*:\s*([\d.]+)rem\s*\)\s*\{", css):
        width = float(match.group(1))
        body = _block_at(css, match.end() - 1)[0]
        if width < 56:
            continue
        for selectors, decls in _rules(body):
            if selectors == [".seance-art-wrap"] and decls.get("display") == "none":
                return
    raise AssertionError("console.css: no @media (max-width: >=56rem) rule hiding .seance-art-wrap")


def test_art_does_not_wrap_and_stays_under_400px(css, rows):
    pre = _rule(css, ".seance-art")
    assert pre.get("white-space") == "pre", "console.css: .seance-art needs white-space: pre"
    font = _px(pre["font-size"])
    assert font >= 16, "console.css: .seance-art font size is under 1rem"
    assert pre.get("font-family") == "inherit"
    height = len(rows) * font * float(pre["line-height"])
    padding = _rule(css, ".seance-art-wrap")["padding"].split()
    vertical = _px(padding[0]) * 2
    assert height + vertical <= 400, f"console.css: computed art height {height + vertical}px is over 400px"


def test_seance_colours_come_only_from_the_three_tokens(css):
    rules = _seance_rules(css)
    assert rules, "console.css: no .seance-* rules"
    for selectors, decls in rules:
        text = "{" + ";".join(f"{p}:{v}" for p, v in decls.items()) + "}"
        assert not _colour_problems(text), f"console.css {selectors}: colour literal"
        for prop, value in decls.items():
            for name in re.findall(r"var\((--[\w-]+)\)", value):
                assert name in ALLOWED_VARS, f"console.css {selectors}: {prop} uses {name}"
            if prop == "color":
                assert value in {f"var({n})" for n in ALLOWED_VARS} or value == "none"
            assert prop not in {"font-weight", "letter-spacing"}, f"console.css {selectors}: {prop}"
    assert _rule(css, ".seance-dim")["color"] == "var(--fg-dim)"
    assert _rule(css, ".seance-ball")["color"] == "var(--fg-bright)"


def test_contrast_of_art_tokens_on_the_stage_backdrop(tokens):
    for back in ("--bg-void", "--bg-scan"):
        for front in ("--fg-dim", "--fg-bright"):
            ratio = _contrast(tokens[front], tokens[back])
            assert ratio >= 4.5, f"contrast {front} on {back} is {ratio:.2f}, need 4.5"
        ratio = _contrast(tokens["--ui-glow"], tokens[back])
        assert ratio >= 3.0, f"contrast --ui-glow on {back} is {ratio:.2f}, need 3"


def test_pulse_is_only_on_the_ball_and_is_slow_and_small(css):
    for selectors, decls in _seance_rules(css):
        has_animation = any(p == "animation" or p.startswith("animation-") for p in decls)
        assert has_animation == (selectors == [".seance-ball"]), (
            f"console.css {selectors}: animation belongs only to .seance-ball"
        )
    assert len(re.findall(r"gs-pulse", css)) == 2, "gs-pulse must appear only in .seance-ball and its @keyframes"
    ball = _rule(css, ".seance-ball")
    assert "gs-pulse" in ball["animation"]
    assert _seconds(ball["animation"]) >= 4, "pulse period is under 4 s"

    start = re.search(r"@keyframes\s+gs-pulse\s*\{", css)
    assert start, "console.css: no @keyframes gs-pulse"
    body = _block_at(css, start.end() - 1)[0]
    decls = _declarations(body)
    assert decls and all(p == "text-shadow" for p, _ in decls), "gs-pulse may change text-shadow only"
    blurs = []
    for _, value in decls:
        lengths = re.findall(r"(?<![\w-])(-?\d*\.?\d+)(?:px)?(?![\w-])", re.sub(r"var\([^)]*\)", "", value))
        assert len(lengths) >= 3, "gs-pulse: text-shadow without a blur radius"
        blurs.append(float(lengths[2]))
    assert max(blurs) - min(blurs) <= 8, "gs-pulse: blur radii differ by more than 8px"


def test_reduced_motion_block_still_disables_everything(css):
    assert len(re.findall(r"prefers-reduced-motion", css)) == 1
    block = _reduce_block(css)
    assert block is not None, "console.css: no prefers-reduced-motion block"
    ok = False
    for selectors, decls in _rules(block):
        clean = {k: re.sub(r"\s*!important\s*$", "", v, flags=re.I).strip() for k, v in decls.items()}
        if {"*", "*::before", "*::after"} <= set(selectors) and clean.get("animation") == "none" and clean.get("transition") == "none":
            ok = True
    assert ok, "console.css: reduce block must set animation and transition to none on *, *::before, *::after"
