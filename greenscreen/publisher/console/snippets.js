// Pure snippet builders for the console page. No import, no DOM, no globals.
// Each input is {name, type, secret, required, value}; value is the typed text.

export const PLACEHOLDER_KEY = "<YOUR_API_KEY>";
export const SECRET_TEXT = "<SECRET>";

const INTEGER_TEXT = /^-?(0|[1-9][0-9]*)$/;

// Wrap text in single quotes for a POSIX shell; a single quote becomes '\''.
export function shellQuote(text) {
  return "'" + String(text).split("'").join("'\\''") + "'";
}

// The JSON object text of the typed values, joined by hand so integer digits stay exact.
export function bodyText(inputs, maskSecrets) {
  const parts = [];
  for (const input of inputs) {
    const text = input.value === undefined || input.value === null ? "" : String(input.value);
    if (text === "" && !input.required) {
      continue;
    }
    let member;
    if (input.secret) {
      member = JSON.stringify(maskSecrets ? SECRET_TEXT : text);
    } else if (input.type === "integer" && INTEGER_TEXT.test(text)) {
      member = text;
    } else {
      member = JSON.stringify(text);
    }
    parts.push(JSON.stringify(String(input.name)) + ":" + member);
  }
  return "{" + parts.join(",") + "}";
}

export function buildCurl(origin, flowName, inputs) {
  const url = origin + "/flows/" + encodeURIComponent(flowName);
  return (
    "curl -sS -X POST " + shellQuote(url) +
    " -H 'Content-Type: application/json'" +
    " -H 'X-API-Key: " + PLACEHOLDER_KEY + "'" +
    " -d " + shellQuote(bodyText(inputs, true))
  );
}

export function buildMcpConfig(origin) {
  return JSON.stringify(
    {
      mcpServers: {
        greenscreen: {
          url: origin + "/mcp",
          headers: { "X-API-Key": PLACEHOLDER_KEY },
        },
      },
    },
    null,
    2,
  );
}

export function buildClaudeCodeCommand(origin) {
  return (
    "claude mcp add --transport http greenscreen " + shellQuote(origin + "/mcp") +
    " --header 'X-API-Key: " + PLACEHOLDER_KEY + "'"
  );
}

// One audit line from a row of the seven audit members. Words are joined by one space.
export function auditLine(row) {
  const source = row !== null && typeof row === "object" ? row : {};
  const whole = (value) => (Number.isSafeInteger(value) ? String(value) : "?");
  const words = [whole(source.step_index), String(source.kind).slice(0, 40)];
  if (source.signature !== null && source.signature !== undefined) {
    words.push(String(source.signature).slice(0, 80));
  }
  const status = source.status;
  words.push(status === "ok" ? "OK" : status === "skipped" ? "SKIPPED" : status === "failed" ? "FAILED" : "UNKNOWN");
  const seconds = source.duration_seconds;
  if (typeof seconds === "number" && Number.isFinite(seconds) && Number(seconds.toFixed(2)) > 0) {
    words.push(seconds.toFixed(2) + "s");
  }
  if (source.phase === "finally") {
    words.push("finally");
  }
  if (source.iteration !== null && source.iteration !== undefined) {
    words.push("pass " + whole(source.iteration));
  }
  return words.join(" ");
}

// "Retry after: 1 second" or "Retry after: N seconds"; null unless the text is 1 to 6 ASCII digits.
export function retryAfterText(value) {
  if (typeof value !== "string" || !/^[0-9]{1,6}$/.test(value)) {
    return null;
  }
  const count = Number(value);
  return "Retry after: " + count + (count === 1 ? " second" : " seconds");
}

// ---------------------------------------------------------------------------
// MCP-visible Run (task 8). Pure functions; none takes the API key, a header
// object from the network or a response. Wire text has no spaces.
// ---------------------------------------------------------------------------

export const MCP_OFFERED_VERSION = "2025-11-25";
export const MCP_KNOWN_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(target, name) {
  return Object.prototype.hasOwnProperty.call(target, name);
}

function idText(id) {
  if (!Number.isSafeInteger(id)) {
    throw new Error("a JSON-RPC id must be a safe integer");
  }
  return String(id);
}

