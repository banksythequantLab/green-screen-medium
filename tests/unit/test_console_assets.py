"""Static scan tests for the six console assets (task 4.8).

The files are read from the installed package path, not from a copy. A failure names
the file, the rule and the line, and never prints more of a line than the rule needs.

Requirements: 2.7, 2.8, 5.3, 5.4, 5.5, 5.6, 5.9, 5.10, 5.11, 7.9, 9.9, 10.3, 10.4, 10.5,
10.7, 11.3, 11.8, 11.9, 14.1, 14.2
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from importlib import resources

import pytest

ALL_FILES = (
    "index.html",
    "console.css",
    "console.js",
    "snippets.js",
    "codes.json",
    "favicon.svg",
)
MARKUP_FILES = ("index.html", "favicon.svg")
SCRIPT_FILES = ("console.js", "snippets.js")

XMLNS = 'xmlns="http://www.w3.org/2000/svg"'


def _read(name: str) -> str:
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _hits(name: str, pattern: str, flags: int = 0) -> list[tuple[int, str]]:
    text = _read(name)
    return [(_line_of(text, m.start()), m.group(0)) for m in re.finditer(pattern, text, flags)]


def _assert_none(name: str, rule: str, pattern: str, flags: int = 0) -> None:
    found = _hits(name, pattern, flags)
    assert not found, f"{name}: rule '{rule}' broken at line(s) {[line for line, _ in found]}"


def _strip_comments(text: str) -> str:
    """Blank out comments, keeping line breaks so line numbers stay right."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"(?<![:\"'\\])//[^\n]*", "", text)


# ---------------------------------------------------------------------------
# Over all six files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_FILES)
def test_no_style_or_form_element(name):
    _assert_none(name, "no <style> element", r"<style\b", re.I)
    _assert_none(name, "no <form> element", r"<form\b", re.I)


@pytest.mark.parametrize("name", ALL_FILES)
def test_no_inline_script_without_src(name):
    text = _read(name)
    for m in re.finditer(r"<script\b([^>]*)>", text, re.I):
        assert re.search(r"\bsrc\s*=", m.group(1), re.I), (
            f"{name}: rule 'no inline script' broken at line {_line_of(text, m.start())}"
        )


@pytest.mark.parametrize("name", MARKUP_FILES)
def test_no_style_or_event_attribute(name):
    _assert_none(name, "no style attribute", r"\sstyle\s*=", re.I)
    _assert_none(name, "no on* attribute", r"\son[a-z]+\s*=", re.I)


@pytest.mark.parametrize("name", ALL_FILES)
def test_no_absolute_url(name):
    text = _read(name)
    if name == "favicon.svg":
        assert text.count(XMLNS) == 1, f"{name}: the xmlns attribute is missing or repeated"
        text = text.replace(XMLNS, "")
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+.\-]*://|[(\"'=]\s*//[A-Za-z0-9]", text):
        pytest.fail(f"{name}: rule 'no absolute URL' broken at line {_line_of(text, m.start())}")


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None], int]] = []
        self.label_for: set[str] = set()
        self.inputs: list[tuple[dict[str, str | None], bool, int]] = []
        self.paragraphs: list[tuple[int, int]] = []
        self.title = ""
        self._open: list[str] = []
        self._in_title = False
        self._p_words: int | None = None
        self._p_line = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        self.tags.append((tag, a, line))
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "input":
            self.inputs.append((a, "label" in self._open, line))
        if tag == "title":
            self._in_title = True
        if tag == "p":
            self._p_words = 0
            self._p_line = line
        if tag not in {"meta", "link", "input", "br", "img", "hr"}:
            self._open.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "p" and self._p_words is not None:
            self.paragraphs.append((self._p_line, self._p_words))
            self._p_words = None
        if tag in self._open:
            while self._open and self._open.pop() != tag:
                pass

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._p_words is not None:
            self._p_words += len(data.split())


@pytest.fixture(scope="module")
def page() -> _Page:
    parsed = _Page()
    parsed.feed(_read("index.html"))
    parsed.close()
    return parsed


def _by_tag(page: _Page, tag: str):
    return [(a, line) for t, a, line in page.tags if t == tag]


def test_exact_icon_link():
    assert '<link rel="icon" href="/console/favicon.svg">' in _read("index.html")


def test_referrer_meta():
    assert '<meta name="referrer" content="no-referrer">' in _read("index.html")


