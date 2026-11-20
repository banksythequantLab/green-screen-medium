// Green Screen Medium page script. One ES module, no framework, no build step.
// The API key lives in the module variable below and nowhere else: not in the
// address bar, not in any browser storage, not in the page text, not in a snippet.
// All text reaches the page through text nodes. No markup string is ever parsed.

import {
  bodyText,
  buildClaudeCodeCommand,
  buildCurl,
  buildMcpConfig,
  auditLine,
  retryAfterText,
  MCP_KNOWN_VERSIONS,
  buildInitialize,
  buildInitialized,
  buildToolsList,
  buildToolsCall,
  mcpRequestHeaders,
  parseMcpReply,
  findReply,
  hasTool,
  classifyToolsCall,
  formatTranscriptEntry,
  summariseRun,
  stripStages,
  jsonRpcErrorText,
  toggleAllLabel,
  fitsInFirstScreen,
  ASK_EXAMPLE_MAX,
  askExamples,
  outputClass,
  askStepToEntries,
  askChain,
  askRunLine,
  askAnswerNotice,
  buildAskBody,
  askParse,
  askCounterText,
} from "./snippets.js";

// ---- State (module scope, nothing on the window object) ----

let apiKey = null;
let keyHeld = false;
let codes = null;
let flows = [];
let running = false;
let callVia = "mcp";
let sessionId = null;
let protocolVersion = null;
let wire = null;
let wireView = null;
let runName = "";
let askMax = null;
let askExampleButtons = [];

const MCP_STEP_TIMEOUT_MS = 15000;
const FIT_LIMIT = 720;

const AUDIT_KEYS = [
  "step_index",
  "kind",
  "phase",
  "iteration",
  "signature",
  "status",
  "duration_seconds",
];
const PAGE_SIDE_KEYS = ["no_response", "unreadable_reply", "unknown_code", "ask_unavailable", "ask_reply_unreadable"];
const ALLOWED_ATTRS = new Set([
  "id", "class", "type", "for", "name", "value", "autocomplete", "inputmode",
  "maxlength", "disabled", "role", "aria-live", "aria-label", "hidden", "tabindex",
  "open", "aria-pressed", "aria-expanded", "aria-controls", "aria-labelledby",
]);

// ---- 1. Key intake from the address fragment (runs before anything else) ----

function takeKeyFromFragment() {
  const prefix = "#key=";
  const hash = window.location.hash;
  if (typeof hash !== "string" || !hash.startsWith(prefix)) {
    return false;
  }
  const raw = hash.slice(prefix.length);
  let text = raw;
  try {
    text = decodeURIComponent(raw);
  } catch (error) {
    text = raw;
  }
  if (text !== "") {
    apiKey = text;
    keyHeld = true;
  }
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return text !== "";
}

takeKeyFromFragment();

// ---- 2. The one function that reads the key ----

async function apiFetch(path, init) {
  const allowed = path === "/openapi.json" || /^\/flows\/[^/]+$/.test(path) || path === "/mcp" || path === "/ask";
  if (!allowed) {
    throw new Error("path not allowed");
  }
  const options = Object.assign({}, init);
  const headers = Object.assign({}, options.headers);
  if (apiKey !== null) {
    headers["X-API-Key"] = apiKey;
  }
  options.headers = headers;
  options.cache = "no-store";
  const response = await fetch(path, options);
  if (response.status === 401) {
    forgetKey();
  }
  return response;
}

// ---- 3. Error table ----

async function loadCodes() {
  try {
    const response = await fetch("/console/codes.json");
    if (!response.ok) {
      return null;
    }
    const table = JSON.parse(await response.text());
    if (table === null || typeof table !== "object" || Array.isArray(table)) {
      return null;
    }
    return table;
  } catch (error) {
    return null;
  }
}

function hasEntry(key) {
  return (
    codes !== null &&
    typeof key === "string" &&
    Object.prototype.hasOwnProperty.call(codes, key) &&
    codes[key] !== null &&
    typeof codes[key] === "object"
  );
}

function isServerCode(key) {
  return hasEntry(key) && !PAGE_SIDE_KEYS.includes(key);
}

// The table entry whose status equals an HTTP status, or the unknown-code entry.
function keyForStatus(status) {
  if (codes !== null) {
    for (const key of Object.keys(codes)) {
      if (isServerCode(key) && codes[key].status === status) {
        return key;
      }
    }
  }
  return "unknown_code";
}

// ---- 4. Forget the key ----

function forgetKey() {
  apiKey = null;
  keyHeld = false;
  flows = [];
  clearChildren(refs.flows);
  clearResult();
  refs.askInput.value = "";
  askMax = null;
  renderAsk();
  showKeyPanel(true);
}

// ---- 5. Listing model (pure) ----