const CLIENT_NAME = "greenscreen-console";

export function buildInitialize(id) {
  return (
    '{"jsonrpc":"2.0","id":' + idText(id) + ',"method":"initialize","params":{"protocolVersion":' +
    JSON.stringify(MCP_OFFERED_VERSION) +
    ',"capabilities":{},"clientInfo":{"name":' + JSON.stringify(CLIENT_NAME) + ',"version":"1"}}}'
  );
}

export function buildInitialized() {
  return '{"jsonrpc":"2.0","method":"notifications/initialized"}';
}

export function buildToolsList(id) {
  return '{"jsonrpc":"2.0","id":' + idText(id) + ',"method":"tools/list","params":{}}';
}

// The unmasked text is what goes on the wire; pass maskSecrets true for what the page shows.
export function buildToolsCall(id, name, inputs, maskSecrets) {
  return (
    '{"jsonrpc":"2.0","id":' + idText(id) + ',"method":"tools/call","params":{"name":' +
    JSON.stringify(String(name)) + ',"arguments":' + bodyText(inputs, maskSecrets) + "}}"
  );
}

// Header members only; the page adds the API credential itself, in one place.
export function mcpRequestHeaders(protocolVersion, sessionId) {
  const headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
  };
  if (typeof protocolVersion === "string" && protocolVersion !== "") {
    headers["MCP-Protocol-Version"] = protocolVersion;
  }
  if (typeof sessionId === "string" && /^[\x21-\x7E]+$/.test(sessionId)) {
    headers["Mcp-Session-Id"] = sessionId;
  }
  return headers;
}

function parseEventStream(text) {
  const lines = (text.charCodeAt(0) === 0xfeff ? text.slice(1) : text).split(/\r\n|\r|\n/);
  const messages = [];
  let data = [];
  let bad = false;
  const dispatch = () => {
    const joined = data.join("\n");
    data = [];
    if (joined === "") {
      return;
    }
    try {
      const parsed = JSON.parse(joined);
      if (isObject(parsed)) {
        messages.push(parsed);
      } else {
        bad = true;
      }
    } catch (error) {
      bad = true;
    }
  };
  for (const line of lines) {
    if (line === "") {
      dispatch();
      continue;
    }
    if (line.charAt(0) === ":") {
      continue;
    }
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.charAt(0) === " ") {
      value = value.slice(1);
    }
    if (field === "data") {
      data.push(value);
    }
  }
  dispatch();
  return bad ? { messages: [], problem: "bad_sse" } : { messages, problem: null };
}

// mediaType is the reply's Content-Type text or null; it only chooses the parser.
export function parseMcpReply(mediaType, text) {
  if (typeof text !== "string") {
    return { messages: [], problem: "bad_json" };
  }
  if (text.trim() === "") {
    return { messages: [], problem: null };
  }
  const type = typeof mediaType === "string" ? mediaType.split(";")[0].trim().toLowerCase() : "";
  if (type === "text/event-stream") {
    return parseEventStream(text);
  }
  if (type === "" || type === "application/json" || type.endsWith("+json")) {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      return { messages: [], problem: "bad_json" };
    }
    if (isObject(parsed)) {
      return { messages: [parsed], problem: null };
    }
    if (Array.isArray(parsed) && parsed.every(isObject)) {
      return { messages: parsed, problem: null };
    }
    return { messages: [], problem: "bad_json" };
  }
  return { messages: [], problem: "unsupported_type" };
}

export function findReply(messages, id) {
  if (!Array.isArray(messages)) {
    return null;
  }
  for (const message of messages) {
    if (isObject(message) && message.id === id && (hasOwn(message, "result") || hasOwn(message, "error"))) {
      return message;
    }
  }
  return null;
}

export function hasTool(listMessage, name) {
  if (!isObject(listMessage) || !isObject(listMessage.result) || !Array.isArray(listMessage.result.tools)) {
    return false;
  }
  return listMessage.result.tools.some((tool) => isObject(tool) && tool.name === name);
}

