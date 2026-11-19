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
} from "./snippets.js";

// ---- State (module scope, nothing on the window object) ----

let apiKey = null;
let keyHeld = false;
let codes = null;
let flows = [];
let running = false;

const AUDIT_KEYS = [
  "step_index",
  "kind",
  "phase",
  "iteration",
  "signature",
  "status",
  "duration_seconds",
];
const PAGE_SIDE_KEYS = ["no_response", "unreadable_reply", "unknown_code"];
const ALLOWED_ATTRS = new Set([
  "id", "class", "type", "for", "name", "value", "autocomplete", "inputmode",
  "maxlength", "disabled", "role", "aria-live", "aria-label", "hidden", "tabindex",
]);

// ---- 1. Key intake from the address fragment (runs before anything else) ----

function takeKeyFromFragment() {
  const prefix = "#key=";
  const hash = window.location.hash;
  if (typeof hash !== "string" || !hash.startsWith(prefix)) {
    return;
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
}

takeKeyFromFragment();

// ---- 2. The one function that reads the key ----

async function apiFetch(path, init) {
  const allowed = path === "/openapi.json" || /^\/flows\/[^/]+$/.test(path);
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
    found.push({ name: match[1], blurb: text, inputs });
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
};

function setStatus(text, busy) {
  refs.status.textContent = text;
  refs.status.classList.toggle("is-busy", busy === true);
}

function clearResult() {
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
    const article = el(
      "article",
      { class: "flow" },
      el("h2", { class: "flow-name" }, flow.name),
      el("p", { class: "flow-summary" }, flow.blurb),
      fieldsBox,
      flow.runButton,
      renderSnippets(flow),
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

function renderSnippets(flow) {
  flow.blocks = [];
  const wrap = el("details", { class: "snippets" }, el("summary", null, "Use this flow from other tools"));
  const labels = ["curl command", "MCP client config (Kiro shape)", "Claude Code command"];
  labels.forEach((label) => {
    const pre = el("pre", { tabindex: "0" });
    const button = el("button", { type: "button", class: "quiet" }, "Copy");
    button.addEventListener("click", () => copyText(pre));
    flow.blocks.push(pre);
    wrap.appendChild(el("div", { class: "snippet" }, el("p", { class: "field-label" }, label), pre, button));
  });
  wrap.appendChild(el("p", { class: "hint" }, "Tool name: " + flow.name));
  wrap.appendChild(
    el(
      "p",
      { class: "hint" },
      "MCP clients differ in how they name these settings. The second block is the shape Kiro reads; the third is the Claude Code command.",
    ),
  );
  return wrap;
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

function showSuccess(body, elapsedSeconds) {
  clearResult();
  const outputs = el("dl", { class: "outputs" });
  for (const [name, value] of Object.entries(body.outputs)) {
    const text = value !== null && typeof value === "object" ? JSON.stringify(value) : String(value);
    outputs.appendChild(el("div", null, el("dt", null, name), el("dd", null, text)));
  }
  refs.result.classList.add("result-success");
  refs.result.appendChild(el("h2", { class: "result-title" }, "Flow " + safeText(body.flow, 80) + " answered"));
  refs.result.appendChild(outputs);
  refs.result.appendChild(
    el("p", { class: "elapsed" }, "Elapsed (as seen by this browser): " + elapsedSeconds.toFixed(1) + " s"),
  );
  if (Array.isArray(body.audit)) {
    refs.result.appendChild(el("h3", { class: "audit-title" }, "Audit trail"));
    refs.result.appendChild(auditList(body.audit));
  }
  finishResult();
}

// Show one table entry. `extra` holds optional details: status, retryAfter, error body, retry callback.
function showError(key, extra) {
  clearResult();
  const info = extra || {};
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
      if (Array.isArray(error.audit)) {
        refs.result.appendChild(el("h3", { class: "audit-title" }, "Audit trail"));
        refs.result.appendChild(auditList(error.audit));
      }
    }
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
  refs.result.focus({ preventScroll: true });
}

// ---- Listing ----

async function loadListing() {
  setStatus("Loading the flow list…", true);
  clearResult();
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
  setStatus("", false);
  renderFlows();
  const first = refs.flows.querySelector(".run");
  if (first) {
    first.focus();
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
}

async function run(flow) {
  if (running) {
    return;
  }
  setRunning(true);
  setStatus("Calling the mainframe…", true);
  try {
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

function wireEvents() {
  refs.connect.addEventListener("click", connect);
  refs.keyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      connect();
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