def test_html_lang_title_viewport_charset(page):
    html = _by_tag(page, "html")
    assert html and html[0][0].get("lang"), "index.html: <html lang> is missing"
    assert page.title.strip(), "index.html: <title> is empty"
    metas = [a for a, _ in _by_tag(page, "meta")]
    assert any(
        a.get("name") == "viewport" and a.get("content") == "width=device-width, initial-scale=1"
        for a in metas
    ), "index.html: viewport meta is missing or different"
    assert any(
        (a.get("charset") or "").lower() == "utf-8" for a in metas
    ), "index.html: charset meta is missing"


def test_no_tabindex_above_zero_in_page_and_script():
    for name in ("index.html", "console.js"):
        text = _read(name)
        for m in re.finditer(r"tabindex[\"']?\s*[=:]\s*[\"']?(-?\d+)", text, re.I):
            assert int(m.group(1)) <= 0, (
                f"{name}: rule 'no tabindex above 0' broken at line {_line_of(text, m.start())}"
            )


def test_every_input_has_a_label(page):
    assert page.inputs, "index.html: no <input> found"
    for attrs, wrapped, line in page.inputs:
        labelled = wrapped or (attrs.get("id") and attrs["id"] in page.label_for)
        assert labelled, f"index.html: rule 'input has a label' broken at line {line}"


def test_live_regions_are_polite(page):
    by_id = {a.get("id"): a for _, a, _ in page.tags if a.get("id")}
    for region in ("status", "result"):
        assert region in by_id, f"index.html: region '{region}' is missing"
        assert by_id[region].get("aria-live") == "polite", (
            f"index.html: region '{region}' lacks aria-live=polite"
        )


def test_no_paragraph_over_40_words(page):
    assert page.paragraphs
    for line, words in page.paragraphs:
        assert words <= 40, f"index.html: rule 'paragraph at most 40 words' broken at line {line}"


def test_index_has_one_module_script_with_src(page):
    scripts = _by_tag(page, "script")
    assert len(scripts) == 1
    attrs, _ = scripts[0]
    assert attrs.get("type") == "module" and attrs.get("src") == "/console/console.js"


# ---------------------------------------------------------------------------
# console.js and snippets.js: forbidden names
# ---------------------------------------------------------------------------

FORBIDDEN = (
    ("localStorage", r"localStorage"),
    ("sessionStorage", r"sessionStorage"),
    ("document.cookie", r"document\s*\.\s*cookie"),
    ("console.", r"\bconsole\s*\."),
    ("innerHTML", r"innerHTML"),
    ("outerHTML", r"outerHTML"),
    ("insertAdjacentHTML", r"insertAdjacentHTML"),
    ("document.write", r"document\s*\.\s*write"),
    ("eval(", r"\beval\s*\("),
    ("new Function", r"\bnew\s+Function\b"),
    ("javascript:", r"javascript:"),
    ("setTimeout with a string", r"\bsetTimeout\s*\(\s*[\"'`]"),
    ("setInterval with a string", r"\bsetInterval\s*\(\s*[\"'`]"),
    ("setAttribute of style", r"setAttribute\s*\(\s*[\"']style[\"']"),
    ("setAttribute of on*", r"setAttribute\s*\(\s*[\"']on[A-Za-z]*[\"']"),
)


@pytest.mark.parametrize("name", SCRIPT_FILES)
@pytest.mark.parametrize("label,pattern", FORBIDDEN, ids=[f[0] for f in FORBIDDEN])
def test_forbidden_names(name, label, pattern):
    found = _hits(name, pattern)
    assert not found, f"{name}: forbidden '{label}' at line(s) {[line for line, _ in found]}"


# ---------------------------------------------------------------------------
# console.js rules
# ---------------------------------------------------------------------------


def test_replace_state_comes_before_first_fetch():
    text = _read("console.js")
    replace = text.find("history.replaceState")
    first_fetch = re.search(r"\bfetch\s*\(", text)
    assert replace != -1, "console.js: history.replaceState is missing"
    assert first_fetch, "console.js: no fetch( found"
    assert replace < first_fetch.start(), (
        f"console.js: history.replaceState (line {_line_of(text, replace)}) "
        f"comes after the first fetch( (line {_line_of(text, first_fetch.start())})"
    )


def _function_body(text: str, header: str) -> tuple[int, int]:
    start = text.index(header)
    open_at = text.index("{", text.index(")", start))
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return open_at, i
    raise AssertionError(f"unbalanced braces after {header}")


def test_api_key_variable_is_read_only_inside_api_fetch():
    text = _read("console.js")
    lo, hi = _function_body(text, "async function apiFetch(")
    reads = 0
    for m in re.finditer(r"\bapiKey\b", text):
        if re.match(r"\s*=(?!=)", text[m.end():]):
            continue  # an assignment, or the declaration with its first value
        reads += 1
        assert lo < m.start() < hi, (
            f"console.js: rule 'apiKey read only in apiFetch' broken at line {_line_of(text, m.start())}"
        )
    assert reads >= 1, "console.js: apiFetch never reads apiKey"