export function classifyToolsCall(message) {
  if (!isObject(message)) {
    return { kind: "unreadable" };
  }
  const result = message.result;
  if (isObject(result)) {
    const content = result.structuredContent;
    if (result.isError === true) {
      if (isObject(content) && isObject(content.error) && typeof content.error.code === "string") {
        return { kind: "tool_error", code: content.error.code, error: content.error };
      }
      return { kind: "unreadable" };
    }
    if (isObject(content) && typeof content.flow === "string" && isObject(content.outputs)) {
      return { kind: "success", body: content };
    }
    return { kind: "unreadable" };
  }
  if (isObject(message.error) && typeof message.error.code === "number") {
    return { kind: "rpc_error", rpcCode: message.error.code };
  }
  return { kind: "unreadable" };
}

// Re-indent JSON text with two spaces without parsing numbers. Unbalanced text is returned as it came.
export function prettyJson(text) {
  const source = String(text);
  const out = [];
  const stack = [];
  const pad = (depth) => "  ".repeat(depth);
  let i = 0;
  while (i < source.length) {
    const ch = source.charAt(i);
    if (ch === '"') {
      let j = i + 1;
      while (j < source.length && source.charAt(j) !== '"') {
        j += source.charAt(j) === "\\" ? 2 : 1;
      }
      if (j >= source.length) {
        return source;
      }
      out.push(source.slice(i, j + 1));
      i = j + 1;
    } else if (ch === "{" || ch === "[") {
      const closer = ch === "{" ? "}" : "]";
      let j = i + 1;
      while (j < source.length && /\s/.test(source.charAt(j))) {
        j += 1;
      }
      if (source.charAt(j) === closer) {
        out.push(ch + closer);
        i = j + 1;
      } else {
        stack.push(closer);
        out.push(ch + "\n" + pad(stack.length));
        i += 1;
      }
    } else if (ch === "}" || ch === "]") {
      if (stack.pop() !== ch) {
        return source;
      }
      out.push("\n" + pad(stack.length) + ch);
      i += 1;
    } else if (ch === ",") {
      out.push(",\n" + pad(stack.length));
      i += 1;
    } else if (ch === ":") {
      out.push(": ");
      i += 1;
    } else {
      if (!/\s/.test(ch)) {
        out.push(ch);
      }
      i += 1;
    }
  }
  return stack.length === 0 ? out.join("") : source;
}

// ---- Transcript_Line and the allow-list projection ----

function clean(value, limit) {
  return typeof value === "string" ? value.slice(0, limit) : "?";
}

function safeCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : "?";
}

function finish(line) {
  const cut = line.length > 100 ? line.slice(0, 97) + "..." : line;
  return cut.replace(/[^\x20-\x7E]/g, "?");
}

function knownVersion(value) {
  return typeof value === "string" && MCP_KNOWN_VERSIONS.includes(value) ? value : "?";
}

function codeText(value) {
  return typeof value === "string" && /^[a-z_]{1,40}$/.test(value) ? value : "unknown";
}

function plural(count, one, many) {
  return count === "1" ? one : many;
}

const AUDIT_SPEC = {
  step_index: true,
  kind: true,
  phase: true,
  iteration: true,
  signature: true,
  status: true,
  duration_seconds: true,
};
const TOOL_SPEC = { name: true, description: true, inputSchema: true, outputSchema: true, annotations: true };
const cutMessage = (value) => (typeof value === "string" ? value.slice(0, 300) : value);
const onlyBoolean = (value) => (typeof value === "boolean" ? value : undefined);
const RESULT_SPECS = {
  initialize: { protocolVersion: true, capabilities: true, serverInfo: { name: true, version: true } },
  list: { tools: [TOOL_SPEC] },
  call: {
    isError: onlyBoolean,
    structuredContent: {
      flow: true,
      outputs: true,
      audit: [AUDIT_SPEC],
      error: {
        code: true,
        message: cutMessage,
        step_index: true,
        kind: true,
        expected: true,
        audit: [AUDIT_SPEC],
      },
    },
  },
};