function parseListing(doc) {
  const found = [];
  if (doc === null || typeof doc !== "object" || doc.paths === null || typeof doc.paths !== "object") {
    return found;
  }
  for (const [path, item] of Object.entries(doc.paths)) {
    const match = /^\/flows\/([^/]+)$/.exec(path);
    if (!match || !item || !item.post) {
      continue;
    }
    const operation = item.post;
    const content = operation.requestBody && operation.requestBody.content;
    const schema = content && content["application/json"] && content["application/json"].schema;
    const properties = schema && schema.properties && typeof schema.properties === "object" ? schema.properties : {};
    const requiredList = schema && Array.isArray(schema.required) ? schema.required : [];
    const inputs = [];
    for (const [name, prop] of Object.entries(properties)) {
      const p = prop && typeof prop === "object" ? prop : {};
      const input = {
        name,
        type: p.type === "integer" ? "integer" : "string",
        required: requiredList.includes(name),
        secret: p.writeOnly === true,
      };
      if (typeof p.description === "string") {
        input.description = p.description;
      }
      if (typeof p.maxLength === "number") {
        input.maxLength = p.maxLength;
      }
      inputs.push(input);
    }
    const text = typeof operation.summary === "string" ? operation.summary : "";
    const example = typeof operation["x-ask-example"] === "string" ? operation["x-ask-example"] : "";
    found.push({ name: match[1], blurb: text, inputs, example });
  }
  return found;
}