def test_api_key_header_name_appears_once():
    assert _read("console.js").count("X-API-Key") == 1


def test_console_js_has_seven_audit_names_and_no_summary_member():
    text = _read("console.js")
    for member in (
        "step_index",
        "kind",
        "phase",
        "iteration",
        "signature",
        "status",
        "duration_seconds",
    ):
        assert f'"{member}"' in text, f"console.js: audit member '{member}' is missing"
    found = summary_violations(text)
    assert not found, f"console.js: rule 'summary only in the allowed forms' broken at line(s) {[line for line, _ in found]}"


# The remove-the-allowed-forms scan of the design's "Summary scan" (Decision D12).
_SUMMARY_SPLIT = re.compile(r"""["']sum["']\s*\+""")
_SUMMARY_ALLOWED = (
    re.compile(r"""\bel\(\s*"summary\""""),
    re.compile(r"""\bcreateElement\(\s*"summary\""""),
    re.compile(r"""(?<![\w$.?])operation\.summary\b"""),
    re.compile(r'"flow-summary"'),
)


def summary_violations(text: str) -> list[tuple[int, str]]:
    """Return (line number, matched text) for every use of `summary` outside the allowed forms."""
    found: list[tuple[int, str]] = [
        (_line_of(text, m.start()), m.group(0)) for m in _SUMMARY_SPLIT.finditer(text)
    ]
    rest = text
    for pattern in _SUMMARY_ALLOWED:
        rest = pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), rest)
    found += [(_line_of(rest, m.start()), m.group(0)) for m in re.finditer(r"summary", rest, re.I)]
    return sorted(found)


SUMMARY_PASS = (
    'el("summary", null, "Use this flow")',
    'document.createElement("summary")',
    'const t = typeof operation.summary === "string" ? operation.summary : "";',
    'el("p", { class: "flow-summary" }, t)',
)
SUMMARY_FAIL = (
    "error.summary",
    "err?.summary",
    "body.summary",
    "info.error.summary",
    'body["summary"]',
    "body['summary']",
    "body[`summary`]",
    "const { summary } = error;",
    "const { error: { summary } } = body;",
    "const summary = 1;",
    "function f(summary) {}",
    "x.operation.summary",
    "operation2.summary",
    "operation?.summary",
    '"sum" + "mary"',
    "'sum' + 'mary'",
    "// reads the summary",
    'el("summary", null, x); body.summary',
)


@pytest.mark.parametrize("line", SUMMARY_PASS)
def test_summary_scan_accepts_the_allowed_forms(line):
    assert summary_violations(line) == []


@pytest.mark.parametrize("line", SUMMARY_FAIL)
def test_summary_scan_rejects_every_other_form(line):
    assert summary_violations(line), "the scan let a forbidden form through"


def test_summary_scan_reports_the_line_number():
    assert [n for n, _ in summary_violations('el("summary", null, x)\nbody.summary\n')] == [2]


SCROLL_NAMES = (
    ("scrollIntoView", r"scrollIntoView"),
    ("scrollTo(", r"scrollTo\s*\("),
    ("scrollBy(", r"scrollBy\s*\("),
    ("window.scroll", r"window\s*\.\s*scroll"),
    ("location.hash assignment", r"location\s*\.\s*hash\s*=(?!=)"),
)


def test_result_focus_prevents_scroll_and_no_scroll_call_exists():
    text = _read("console.js")
    calls = list(re.finditer(r"refs\.result\.focus\(([^)]*)\)", text))
    assert calls, "console.js: no focus call on the result region"
    for m in calls:
        assert re.sub(r"\s+", " ", m.group(1)).strip() == "{ preventScroll: true }", (
            f"console.js: rule 'result focus passes preventScroll' broken at line {_line_of(text, m.start())}"
        )
    for label, pattern in SCROLL_NAMES:
        found = _hits("console.js", pattern)
        assert not found, f"console.js: forbidden '{label}' at line(s) {[line for line, _ in found]}"