function project(value, spec, path, omitted) {
  if (spec === true) {
    return value;
  }
  if (typeof spec === "function") {
    const kept = spec(value);
    if (kept === undefined) {
      omitted.push(path);
    }
    return kept;
  }
  if (Array.isArray(spec)) {
    if (!Array.isArray(value)) {
      omitted.push(path);
      return undefined;
    }
    return value.map((item) => project(item, spec[0], path + "[]", omitted));
  }
  if (!isObject(value)) {
    omitted.push(path);
    return undefined;
  }
  const kept = {};
  for (const member of Object.keys(value)) {
    const name = path === "" ? member : path + "." + member;
    if (hasOwn(spec, member)) {
      const inner = project(value[member], spec[member], name, omitted);
      if (inner !== undefined) {
        kept[member] = inner;
      }
    } else {
      omitted.push(name);
    }
  }
  return kept;
}

function limitNames(names) {
  const seen = [];
  for (const name of names) {
    const shown = name.slice(0, 60);
    if (!seen.includes(shown)) {
      seen.push(shown);
    }
  }
  return seen.length > 12 ? seen.slice(0, 12).concat(["\u2026"]) : seen;
}

// Returns { shown, names } for a received message of the given kind.
function projectMessage(message, kind) {
  const omitted = [];
  const shown = {};
  for (const member of Object.keys(message)) {
    if (member === "jsonrpc" || member === "id") {
      shown[member] = message[member];
    } else if (member === "method" && kind === "other") {
      shown[member] = message[member];
    } else if (member === "result" && hasOwn(RESULT_SPECS, kind)) {
      const inner = project(message.result, RESULT_SPECS[kind], "", omitted);
      if (inner !== undefined) {
        shown.result = inner;
      } else {
        omitted.push("result");
      }
    } else if (member === "error" && kind === "rpc") {
      const code = isObject(message.error) ? message.error.code : undefined;
      shown.error = { code: Number.isSafeInteger(code) ? code : "?", text: jsonRpcErrorText(code) };
      if (isObject(message.error)) {
        for (const inner of Object.keys(message.error)) {
          if (inner !== "code") {
            omitted.push("error." + inner);
          }
        }
      }
    } else {
      omitted.push(member);
    }
  }
  return { shown, names: limitNames(omitted) };
}

function receivedLine(message, entry) {
  const status = entry.status;
  const method = typeof entry.method === "string" ? entry.method : "?";
  const unrecognised = () => {
    const own = typeof message.method === "string" ? message.method : method;
    return { kind: "other", line: "received " + clean(own, 40) + ": unrecognised message" };
  };
  if (isObject(message.error)) {
    const hostCode = message.error.code;
    if (hasOwn(message, "jsonrpc") || typeof hostCode === "number") {
      const code = Number.isSafeInteger(hostCode) ? String(hostCode) : "?";
      const tail = status === 200 ? "" : ", HTTP " + safeCount(status);
      return { kind: "rpc", line: "received error: JSON-RPC " + code + tail };
    }
    if (typeof hostCode === "string") {
      return { kind: "other", line: "received error: " + codeText(hostCode) + ", HTTP " + safeCount(status) };
    }
    return unrecognised();
  }
  const result = message.result;
  if (!isObject(result)) {
    return unrecognised();
  }
  if (method === "initialize") {
    const info = result.serverInfo;
    const name = isObject(info) && typeof info.name === "string" ? clean(info.name, 40) : "unknown server";
    return {
      kind: "initialize",
      line: "received initialize: " + name + ", protocol " + knownVersion(result.protocolVersion),
    };
  }
  if (method === "tools/list" && Array.isArray(result.tools)) {
    const count = safeCount(result.tools.length);
    let line = "received tools/list: " + count + plural(count, " tool", " tools");
    if (result.tools.length > 0) {
      const names = result.tools.slice(0, 3).map((tool) => clean(isObject(tool) ? tool.name : undefined, 40));
      line += ", " + names.join(", ");
      if (result.tools.length > 3) {
        line += ", +" + safeCount(result.tools.length - 3) + " more";
      }
    }
    return { kind: "list", line };
  }
  if (method === "tools/call") {
    const outcome = classifyToolsCall(message);
    if (outcome.kind === "tool_error") {
      return { kind: "call", line: "received error: " + codeText(outcome.code) };
    }
    if (outcome.kind === "success") {
      const outputs = safeCount(Object.keys(outcome.body.outputs).length);
      const audit = safeCount(Array.isArray(outcome.body.audit) ? outcome.body.audit.length : 0);
      return {
        kind: "call",
        line:
          "received result: " + outputs + plural(outputs, " output", " outputs") + ", " + audit +
          plural(audit, " audit entry", " audit entries"),
      };
    }
  }
  return unrecognised();
}

