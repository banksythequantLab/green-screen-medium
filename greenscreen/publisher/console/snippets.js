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