def test_requests_stay_on_allowed_paths():
    text = _read("console.js")
    allowed = ("/openapi.json", "/flows/", "/mcp", "/console/codes.json", "/ask")
    calls = list(re.finditer(r"(?<![\w.])(?:api)?[Ff]etch\s*\(\s*([^,)]*)", text))
    literal_calls = 0
    for m in calls:
        arg = m.group(1).strip()
        line = _line_of(text, m.start())
        if arg.startswith(("\"", "'", "`")):
            literal_calls += 1
            assert arg[1:].startswith(allowed), (
                f"console.js: rule 'request path allow-list' broken at line {line}"
            )
        else:
            # Only the generic forwarding inside apiFetch (fetch(path, ...)) and its
            # declaration take a variable; apiFetch itself checks the path.
            assert arg in {"path", ""}, f"console.js: request with a computed target at line {line}"
    assert literal_calls >= 3
    assert re.search(r"path\s*===\s*\"/openapi\.json\"\s*\|\|\s*/\^\\/flows\\/", text), (
        "console.js: the apiFetch path allow-list is missing"
    )
    for banned in ("XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "importScripts"):
        assert banned not in text, f"console.js: '{banned}' is not allowed"


# ---------------------------------------------------------------------------
# snippets.js rules
# ---------------------------------------------------------------------------

NODE_NAMES = (
    "document",
    "window",
    "globalThis",
    "self",
    "location",
    "navigator",
    "fetch",
    "localStorage",
    "sessionStorage",
    "console",
)


def test_snippets_has_no_import():
    code = _strip_comments(_read("snippets.js"))
    for m in re.finditer(r"\bimport\b", code):
        pytest.fail(f"snippets.js: rule 'no import' broken at line {_line_of(code, m.start())}")


_TOKENS = re.compile(
    r"""//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`""",
    re.S,
)


def _code_only(text: str) -> str:
    """Blank comments and string literals (quotes included), keeping line breaks."""
    return _TOKENS.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


# The browser `console` object as a name in code: not part of a longer word or of a
# hyphenated text such as `greenscreen-console` or `.console-x`.
_CONSOLE_NAME = re.compile(r"(?<![\w$-])console(?![\w$-])")


def console_violations(text: str) -> list[tuple[int, str]]:
    """Return (line number, matched text) for every use of the `console` name in code."""
    code = _code_only(text)
    return [(_line_of(code, m.start()), m.group(0)) for m in _CONSOLE_NAME.finditer(code)]


CONSOLE_PASS = (
    'const CLIENT_NAME = "greenscreen-console";',
    "const c = 'greenscreen-console';",
    'el("div", { class: "console-x" }, t)',
    ".console-x { color: red; }",
    "// console is a browser object",
    "/* console */ const a = 1;",
    "const consoleLike = 1;",
)
CONSOLE_FAIL = (
    "console.log(x)",
    'console["log"](x)',
    "window.console",
    "console .log(x)",
    "const c = console;",
    "x(console)",
)


@pytest.mark.parametrize("line", CONSOLE_PASS)
def test_console_scan_accepts_text_that_is_not_the_object(line):
    assert console_violations(line) == []


@pytest.mark.parametrize("line", CONSOLE_FAIL)
def test_console_scan_rejects_the_object(line):
    assert console_violations(line), "the scan let a forbidden form through"


def test_console_scan_reports_the_line_number():
    assert [n for n, _ in console_violations('const a = "console";\nconsole.log(a)\n')] == [2]


@pytest.mark.parametrize("word", NODE_NAMES)
def test_snippets_has_none_of_the_requirement_14_names(word):
    # Comments are blanked: a word in prose is not a reference. The raw-text scan
    # above already rejects `console.` anywhere, comments included.
    if word == "console":
        for line, _ in console_violations(_read("snippets.js")):
            pytest.fail(f"snippets.js: forbidden name '{word}' at line {line}")
        return
    code = _strip_comments(_read("snippets.js"))
    for m in re.finditer(rf"\b{word}\b", code):
        pytest.fail(f"snippets.js: forbidden name '{word}' at line {_line_of(code, m.start())}")


def test_snippets_has_no_parameter_named_like_a_key():
    code = _strip_comments(_read("snippets.js"))
    lists = re.findall(r"function\s*\w*\s*\(([^)]*)\)", code)
    lists += re.findall(r"\(([^()]*)\)\s*=>", code)
    lists += re.findall(r"\b(\w+)\s*=>", code)
    for params in lists:
        for param in params.split(","):
            name = param.split("=")[0].strip()
            assert not re.search(r"key", name, re.I), "snippets.js: a parameter is named like a key"


def test_snippets_holds_the_placeholders():
    text = _read("snippets.js")
    assert "<YOUR_API_KEY>" in text
    assert "<SECRET>" in text


def test_snippets_has_no_host_or_url_literal():
    text = _read("snippets.js")
    assert not re.search(r"https?://", text, re.I), "snippets.js: an http(s) literal is present"
    assert not re.search(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|app|local|lan|invalid)\b", text, re.I), (
        "snippets.js: a host name literal is present"
    )