function sentLine(entry) {
  let message = isObject(entry.message) ? entry.message : null;
  if (message === null && typeof entry.text === "string") {
    try {
      const parsed = JSON.parse(entry.text);
      message = isObject(parsed) ? parsed : null;
    } catch (error) {
      message = null;
    }
  }
  const method = typeof entry.method === "string" ? entry.method : message !== null && typeof message.method === "string" ? message.method : "?";
  const params = message !== null && isObject(message.params) ? message.params : {};
  if (method === "initialize") {
    return "sent initialize: protocol " + knownVersion(params.protocolVersion);
  }
  if (method === "tools/call") {
    return "sent tools/call: " + clean(params.name, 40);
  }
  return "sent " + clean(method, 40);
}

// entry: { direction, method, status, text, message }. Returns { line, text, omitted }.
export function formatTranscriptEntry(entry) {
  const source = isObject(entry) ? entry : {};
  if (source.direction === "sent") {
    return {
      line: finish(sentLine(source)),
      text: prettyJson(typeof source.text === "string" ? source.text : ""),
      omitted: [],
    };
  }
  const message = isObject(source.message) ? source.message : null;
  if (message === null) {
    const empty = typeof source.text !== "string" || source.text.trim() === "";
    if (source.status === 202 && empty) {
      return { line: "received notifications/initialized: HTTP 202, no body", text: "(no body)", omitted: [] };
    }
    const method = typeof source.method === "string" ? source.method : "?";
    return {
      line: finish("received " + clean(method, 40) + ": nothing readable, HTTP " + safeCount(source.status)),
      text: "(nothing readable)",
      omitted: [],
    };
  }
  const described = receivedLine(message, source);
  const { shown, names } = projectMessage(message, described.kind);
  let text = JSON.stringify(shown, null, 2);
  if (names.length > 0) {
    text += "\n\nLeft out by this page: " + names.join(", ");
  }
  return { line: finish(described.line), text, omitted: names };
}

export function toggleAllLabel(allOpen) {
  return allOpen === true ? "Collapse all" : "Expand all";
}

export function fitsInFirstScreen(bottom, limit) {
  return (
    typeof bottom === "number" && typeof limit === "number" &&
    Number.isFinite(bottom) && Number.isFinite(limit) &&
    bottom > 0 && limit > 0 && bottom <= limit
  );
}

export function summariseRun(audit) {
  if (!Array.isArray(audit)) {
    return { steps: 0, screens: 0 };
  }
  let steps = 0;
  const screens = new Set();
  for (const entry of audit) {
    if (isObject(entry) && entry.status !== "skipped") {
      steps += 1;
      if (typeof entry.signature === "string" && entry.signature !== "") {
        screens.add(entry.signature);
      }
    }
  }
  return { steps, screens: screens.size };
}

export function stripStages(via, toolName, counts) {
  const name = clean(toolName, 80);
  const source = isObject(counts) ? counts : {};
  const steps = safeCount(source.steps);
  const screens = safeCount(source.screens);
  const third =
    "3270 screens: " + steps + plural(steps, " step", " steps") + " on " + screens +
    " distinct" + plural(screens, " screen", " screens");
  return via === "mcp"
    ? ["MCP client (this page)", "MCP tool " + name, third]
    : ["REST client (this page)", "POST /flows/" + name, third];
}

export function jsonRpcErrorText(code) {
  switch (code) {
    case -32700:
      return "Parse error";
    case -32600:
      return "Invalid request";
    case -32601:
      return "Method not found";
    case -32602:
      return "Invalid params";
    case -32603:
      return "Internal error";
    default:
      return "Unknown error code";
  }
}

// ---------------------------------------------------------------------------
// Ask (task 4.2). Pure functions; none takes the API credential or a response.
// ---------------------------------------------------------------------------

