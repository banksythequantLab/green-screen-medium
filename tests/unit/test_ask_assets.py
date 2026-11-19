"""Static scans of the Ask additions to the console assets (task 4.6).

Reads the installed package files. A failure names the file, the rule and the line.

Requirements: 12.1, 12.2, 12.9, 12.10, 12.11, 12.13, 12.14, 12.15, 17.2
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from importlib import resources

import pytest

from greenscreen.publisher.ask.codes import ASK_ERROR_CODES


def _read(name: str) -> str:
    text = (
        resources.files("greenscreen.publisher.console")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )
    return text.replace("\r\n", "\n")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _function_text(text: str, header: str) -> tuple[int, str]:
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
    raise AssertionError(f"unbalanced braces after {header}")


def _ask_section(js: str) -> tuple[int, str]:
    start = js.index("// ---- Ask ----")
    end = js.index("// ---- Events and start ----")
    return start, js[start:end]


# ---------------------------------------------------------------------------
# console.js
# ---------------------------------------------------------------------------


def test_ask_is_the_only_new_request_path_and_goes_through_api_fetch():
    js = _read("console.js")
    # The allow-list gained exactly one path, after the existing text.
    assert re.search(
        r'path === "/openapi\.json" \|\| /\^\\/flows\\/\[\^/\]\+\$/\.test\(path\) '
        r'\|\| path === "/mcp" \|\| path === "/ask";',
        js,
    ), "console.js: rule 'allow-list gains only /ask' broken"
    literals = re.findall(r"""(["'`])(/[A-Za-z0-9_./-]*)\1""", js)
    paths = {p for _, p in literals if p.startswith(("/ask", "/flows", "/mcp", "/openapi", "/console"))}
    assert "/ask" in paths
    assert not {p for p in paths if p.startswith("/ask") and p != "/ask"}
    # Every use of the "/ask" literal is in the allow-list or in apiFetch("/ask".
    for m in re.finditer(r"""["']/ask["']""", js):
        around = js[max(0, m.start() - 40) : m.end()]
        assert around.endswith(('apiFetch("/ask"', 'path === "/ask"')) or "paths[" in around, (
            f"console.js: rule '/ask only through apiFetch' broken at line {_line_of(js, m.start())}"
        )
    assert len(re.findall(r'apiFetch\(\s*"/ask"', js)) == 1
    # No bare fetch( outside apiFetch itself.
    start, body = _function_text(js, "async function apiFetch(")
    for m in re.finditer(r"(?<![\w.])fetch\s*\(", js):
        if js[m.end() :].lstrip().startswith('"/console/codes.json"'):
            continue  # the existing error-table load, not an Ask path
        assert start < m.start() < start + len(body), (
            f"console.js: rule 'fetch only inside apiFetch' broken at line {_line_of(js, m.start())}"
        )


def test_key_header_once_and_key_is_read_only_in_api_fetch():
    js = _read("console.js")
    assert js.count("X-API-Key") == 1
    start, ask = _ask_section(js)
    assert not re.search(r"\bapiKey\b", ask), "console.js: the Ask section touches apiKey"


def test_ask_section_has_no_forbidden_names():
    js = _read("console.js")
    start, ask = _ask_section(js)
    forbidden = (
        r"innerHTML",
        r"outerHTML",
        r"insertAdjacentHTML",
        r"document\s*\.\s*write",
        r"\bconsole\s*\.",
        r"localStorage",
        r"sessionStorage",
        r"scrollIntoView",
        r"scrollTo\s*\(",
        r"scrollBy\s*\(",
        r"window\s*\.\s*scroll",
        r"location\s*\.",
        r"history\s*\.",
        r"\beval\s*\(",
        r"\bnew\s+Function\b",
    )
    for pattern in forbidden:
        for m in re.finditer(pattern, ask):
            pytest.fail(
                f"console.js: forbidden '{pattern}' at line {_line_of(js, start + m.start())}"
            )


def test_question_is_a_local_of_ask_and_goes_only_to_the_body_and_the_chain():
    js = _read("console.js")
    _, body = _function_text(js, "async function ask(")
    assert len(re.findall(r"const question = refs\.askInput\.value\.trim\(\);", body)) == 1
    allowed = (
        "buildAskBody(question)",
        "renderAskReply(question,",
        'showAskError(question, "no_response"',
        'question === ""',
    )
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', body)
    allowed = ("buildAskBody(question)", "renderAskReply(question,", "showAskError(question,", "question = refs", "question === ")
    for m in re.finditer(r"\bquestion\b", code):
        window = code[max(0, m.start() - 30) : m.end() + 20]
        assert any(a in window for a in allowed), (
            f"console.js: rule 'question stays local' broken near ask() offset {m.start()}"
        )
    # Reply helpers receive it only to build the Chain.
    for name in ("showAskError", "showAskAnswer", "askChainList", "renderAskReply"):
        _, text = _function_text(js, f"function {name}(")
        for m in re.finditer(r"\bquestion\b", text):
            line = text[text.rfind("\n", 0, m.start()) + 1 : text.find("\n", m.start())]
            assert re.search(
                r"(function \w+\(question|\w+\(question,|askChain\(question,)", line
            ), f"console.js: rule 'question only for the Chain' broken in {name}: {line.strip()}"


def test_reply_text_goes_in_as_text_nodes_and_answer_is_one_text_node():
    js = _read("console.js")
    assert 'el("p", { class: "ask-answer-text" }, body.answer)' in js
    assert js.count("ask-answer-text") == 1


def test_focus_after_reply_prevents_scroll():
    js = _read("console.js")
    calls = list(re.finditer(r"refs\.askOut\.focus\(([^)]*)\)", js))
    assert len(calls) == 2, "console.js: expected a focus call after an answer and after an error"
    for m in calls:
        assert re.sub(r"\s+", " ", m.group(1)).strip() == "{ preventScroll: true }", (
            f"console.js: rule 'Ask focus passes preventScroll' broken at line {_line_of(js, m.start())}"
        )
    assert "refs.askOut.focus({ preventScroll: true });" in js


def test_summary_only_in_allowed_forms_in_console_js():
    from tests.unit.test_console_assets import summary_violations

    js = _read("console.js")
    found = summary_violations(js)
    assert not found, f"console.js: rule 'summary only in allowed forms' broken at line(s) {[n for n, _ in found]}"


def test_summary_nowhere_in_snippets_js():
    text = _read("snippets.js")
    for m in re.finditer(r"summary", text, re.I):
        pytest.fail(f"snippets.js: rule 'no summary' broken at line {_line_of(text, m.start())}")


def test_the_nine_ask_codes_are_not_literals_in_console_js():
    js = _read("console.js")
    assert len(ASK_ERROR_CODES) == 9
    for code in sorted(ASK_ERROR_CODES):
        for m in re.finditer(rf"""["'`]{re.escape(code)}["'`]""", js):
            pytest.fail(f"console.js: Ask code '{code}' as a literal at line {_line_of(js, m.start())}")


def test_snippets_js_still_has_no_import_and_no_key_parameter():
    text = _read("snippets.js")
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"(?<![:\"'\\])//[^\n]*", "", code)
    assert not re.search(r"\bimport\b", code), "snippets.js: an import is present"
    lists = re.findall(r"function\s*\w*\s*\(([^)]*)\)", code)
    lists += re.findall(r"\(([^()]*)\)\s*=>", code)
    lists += re.findall(r"\b(\w+)\s*=>", code)
    for params in lists:
        for param in params.split(","):
            name = param.split("=")[0].strip()
            assert not re.search(r"key", name, re.I), f"snippets.js: parameter '{name}' is named like a key"


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------


