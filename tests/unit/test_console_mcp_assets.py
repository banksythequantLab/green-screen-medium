"""Static checks for the MCP-visible Run in the console assets (task 8.5).

No Node and no browser. The files are read from the installed package path. A failure
names the file, the line and the rule, and never prints a line of the source.

Requirements: 18.20, 18.22, 5.10, 10.7
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from importlib import resources

import pytest


def _read(name: str) -> str:
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _lines(name: str, pattern: str, flags: int = 0) -> list[int]:
    text = _read(name)
    return [_line_of(text, m.start()) for m in re.finditer(pattern, text, flags)]


def _assert_absent(name: str, rule: str, pattern: str, flags: int = 0) -> None:
    found = _lines(name, pattern, flags)
    assert not found, f"{name}: rule '{rule}' broken at line(s) {found}"


def _assert_present(name: str, rule: str, pattern: str, flags: int = 0) -> None:
    assert re.search(pattern, _read(name), flags), f"{name}: rule '{rule}' is not met"


def _body(text: str, header: str) -> tuple[int, str]:
    """Return the start offset and the text of the function whose header starts with `header`."""
    start = text.index(header)
    open_at = text.index("{", text.index(")", start))
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, text[start : i + 1]
    raise AssertionError(f"console.js: unbalanced braces after function '{header}'")


# ---------------------------------------------------------------------------
# console.js: requests and reading
# ---------------------------------------------------------------------------


def test_mcp_requests_go_through_api_fetch_with_a_literal_path():
    text = _read("console.js")
    assert re.search(r"(?<![\w.])apiFetch\(\s*\"/mcp\"", text), (
        "console.js: no apiFetch(\"/mcp\" call with a literal first argument"
    )
    for m in re.finditer(r"(?<=[\"'`])/mcp(?=[\"'`])", text):
        before = text[max(0, m.start() - 40) : m.start()]
        line = _line_of(text, m.start())
        assert not re.search(r"(?<![\w.])fetch\s*\(\s*[\"'`]$", before), (
            f"console.js: rule 'no fetch of /mcp' broken at line {line}"
        )
        in_call = re.search(r"apiFetch\(\s*[\"'`]$", before)
        in_allow_list = re.search(r"path\s*===\s*[\"']$", before)
        in_comment = re.search(r"//[^\n]*$", text[text.rfind("\n", 0, m.start()) + 1 : m.start()])
        assert in_call or in_allow_list or in_comment, (
            f"console.js: rule '/mcp only as the literal first argument of apiFetch' broken at line {line}"
        )


def test_api_key_header_name_still_appears_once():
    assert _read("console.js").count("X-API-Key") == 1, "console.js: rule 'X-API-Key appears once' broken"


@pytest.mark.parametrize(
    "rule,pattern",
    (
        ("no getReader", r"\bgetReader\b"),
        ("no ReadableStream", r"\bReadableStream\b"),
        ("no EventSource", r"\bEventSource\b"),
        ("no response.body read", r"\bresponse\s*\.\s*body\b"),
        ("no response.json()", r"\bresponse\s*\.\s*json\s*\("),
        ("no window.scroll text", r"window\s*\.\s*scroll"),
        ("no literal Expand all", r"Expand all"),
        ("no literal Collapse all", r"Collapse all"),
    ),
)
def test_console_js_forbidden_text(rule, pattern):
    _assert_absent("console.js", rule, pattern)


def test_console_js_reads_the_reply_once_as_text():
    _assert_present("console.js", "reply read with response.text()", r"\bresponse\s*\.\s*text\s*\(\s*\)")


def test_only_the_three_header_names_are_read():
    text = _read("console.js")
    names = set()
    for m in re.finditer(r"\bheaders\s*\.\s*get\s*\(\s*([^)]*)\)", text):
        arg = m.group(1).strip()
        assert re.fullmatch(r"\"[^\"]*\"", arg), (
            f"console.js: rule 'header names are literals' broken at line {_line_of(text, m.start())}"
        )
        names.add(arg.strip('"'))
    allowed = {"Content-Type", "Mcp-Session-Id", "Retry-After"}
    assert names <= allowed, f"console.js: rule 'only three header names are read' broken: {sorted(names - allowed)}"
    assert {"Content-Type", "Mcp-Session-Id"} <= names, "console.js: a required header name is never read"


_NEW_IMPORTS = (
    "buildInitialize",
    "buildInitialized",
    "buildToolsList",
    "buildToolsCall",
    "mcpRequestHeaders",
    "parseMcpReply",
    "findReply",
    "hasTool",
    "classifyToolsCall",
    "formatTranscriptEntry",
    "summariseRun",
    "stripStages",
    "jsonRpcErrorText",
    "toggleAllLabel",
    "fitsInFirstScreen",
)


@pytest.mark.parametrize("name", _NEW_IMPORTS)
def test_console_js_imports_the_pure_function(name):
    text = _read("console.js")
    block = re.search(r"import\s*\{([^}]*)\}\s*from\s*\"\./snippets\.js\"", text, re.S)
    assert block, "console.js: the import from snippets.js is missing"
    assert re.search(rf"\b{name}\b", block.group(1)), f"console.js: '{name}' is not imported"


@pytest.mark.parametrize(
    "literal", ('"jsonrpc"', '"tools/call"', '"notifications/initialized"')
)
def test_console_js_holds_no_wire_text(literal):
    text = _read("console.js")
    for quote in ('"', "'", "`"):
        needle = quote + literal.strip('"') + quote
        assert needle not in text, (
            f"console.js: rule 'no wire text literal' broken at line {_line_of(text, text.index(needle))}"
        )


def test_set_timeout_takes_a_function():
    text = _read("console.js")
    calls = list(re.finditer(r"\bsetTimeout\s*\(", text))
    assert calls, "console.js: no setTimeout( call found"
    for m in calls:
        rest = text[m.end() :]
        assert re.match(r"\s*(?:\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>|function\b)", rest), (
            f"console.js: rule 'setTimeout takes a function' broken at line {_line_of(text, m.start())}"
        )


# ---------------------------------------------------------------------------
# console.js: transcript and result view
# ---------------------------------------------------------------------------


def test_console_js_defines_and_calls_the_transcript_functions():
    text = _read("console.js")
    for name in ("settleTranscript", "setAllWire"):
        assert re.search(rf"\bfunction\s+{name}\s*\(", text), f"console.js: function '{name}' is not defined"
        assert len(re.findall(rf"\b{name}\s*\(", text)) >= 2, f"console.js: function '{name}' is never called"
    for name in ("toggleAllLabel", "fitsInFirstScreen"):
        assert re.search(rf"(?<!function )\b{name}\s*\(", text), f"console.js: '{name}' is never called"
    assert "getBoundingClientRect" in text, "console.js: getBoundingClientRect is never called"


@pytest.mark.parametrize("header", ("function showSuccess(", "function showError("))
def test_the_strip_is_built_before_the_result_title(header):
    text = _read("console.js")
    start, body = _body(text, header)
    strip = body.find("appendStrip(")
    title = body.find("result-title")
    line = _line_of(text, start)
    assert strip != -1, f"console.js: '{header}' (line {line}) never builds the strip"
    assert title != -1, f"console.js: '{header}' (line {line}) never builds the result title"
    assert strip < title, f"console.js: rule 'strip before the result title' broken in '{header}' (line {line})"


def test_wire_entries_are_details_with_a_summary_element():
    _assert_present("console.js", "wire entry is a details element", r"\bel\(\s*\"details\"")
    _assert_present("console.js", "wire entry line is a summary element", r"\bel\(\s*\"summary\"")


def test_console_js_writes_the_heading_and_line_texts():
    text = _read("console.js")
    for fixed in (
        "Any MCP client can use this same tool",
        "This screen flow is published as an MCP tool",
    ):
        assert fixed in text, "console.js: a fixed heading or line text is missing"


# ---------------------------------------------------------------------------
# snippets.js
# ---------------------------------------------------------------------------


def test_snippets_js_never_holds_the_word_summary():
    _assert_absent("snippets.js", "the word summary appears nowhere", r"summary", re.I)



# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------


class _Group(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.groups: list[dict[str, str | None]] = []
        self.depth = 0
        self.inside = False
        self.buttons: list[tuple[dict[str, str | None], str]] = []
        self.inputs_inside = 0
        self.other_inside: list[str] = []
        self._text: list[str] | None = None
        self._attrs: dict[str, str | None] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("role") == "group" and a.get("aria-label") == "Call via":
            self.groups.append(a)
            self.inside = True
            self.depth = 1
            return
        if not self.inside:
            return
        if tag == "div":
            self.depth += 1
        if tag == "input":
            self.inputs_inside += 1
        if tag == "button":
            self._text = []
            self._attrs = a
        elif tag not in {"p"}:
            self.other_inside.append(tag)

    def handle_endtag(self, tag):
        if not self.inside:
            return
        if tag == "button" and self._text is not None:
            self.buttons.append((self._attrs, "".join(self._text).strip()))
            self._text = None
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.inside = False

    def handle_data(self, data):
        if self._text is not None:
            self._text.append(data)


def test_index_html_call_via_markup():
    parsed = _Group()
    parsed.feed(_read("index.html"))
    parsed.close()
    assert len(parsed.groups) == 1, "index.html: expected exactly one Call via group"
    assert "hidden" in parsed.groups[0], "index.html: the Call via group is not hidden at first"
    assert parsed.inputs_inside == 0, "index.html: the Call via group holds an <input>"
    assert not parsed.other_inside, "index.html: the Call via group holds an unexpected element"
    assert [(a.get("type"), a.get("aria-pressed"), text) for a, text in parsed.buttons] == [
        ("button", "true", "MCP"),
        ("button", "false", "REST"),
    ], "index.html: the Call via buttons are not MCP (pressed) then REST (not pressed)"


# ---------------------------------------------------------------------------
# console.css
# ---------------------------------------------------------------------------

_HOOK_CLASSES = (
    "call-via",
    "mcp-line",
    "mcp-clients",
    "mcp-clients-title",
    "strip",
    "strip-stage",
    "wire",
    "wire-head",
    "wire-title",
    "wire-toggle",
    "wire-note",
    "wire-list",
    "wire-entry",
    "wire-msg",
    "wire-json",
    "wire-sent",
    "wire-received",
)


@pytest.mark.parametrize("name", _HOOK_CLASSES)
def test_css_has_the_hook_class(name):
    _assert_present("console.css", f"class .{name} has a rule", rf"(?m)^[^{{}}\n]*\.{re.escape(name)}(?![\w-])[^{{}}]*\{{")


def test_css_pressed_rule_has_a_before_mark():
    css = _read("console.css")
    pressed = re.search(r"\[aria-pressed=\"true\"\][^{]*\{", css)
    assert pressed, "console.css: no [aria-pressed=\"true\"] rule"
    marked = re.search(r"\[aria-pressed=\"true\"\]::before\s*\{[^}]*\bcontent\s*:", css)
    assert marked, "console.css: the pressed button has no ::before content mark"


def test_css_wire_json_is_bounded_and_scrolls():
    css = _read("console.css")
    rule = re.search(r"\.wire-json\s*\{([^}]*)\}", css)
    assert rule, "console.css: no .wire-json rule"
    assert re.search(r"\bmax-height\s*:", rule.group(1)), "console.css: .wire-json has no max-height"
    assert re.search(r"\boverflow\s*:", rule.group(1)), "console.css: .wire-json has no overflow"
