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