export const ASK_REFUSAL = "I can only answer questions about this mainframe, using its tools, and I cannot answer that.";

const ASK_NAME = /^[a-zA-Z0-9_-]{1,64}$/;

export function buildAskBody(question) {
  return '{"question":' + JSON.stringify(String(question)) + "}";
}

export const ASK_EXAMPLE_MAX = 12;
const EXAMPLE_TEXT = /^[\x20-\x7E]+$/;

// First sentence of the text, or a whole-word cut with "...", or "". Never more than 100 characters.
export function hintText(source) {
  const words = typeof source === "string" ? source : "";
  const text = words.replace(/[^\x20-\x7E]/g, " ").replace(/ +/g, " ").trim();
  const end = /[.!?](?= |$)/.exec(text);
  const start = end === null ? text : text.slice(0, end.index + 1);
  if (start.length <= 100) {
    return start;
  }
  const cut = start.lastIndexOf(" ", 97);
  if (cut <= 0) {
    return "";
  }
  const kept = start.slice(0, cut).replace(/[ .!?,;:]+$/, "");
  return kept === "" ? "" : kept + "...";
}

// flows: listing items {name, description or blurb, inputs, example}.
// Returns at most min(limit, ASK_EXAMPLE_MAX) items {text, hint}, one per Flow that carries an example.
export function askExamples(flows, limit, maxQuestion) {
  const found = [];
  const most = Number.isSafeInteger(limit) ? Math.min(Math.max(limit, 0), ASK_EXAMPLE_MAX) : 0;
  if (!Array.isArray(flows)) {
    return found;
  }
  for (const flow of flows) {
    if (found.length >= most) {
      break;
    }
    if (!isObject(flow) || typeof flow.name !== "string" || !ASK_NAME.test(flow.name)) {
      continue;
    }
    const inputs = Array.isArray(flow.inputs) ? flow.inputs : [];
    if (inputs.some((input) => !isObject(input) || input.secret === true)) {
      continue;
    }
    if (typeof flow.example !== "string" || !EXAMPLE_TEXT.test(flow.example)) {
      continue;
    }
    if (Number.isSafeInteger(maxQuestion) && flow.example.length > maxQuestion) {
      continue;
    }
    const words = typeof flow.description === "string" ? flow.description : typeof flow.blurb === "string" ? flow.blurb : "";
    found.push({ text: flow.example, hint: hintText(words) });
  }
  return found;
}

export function outputClass(text) {
  return typeof text === "string" && text.includes("\n") ? "multiline" : null;
}

function traceSteps(trace) {
  return isObject(trace) && Array.isArray(trace.steps) ? trace.steps : [];
}

function isToolStep(step) {
  return isObject(step) && step.type === "tool";
}

// For a tool step that was not rejected: {sent, received}; otherwise null.
export function askStepToEntries(step) {
  if (!isToolStep(step) || step.code === "rejected") {
    return null;
  }
  const params = { name: step.tool, arguments: isObject(step.arguments) ? step.arguments : {} };
  const sent = {
    direction: "sent",
    method: "tools/call",
    text: JSON.stringify({ jsonrpc: "2.0", id: step.id, method: "tools/call", params }),
  };
  const received = {
    direction: "received",
    method: "tools/call",
    status: 200,
    text: "",
    message: {
      jsonrpc: "2.0",
      id: step.id,
      result: { isError: step.ok !== true, structuredContent: step.result },
    },
  };
  return { sent, received };
}

// The audit rows of one tool step: the success audit, or the error audit.
function stepAudit(step) {
  const result = isObject(step) && isObject(step.result) ? step.result : {};
  if (Array.isArray(result.audit)) {
    return result.audit;
  }
  return isObject(result.error) && Array.isArray(result.error.audit) ? result.error.audit : [];
}

function countsText(audit) {
  const counts = summariseRun(audit);
  const steps = String(counts.steps);
  const screens = String(counts.screens);
  return steps + plural(steps, " step", " steps") + " on " + screens + plural(screens, " screen", " screens");
}