class _Dom(HTMLParser):
    VOID = {"meta", "link", "input", "br", "img", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.nodes: list[dict] = []
        self.order: list[str] = []

    def handle_starttag(self, tag, attrs):
        node = {
            "tag": tag,
            "attrs": dict(attrs),
            "parent": self.stack[-1] if self.stack else None,
            "line": self.getpos()[0],
            "text": "",
            "children": [],
        }
        if node["parent"] is not None:
            node["parent"]["children"].append(node)
        self.nodes.append(node)
        if tag in {"textarea", "button", "input", "a", "select"}:
            self.order.append(node["attrs"].get("id") or tag)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data


@pytest.fixture(scope="module")
def dom() -> _Dom:
    parsed = _Dom()
    parsed.feed(_read("index.html"))
    parsed.close()
    return parsed


def _one(dom: _Dom, **match) -> dict:
    found = [
        n
        for n in dom.nodes
        if all((n["tag"] == v) if k == "tag" else (n["attrs"].get(k) == v) for k, v in match.items())
    ]
    assert len(found) == 1, f"index.html: expected exactly one node {match}, found {len(found)}"
    return found[0]


def test_panel_is_the_first_child_of_main_stage_and_hidden_by_default(dom):
    stage = _one(dom, tag="main", **{"class": "stage"})
    first = stage["children"][0]
    assert first["tag"] == "section" and first["attrs"].get("id") == "ask-panel", (
        f"index.html: rule 'Ask panel is first child of main.stage' broken at line {first['line']}"
    )
    assert "hidden" in first["attrs"], "index.html: the Ask panel is not hidden by default"
    assert "ask-panel" in (first["attrs"].get("class") or "").split()
    # The status line and the result region come after it.
    ids = [c["attrs"].get("id") for c in stage["children"]]
    assert ids.index("ask-panel") < ids.index("status") < ids.index("result")


def test_panel_markup_facts(dom):
    assert not [n for n in dom.nodes if n["tag"] == "form"], "index.html: a <form> is present"
    textarea = _one(dom, tag="textarea")
    assert textarea["attrs"].get("id") == "ask-input"
    labels = [n for n in dom.nodes if n["tag"] == "label" and n["attrs"].get("for") == "ask-input"]
    assert len(labels) == 1, "index.html: the textarea needs exactly one label for it"
    # maxlength is set from the request schema by console.js, never fixed in the markup.
    assert "maxlength" not in textarea["attrs"]
    assert "maxLength" in _read("console.js")
    panel = _one(dom, id="ask-panel")
    buttons = []

    def walk(node):
        if node["tag"] == "button":
            buttons.append(node)
        for child in node["children"]:
            walk(child)

    walk(panel)
    assert len(buttons) == 1, "index.html: the Ask panel must hold exactly one button"
    assert buttons[0]["attrs"].get("type") == "button" and buttons[0]["attrs"].get("id") == "ask-button"
    assert buttons[0]["text"].strip() == "Ask"
    assert panel["children"][0]["tag"] == "h2" and panel["children"][0]["text"].strip() == "Ask the mainframe"


def test_live_regions_and_focus_target(dom):
    count = _one(dom, id="ask-count")
    out = _one(dom, id="ask-out")
    assert count["attrs"].get("aria-live") == "polite"
    assert out["attrs"].get("aria-live") == "polite"
    assert out["attrs"].get("tabindex") == "-1"
    assert out["attrs"].get("aria-label")


def test_help_line_is_under_40_words(dom):
    panel = _one(dom, id="ask-panel")
    helps = [c for c in panel["children"] if c["tag"] == "p" and "help" in (c["attrs"].get("class") or "")]
    assert len(helps) == 1
    words = len(helps[0]["text"].split())
    assert words < 40, f"index.html: help line has {words} words (line {helps[0]['line']})"
    text = helps[0]["text"].lower()
    assert "ai service" in text and "password" in text


def test_no_inline_style_or_event_attribute_in_panel(dom):
    panel = _one(dom, id="ask-panel")

    def walk(node):
        for name in node["attrs"]:
            assert name != "style" and not name.startswith("on"), (
                f"index.html: attribute '{name}' at line {node['line']}"
            )
            if name == "tabindex":
                assert int(node["attrs"][name]) <= 0
        for child in node["children"]:
            walk(child)

    walk(panel)


def test_keyboard_order_is_textarea_then_ask_then_examples_then_key_controls_first(dom):
    order = dom.order
    assert order.index("ask-input") + 1 == order.index("ask-button"), order
    # The examples are generated buttons inside #ask-examples, after the Ask button in the DOM.
    examples = _one(dom, id="ask-examples")
    out = _one(dom, id="ask-out")
    panel = _one(dom, id="ask-panel")
    kids = [c["attrs"].get("id") or c["tag"] for c in panel["children"]]
    assert kids.index("ask-input") < kids.index("ask-examples") < kids.index("ask-out")
    assert examples["children"] == [] and out["children"] == []
    # The side column (key and Flow controls) precedes the stage in the DOM; the stacked
    # layout reorders visually only (checked in the manual checklist).
    layout = _one(dom, tag="div", **{"class": "layout"})
    assert [c["tag"] for c in layout["children"]] == ["aside", "main"]
    # No control of the panel is created without a native element.
    js = _read("console.js")
    assert 'el("button", { type: "button", class: "quiet" }, item.text)' in js


def test_seance_art_markup_is_still_present_once(dom):
    wraps = [n for n in dom.nodes if n["attrs"].get("class") == "seance-art-wrap"]
    assert len(wraps) == 1


# ---------------------------------------------------------------------------
# console.css
# ---------------------------------------------------------------------------


def _rules(css: str) -> list[tuple[str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(re.sub(r"\s+", " ", s).strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_has_ask_art_rule_is_separate_and_has_result_rule_is_unchanged():
    css = _read("console.css")
    rules = _rules(css)
    selectors = [s for s, _ in rules]
    assert selectors.count(".has-ask .seance-art-wrap") == 1, (
        "console.css: the separate '.has-ask .seance-art-wrap' rule is missing or repeated"
    )
    body = dict(rules)[".has-ask .seance-art-wrap"]
    assert re.sub(r"\s+", "", body) == "display:none;"
    assert selectors.count(".has-result .seance-art-wrap") == 1, (
        "console.css: the '.has-result .seance-art-wrap' rule is not alone in its selector"
    )
    assert re.sub(r"\s+", "", dict(rules)[".has-result .seance-art-wrap"]) == "display:none;"
    for selector in selectors:
        if "seance-art-wrap" in selector:
            assert "," not in selector, f"console.css: grouped art selector '{selector}'"
    assert "has-ask" not in "".join(s for s in selectors if "has-result" in s)


def test_ask_block_adds_no_colour_token_animation_or_small_font():
    css = _read("console.css")
    start = css.index("/* Ask panel: the first block of the stage")
    end = css.index("/* Motion */")
    block = css[start:end]
    line0 = _line_of(css, start)
    for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|color-mix)\s*\(", block):
        pytest.fail(f"console.css: new colour literal at line {line0 + _line_of(block, m.start()) - 1}")
    assert not re.search(r"^\s*--[\w-]+\s*:", block, re.M), "console.css: a new token in the Ask block"
    assert "@keyframes" not in block and "animation" not in block and "transition" not in block
    defined = set(re.findall(r"^\s*(--[\w-]+)\s*:", css[:start] + css[end:], re.M))
    for token in re.findall(r"var\(\s*(--[\w-]+)", block):
        assert token in defined, f"console.css: Ask block uses undefined token {token}"
    for m in re.finditer(r"font-size\s*:\s*([\d.]+)(\w*)", block):
        assert not (m.group(2) == "rem" and float(m.group(1)) < 1), "console.css: font size below 1rem"
        assert m.group(2) in {"rem", "em"} or float(m.group(1)) >= 16


def test_chain_reuses_strip_classes_without_new_rules_for_them():
    css = _read("console.css")
    js = _read("console.js")
    assert 'el("ol", { class: "strip ask-chain" })' in js
    assert js.count('el("li", { class: "strip-stage" }') >= 2
    rules = dict(_rules(css))
    # Only spacing for .ask-chain and .ask-run-line.
    for selector in (".ask-chain", ".ask-run-line"):
        props = re.findall(r"([\w-]+)\s*:", rules[selector])
        assert props and all(p.startswith("margin") for p in props), (selector, props)
    # .strip and .strip-stage keep a single definition each.
    selectors = [s for s, _ in _rules(css)]
    assert selectors.count(".strip") == 1 and selectors.count(".strip-stage") == 1


def test_stacked_layout_rule_is_one_separate_order_rule():
    css = _read("console.css")
    assert len(re.findall(r"\border\s*:", css)) == 1
    rules = _rules(css)
    assert [s for s, b in rules if re.sub(r"\s+", "", b) == "order:-1;"] == [".has-ask .stage"]


# ---------------------------------------------------------------------------
# task 8.2: plain-text answers (Requirement 12.5; Decisions 28 and 35)
# ---------------------------------------------------------------------------


def test_answer_rendering_is_one_text_node_and_never_strips_or_renders():
    js = _read("console.js")
    # el() puts a string child in through createTextNode and never through innerHTML.
    _, el_body = _function_text(js, "function el(")
    assert "document.createTextNode(child)" in el_body
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML", el_body)
    # showAskAnswer builds the answer as one <p> whose only child is body.answer, unchanged.
    start, show = _function_text(js, "function showAskAnswer(")
    # The only other use is the argument of askChainList (the Chain's refusal check).
    assert show.count("body.answer") == 2
    assert "askChainList(question, body.trace, body.answer, null)" in show
    assert 'el("p", { class: "ask-answer-text" }, body.answer)' in show
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|\.replace(All)?\s*\(|\.split\s*\(|\.trim", show), (
        f"console.js: answer rendering transforms the text near line {_line_of(js, start)}"
    )
    # Nowhere in console.js is a * or _ replaced or stripped.
    for m in re.finditer(r"\.replace(?:All)?\s*\(\s*(/[^/\n]*[*_][^/\n]*/\w*|[\"'][^\"']*[*_][^\"']*[\"'])", js):
        pytest.fail(f"console.js: replace of '*' or '_' at line {_line_of(js, m.start())}")
    # The answer reaches the page only through that one node.
    assert js.count("ask-answer-text") == 1


# ---------------------------------------------------------------------------
# task 11.4: page fixes after the reviewer's browser pass (Requirement 12.14, 12.16-12.18)
# ---------------------------------------------------------------------------


def _code_only(text: str) -> str:
    """Drop // comments so scans see code only (the page code has no '//' inside strings that matter here)."""
    return re.sub(r"(?m)^\s*//[^\n]*$", "", text)


def _css_body(selector: str) -> str:
    bodies = [b for s, b in _rules(_read("console.css")) if s == selector]
    assert len(bodies) == 1, f"console.css: expected exactly one rule '{selector}', found {len(bodies)}"
    return re.sub(r"\s+", " ", bodies[0]).strip()


def _declarations(body: str) -> dict[str, str]:
    return {
        k.strip(): v.strip()
        for k, v in (d.split(":", 1) for d in body.split(";") if ":" in d)
    }


def test_counter_uses_ask_counter_text_and_ask_max_is_only_read_through_limit():
    js = _code_only(_read("console.js"))
    for m in re.finditer(r"\baskMax\b", js):
        tail = js[m.end() :]
        assert re.match(r"\s*(===|!==|=(?!=)|\.maxQuestion)", tail), (
            f"console.js: rule 'askMax only by ===, !==, = or .maxQuestion' broken at line {_line_of(js, m.start())}"
        )
    calls = re.findall(r"askCounterText\(([^;]*)\);", js)
    assert len(calls) == 1, "console.js: expected exactly one askCounterText( call"
    args = calls[0]
    assert args.endswith(", askLimit()"), f"console.js: second argument is not askLimit(): {args}"
    assert not re.search(r"\bfunction\s+parseAsk\b|\bparseAsk\b", js), "console.js: parseAsk is still defined or used"
    import_block = re.search(r"import\s*\{([^}]*)\}\s*from\s*\"\./snippets\.js\"", js)
    assert import_block, "console.js: no import from snippets.js"
    names = {n.strip() for n in import_block.group(1).split(",") if n.strip()}
    assert {"askParse", "askCounterText"} <= names


def test_ask_input_focus_after_connecting_and_nowhere_else():
    js = _read("console.js")
    calls = list(re.finditer(r"askInput\.focus\(([^)]*)\)", js))
    assert len(calls) == 2, f"console.js: expected two askInput.focus( calls, found {len(calls)}"
    for m in calls:
        assert re.sub(r"\s+", " ", m.group(1)).strip() == "{ preventScroll: true }", (
            f"console.js: askInput.focus without preventScroll at line {_line_of(js, m.start())}"
        )
    # One in the example click handler of renderAsk.
    _, render = _function_text(js, "function renderAsk(")
    assert len(re.findall(r"askInput\.focus\(", render)) == 1
    handler = re.search(r'addEventListener\("click", \(\) => \{(.*?)\n    \}\);', render, re.S)
    assert handler and "askInput.focus({ preventScroll: true });" in handler.group(1), (
        "console.js: renderAsk's focus call is not inside the example click handler"
    )
    # One in loadListing, after renderAsk(), guarded by !refs.askPanel.hidden.
    _, load = _function_text(js, "function loadListing(")
    assert len(re.findall(r"askInput\.focus\(", load)) == 1
    after_render = load.index("renderFlows();\n  renderAsk();")
    guard = load.index("if (!refs.askPanel.hidden) {", after_render)
    focus = load.index("refs.askInput.focus({ preventScroll: true });", guard)
    assert after_render < guard < focus
    assert re.search(
        r'\} else \{\s*const first = refs\.flows\.querySelector\("\.run"\);\s*if \(first\) \{\s*first\.focus\(\);\s*\}\s*\}',
        load[guard:],
    ), "console.js: the Ask-off branch of loadListing changed"
    # None elsewhere.
    for header in (
        "function forgetKey(",
        "function ask(",
        "function run(",
        "function showAskAnswer(",
        "function showAskError(",
    ):
        if header in js:
            _, text = _function_text(js, header)
            assert "askInput.focus(" not in text, f"console.js: askInput.focus( inside {header}"


def test_ask_output_order_answer_then_strip_then_panels():
    js = _read("console.js")
    _, show = _function_text(js, "function showAskAnswer(")
    answer = show.index('class: "ask-answer"')
    appended = show.index("refs.askOut.appendChild(answerBox);")
    chain = show.index("askChainList(")
    strip = show.index("refs.askOut.appendChild(chain.list);")
    panels = show.index("refs.askOut.appendChild(chain.panels);")
    assert answer < appended < chain < strip < panels

    _, err = _function_text(js, "function showAskError(")
    order = [
        err.index('el("p", { class: "error-code" }'),
        err.index('el("p", { class: "error-text" }, text)'),
        err.index('class: "ask-run-line"'),
        err.index("askChainList("),
        err.index("refs.askOut.appendChild(chain.list);"),
        err.index("refs.askOut.appendChild(chain.panels);"),
    ]
    assert order == sorted(order), f"console.js: showAskError output order broken: {order}"


def test_chain_markup_contract_toggle_button_and_hidden_section():
    js = _read("console.js")
    css = _read("console.css")
    assert "ask-grid" not in js and "ask-grid" not in css
    _, ask = _ask_section(js)
    assert 'el("details"' not in ask and "wire-msg" not in ask
    assert not re.search(r"<details", ask)
    _, line_item = _function_text(js, "function askLineItem(")
    button = re.search(r'el\(\s*"button",\s*\{([^}]*)\}', line_item)
    assert button, "console.js: askLineItem builds no button"
    attrs = button.group(1)
    assert 'type: "button"' in attrs and 'class: "ask-step-toggle"' in attrs
    assert '"aria-expanded": "false"' in attrs and '"aria-controls": panelId' in attrs
    section = re.search(r'el\(\s*"section",\s*\{([^}]*)\}', line_item)
    assert section and 'class: "ask-wire"' in section.group(1) and 'hidden: ""' in section.group(1)
    assert '"aria-labelledby": toggleId' in section.group(1)
    assert "panel.hidden = !open;" in line_item
    allowed = re.search(r"const ALLOWED_ATTRS = new Set\(\[(.*?)\]\)", js, re.S)
    assert allowed, "console.js: ALLOWED_ATTRS not found"
    for name in ("aria-expanded", "aria-controls", "aria-labelledby"):
        assert f'"{name}"' in allowed.group(1), f"console.js: ALLOWED_ATTRS lacks {name}"


def test_ask_css_contract():
    assert "ask-grid" not in _read("console.css")
    assert _declarations(_css_body(".ask-example")).get("display") == "block"

    hint = _declarations(_css_body(".ask-hint"))
    assert hint.get("display") == "block" and hint.get("color") == "var(--fg-dim)"
    assert not any("flex" in k or "flex" in v for k, v in hint.items())

    answer = _declarations(_css_body(".ask-answer-text"))
    size = re.fullmatch(r"([\d.]+)rem", answer.get("font-size", ""))
    assert size and float(size.group(1)) >= 1.25, "console.css: answer font below 1.25rem"
    assert answer.get("color") == "var(--fg-bright)"

    row = _declarations(_css_body(".ask-chain > .strip-stage"))
    assert row.get("display") == "flex" and row.get("align-items") == "baseline"
    assert _declarations(_css_body(".ask-chain > .strip-stage::before")).get("flex") == "none"

    toggle = _declarations(_css_body(".ask-step-toggle"))
    assert toggle.get("border") == "0" and toggle.get("padding") == "0"
    assert toggle.get("background") == "none"
    toggle_before = _css_body(".ask-step-toggle::before")
    assert "content:" in toggle_before

    wire = _declarations(_css_body(".ask-wire"))
    assert "display" not in wire, "console.css: .ask-wire declares display, so [hidden] would not hide it"
    css = _read("console.css")
    assert len(re.findall(r"\border\s*:", css)) == 1


def test_ask_block_has_no_font_below_one_rem_and_no_new_colour():
    css = _read("console.css")
    start = css.index("/* Ask panel: the first block of the stage")
    end = css.index("/* Motion */")
    block = css[start:end]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|color-mix)\s*\(", block)
    assert not re.search(r"^\s*--[\w-]+\s*:", block, re.M)
    for m in re.finditer(r"font-size\s*:\s*([\d.]+)rem", block):
        assert float(m.group(1)) >= 1