// ---- 6. DOM helpers ----

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      if (!ALLOWED_ATTRS.has(name)) {
        throw new Error("attribute not allowed");
      }
      if (value === false || value === null || value === undefined) {
        continue;
      }
      node.setAttribute(name, value === true ? "" : String(value));
    }
  }
  for (const child of children) {
    if (child === null || child === undefined) {
      continue;
    }
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function clearChildren(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

const refs = {
  layout: document.querySelector(".layout"),
  keyInput: document.getElementById("key-input"),
  keyLabel: document.querySelector('label[for="key-input"]'),
  connect: document.getElementById("connect-button"),
  forget: document.getElementById("forget-button"),
  flows: document.getElementById("flows"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  via: document.querySelector(".call-via"),
  viaMcp: document.getElementById("via-mcp"),
  viaRest: document.getElementById("via-rest"),
  askPanel: document.getElementById("ask-panel"),
  askInput: document.getElementById("ask-input"),
  askButton: document.getElementById("ask-button"),
  askCount: document.getElementById("ask-count"),
  askExamples: document.getElementById("ask-examples"),
  askOut: document.getElementById("ask-out"),
};

function setStatus(text, busy) {
  refs.status.textContent = text;
  refs.status.classList.toggle("is-busy", busy === true);
}

function clearResult() {
  wire = null;
  wireView = null;
  clearChildren(refs.result);
  refs.result.classList.remove("result-success", "result-error");
  refs.layout.classList.remove("has-result");
}

function showKeyPanel(show) {
  refs.keyInput.hidden = !show;
  refs.keyLabel.hidden = !show;
  refs.connect.hidden = !show;
  refs.forget.hidden = show;
  if (show) {
    refs.keyInput.value = "";
  }
  renderCallVia();
}

// The Call via group: shown only while a key is held, disabled while a call runs.
function renderCallVia() {
  refs.via.hidden = !keyHeld;
  refs.viaMcp.setAttribute("aria-pressed", callVia === "mcp" ? "true" : "false");
  refs.viaRest.setAttribute("aria-pressed", callVia === "rest" ? "true" : "false");
  refs.viaMcp.disabled = running;
  refs.viaRest.disabled = running;
}

function chooseVia(value) {
  if (running) {
    return;
  }
  callVia = value;
  renderCallVia();
}

function safeText(value, limit) {
  const text = typeof value === "string" ? value : String(value);
  return text.length > limit ? text.slice(0, limit) + "…" : text;
}

// ---- Rendering: flows ----

function renderFlows() {
  clearChildren(refs.flows);
  if (flows.length === 0) {
    refs.flows.appendChild(el("p", { class: "empty-note" }, "No flows are published."));
    return;
  }
  flows.forEach((flow, flowIndex) => {
    flow.fields = [];
    const fieldsBox = el("div", { class: "flow-inputs" });
    flow.inputs.forEach((input, inputIndex) => {
      const id = "in-" + flowIndex + "-" + inputIndex;
      const attrs = {
        id,
        name: input.name,
        type: input.secret ? "password" : "text",
        autocomplete: "off",
      };
      if (input.type === "integer") {
        attrs.inputmode = "numeric";
      }
      if (typeof input.maxLength === "number") {
        attrs.maxlength = input.maxLength;
      }
      const field = el("input", attrs);
      field.addEventListener("input", () => updateSnippets(flow));
      flow.fields.push(field);
      const box = el("div", { class: "field" }, el("label", { for: id }, input.name));
      if (input.secret) {
        box.appendChild(el("span", { class: "tag" }, "secret"));
      } else if (input.type === "integer") {
        box.appendChild(el("span", { class: "tag" }, "number"));
      }
      box.appendChild(field);
      if (input.description) {
        box.appendChild(el("p", { class: "field-desc" }, input.description));
      }
      fieldsBox.appendChild(box);
    });
    flow.runButton = el("button", { type: "button", class: "run" }, "Run");
    flow.runButton.disabled = running;
    flow.runButton.addEventListener("click", () => run(flow));
    const curlBox = renderSnippets(flow);
    const clientsBox = renderMcpClients(flow);
    const article = el(
      "article",
      { class: "flow" },
      el("h2", { class: "flow-name" }, flow.name),
      el("p", { class: "mcp-line" }, "This screen flow is published as an MCP tool: " + flow.name + "."),
      el("p", { class: "flow-summary" }, flow.blurb),
      fieldsBox,
      flow.runButton,
      clientsBox,
      curlBox,
    );
    refs.flows.appendChild(article);
    updateSnippets(flow);
  });
}

// ---- Rendering: snippets ----

function collectInputs(flow) {
  return flow.inputs.map((input, index) => ({
    name: input.name,
    type: input.type,
    secret: input.secret,
    required: input.required,
    value: flow.fields[index].value,
  }));
}

// One labelled, copyable text block; its <pre> is appended to flow.blocks.
function snippetBox(flow, label) {
  const pre = el("pre", { tabindex: "0" });
  const button = el("button", { type: "button", class: "quiet" }, "Copy");
  button.addEventListener("click", () => copyText(pre));
  flow.blocks.push(pre);
  return el("div", { class: "snippet" }, el("p", { class: "field-label" }, label), pre, button);
}

// Block order in flow.blocks: curl (here), then the MCP config and the Claude Code command.
function renderSnippets(flow) {
  flow.blocks = [];
  return el(
    "details",
    { class: "snippets" },
    el("summary", null, "Use this flow with curl"),
    snippetBox(flow, "curl command"),
  );
}

function renderMcpClients(flow) {
  return el(
    "section",
    { class: "mcp-clients" },
    el("h3", { class: "mcp-clients-title" }, "Any MCP client can use this same tool"),
    snippetBox(flow, "MCP client config (Kiro shape)"),
    snippetBox(flow, "Claude Code command"),
    el("p", { class: "hint" }, "Tool name: " + flow.name),
    el(
      "p",
      { class: "hint" },
      "MCP clients differ in how they name these settings. The first block is the shape Kiro reads; the second is the Claude Code command.",
    ),
  );
}

function updateSnippets(flow) {
  const origin = window.location.origin;
  flow.blocks[0].textContent = buildCurl(origin, flow.name, collectInputs(flow));
  flow.blocks[1].textContent = buildMcpConfig(origin);
  flow.blocks[2].textContent = buildClaudeCodeCommand(origin);
}

function selectText(node) {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  const range = document.createRange();
  range.selectNodeContents(node);
  selection.removeAllRanges();
  selection.addRange(range);
}

async function copyText(pre) {
  const text = pre.textContent;
  try {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      throw new Error("no clipboard");
    }
    await navigator.clipboard.writeText(text);
    setStatus("Copied.", false);
  } catch (error) {
    selectText(pre);
    setStatus("Press Ctrl+C to copy.", false);
  }
}

// ---- Rendering: result ----

function auditList(audit) {
  const list = el("ol", { class: "audit" });
  for (const entry of audit) {
    const row = {};
    const source = entry && typeof entry === "object" ? entry : {};
    for (const key of AUDIT_KEYS) {
      row[key] = source[key];
    }
    const cls = row.status === "ok" ? "audit-ok" : row.status === "skipped" ? "audit-skipped" : row.status === "failed" ? "audit-failed" : "audit-ok";
    list.appendChild(el("li", { class: cls }, auditLine(row)));
  }
  return list;
}

// The three-stage strip: the first child of the result region, built only when an audit list exists.
function appendStrip(via, name, audit) {
  if (!Array.isArray(audit)) {
    return;
  }
  const stages = stripStages(via === "mcp" ? "mcp" : "rest", name, summariseRun(audit));
  const list = el("ol", { class: "strip" });
  for (const text of stages) {
    list.appendChild(el("li", { class: "strip-stage" }, text));
  }
  refs.result.appendChild(list);
}

function allWireOpen() {
  return wireView !== null && wireView.all.length > 0 && wireView.all.every((node) => node.open === true);
}

function refreshWireToggle() {
  if (wireView !== null) {
    wireView.button.textContent = toggleAllLabel(allWireOpen());
  }
}

function setAllWire(open) {
  if (wireView === null) {
    return;
  }
  for (const node of wireView.all) {
    node.open = open;
  }
  refreshWireToggle();
}

// The wire transcript: every entry is built closed. settleTranscript may open two of them later.
function appendWire() {
  if (wire === null) {
    return;
  }
  const button = el("button", { type: "button", class: "quiet wire-toggle" }, toggleAllLabel(false));
  const list = el("ol", { class: "wire-list" });
  const view = { list, button, all: [], calls: [] };
  wireView = view;
  button.addEventListener("click", () => setAllWire(!allWireOpen()));
  for (const entry of wire) {
    const body = el("pre", { class: "wire-json", tabindex: "0" }, entry.text);
    const node = el(
      "details",
      { class: "wire-msg " + (entry.direction === "sent" ? "wire-sent" : "wire-received") },
      el("summary", null, entry.line),
      body,
    );
    node.addEventListener("toggle", refreshWireToggle);
    view.all.push(node);
    if (entry.call) {
      view.calls.push(node);
    }
    list.appendChild(el("li", { class: "wire-entry" }, node));
  }
  refs.result.appendChild(
    el(
      "section",
      { class: "wire" },
      el("div", { class: "wire-head" }, el("h3", { class: "wire-title" }, "MCP wire transcript"), button),
      el(
        "p",
        { class: "wire-note" },
        "JSON-RPC messages this page sent to /mcp and received from it. Headers and the API key are not shown. Secret inputs show as <SECRET>. Numbers in received messages are shown as JavaScript prints them.",
      ),
      list,
    ),
  );
}

// Decides once per run whether the two tool-call entries start open. Any doubt leaves them closed.
function settleTranscript() {
  const view = wireView;
  if (view === null || view.calls.length < 2 || !document.documentElement.contains(view.list)) {
    return;
  }
  const close = () => {
    for (const node of view.calls) {
      node.open = false;
    }
  };
  try {
    for (const node of view.calls) {
      node.open = true;
    }
    if (typeof view.list.getBoundingClientRect !== "function") {
      throw new Error("no layout");
    }
    const listRect = view.list.getBoundingClientRect();
    const rootRect = document.documentElement.getBoundingClientRect();
    const bottom = listRect.bottom - rootRect.top;
    const inner = window.innerHeight;
    const limit = Number.isFinite(inner) && inner > 0 && inner < FIT_LIMIT ? inner : FIT_LIMIT;
    if (!(listRect.height > 0 && fitsInFirstScreen(bottom, limit))) {
      close();
    }
  } catch (error) {
    close();
  }
  refreshWireToggle();
}

function showSuccess(body, elapsedSeconds, via) {
  const kept = wire;
  clearResult();
  wire = kept;
  appendStrip(via, runName, body.audit);
  const outputs = el("dl", { class: "outputs" });
  for (const [name, value] of Object.entries(body.outputs)) {
    const text = value !== null && typeof value === "object" ? JSON.stringify(value) : String(value);
    outputs.appendChild(el("div", null, el("dt", null, name), el("dd", { class: outputClass(text) }, text)));
  }
  refs.result.classList.add("result-success");
  refs.result.appendChild(el("h2", { class: "result-title" }, "Flow " + safeText(body.flow, 80) + " answered"));
  refs.result.appendChild(outputs);
  refs.result.appendChild(
    el("p", { class: "elapsed" }, "Elapsed (as seen by this browser): " + elapsedSeconds.toFixed(1) + " s"),
  );
  appendWire();
  if (Array.isArray(body.audit)) {
    refs.result.appendChild(el("h3", { class: "audit-title" }, "Audit trail"));
    refs.result.appendChild(auditList(body.audit));
  }
  finishResult();
}

// Show one table entry. `extra` holds optional details: status, retryAfter, error body, retry callback.
function showError(key, extra) {
  const kept = wire;
  clearResult();
  wire = kept;
  const info = extra || {};
  let auditRows = null;
  if (hasEntry(key) && info.error && typeof info.error === "object" && Array.isArray(info.error.audit)) {
    auditRows = info.error.audit;
  }
  appendStrip(info.via, runName, auditRows);
  refs.result.classList.add("result-error");
  refs.result.appendChild(el("h2", { class: "result-title" }, "The call did not complete"));
  if (!hasEntry(key)) {
    refs.result.appendChild(el("p", { class: "error-text" }, "Could not load the error table."));
    if (typeof info.status === "number") {
      refs.result.appendChild(el("p", { class: "error-detail" }, "HTTP status: " + info.status));
    }
  } else {
    const entry = codes[key];
    refs.result.appendChild(el("p", { class: "error-code" }, key));
    refs.result.appendChild(el("p", { class: "error-text" }, String(entry.text)));
    if (typeof info.status === "number") {
      refs.result.appendChild(el("p", { class: "error-detail" }, "HTTP status: " + info.status));
    }
    if (typeof info.detail === "string") {
      refs.result.appendChild(el("p", { class: "error-detail" }, info.detail));
    }
    if (info.reportedByTool === true) {
      refs.result.appendChild(el("p", { class: "error-detail" }, "Reported by the MCP tool as an error result."));
    }
    const retryText = retryAfterText(info.retryAfter);
    if (retryText !== null) {
      refs.result.appendChild(el("p", { class: "error-detail" }, retryText));
    }
    const error = info.error;
    if (error && typeof error === "object") {
      if (error.step_index !== undefined && error.step_index !== null) {
        refs.result.appendChild(el("p", { class: "error-detail" }, "Step: " + safeText(error.step_index, 10)));
      }
      if (typeof error.kind === "string") {
        refs.result.appendChild(el("p", { class: "error-detail" }, "Kind: " + safeText(error.kind, 40)));
      }
      if (Array.isArray(error.expected) && error.expected.length > 0) {
        const names = error.expected.map((item) => safeText(item, 80)).join(", ");
        refs.result.appendChild(el("p", { class: "error-detail" }, "Expected screens: " + names));
      } else if (typeof error.expected === "string" && error.expected !== "") {
        refs.result.appendChild(el("p", { class: "error-detail" }, "Expected screen: " + safeText(error.expected, 80)));
      }
      if (entry.show_message === true && typeof error.message === "string") {
        refs.result.appendChild(el("p", { class: "error-detail" }, "Message: " + safeText(error.message, 300)));
      }
    }
  }
  appendWire();
  if (auditRows !== null) {
    refs.result.appendChild(el("h3", { class: "audit-title" }, "Audit trail"));
    refs.result.appendChild(auditList(auditRows));
  }
  if (typeof info.retry === "function") {
    const retry = el("button", { type: "button", class: "quiet" }, "Retry");
    retry.addEventListener("click", info.retry);
    refs.result.appendChild(retry);
  }
  if (info.final !== false) {
    finishResult();
  }
}

function finishResult() {
  refs.layout.classList.add("has-result");
  settleTranscript();
  refs.result.focus({ preventScroll: true });
}

// ---- Listing ----

async function loadListing() {
  setStatus("Loading the flow list…", true);
  clearResult();
  askMax = null;
  renderAsk();
  let response;
  try {
    response = await apiFetch("/openapi.json");
  } catch (error) {
    setStatus("", false);
    showError("no_response", { final: false, retry: loadListing });
    return;
  }
  if (response.status === 401) {
    setStatus(hasEntry(keyForStatus(401)) ? String(codes[keyForStatus(401)].text) : "Could not load the error table.", false);
    refs.keyInput.focus();
    return;
  }
  if (!response.ok) {
    setStatus("", false);
    showError(keyForStatus(response.status), { status: response.status, final: false, retry: loadListing });
    return;
  }
  let doc = null;
  try {
    doc = JSON.parse(await response.text());
  } catch (error) {
    setStatus("", false);
    showError("unreadable_reply", { status: response.status, final: false, retry: loadListing });
    return;
  }
  flows = parseListing(doc);
  askMax = askParse(doc);
  setStatus("", false);
  renderFlows();
  renderAsk();
  if (!refs.askPanel.hidden) {
    refs.askInput.focus({ preventScroll: true });
  } else {
    const first = refs.flows.querySelector(".run");
    if (first) {
      first.focus();
    }
  }
}

// ---- Run ----

function setRunning(value) {
  running = value;
  for (const flow of flows) {
    if (flow.runButton) {
      flow.runButton.disabled = value;
    }
  }
  refs.askButton.disabled = value;
  for (const button of askExampleButtons) {
    button.disabled = value;
  }
  renderCallVia();
}

async function run(flow) {
  if (running) {
    return;
  }
  clearAskOut();
  setRunning(true);
  setStatus("Calling the mainframe…", true);
  runName = flow.name;
  try {
    if (callVia === "mcp") {
      await runMcp(flow);
    } else {
      wire = null;
      await runRest(flow);
    }
  } finally {
    flow.inputs.forEach((input, index) => {
      if (input.secret) {
        flow.fields[index].value = "";
      }
    });
    updateSnippets(flow);
    setRunning(false);
    if (refs.status.textContent === "Calling the mainframe…") {
      setStatus("", false);
    }
  }
}

async function runRest(flow) {
  {
    const payload = bodyText(collectInputs(flow), false);
    const started = performance.now();
    let response;
    try {
      response = await apiFetch("/flows/" + encodeURIComponent(flow.name), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
      });
    } catch (error) {
      showError("no_response", {});
      return;
    }
    const elapsed = (performance.now() - started) / 1000;
    if (response.status === 401) {
      const key = keyForStatus(401);
      setStatus(hasEntry(key) ? String(codes[key].text) : "Could not load the error table.", false);
      refs.keyInput.focus();
      return;
    }
    let body = null;
    try {
      body = JSON.parse(await response.text());
    } catch (error) {
      body = null;
    }
    const isObject = body !== null && typeof body === "object" && !Array.isArray(body);
    if (
      response.ok &&
      isObject &&
      typeof body.flow === "string" &&
      body.outputs !== null &&
      typeof body.outputs === "object" &&
      !Array.isArray(body.outputs)
    ) {
      showSuccess(body, elapsed);
      return;
    }
    const error = isObject && body.error && typeof body.error === "object" ? body.error : null;
    if (!response.ok && error && typeof error.code === "string") {
      const key = isServerCode(error.code) ? error.code : "unknown_code";
      showError(key, {
        status: response.status,
        retryAfter: response.status === 429 ? response.headers.get("Retry-After") : null,
        error: key === "unknown_code" ? null : error,
      });
      return;
    }
    showError("unreadable_reply", { status: response.status });
  }
}

// ---- Run through the MCP endpoint ----

function isPlain(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function record(entry) {
  if (wire !== null) {
    wire.push(entry);
  }
}

// The method of a message this page built, read back from its own text. Never shown on its own.
function methodOf(wireText) {
  try {
    const parsed = JSON.parse(wireText);
    return isPlain(parsed) && typeof parsed.method === "string" ? parsed.method : "?";
  } catch (error) {
    return "?";
  }
}

// One POST to the MCP endpoint. wireText goes on the wire; shownText goes into the transcript.
// expectId is the id of the reply to look for (null for the notification).
async function post(wireText, shownText, expectId, timeoutMs, isCall) {
  const method = methodOf(wireText);
  const sent = formatTranscriptEntry({ direction: "sent", method, text: shownText });
  record({ direction: "sent", line: sent.line, text: sent.text, call: isCall });
  const controller = new AbortController();
  const timer = timeoutMs === null ? null : setTimeout(() => controller.abort(), timeoutMs);
  let response;
  let text;
  let started = 0;
  let arrived = 0;
  try {
    started = performance.now();
    response = await apiFetch("/mcp", {
      method: "POST",
      headers: mcpRequestHeaders(protocolVersion, sessionId),
      body: wireText,
      signal: controller.signal,
    });
    arrived = performance.now();
    if (response.status === 401) {
      return { kind: "auth-rejected" };
    }
    text = await response.text();
  } catch (error) {
    const none = formatTranscriptEntry({ direction: "received", method, status: null, text: "", message: null });
    record({ direction: "received", line: none.line, text: none.text, call: isCall });
    return { kind: "none" };
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
  }
  const reply = parseMcpReply(response.headers.get("Content-Type"), text);
  const message = expectId === null ? null : findReply(reply.messages, expectId);
  const shown = reply.messages.length > 0 ? reply.messages : [null];
  shown.forEach((one, index) => {
    const entry = formatTranscriptEntry({ direction: "received", method, status: response.status, text, message: one });
    record({ direction: "received", line: entry.line, text: entry.text, call: isCall && index === 0 });
  });
  return { kind: "reply", status: response.status, response, reply, message, elapsed: (arrived - started) / 1000 };
}

// The fixed-text line for a JSON-RPC error object found in a reply, or null.
function rpcDetail(result) {
  for (const one of result.reply.messages) {
    if (isPlain(one) && isPlain(one.error) && typeof one.error.code === "number") {
      const shown = Number.isSafeInteger(one.error.code) ? String(one.error.code) : "?";
      return "MCP error " + shown + ": " + jsonRpcErrorText(one.error.code);
    }
  }
  return null;
}

// Shows the failure for a step that did not pass and returns "again" (repeat once) or "stopped".
// Returns null when the step passed. `valid` checks the matched message of steps 1 and 3.
function mcpFailure(step, result, repeated, valid) {
  if (result.kind === "none") {
    showError("no_response", { via: "mcp" });
    return "stopped";
  }
  if (result.kind === "auth-rejected") {
    const key = keyForStatus(401);
    setStatus(hasEntry(key) ? String(codes[key].text) : "Could not load the error table.", false);
    refs.keyInput.focus();
    return "stopped";
  }
  const status = result.status;
  const statusGood = step === 2 ? status >= 200 && status < 300 : status === 200;
  const bodyGood = result.reply.problem === null && (step === 2 || result.message !== null);
  if (statusGood && bodyGood && (valid === null || valid(result.message))) {
    return null;
  }
  if (status === 404 && sessionId !== null && !repeated) {
    return "again";
  }
  if (status < 200 || status >= 300) {
    for (const one of result.reply.messages) {
      if (isPlain(one) && isPlain(one.error) && typeof one.error.code === "string" && isServerCode(one.error.code)) {
        showError(one.error.code, { status, via: "mcp" });
        return "stopped";
      }
    }
  }
  showError("unreadable_reply", { status, detail: rpcDetail(result), via: "mcp" });
  return "stopped";
}

function initializeOk(message) {
  return (
    isPlain(message.result) &&
    typeof message.result.protocolVersion === "string" &&
    MCP_KNOWN_VERSIONS.includes(message.result.protocolVersion)
  );
}

function toolListOk(message) {
  return isPlain(message.result) && Array.isArray(message.result.tools);
}

// One pass through the four requests. Returns true only when the whole pass should be repeated.
async function mcpAttempt(flow, inputs, repeated) {
  const first = await post(buildInitialize(1), buildInitialize(1), 1, MCP_STEP_TIMEOUT_MS, false);
  let outcome = mcpFailure(1, first, repeated, initializeOk);
  if (outcome !== null) {
    return outcome === "again";
  }
  protocolVersion = first.message.result.protocolVersion;
  const heldId = first.response.headers.get("Mcp-Session-Id");
  if (typeof heldId === "string" && /^[\x21-\x7E]+$/.test(heldId)) {
    sessionId = heldId;
  }
  const second = await post(buildInitialized(), buildInitialized(), null, MCP_STEP_TIMEOUT_MS, false);
  outcome = mcpFailure(2, second, repeated, null);
  if (outcome !== null) {
    return outcome === "again";
  }
  const third = await post(buildToolsList(2), buildToolsList(2), 2, MCP_STEP_TIMEOUT_MS, false);
  outcome = mcpFailure(3, third, repeated, toolListOk);
  if (outcome !== null) {
    return outcome === "again";
  }
  if (!hasTool(third.message, flow.name)) {
    showError(keyForStatus(404), { via: "mcp" });
    return false;
  }
  const call = await post(
    buildToolsCall(3, flow.name, inputs, false),
    buildToolsCall(3, flow.name, inputs, true),
    3,
    null,
    true,
  );
  outcome = mcpFailure(4, call, repeated, null);
  if (outcome !== null) {
    return outcome === "again";
  }
  const verdict = classifyToolsCall(call.message);
  if (verdict.kind === "success") {
    showSuccess(verdict.body, call.elapsed, "mcp");
  } else if (verdict.kind === "tool_error") {
    const key = isServerCode(verdict.code) ? verdict.code : "unknown_code";
    showError(key, {
      error: key === "unknown_code" ? null : verdict.error,
      reportedByTool: true,
      via: "mcp",
    });
  } else {
    showError("unreadable_reply", { status: call.status, detail: rpcDetail(call), via: "mcp" });
  }
  return false;
}

async function runMcp(flow) {
  wire = [];
  sessionId = null;
  protocolVersion = null;
  const inputs = collectInputs(flow);
  let repeated = false;
  while (await mcpAttempt(flow, inputs, repeated)) {
    repeated = true;
    sessionId = null;
    protocolVersion = null;
  }
}

// ---- Ask ----

// The question limit, or null when the listing offers no usable one.
function askLimit() {
  return askMax === null ? null : askMax.maxQuestion;
}

function updateAskCount() {
  refs.askCount.textContent = askCounterText(refs.askInput.value.length, askLimit());
}

function clearAskOut() {
  clearChildren(refs.askOut);
}

// Shows or hides the Ask panel from the parsed listing; the layout class follows the panel.
function renderAsk() {
  const show = keyHeld && askMax !== null;
  refs.askPanel.hidden = !show;
  refs.layout.classList.toggle("has-ask", show);
  clearChildren(refs.askExamples);
  askExampleButtons = [];
  if (!show) {
    clearAskOut();
    refs.askCount.textContent = "";
    return;
  }
  refs.askInput.maxLength = askMax.maxQuestion;
  for (const item of askExamples(flows, ASK_EXAMPLE_MAX, askMax.maxQuestion)) {
    const button = el("button", { type: "button", class: "quiet" }, item.text);
    button.disabled = running;
    button.addEventListener("click", () => {
      refs.askInput.value = item.text;
      updateAskCount();
      refs.askInput.focus({ preventScroll: true });
    });
    askExampleButtons.push(button);
    const row = el("div", { class: "ask-example" }, button);
    if (item.hint !== "") {
      row.appendChild(el("span", { class: "ask-hint" }, item.hint));
    }
    refs.askExamples.appendChild(row);
  }
  refs.askButton.disabled = running;
  updateAskCount();
}

// One Chain line: { item, panel }. A tool step that went through the MCP tool gets a toggle button
// in the strip and its wire panel (hidden) for the container below the strip.
function askLineItem(line, trace) {
  const step = line.step !== null && Array.isArray(trace.steps) ? trace.steps[line.step] : null;
  const entries = step ? askStepToEntries(step) : null;
  if (entries === null) {
    return { item: el("li", { class: "strip-stage" }, line.text), panel: null };
  }
  const sent = formatTranscriptEntry(entries.sent);
  const received = formatTranscriptEntry(entries.received);
  const toggleId = "ask-toggle-" + line.step;
  const panelId = "ask-wire-" + line.step;
  const button = el(
    "button",
    { type: "button", class: "ask-step-toggle", id: toggleId, "aria-expanded": "false", "aria-controls": panelId },
    line.text,
  );
  const panel = el(
    "section",
    { class: "ask-wire", id: panelId, "aria-labelledby": toggleId, hidden: "" },
    el("pre", { class: "wire-json", tabindex: "0" }, sent.text),
    el("pre", { class: "wire-json", tabindex: "0" }, received.text),
  );
  button.addEventListener("click", () => {
    const open = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
  });
  return { item: el("li", { class: "strip-stage ask-has-wire" }, button), panel };
}

// Returns { list, panels }; panels is null when no step has a wire panel.
function askChainList(question, trace, answer, stopped) {
  const list = el("ol", { class: "strip ask-chain" });
  const panelNodes = [];
  for (const line of askChain(question, trace, answer)) {
    const built = askLineItem(line, trace);
    list.appendChild(built.item);
    if (built.panel !== null) {
      panelNodes.push(built.panel);
    }
  }
  if (stopped !== null) {
    list.appendChild(el("li", { class: "strip-stage" }, "Stopped: " + stopped));
  }
  const panels = panelNodes.length > 0 ? el("div", { class: "ask-wire-panels" }, ...panelNodes) : null;
  return { list, panels };
}
function askEntryText(key) {
  const text = String(codes[key].text);
  return askMax === null ? text : text.replace(/\bN\b/g, String(askMax.maxQuestion));
}

function showAskError(question, key, info) {
  clearAskOut();
  if (!hasEntry(key)) {
    refs.askOut.appendChild(el("p", { class: "error-text" }, "Could not load the error table."));
  } else {
    const text = askEntryText(key);
    refs.askOut.appendChild(el("p", { class: "error-code" }, key));
    refs.askOut.appendChild(el("p", { class: "error-text" }, text));
    if (typeof info.status === "number") {
      refs.askOut.appendChild(el("p", { class: "error-detail" }, "HTTP status: " + info.status));
    }
    const retryText = retryAfterText(info.retryAfter);
    if (retryText !== null) {
      refs.askOut.appendChild(el("p", { class: "error-detail" }, retryText));
    }
    if (isPlain(info.trace) && Array.isArray(info.trace.steps)) {
      const runLine = askRunLine(info.trace);
      if (runLine !== "") {
        refs.askOut.appendChild(el("p", { class: "ask-run-line" }, runLine));
      }
      const chain = askChainList(question, info.trace, "", text);
      refs.askOut.appendChild(chain.list);
      if (chain.panels !== null) {
        refs.askOut.appendChild(chain.panels);
      }
    }
  }
  refs.askOut.focus({ preventScroll: true });
}

function showAskAnswer(question, body) {
  clearAskOut();
  const answerBox = el("div", { class: "ask-answer" }, el("p", { class: "ask-answer-text" }, body.answer));
  const notice = askAnswerNotice(body.truncated);
  if (notice !== "") {
    answerBox.appendChild(el("p", { class: "ask-notice" }, notice));
  }
  const runLine = askRunLine(body.trace);
  if (runLine !== "") {
    answerBox.appendChild(el("p", { class: "ask-run-line" }, runLine));
  }
  refs.askOut.appendChild(answerBox);
  const chain = askChainList(question, body.trace, body.answer, null);
  refs.askOut.appendChild(chain.list);
  if (chain.panels !== null) {
    refs.askOut.appendChild(chain.panels);
  }
  refs.askOut.focus({ preventScroll: true });
}

function renderAskReply(question, status, retryAfter, body) {
  const plain = isPlain(body);
  if (status === 404 || status === 405) {
    showAskError(question, "ask_unavailable", { status });
  } else if (
    status === 200 &&
    plain &&
    typeof body.answer === "string" &&
    typeof body.truncated === "boolean" &&
    isPlain(body.trace) &&
    Array.isArray(body.trace.steps)
  ) {
    showAskAnswer(question, body);
  } else if (plain && isPlain(body.error) && typeof body.error.code === "string") {
    const key = isServerCode(body.error.code) ? body.error.code : "unknown_code";
    showAskError(question, key, {
      status,
      retryAfter: status === 429 ? retryAfter : null,
      trace: key === "unknown_code" ? null : body.error.trace,
    });
  } else {
    showAskError(question, "ask_reply_unreadable", { status });
  }
}

async function ask() {
  if (running) {
    return;
  }
  const question = refs.askInput.value.trim();
  if (question === "") {
    setStatus("Type a question first.", false);
    return;
  }
  clearResult();
  clearAskOut();
  setRunning(true);
  setStatus("Asking the mainframe…", true);
  try {
    let response;
    let body = null;
    try {
      response = await apiFetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: buildAskBody(question),
      });
      if (response.status === 401) {
        const key = keyForStatus(401);
        setStatus(hasEntry(key) ? String(codes[key].text) : "Could not load the error table.", false);
        refs.keyInput.focus();
        return;
      }
      const text = await response.text();
      try {
        body = JSON.parse(text);
      } catch (error) {
        body = null;
      }
    } catch (error) {
      showAskError(question, "no_response", {});
      return;
    }
    renderAskReply(question, response.status, response.headers.get("Retry-After"), body);
  } finally {
    setRunning(false);
    if (refs.status.textContent === "Asking the mainframe…") {
      setStatus("", false);
    }
  }
}

