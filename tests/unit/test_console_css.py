"""Static CSS contrast and motion tests for the console stylesheet (task 4.9).

Reads ``console.css`` from the installed package and checks it as text. No
browser is needed. The colour-keyword scan looks at declaration values only,
so a property such as ``white-space`` is never taken for a colour.

Requirements: 11.2, 11.4, 11.5, 11.6, 11.7, 11.9
"""

from __future__ import annotations

import re
from importlib import resources

import pytest

TEXT_MIN = 4.5
UI_MIN = 3.0
ALLOWED_KEYWORDS = {"transparent", "currentcolor"}

# CSS named colours (CSS Color Module Level 4), lower case.
NAMED_COLOURS = set(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black
    blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse
    chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
    darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta
    darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite
    forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green
    greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender
    lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon
    lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue
    lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
    mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
    mistyrose moccasin navajowhite navy oldlace olive olivedrab orange
    orangered orchid palegoldenrod palegreen paleturquoise palevioletred
    papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red
    rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell
    sienna silver skyblue slateblue slategray slategrey snow springgreen
    steelblue tan teal thistle tomato turquoise violet wheat white
    whitesmoke yellow yellowgreen""".split()
)


def _read_css() -> str:
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath("console.css")
        .read_text(encoding="utf-8")
    )


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block_at(css: str, open_index: int) -> tuple[str, int]:
    """Return (body, index after the closing brace) for the brace at open_index."""
    depth = 0
    for i in range(open_index, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_index + 1 : i], i + 1
    raise AssertionError("unbalanced braces in console.css")


def _split_root(css: str) -> tuple[str, str]:
    """Return (root block body, the stylesheet with the :root block removed)."""
    match = re.search(r":root\s*\{", css)
    assert match, "no :root block in console.css"
    brace = match.end() - 1
    body, end = _block_at(css, brace)
    return body, css[: match.start()] + css[end:]


def _declarations(css: str) -> list[tuple[str, str]]:
    """Every (property, value) found in an innermost { ... } block."""
    found: list[tuple[str, str]] = []
    for body in re.findall(r"\{([^{}]*)\}", css):
        for part in body.split(";"):
            if ":" not in part:
                continue
            prop, value = part.split(":", 1)
            prop = prop.strip().lower()
            if prop:
                found.append((prop, value.strip()))
    return found


def _colour_problems(css_outside_root: str) -> list[str]:
    """Colour literals in a stylesheet that has no :root block. Names only."""
    problems: list[str] = []
    if "#" in css_outside_root:
        problems.append("hash literal")
    for fn in re.findall(
        r"(?<![\w-])(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\(",
        css_outside_root,
        flags=re.I,
    ):
        problems.append(f"{fn.lower()}( literal")
    for prop, value in _declarations(css_outside_root):
        value = re.sub(r'"[^"]*"|\'[^\']*\'', "", value)
        value = re.sub(r"var\([^)]*\)", "", value, flags=re.I)
        for word in re.findall(r"(?<![\w-])[A-Za-z]+(?![\w-])", value):
            lowered = word.lower()
            if lowered in ALLOWED_KEYWORDS:
                continue
            if lowered in NAMED_COLOURS:
                problems.append(f"colour keyword {lowered!r} in {prop}")
    return problems


def _tokens(root_body: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for prop, value in _declarations("{" + root_body + "}"):
        assert prop.startswith("--"), f"unexpected property in :root: {prop}"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), (
            f"token {prop} is not a six-digit hex value"
        )
        assert prop not in tokens, f"token {prop} defined twice"
        tokens[prop] = value.lower()
    return tokens


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(scope="module")
def css() -> str:
    return _strip_comments(_read_css())


@pytest.fixture(scope="module")
def tokens(css) -> dict[str, str]:
    return _tokens(_split_root(css)[0])


def test_theme_tokens_are_present(tokens):
    assert any(n.startswith("--bg-") for n in tokens)
    assert any(n.startswith("--fg-") for n in tokens)
    assert any(n.startswith("--ui-") for n in tokens)


def test_text_tokens_meet_4_5_on_every_background(tokens):
    backgrounds = {n: v for n, v in tokens.items() if n.startswith("--bg-")}
    failures = [
        f"{fg} on {bg}: {_contrast(fv, bv):.2f}"
        for fg, fv in tokens.items()
        if fg.startswith("--fg-")
        for bg, bv in backgrounds.items()
        if _contrast(fv, bv) < TEXT_MIN
    ]
    assert not failures, "text contrast below 4.5: " + "; ".join(failures)


def test_ui_tokens_meet_3_on_every_background(tokens):
    backgrounds = {n: v for n, v in tokens.items() if n.startswith("--bg-")}
    failures = [
        f"{ui} on {bg}: {_contrast(uv, bv):.2f}"
        for ui, uv in tokens.items()
        if ui.startswith("--ui-")
        for bg, bv in backgrounds.items()
        if _contrast(uv, bv) < UI_MIN
    ]
    assert not failures, "non-text contrast below 3.0: " + "; ".join(failures)


def test_no_colour_literal_outside_root(css):
    outside = _split_root(css)[1]
    problems = _colour_problems(outside)
    assert not problems, "colour literal outside :root: " + "; ".join(problems)


def test_colour_scan_reads_values_not_property_names():
    clean = ".a { white-space: pre-wrap; color: var(--fg-main); border: 1px solid transparent; }"
    assert _colour_problems(clean) == []
    assert _colour_problems(".a { color: red; }")
    assert _colour_problems(".a { border: 1px solid WHITE; }")
    assert _colour_problems(".a { color: #fff; }")
    assert _colour_problems(".a { color: rgb(0 0 0); }")


def test_no_font_face_import_or_url(css):
    lowered = css.lower()
    for forbidden in ("@font-face", "@import", "url("):
        assert forbidden not in lowered, f"console.css contains {forbidden}"


def _reduce_block(css: str) -> str | None:
    match = re.search(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{", css)
    if not match:
        return None
    return _block_at(css, match.end() - 1)[0]


def test_motion_is_disabled_by_a_reduced_motion_block(css):
    motion_props = [
        p
        for p, _ in _declarations(css)
        if p == "animation" or p.startswith("animation-") or p == "transition"
        or p.startswith("transition-")
    ]
    has_keyframes = re.search(r"@(-\w+-)?keyframes\b", css) is not None
    assert motion_props or has_keyframes, "expected some motion in console.css"

    block = _reduce_block(css)
    assert block is not None, "no prefers-reduced-motion: reduce block"
    assert len(re.findall(r"prefers-reduced-motion", css)) == 1

    ok = False
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
        selectors = {s.strip() for s in match.group(1).split(",")}
        decls = dict(_declarations("{" + match.group(2) + "}"))
        values = {
            k: re.sub(r"\s*!important\s*$", "", v, flags=re.I).strip().lower()
            for k, v in decls.items()
        }
        if (
            {"*", "*::before", "*::after"} <= selectors
            and values.get("animation") == "none"
            and values.get("transition") == "none"
        ):
            ok = True
    assert ok, "reduce block must set animation: none and transition: none on *, *::before, *::after"


def test_focus_visible_outline_is_at_least_2px(css):
    widths = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if ":focus-visible" not in match.group(1):
            continue
        for prop, value in _declarations("{" + match.group(2) + "}"):
            if prop == "outline":
                assert "none" not in value.lower().split(), "focus outline removed"
                px = re.search(r"(\d+(?:\.\d+)?)px", value)
                if px:
                    widths.append(float(px.group(1)))
    assert widths, "no :focus-visible rule with an outline width"
    assert max(widths) >= 2.0, "focus outline is thinner than 2px"


def _seconds(value: str) -> float:
    match = re.search(r"(?<![\w.-])(\d*\.?\d+)(ms|s)\b", value)
    assert match, f"no duration in animation value {value!r}"
    number = float(match.group(1))
    return number / 1000 if match.group(2) == "ms" else number


def test_blinking_cursor_period_is_at_least_one_second(css):
    blink_names = re.findall(r"@keyframes\s+([\w-]*blink[\w-]*)", css, flags=re.I)
    assert blink_names, "no blink keyframes found"
    periods = []
    for _, value in [d for d in _declarations(css) if d[0] == "animation"]:
        if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", value) for n in blink_names):
            periods.append(_seconds(value))
    assert periods, "no animation uses the blink keyframes"
    assert min(periods) >= 1.0, f"blink period {min(periods)}s is under one second"