function askedText(question) {
  const text = String(question).replace(/[\x00-\x1f\x7f-\x9f]/g, " ").replace(/\s+/g, " ").trim();
  const points = Array.from(text);
  return "You asked: " + (points.length > 200 ? points.slice(0, 200).join("") + "\u2026" : text);
}

function toolNames(steps, turn) {
  const names = [];
  for (const step of steps) {
    if (isToolStep(step) && step.turn === turn) {
      const shown = clean(step.tool, 40);
      if (!names.includes(shown)) {
        names.push(shown);
      }
    }
  }
  return names;
}

function toolLine(step) {
  const name = clean(step.tool, 40);
  if (step.code === "rejected") {
    return "refused tool call " + safeCount(step.id) + ": " + clean(step.reason, 60);
  }
  const audit = stepAudit(step);
  if (step.ok === true) {
    return "MCP tool " + name + ": " + (audit.length > 0 ? countsText(audit) : "ok");
  }
  const failed = "failed (" + codeText(step.code) + ")";
  return "MCP tool " + name + ": " + (audit.length > 0 ? failed + ", " + countsText(audit) : failed);
}

// Returns the ordered Chain lines {text, step}; step is the index of the Trace_Step or null.
export function askChain(question, trace, answer) {
  const lines = [{ text: askedText(question), step: null }];
  const steps = traceSteps(trace);
  const refused = typeof answer === "string" && answer.trim() === ASK_REFUSAL;
  let toolSeen = false;
  steps.forEach((step, index) => {
    if (!isObject(step)) {
      return;
    }
    if (step.type === "model") {
      const turn = safeCount(step.turn);
      if (step.outcome === "tool_calls") {
        const names = toolNames(steps, step.turn);
        const shown = names.slice(0, 3).join(", ");
        const more = names.length > 3 ? " +" + (names.length - 3) + " more" : "";
        lines.push({
          text: finish("model turn " + turn + ": asked for " + (names.length === 1 ? "tool " : "tools ") + shown + more),
          step: null,
        });
      } else if (step.outcome === "answer") {
        const tail = toolSeen ? "answered" : "answered without a tool";
        lines.push({ text: finish("model turn " + turn + ": " + tail + (refused ? " (refused)" : "")), step: null });
      }
    } else if (isToolStep(step)) {
      toolSeen = true;
      lines.push({ text: finish(toolLine(step)), step: index });
    }
  });
  return lines;
}

// "N step(s) on M distinct screen(s)" over every tool step's audit, or "" when there is none.
export function askRunLine(trace) {
  const audit = [];
  for (const step of traceSteps(trace)) {
    if (isToolStep(step)) {
      audit.push(...stepAudit(step));
    }
  }
  if (audit.length === 0) {
    return "";
  }
  const counts = summariseRun(audit);
  const steps = String(counts.steps);
  const screens = String(counts.screens);
  return steps + plural(steps, " step", " steps") + " on " + screens + " distinct" + plural(screens, " screen", " screens");
}

export function askAnswerNotice(truncated) {
  return truncated === true ? "The answer was cut to the length limit." : "";
}

// Returns { maxQuestion } when the listing document offers POST /ask with a question limit
// that is a safe integer from 1 to 2000, else null. Never throws.
export function askParse(openapi) {
  if (!isObject(openapi) || !isObject(openapi.paths) || !isObject(openapi.paths["/ask"])) {
    return null;
  }
  const post = openapi.paths["/ask"].post;
  if (!isObject(post)) {
    return null;
  }
  const body = post.requestBody;
  const content = isObject(body) && isObject(body.content) ? body.content["application/json"] : null;
  const schema = isObject(content) ? content.schema : null;
  const props = isObject(schema) && isObject(schema.properties) ? schema.properties.question : null;
  const limit = isObject(props) ? props.maxLength : null;
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 2000) {
    return null;
  }
  return { maxQuestion: limit };
}

// "65 / 500" from two numbers; the empty string for anything else. Never throws.
export function askCounterText(used, max) {
  if (!Number.isSafeInteger(used) || used < 0) {
    return "";
  }
  if (!Number.isSafeInteger(max) || max < 1 || max > 2000) {
    return "";
  }
  return used + " / " + max;
}