// ---- Events and start ----
function connect() {
  const typed = refs.keyInput.value;
  refs.keyInput.value = "";
  if (typed === "") {
    setStatus("Enter the API key.", false);
    return;
  }
  apiKey = typed;
  keyHeld = true;
  showKeyPanel(false);
  loadListing();
}

// A key pasted into the address bar after load: adopt it. While a call runs the
// listing is not reloaded, so the running call is not disturbed.
function onHashChange() {
  if (!takeKeyFromFragment()) {
    return;
  }
  showKeyPanel(false);
  if (!running) {
    loadListing();
  }
}

function wireEvents() {
  refs.connect.addEventListener("click", connect);
  refs.viaMcp.addEventListener("click", () => chooseVia("mcp"));
  refs.viaRest.addEventListener("click", () => chooseVia("rest"));
  refs.keyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      connect();
    }
  });
  refs.askButton.addEventListener("click", ask);
  refs.askInput.addEventListener("input", updateAskCount);
  refs.askInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      ask();
    }
  });
  refs.forget.addEventListener("click", () => {
    forgetKey();
    setStatus("", false);
    refs.keyInput.focus();
  });
}

async function start() {
  wireEvents();
  codes = await loadCodes();
  window.addEventListener("hashchange", onHashChange);
  onHashChange();
  if (keyHeld) {
    showKeyPanel(false);
    await loadListing();
  } else {
    showKeyPanel(true);
    refs.keyInput.focus();
  }
  if (codes === null) {
    setStatus("Could not load the error table.", false);
  }
}

start();
