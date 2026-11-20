# Green Screen Medium

## What it is

Green Screen Medium is a bridge to a legacy terminal host. It logs on to a TN3270 host through `s3270` (or `ws3270` on Windows), reads the 24 by 80 character screens, and replays stored key sequences, called Flows, on demand. A Flow is replayed deterministically, with no LLM at run time. At every step the runtime checks which screen the host is showing, and a Flow stops with an error on any screen it does not know. It never guesses.

Each Flow is published as an MCP tool and as a REST endpoint with generated API docs. A web console shows the tool library, runs a tool and shows the call log. An optional question box (Ask) lets a model pick a tool.

Live demo: https://greenscreen.banksyai.com . An API key is needed to use it.

Built with [Kiro](https://kiro.dev) for the Kiroween 2026 hackathon (Resurrection category). The demo host is MVS 3.8j (TK5) on the Hercules emulator.

## Published tools

The Publisher serves six tools. Each logs on to TSO, does one read-only thing, and logs off.

| Tool | What it returns |
|---|---|
| `tk5-system-info` | The user id, terminal, release and system id shown on the ISPF primary option menu. |
| `tk5-time` | The host's own answer to the TSO `TIME` command: time of day, CPU time, service units, session time and date. |
| `tk5-list-datasets` | The data set names in the account's own catalog (TSO `LISTCAT`), one per line. |
| `tk5-dataset-info` | Whether one data set (input `dsname`) is catalogued, and its attributes (TSO `LISTDS`). |
| `tk5-library-members` | The member names of one partitioned data set (input `dsname`), one per line, and `MEMBER_COUNT`, the number of names. |
| `tk5-job-status` | The jobs of the account (TSO `STATUS`), one line per job. |

The repository holds two more Flows, `tk5-logon` and `tk5-logoff`. They are building blocks. `tk5-logon` stops at the ISPF menu and leaves the user id logged on, so it is not one of the six tools.

## Run the Publisher locally

### Install and start

You need Python 3.11 or newer, and `s3270` or `ws3270` (the x3270 suite). The Publisher is the console script `greenscreen-publish` of the extra `publish`.

Windows (PowerShell), with `ws3270`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[publish]"
$env:GS_S3270_BINARY = "<path to ws3270.exe>"
$env:GS_HOST = "<mainframe host>"
$env:GS_PORT = "3270"
$env:GS_PUBLISH_FLOWS = "tk5-system-info,tk5-time,tk5-list-datasets,tk5-dataset-info,tk5-library-members,tk5-job-status"
Set-Item -Path Env:GS_API_KEY -Value (Read-Host "API key")
greenscreen-publish
```

Linux (sh), with `s3270`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[publish]"
export GS_S3270_BINARY="<path to s3270>"
export GS_HOST="<mainframe host>"
export GS_PORT="3270"
export GS_PUBLISH_FLOWS="tk5-system-info,tk5-time,tk5-list-datasets,tk5-dataset-info,tk5-library-members,tk5-job-status"
read -rs GS_API_KEY && export GS_API_KEY
greenscreen-publish
```

The API key needs at least 16 characters. The Publisher listens on `127.0.0.1` port 8080 by default; do not expose it publicly. It logs a line such as `publishing 6 of 8 flows over http` at start.

Set `GS_PUBLISH_FLOWS` to the six tool names as shown. Without it the Publisher publishes every loaded Flow, which is all eight, including `tk5-logon`. A call to `tk5-logon` leaves the user id logged on.

The host has one TSO session per user id, so the default is one call at a time (`GS_MAX_CONCURRENCY`). If a call ends without its logoff, the bundled logon steps reconnect the orphaned session at the next call. This is verified on the live host for a session left at the ISPF menu, at READY, at a cleared screen, at a REENTER prompt, and mid-listing at a *** pause. The call that finds such a session releases it and stops with `unexpected_screen`, and the next call works.

Optional parts, off by default:

- The web console at `/` (`GS_ENABLE_CONSOLE`, HTTP only). It lists the tools, runs one, and shows outputs, the audit trail and the call log. Pasting `#key=<YOUR_API_KEY>` after the address gives the page the key; the page removes it from the address bar.
- The interactive API docs at `/docs` (`GS_ENABLE_DOCS`).
- Ask, a question box at `POST /ask` (`GS_ENABLE_ASK`, HTTP only). Ask is optional. It sends the question and the tool results to an OpenAI-compatible model that the operator configures, and the model only chooses which published tool to call. The tool then runs through the same deterministic runtime. When Ask is on, the console shows one example question for each tool that Ask offers.

### Environment variables

Names only. Never put a value that is a key, a password or a user id in a file that is committed. `.env.example` lists the same names with the ranges and defaults.

| Variable | What it does |
|---|---|
| `GS_HOST` | Host name or address of the tn3270 host. |
| `GS_PORT` | tn3270 port of the host. |
| `GS_S3270_BINARY` | Path to the `s3270` or `ws3270` binary. |
| `GS_PUBLISH_HOST` | Listen address (default `127.0.0.1`). |
| `GS_PUBLISH_PORT` | Listen port, 1 to 65535 (default 8080). |
| `GS_TRANSPORT` | `http` or `stdio` (default `http`). |
| `GS_API_KEY` | API key, at least 16 characters, required for `http`. Set it in the shell. Ignored for `stdio`. |
| `GS_AUTH_DISABLED` | `true` turns the key check off. Allowed only on a loopback `GS_PUBLISH_HOST`. |
| `GS_MAX_CONCURRENCY` | Calls in flight at once, 1 to 64 (default 1). |
| `GS_CALL_TIMEOUT` | Seconds per call, 1 to 900 (default 180). |
| `GS_MAX_BODY_BYTES` | Largest request body in bytes, 1024 to 1048576 (default 65536). |
| `GS_SHUTDOWN_GRACE` | Seconds to wait for calls in flight on shutdown, 1 to 120 (default 10). |
| `GS_FLOWS_DIR` | Extra directory of `*.yaml` Flows, loaded after the bundled Flows. |
| `GS_PUBLISH_FLOWS` | Comma-separated Flow names to publish. Unset or empty publishes every loaded Flow. |
| `GS_ENABLE_DOCS` | `true` serves the interactive `/docs` page (default false). |
| `GS_ENABLE_CONSOLE` | `true` serves the web console at `/` (HTTP only, default false). |
| `GS_ENABLE_ASK` | `true` turns Ask on (HTTP only, default false). The model and Ask variables below are ignored while it is off. |
| `GS_LLM_BASE_URL` | Base URL of an OpenAI-compatible chat API. Required when Ask is on. `https`, or `http` only for a loopback host. |
| `GS_LLM_MODEL` | Model name. Required when Ask is on. |
| `GS_LLM_API_KEY` | API key for the model provider. Required unless the base URL host is loopback. Set it in the shell. |
| `GS_LLM_REASONING_EFFORT` | Optional: `none`, `minimal`, `low`, `medium` or `high`. Unset means it is not sent. |
| `GS_ASK_MAX_TOOL_CALLS` | Most tool calls per question, 1 to 20 (default 6). |
| `GS_ASK_MAX_TURNS` | Most model turns per question, 1 to 30 (default 8). |
| `GS_ASK_TIMEOUT_SECONDS` | Seconds per question, 20 to 95 (default 90). |
| `GS_ASK_MODEL_TIMEOUT_SECONDS` | Seconds per model turn, 1 to 60 (default 25). Twice this must not exceed `GS_ASK_TIMEOUT_SECONDS`. |
| `GS_ASK_FLOWS` | Comma-separated Flow names the model may use. Unset or empty offers every eligible published Flow. |
| `GS_ASK_MAX_QUESTION_CHARS` | Longest question in characters, 1 to 2000 (default 500). |
| `GS_ASK_MAX_ANSWER_CHARS` | Longest answer in characters, 100 to 20000 (default 2000). |
| `GS_ASK_MAX_RESULT_CHARS` | Largest tool result shown to the model in characters, 200 to 20000 (default 4000). |
| `GS_ASK_DAILY_LIMIT` | Questions per UTC day, 1 to 100000 (default 100). |

With Ask on and the defaults, `GS_CALL_TIMEOUT` must be 30 or less; a larger value stops the start.

### Bound inputs

A variable named `GS_BIND_<FLOW>__<INPUT>` supplies the input `<INPUT>` of the Flow `<FLOW>` from the environment. Both names are in upper case and `-` is written as `_`. For example, `GS_BIND_TK5_TIME__USERID` supplies the input `userid` of `tk5-time`. The demo binds the `userid` and `password` of every tool this way, so a caller never sends them: a bound input is not part of a request, and the caller cannot supply it. Set these variables in the shell only, the way `GS_API_KEY` is set above:

```powershell
Set-Item -Path Env:GS_BIND_TK5_TIME__USERID -Value (Read-Host "User id")
```

```sh
read -rs GS_BIND_TK5_TIME__USERID && export GS_BIND_TK5_TIME__USERID
```

## How a Flow is built

A Flow is a YAML file: a name, typed inputs, optional typed outputs and a list of steps. The six step kinds are:

- `expect`: the host must show one of the named screen signatures, or the Flow stops.
- `type`: type an input or a fixed text.
- `key`: press a key such as Enter, Clear or PA1.
- `extract`: read the region of the recognized screen that an output names into that output.
- `collect`: read rows from one screen after another, pressing a named key between screens, up to a screen limit, into one output.
- `handle`: name a screen that may show up (for example a `***` pause), how often it may show, and the `type` and `key` steps that get past it.

A screen signature is a fingerprint of a screen: title text and field layout, with volatile content such as the clock ignored. The bundled signatures live in `greenscreen/recognizer/signatures`. If the host shows a screen that no signature of the step names, the Flow stops with `unknown_screen`, and the call returns a clear error. Flows are validated when they are loaded.

This short fragment shows the format. It is for explanation, not a Flow to publish: it leaves the host at the password prompt.

```yaml
version: 1
name: logon-prompt-check
description: Type a user id at the logon screen and stop at the password prompt. For illustration only.
inputs:
- name: userid
  type: str
  required: true
  max_length: 8
  regex: '[A-Za-z0-9@#$]{1,8}'
steps:
- kind: expect
  signatures:
  - tk5-logon
- kind: type
  input: userid
- kind: key
  key: enter
- kind: expect
  signatures:
  - tso-password-prompt
```

The bundled Flows are in `greenscreen/flow/flows`. Flows in the directory `GS_FLOWS_DIR` are loaded after them.

### Check a Flow file

```sh
python -m greenscreen.flow.check greenscreen/flow/flows/tk5-time.yaml
```

The command validates one Flow file against the bundled signatures and changes nothing. A clean file prints `ok: <file name>`. Anything else prints one short line to standard error. Exit codes:

| Code | Meaning |
|---|---|
| 0 | The file is a valid Flow. |
| 1 | The file breaks a rule of the Flow format. The line names the step and the rule. |
| 2 | Usage error: not exactly one argument. |
| 3 | The file is missing or cannot be read. |
| 4 | The file is not a YAML mapping. |
| 5 | The bundled signatures could not be loaded. |

## Call a tool

The examples use the placeholder `<YOUR_API_KEY>`. The key goes in the header `X-API-Key`, or as a Bearer token. Because the demo binds `userid` and `password`, the body below holds only the inputs that are not bound.

REST: `POST /flows/<name>`. The API description is at `/openapi.json`.

```sh
curl -sS -X POST 'https://greenscreen.banksyai.com/flows/tk5-library-members' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <YOUR_API_KEY>' \
  -d '{"dsname":"SYS2.JCLLIB"}'
```

MCP over HTTP: the Streamable HTTP endpoint is `/mcp`, with the same key header. With Claude Code:

```sh
claude mcp add --transport http greenscreen 'https://greenscreen.banksyai.com/mcp' --header 'X-API-Key: <YOUR_API_KEY>'
```

MCP over stdio: start `greenscreen-publish` with `GS_TRANSPORT` set to `stdio`. No key is used on stdio.

Kiro: add the server to `.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "greenscreen": {
      "url": "https://greenscreen.banksyai.com/mcp",
      "headers": { "X-API-Key": "<YOUR_API_KEY>" }
    }
  }
}
```

For a local Publisher use `http://127.0.0.1:8080` instead of the demo address.

## How Kiro built it

The project was built spec by spec in Kiro. Each folder in `.kiro/specs` holds `requirements.md`, `design.md` and `tasks.md`.

| Spec | What it built |
|---|---|
| `tn3270-connector` | The Connector: a headless session that drives `s3270` or `ws3270` and returns typed screens. |
| `screen-recognizer` | Screen signatures and the recognizer that names the screen the host shows, offline and deterministic. |
| `flow-runtime` | The Flow model, YAML format, validator and the runner that replays a Flow and stops on an unknown screen. |
| `publisher` | The MCP and REST publisher: one tool and one endpoint per Flow, the API key, limits and the call log. |
| `logon-recovery` | Bundled logon steps that reconnect a TSO session left logged on by a dropped call. |
| `linux-readiness` | Fixes found on Linux, so the Publisher and the suite run with `s3270` there. |
| `console` | The web console: tool library, run page, audit trail and call log. |
| `ask` | The optional question box: a model chooses published tools, the runtime runs them. |
| `more-flows` | Five read-only TSO command Flows, which with `tk5-system-info` make the six tools. |
| `polish` | This README, the two hooks, the Flow check command, `MEMBER_COUNT`, console examples and text fixes. |

Steering. Two files in `.kiro/steering` are always in the agent's context: `product.md` (what the product is, and the rules that never change: deterministic runtime, a Flow never guesses, credentials from the environment, MIT licence) and `mainframe-host.md` (facts about the demo host, each written down only after it was observed live, and the rules that follow from them).

Captures. `captures/` holds the exact screen text that `s3270` returned from the real demo host. Recognizer and Flow tests are built from these files, not from invented screens. A test checks that no capture holds a password.

Hooks. Two Kiro hooks live in `.kiro/hooks`. Both run pytest through `python tests/hook_pytest.py`, which writes the pytest report to standard error. A passing run prints nothing; a failing run shows the report to the agent.

| File | Trigger | What it runs |
|---|---|---|
| `.kiro/hooks/flow-yaml-check.json` | A file `greenscreen/flow/flows/*.yaml` is saved. | `python tests/hook_pytest.py tests/unit/test_flow_bundled.py tests/unit/test_flow_sync.py tests/unit/test_flow_command_sync.py -p no:cacheprovider`: every bundled Flow is validated against the bundled signatures, each file must equal what the writer produces, and the shared logon and exit steps must stay equal. |
| `.kiro/hooks/captures-check.json` | A file under `captures/` is created or saved (two hooks in the file). | `python tests/hook_pytest.py` over the capture tests: no typed password in any capture (plain or hex), hidden-field cells blank, and the capture inventory. |

Tests. The suite uses pytest and Hypothesis, including property-based tests. It needs no live host: it uses captured screens and a fake host. Tests that do need the host are marked `integration`.

```sh
pip install -e ".[dev]"
python -m pytest -m "not integration" -p no:cacheprovider
```

The console page tests run the page code under Node, so `node` must be on the PATH. Integration tests run only with a reachable host.

## Not built yet

- A Flow recorder: today Flows are written as YAML by hand.
- 5250 (AS/400) support: only 3270 works.
- Flows that write to the host: every bundled Flow is read-only.

## License

MIT. See [LICENSE](LICENSE).
