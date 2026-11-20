# Requirements Document

## Introduction

The publisher is the `greenscreen.publisher` Python package, built on top of `greenscreen.flow` and `greenscreen.connector`. It is Core Piece 5 of Green Screen Medium. One process loads every Flow, and publishes each selected Flow twice: as an MCP tool and as a REST endpoint. By default every loaded Flow is selected, and the operator can narrow the set with an allow-list (`GS_PUBLISH_FLOWS`, Requirement 1). A call opens its own Connector session, runs the Flow with `run_flow`, closes the session and returns the Outputs together with a redacted audit summary. The runtime stays deterministic. The publisher adds no LLM and no guessing: a Flow that stops on an unexpected screen is reported as a structured error.

The main risk of this feature is a leak. The publisher is the first component that receives secrets from the network and returns data to the network, so most requirements below are "never" rules. Each of them is written so that a Hypothesis property test can check it, and the property is named in the requirement (Requirements 7 and 20).

### Assumptions

- One process, one event loop. The Connector is blocking and is not documented as thread-safe, so each call runs `Connector.open`, `run_flow` and `Connector.close` on a worker thread, and one Connector instance serves exactly one call.
- The publisher is the owner of the plaintext Input values between request parsing and the call of `run_flow`. The runner clears its own frames on error (flow-runtime Requirement 14), and the publisher does the same for its own frames.
- Callers supply every Input value that is not a Bound_Input, including Secret_Inputs, in the call. The publisher does not read `TK5_USERNAME` or `TK5_PASSWORD`. An operator can supply an Input from the environment through a Binding_Variable only (Requirement 22); filling Inputs from a vault or any other source remains out of scope.
- Flows loaded from `GS_FLOWS_DIR` reference only the Signatures of `load_bundled_signatures()`. A directory of custom Signatures is out of scope.
- CORRECTED 2026-11-17: closing the session does NOT end the TSO session. An earlier version of this document assumed that `Connector.close` ends the TSO session on the demo host. The mainframe-host steering ("Verified 2026-11-17: one TSO session per user id, and dropped connections") says the opposite: closing the connection without `LOGOFF` (`Connector.close()`, or killing s3270) leaves the TSO session alive, and the user id stays `IN USE` for at least three minutes and does not clear by itself. The Publisher opens a new session per call (Requirement 3), so a call that ends without a logoff locks the user id for the next call.
- Which bundled Flows end with a logoff (read from `greenscreen/flow/flows/*.yaml` on 2026-11-17; no Flow is changed by this spec):
  - `tk5-system-info`: the steps end with `X` at the ISPF primary menu, `LOGOFF` at `READY` and an Expect of `tk5-logon`. Its `finally` steps repeat the logoff (a handler for `ispf-primary-menu`, a handler for `tso-ready`, then an Expect of `tk5-logon`). A normal call ends logged off, and a stop that leaves the session at the ISPF primary menu or at `READY` is logged off by the `finally` steps. A stop elsewhere (for example an unknown screen) has no such guarantee.
  - `tk5-logon`: the steps stop at the ISPF primary menu and `finally` is empty. A call leaves the user logged on, so the user id is `IN USE` for the next call. A later logon for that user id is refused with `IKJ56425I LOGON REJECTED, USERID <id> IN USE`, and a Flow that logs on stops with `unknown_screen` at the Expect of `tso-password-prompt`, because no bundled Signature matches that screen (steering).
  - `tk5-logoff`: no inputs, and its first step is an Expect of `ispf-primary-menu`. A per-call session starts at the logo or logon screen and never at ISPF, so a call of `tk5-logoff` is expected to stop (`unknown_screen` or a timeout) and does not log off another call's session.
- Consequence for operators: do not publish `tk5-logon`, or accept that a call locks the user id (the lock does not clear by itself). By default the Publisher publishes every loaded Flow, so an operator excludes a Flow with the allow-list `GS_PUBLISH_FLOWS` (Requirement 1, criteria 9 to 15; for example `GS_PUBLISH_FLOWS=tk5-system-info`). Recovery by hand is `<id> RECONNECT` at `Logon ===>` (steering).
- A call that ends by `call_timeout`, by cancellation or by shutdown teardown is aborted (Requirement 10), and the `finally` steps of the Flow do not run. Such a call leaves the user id logged on and locked, whichever Flow it ran. The Publisher itself adds NO recovery logic for a locked user id; recovery is done by the bundled Flows. Requirement 23 only marks such calls in the Call_Log_Record, and also marks every Flow stop after which the runtime skips the `finally` steps.
- Recovery of a locked user id now exists in the bundled Flows (a self-healing logon built on new Signatures and checked against the live host on 2026-11-18). The restriction that the Publisher must not be exposed publicly is lifted, within this limit. Recovery covers an orphan session left at the ISPF primary option menu, at `READY`, at the cleared screen and at a ` REENTER -` prompt. At the menu the call succeeds; at the other three the Flow ends the reconnected session and the call stops with `unexpected_screen`, so that the next call succeeds. The menu landing was verified through the Flow on 2026-11-17 and 2026-11-18 and the REENTER landing by hand on 2026-11-19; the `READY` and cleared-screen landings are not yet seen on the host. An orphan left in a sub-panel or mid-logon (for example an abandoned logon showing `IKJ56700A ENTER USERID`, or the second IN USE state with `IKJ56400A` after an extra Enter) is not handled: the call stops with `session_clean` false (`unknown_screen` or another stop after which the runtime skips the `finally` steps), and the user id stays locked until the host purges the orphan or an operator recovers it by hand. RECONNECT takes over whatever session holds the user id, so recovery ends the orphaned session without regard to who or what owns it. The host may also purge an orphaned session by itself. The defaults stay: a loopback listen address (Requirement 15) and a mandatory API_Key (Requirement 13).
- Not in scope: the recorder, the console UI, 5250, user management, hot reload of Flows, multiple API keys, Flow-to-Flow calls, recovery of a locked TSO user id by the Publisher itself (the bundled Flows recover an orphan left at the ISPF primary option menu, at `READY`, at the cleared screen or at a ` REENTER -` prompt; an orphan left in a sub-panel or mid-logon is not recovered), and changes to bundled Flows or Signatures. Excluding a Flow from publication is in scope as the allow-list of Requirement 1.

### Documentation checked (2026-11-17)

- MCP Python SDK `mcp` 2.3.0 (2.x is the stable line since 2.0.0 on 2026-07-28): [docs](https://py.sdk.modelcontextprotocol.io/), [what's new in v2](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md), [migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md). Facts used here: the high-level class `MCPServer` wraps the low-level `Server` (`from mcp.server import MCPServer, Server`); transports are stdio, Streamable HTTP and SSE; the Streamable HTTP app is an ASGI app that can be mounted in another app. The design verified the following locally against `mcp` 2.3.0 on 2026-11-17 (design document, "Documentation checked", claims 2 and 3):
  - `MCPServer` validates tool arguments against a model built from the function signature, and its validation error text, which the client receives, contains the submitted value. It cannot take a hand-written input or output schema. The low-level `Server` does not look at the arguments at all and takes hand-written schemas.
  - In the low-level `Server`, an exception that escapes the call handler reaches a client of the 2025 handshake era as the exception text, and reaches a client of the 2026-07-28 era as `Internal server error`. In both eras the SDK writes an ERROR log record with the traceback, whose frames hold the values. (`MCPServer` instead returns `Error executing tool <name>` and logs the traceback with the exception text.)
  - Consequence: the Publisher uses the low-level `Server`, validates all arguments itself and catches every `Exception` itself, so that no exception and no argument value ever reaches the SDK error path (Requirements 4 and 14).
- FastAPI 0.163.2 (MIT, python>=3.11): [security reference](https://fastapi.tiangolo.com/reference/security/); `APIKeyHeader` appears in the generated OpenAPI document as a security scheme. FastAPI emits OpenAPI 3.1.
- Verified locally (FastAPI 0.141.1, pydantic 2.13.4): the default 422 response echoes the submitted value in `detail[].input` (a request with `{"password": "hunter2"}` for an `int` field returned `"input":"hunter2"`). The default `RequestValidationError` handler is therefore a secret leak and Requirement 7 forbids it.
- Local environment: Python 3.11.9, installed `mcp` 1.22.0 (a 1.x line, so the project must pin a range on purpose), `hypothesis` 6.170.15, `pytest` 9.1.1.

### Open items

1. **RESOLVED 2026-11-17: second TSO logon for a user id that is already logged on.** Verified on the live host (mainframe-host steering, "Verified 2026-11-17: one TSO session per user id, and dropped connections"): the second logon is refused with `IKJ56425I LOGON REJECTED, USERID <id> IN USE` and no password prompt (one more Enter also shows `IKJ56400A ENTER LOGON OR LOGOFF-`); no bundled Signature matches those screens, so a Flow stops with `unknown_screen` at the Expect of `tso-password-prompt`. Closing the connection without `LOGOFF` leaves the TSO session alive and the user id `IN USE` for at least three minutes, without clearing by itself; recovery by hand is `<id> RECONNECT` at `Logon ===>`. The default `GS_MAX_CONCURRENCY` of 1 stays, now for this verified reason (Requirement 9, criterion 5). See Assumptions for the consequences and Requirement 23 for the log marker.
2. **Residual risk, MCP error results.** The design verified that the SDK client accepts an `isError` result whose `structuredContent` is the Error_Body although an `outputSchema` is declared. A third-party MCP client that validates error results against the `outputSchema` would reject them. Accepted.
3. **RESOLVED 2026-11-17: outcome value of a cancelled Call.** A Call cancelled in flight has no response. Its Call_Log_Record has `outcome` `cancelled` when the Publisher is not shutting down, and `shutting_down` when it is (Requirement 8, criterion 2; Requirement 23, criteria 3 and 4). `cancelled` is a log value only and is not an Error_Code (Requirement 8, criterion 8).

### Decisions (confirmed by the user, 2026-11-17)

1. **HTTP status table.** The requirements fix the set of error codes and demand exactly one HTTP status per code. The table itself is left to design. Confirmed.
2. **OpenAPI document needs the API key.** `GET /health` is the only route without the key (Requirement 13). The OpenAPI document lists Flow names and Input names, which describe the host's capabilities, so it is protected. The interactive docs page is off by default. Confirmed.
3. **Extra name `publish`.** The new dependencies go into `[project.optional-dependencies] publish`, so `greenscreen.flow` and `greenscreen.connector` keep a `pyyaml`-only footprint. The console script is `greenscreen-publish`. Confirmed.
4. **Listen address variables.** `GS_HOST` and `GS_PORT` already name the mainframe. The listening address is `GS_PUBLISH_HOST` and `GS_PUBLISH_PORT`, so the two cannot be mixed up. Confirmed.
5. **Per-call session on `tk5-logon`.** Described under Assumptions. No session pooling is proposed. Confirmed. The earlier assumption that closing the session ends the TSO session was CORRECTED on 2026-11-17 (decision 12, item h).
6. **Property-test time budget.** Requirement 20 gives the publisher property modules 120 seconds together and the whole of `tests/property` 240 seconds. History: the first version gave 25 seconds and raised the total from 90 to 115 seconds; both limits were raised to 60 and 150 seconds on 2026-11-17 by the user's decision, after the measurements of Properties 12 and 13, and raised again to 120 and 240 seconds on 2026-11-17 by the user's decision after the checkpoint measurements. Measured on 2026-11-17: a clean serial run of the 14 publisher property modules took 74.7 s (pytest-reported; slowest: Property 6 15.2 s, Property 14 13.4 s, Property 11 9.0 s), and the user's checkpoint run of `pytest -m "not integration"` gave 1940 passed, 4 skipped, 0 failed in 301 s on a loaded machine. This changes the limit in flow-runtime Requirement 19, criterion 9 for the whole `tests/property` total (now 240 seconds). Tests are not trimmed and `max_examples` is not lowered to save time (at least 100 always). Confirmed.
7. **Schema patterns.** The generated JSON Schema is advisory. The Input_Validator is the authority (Requirement 2, criterion 8), because a Python `re` pattern and a JSON Schema `pattern` are different dialects. Confirmed.
8. **Error results and `outputSchema`.** The MCP `outputSchema` describes the success body only. Design must confirm that the SDK accepts an `isError` result whose `structuredContent` is the error body (Requirement 14, criterion 6). Confirmed as a design risk.
9. **No caching of `ScreenView`.** Requirement 17 records the decision and the measurements. Confirmed as a design risk alongside decision 8 (the second design risk is the teardown of a Connector from outside its worker thread, Requirement 10, criterion 3; the design settled it with `abort()`, decision 12, item e).
10. **Dependencies.** `mcp>=2.3,<3` and `fastapi>=0.163,<1` in the extra `publish` were APPROVED on 2026-11-17. They are added to `pyproject.toml` when the packaging task runs (Requirement 18).
11. **Bound Inputs and API key carriers (added 2026-11-17).** An operator can supply an Input from the environment (Requirement 22), the API key can arrive as `X-API-Key` or as `Authorization: Bearer` (Requirement 13), and the default `GS_MAX_CONCURRENCY` is 1 (Requirement 9).
12. **Design review round (confirmed by the user, 2026-11-17).** The user approved the design with these changes to the requirements:
    - a. Low-level `mcp.server.lowlevel.Server` instead of `MCPServer`, with hand-written schemas (Requirements 4.6, 14.10).
    - b. An outermost Crash_Guard, because replacing the framework handlers is not enough (Requirement 6.9, 6.10).
    - c. The `BoundValues` store is the one permitted long-lived holder of Bound_Values (Requirement 7.6).
    - d. The Input_Validator is the authority on floats: the schema may accept an integral float, so the agreement property is one-directional (Requirements 4.4, 20.3).
    - e. The Session_Factory contract gains `abort()` (Requirements 10.3, 10.4, 19.1, 19.2).
    - f. Property 14 is added, and the property count is 14 (Requirement 20).
    - g. An empty `X-API-Key` header next to a valid Bearer header is `unauthorized` (Requirement 13.11); an unknown path and a wrong method give `request_invalid` (Requirement 11.5, 11.6); `/mcp` oversize bodies are answered by the SDK transport (Requirement 4.5); Property 9 draws undeclared names from an alphabet disjoint from the Probe_Values (Requirement 20.10); the `/docs` page limitation (Requirement 12.6); stdio hygiene through duplicated file descriptors (Requirement 14.11); the traceback-stripping stderr filter (Requirement 8.7); removal of `GS_API_KEY` and `GS_BIND_*` from the process environment after loading (Requirement 15.8); the transitive dependency list (Requirement 18.2); the time budget (Requirement 20.17; first 25 seconds, raised to 60 seconds and then to 120 seconds on 2026-11-17, see decision 6).
    - h. CHANGED decision: the bundled Signatures are loaded ONCE at startup and passed to every `run_flow` call (Requirements 1.8, 3.7). Tests do not patch the loader.
    - i. The open item on the second TSO logon is RESOLVED, the assumption about the per-call session is CORRECTED, the lack of recovery is recorded (Assumptions), and Requirement 23 adds the `session_clean` log marker.

13. **Flow allow-list and log outcome `cancelled` (confirmed by the user, 2026-11-17).**
    - a. New variable `GS_PUBLISH_FLOWS`, a comma-separated allow-list of Flow names (Requirement 1, criteria 9 to 15; Requirement 15.1). Unset or empty publishes every loaded Flow, so Requirement 1.1 is amended and not removed. The demo runs with `GS_PUBLISH_FLOWS=tk5-system-info`, because `tk5-logon` leaves the user id in use (Assumptions). The allow-list is applied after all Flows are loaded and validated (Requirement 1.3 is unchanged) and before schema generation and binding. A `GS_BIND_*` variable for a loaded but unpublished Flow stops the startup with the rule `flow_not_published` (Requirement 22.7). The Flow_Registry holds the published Flows only.
    - b. The `outcome` of a Call_Log_Record is `ok`, an Error_Code, or `cancelled` (Requirement 8.2). A client disconnect (cancellation while the Publisher is not shutting down) logs `cancelled` with `session_clean` false. A drain teardown, and a cancellation while the Publisher is shutting down, log `shutting_down` with `session_clean` false (Requirement 23.3, 23.4). `cancelled` is not an Error_Code and appears in no response (Requirement 8.8). This replaces the design's use of `internal_error` for this case; the design is updated in a later step.

## Glossary

- **Publisher**: The `greenscreen.publisher` package and the process started by the `greenscreen-publish` console script.
- **Loaded_Flow**: A Flow that the Publisher has loaded and validated at startup, from `load_bundled_flows()` or from `GS_FLOWS_DIR` (Requirement 1, criteria 1 to 4). A Loaded_Flow is not necessarily published.
- **Publish_List**: The parsed value of `GS_PUBLISH_FLOWS` (Requirement 1, criterion 10).
- **Flow_Registry**: The immutable mapping from Flow_Name to `Flow` that the Publisher builds at startup (Requirement 1), holding the Published_Flows only.
- **Published_Flow**: A Loaded_Flow that the Publish_List selects, or every Loaded_Flow when the Publish_List is not set. Only a Published_Flow is held by the Flow_Registry.
- **Schema_Generator**: The one function that turns a `Flow` into an Input_Schema, an Output_Schema and a Success_Schema (Requirement 2).
- **Input_Schema**: A JSON Schema (draft 2020-12) object that describes the Inputs of one Published_Flow.
- **Output_Schema**: A JSON Schema object that describes the `outputs` mapping of a success result of one Published_Flow.
- **Success_Body**: The JSON object `{"flow": <Flow_Name>, "outputs": {...}, "audit": [...]}` returned for a run that finished without error.
- **Success_Schema**: The JSON Schema of the Success_Body of one Published_Flow.
- **Error_Body**: The JSON object `{"error": {...}}` described in Requirement 6.
- **Error_Code**: One of the Reason_Codes of `greenscreen.flow.errors.REASON_CODES`, or one of the Publisher_Codes. The Error_Code is the `code` member of an Error_Body.
- **Publisher_Codes**: `unauthorized`, `unknown_flow`, `request_invalid`, `request_too_large`, `busy`, `shutting_down`, `call_timeout`, `host_unavailable` and `internal_error`.
- **Call**: One invocation of a Published_Flow through REST or MCP.
- **Call_Handler**: The single code path that both front ends use to execute a Call (Requirement 3).
- **REST_Front_End**: The HTTP API of the Publisher (Requirement 11).
- **MCP_Front_End**: The MCP server of the Publisher (Requirement 14).
- **Input_Validator**: The check of supplied Input values against the declared Inputs that `run_flow` itself applies (`greenscreen.flow.inputs.prepare_inputs`, flow-runtime Requirement 2, criteria 6 to 9). The Publisher runs it before a session is opened.
- **Session_Factory**: A callable that returns a new session object with `open()`, `close()`, `abort()` and the Session protocol of flow-runtime. `abort()` is thread-safe, may be called from another thread, kills the s3270 process without using the send path of the session, and is idempotent. The default builds a `greenscreen.connector.Connector` from a `ConnectorConfig`. Tests replace it.
- **Startup_Signatures**: The Signatures returned by one call of `load_bundled_signatures()` at startup, held by the application and passed to every `run_flow` call.
- **Crash_Guard**: The outermost ASGI layer of the REST_Front_End that catches every `Exception` that the framework re-raises (Requirement 6, criterion 10).
- **BoundValues_Store**: The one object that holds the Bound_Values between Calls. Its `repr` shows no value, it is never logged, and it is never placed in an exception or in a frame of a transient Call (Requirement 7, criterion 6).
- **Limiter**: The counter of Calls in flight, shared by both front ends (Requirement 9).
- **Slot**: One unit of the Limiter. A Slot is held from the acquisition until the session of the Call has been closed.
- **Call_Deadline**: The time limit of one Call (Requirement 10).
- **Auth_Guard**: The component that checks the API_Key (Requirement 13).
- **API_Key**: The value of the environment variable `GS_API_KEY`.
- **Key_Carrier**: One of the two request headers that can carry a key: `X-API-Key` (the key is the header value) and `Authorization` (the key is the credentials after the scheme word `Bearer`).
- **Config_Loader**: The component that reads and validates the environment variables of Requirement 15.
- **Call_Log_Record**: A log record written by the Publisher for a finished Call (Requirement 8). Its `outcome` is `ok`, an Error_Code or `cancelled`.
- **cancelled**: A value of the `outcome` field of a Call_Log_Record only, for a Call cancelled in flight while the Publisher is not shutting down. It is not an Error_Code and appears in no response (Requirement 8, criterion 8).
- **session_clean**: A boolean field of the Call_Log_Record, present only with the value `false`, that marks a Call after which the TSO user id may still be logged on: a Flow stop for which the flow runtime skips the `finally` steps (`unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error`), `call_timeout`, cancellation and shutdown teardown (Requirement 23). Its absence makes no claim.
- **Binding_Variable**: An environment variable whose name starts with the exact, case-sensitive prefix `GS_BIND_` (Requirement 22).
- **Bound_Input**: An Input of a Published_Flow for which a non-empty Binding_Variable exists. Whether the Input has `secret` true is irrelevant.
- **Bound_Value**: The value of a Binding_Variable after parsing (Requirement 22, criterion 4). Every Bound_Value counts as a Secret_Value in every requirement and property of this document, whether or not its Input is marked secret.
- **Probe_Value**: A value that a property test supplies as an Input value (secret or not), or sets as a Bound_Value, to find leaks. It has at least 4 characters, is accepted by the Input that carries it, and does not occur in the fixed text of any response (Flow_Names, field names, Signature_Names, fixed messages). An `int` Probe_Value has at least 4 digits. The undeclared Input names that tests send are drawn from an alphabet disjoint from the characters of every Probe_Value, because an `input_invalid` message may name an undeclared Input by design (an identifier, not a value), so a hit of a Probe_Value in a response is always a leak.
- **Leak_Forms**: For a Probe_Value `v` (rendered with `str()`), the forms: `v` itself; `json.dumps(v)` without its quotes; `urllib.parse.quote(v, safe="")` and `urllib.parse.quote_plus(v)`; the UTF-8 bytes of `v` in hex, lowercase and uppercase, each with and without a space between bytes; the UTF-8 bytes of `v` in base64 and in URL-safe base64, each with and without padding.
- **Host_Data**: Any of the following: the text of a `S3270Error.data_lines` entry, the `raw` attribute of a `ParseError`, a `Screen` or `Field` object or its `repr`, the cell text of a hidden field, a traceback, a frame local.
- **Fake_Host**: A test Session_Factory that serves sessions built on `ScriptedSession`, `FakeClock` and the capture screens of `tests/flow_support.py`, so that no live host is needed. It can inject failures.
- **Redacted_Summary**: The `greenscreen.recognizer.summary.RedactedSummary` of flow-runtime. Its `to_dict()` output holds only `str`, `int`, `bool`, lists and dicts, and shows hidden cells as `*`.
- **Audit_Summary**: The list of audit entries in a Success_Body or Error_Body. Each entry has exactly the members `step_index`, `kind`, `phase`, `iteration`, `signature`, `status` and `duration_seconds` of an `AuditRecord`.
- **Call_Id**: A random identifier that the Publisher generates for one Call and that appears in its Call_Log_Record. It carries no information about the Call.

## Requirements

### Requirement 1: Flow Registry

**User Story:** As an operator, I want to choose which Flows are published and to learn about a broken Flow at startup, so that the Publisher never runs with a half-loaded set.

#### Acceptance Criteria

1. WHEN the Publisher starts, THE Publisher SHALL load every Flow returned by `load_bundled_flows()` as a Loaded_Flow, and THE Flow_Registry SHALL contain every Loaded_Flow that the Publish_List selects (criterion 9), which is every Loaded_Flow when `GS_PUBLISH_FLOWS` is unset or empty.
2. WHERE `GS_FLOWS_DIR` is set, THE Publisher SHALL also load as a Loaded_Flow every Flow loaded with `load_flow` from each file with the suffix `.yaml` directly inside that directory, in ascending file name order, without descending into subdirectories.
3. IF a Flow file of `GS_FLOWS_DIR` is missing, unreadable or invalid, or the directory does not exist or is not a directory, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message on stderr that names the file or the directory and the violated rule, and SHALL publish no Flow.
4. IF two Flows have the same Flow_Name, whether both come from `GS_FLOWS_DIR` or one comes from the bundled Flows, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names the Flow_Name and both sources, and SHALL publish no Flow.
5. THE Flow_Registry SHALL be immutable after the startup, and THE Publisher SHALL NOT reload Flows while it runs.
6. THE Publisher SHALL use the Flow_Name as the MCP tool name and as the last segment of the REST path, which is valid for both because a Flow_Name uses only the characters `a-z`, `0-9`, `-` and `_` (flow-runtime Glossary).
7. THE Publisher SHALL load the Flow_Registry without opening a session to the host.
8. WHEN the Publisher starts, THE Publisher SHALL load the Startup_Signatures with one call of `load_bundled_signatures()`, without opening a session to the host. IF the loading fails, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names the failed loading and holds no value, and SHALL publish no Flow.
9. WHERE `GS_PUBLISH_FLOWS` is set to a non-empty value, THE Flow_Registry SHALL contain exactly the Loaded_Flows named in the Publish_List, in loading order (bundled Flows first, then the Flows of `GS_FLOWS_DIR` in file name order) and not in list order. Names match exactly and case-sensitively.
10. THE Config_Loader SHALL parse `GS_PUBLISH_FLOWS` by splitting the text at each comma and trimming whitespace around each item.
11. IF an item of the Publish_List is empty after trimming (for example a trailing comma, two adjacent commas, or a value that holds only whitespace), THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names `GS_PUBLISH_FLOWS` and the rule `empty_item`, and SHALL publish no Flow.
12. IF a Flow_Name occurs twice in the Publish_List, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names `GS_PUBLISH_FLOWS`, the Flow_Name and the rule `duplicate_name`, and SHALL publish no Flow.
13. IF a Flow_Name of the Publish_List is not the name of a Loaded_Flow (bundled or from `GS_FLOWS_DIR`), THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names `GS_PUBLISH_FLOWS`, the Flow_Name and the rule `unknown_flow`, and SHALL publish no Flow. A Flow_Name is not a secret and may appear in the message. The checks of criteria 11, 12 and 13 run in this order, and the first failure is reported.
14. THE Publisher SHALL apply the Publish_List after it has loaded and validated ALL Flows, so that criteria 3 and 4 stop the startup for a Flow that the Publish_List would not select, and before it generates any schema or parses any Binding_Variable (Requirement 22).
15. A Loaded_Flow that is not a Published_Flow SHALL appear in no REST route, no OpenAPI path, no `tools/list` entry and no count of `GET /health`, and a Call that names it SHALL get `unknown_flow` through REST and through MCP, with the same body as for a name that no Loaded_Flow has, so that the response does not reveal whether such a Flow exists.

### Requirement 2: Schema Generation

**User Story:** As an API consumer, I want one machine-readable description of every Flow, so that MCP clients and REST clients see the same contract.

#### Acceptance Criteria

1. THE Schema_Generator SHALL be one pure function of a `Flow` and of the set of its Bound_Input names, whose result is used by the REST_Front_End, the OpenAPI document and the MCP_Front_End, so that no front end builds a schema of its own.
2. THE Schema_Generator SHALL derive its result only from `Flow.name`, `Flow.description`, the `InputSpec` entries, the `OutputSpec` entries and the names (never the values) of the Bound_Inputs.
3. THE Input_Schema SHALL have `type` `object`, `additionalProperties` `false`, one property per Input that is not a Bound_Input, in declaration order, and `required` listing exactly the Inputs with `required` true that are not Bound_Inputs (Requirement 22, criterion 1).
4. THE Input_Schema SHALL describe an Input of type `str` with `type` `string`, `maxLength` equal to `max_length`, and `pattern` equal to `^(?:<regex>)$` when the Input has a `regex`. It SHALL describe an Input of type `int` with `type` `integer`, a `maximum` of `10**max_length - 1` and a `minimum` of `-(10**(max_length - 1) - 1)` (0 when `max_length` is 1), so that the bounds equal the values whose `str()` has at most `max_length` characters.
5. WHERE an Input has `secret` true, THE Input_Schema SHALL set `writeOnly` to `true` on that property, and THE Schema_Generator SHALL set no `writeOnly` on any other property.
6. THE Schema_Generator SHALL copy `InputSpec.description` into the `description` of its property when it is not empty.
7. THE Schema_Generator SHALL emit no `default`, `examples`, `example`, `const` and `enum` member anywhere in a schema, and no value of any Input.
8. THE Input_Validator SHALL be the authority on whether Input values are accepted. THE Input_Schema SHALL NOT reject any set of values that the Input_Validator accepts over the Inputs that are not Bound_Inputs (Property 2).
9. THE Output_Schema SHALL have `type` `object`, `additionalProperties` `false`, one property per Output in declaration order (`type` `string` or `integer` by Output type) and `required` listing every Output.
10. THE Success_Schema SHALL describe a Success_Body: `flow` (string), `outputs` (the Output_Schema) and `audit` (an array of Audit_Summary entries with exactly the members of Glossary entry Audit_Summary).
11. THE Output_Schema and the Success_Schema SHALL contain no property that comes from an Input, so that a Secret_Input never appears in an output description.
12. FOR ALL equal Flows, two calls of the Schema_Generator SHALL return equal results, and every schema it returns SHALL be a valid JSON Schema document under the draft 2020-12 meta-schema (Property 1).
13. WHERE a `regex` of an Input is not accepted by `re.compile`, THE Flow_Validator of flow-runtime has already rejected the Flow, so the Schema_Generator SHALL NOT handle that case.

### Requirement 3: Call Lifecycle

**User Story:** As a caller, I want each call to run in its own clean session, so that one call cannot see or disturb another.

#### Acceptance Criteria

1. THE Call_Handler SHALL execute every Call, from REST or from MCP, with the same steps in this order: resolve the Flow, validate the Inputs (Requirement 4), acquire a Slot (Requirement 9), merge the Bound_Values (Requirement 22, criterion 6), obtain a session from the Session_Factory and open it, run `run_flow` on a worker thread, close the session, release the Slot, and build the response.
2. THE Call_Handler SHALL open a new session for every Call and SHALL NOT reuse, pool or share a session between Calls.
3. WHEN `run_flow` returns or raises, whatever the outcome, THE Call_Handler SHALL call `close` on the session exactly once before it releases the Slot.
4. IF opening the session raises, THEN THE Call_Handler SHALL still call `close` on the session object if one was created, SHALL release the Slot, and SHALL return `host_unavailable`.
5. IF `close` raises, THEN THE Call_Handler SHALL ignore the exception for the response, SHALL release the Slot, and SHALL write one Call_Log_Record field `close_failed` with the value `true`. The log record SHALL NOT contain the text of the exception. This applies to an `Exception` only: a `BaseException` that is not an `Exception` raised by `close` is handled as in Requirement 6, criterion 8 (re-raised unchanged after teardown and Slot release, like one raised by `run_flow`) and does NOT set `close_failed`. The Call SHALL be signalled as ended on every exit path of the worker, so that a `BaseException` from `close` never leaves the Call waiting for its deadline.
6. IF the Call is cancelled (for example because the client disconnected), THEN THE Call_Handler SHALL tear down the session as in Requirement 10, criterion 3 before it re-raises the cancellation, and the Call_Log_Record carries the `outcome` and `session_clean` of Requirement 23, criteria 3 and 4.
7. THE Call_Handler SHALL pass to `run_flow` the Flow from the Flow_Registry, the session, the validated Input mapping merged with the Bound_Values, the Startup_Signatures as the `signatures` argument, and nothing else except the optional `clock` and `poll_interval` of the Session_Factory seam (Requirement 19, criterion 1). THE Call_Handler SHALL NOT load Signatures during a Call.
8. THE Call_Handler SHALL NOT call `run_flow` on the event loop thread.
9. WHEN `run_flow` has returned or raised, THE Call_Handler SHALL release every reference to the Input mapping, to the supplied values, to the Bound_Values and to any `Screen` before it builds the response, so that no frame of `greenscreen.publisher` holds them when the Call ends.
10. WHILE the Publisher is shutting down, THE Call_Handler SHALL reject a new Call with `shutting_down` before it validates anything beyond the Flow name.

### Requirement 4: Input Validation Before the Host

**User Story:** As an operator, I want a bad call refused before it touches the mainframe, so that wrong requests cost no host session.

#### Acceptance Criteria

1. WHEN a Call arrives, THE Call_Handler SHALL apply the Input_Validator to the supplied Input values before it acquires a Slot and before it calls the Session_Factory.
2. IF the Input_Validator rejects a value, THEN THE Call_Handler SHALL return `input_invalid` with a `message` equal to the `str()` of the `FlowInputError`, which names the Input and the violated rule and holds no value (flow-runtime Requirement 2, criterion 9), and SHALL call the Session_Factory zero times.
3. WHEN the request body is not a JSON object, or has a duplicate key at any depth, or contains `NaN`, `Infinity` or `-Infinity`, or a JSON `true` or `false` where an `int` Input is declared, THE Call_Handler SHALL return `request_invalid` or `input_invalid` as the case defines (a body that is not a JSON object, a duplicate key and a non-finite number give `request_invalid`; a boolean in an `int` Input gives `input_invalid`) and SHALL call the Session_Factory zero times.
4. WHEN a JSON number for an `int` Input has a fraction or an exponent (for example `1.0` or `1e3`), THE Call_Handler SHALL treat it as a value of type `float`, and THE Input_Validator SHALL reject it with the rule `type`. The Input_Schema is advisory (Requirement 2, criterion 8) and MAY accept an integral float such as `1.0` for an `integer` property, because JSON Schema 2020-12 counts it as an integer; the rejection is the work of the Input_Validator.
5. IF the request body is larger than `GS_MAX_BODY_BYTES`, THEN THE REST_Front_End SHALL return `request_too_large` as an Error_Body without reading the rest of the body into memory and SHALL call the Session_Factory zero times. On the MCP endpoint `/mcp`, the size limit is the transport's own limit, set to `GS_MAX_BODY_BYTES`, and the MCP SDK answers an oversize body with its own plain-text 413 response and not with an Error_Body. That answer SHALL contain no part of the body, and the Session_Factory SHALL be called zero times.
6. THE Call_Handler SHALL validate MCP arguments with the same Input_Validator, because the low-level `Server` of the MCP SDK does not validate tool arguments before the handler runs, and the Publisher does not use `MCPServer`, which validates against a model built from a function signature and puts the submitted value into its error text (Requirement 14, criterion 10).
7. THE Call_Handler SHALL NOT put a submitted value in any error message, attribute or response of this requirement (Requirement 7, criterion 5).

### Requirement 5: Success Response and Audit Summary

**User Story:** As a compliance reviewer, I want every successful call to return the declared outputs and a value-free record of what ran.

#### Acceptance Criteria

1. WHEN `run_flow` returns a `FlowResult`, THE Call_Handler SHALL return a Success_Body whose `flow` is the Flow_Name, whose `outputs` is the `FlowResult.outputs` mapping in declaration order, and whose `audit` is the Audit_Summary of `FlowResult.audit`.
2. THE Call_Handler SHALL build each Audit_Summary entry with exactly the members `step_index`, `kind`, `phase`, `iteration`, `signature`, `status` and `duration_seconds`, copied from the `AuditRecord`, and no other member.
3. THE Success_Body SHALL validate against the Success_Schema of its Flow (Property 3).
4. THE Success_Body SHALL contain no Input value, no Redacted_Summary and no Host_Data.
5. THE Success_Body SHALL hold Output values only as `str` or `int`, as `FlowResult` guarantees (flow-runtime Requirement 3, criterion 9).

### Requirement 6: Error Mapping

**User Story:** As a caller, I want every failure to arrive in one structured shape with a code I can act on, and without anything that helps an attacker.

#### Acceptance Criteria

1. THE Error_Body SHALL be `{"error": {"code": <Error_Code>, "message": <fixed text>, ...}}`, where `message` is a fixed text that depends only on the `code` (Requirement 6, criterion 6 gives the one exception).
2. IF `run_flow` raises a `FlowError` that is not a `FlowInputError`, THEN THE Call_Handler SHALL return an Error_Body whose `code` is `FlowError.reason` and whose `error` object also holds `step_index`, `kind`, `expected` (a list), `summary` (the `to_dict()` of the Redacted_Summary, or `null`) and `audit` (the Audit_Summary). It SHALL hold no other member and SHALL NOT use `str(exc)` or `repr(exc)`.
3. IF a `FlowInputError` is raised, THEN THE Call_Handler SHALL return `input_invalid` as in Requirement 4, criterion 2.
4. IF `run_flow` raises a `FlowDefinitionError`, any other `Exception`, or a `ConnectorError` of any subclass (`S3270Error`, `ConnectorTimeoutError`, `ParseError`, `ConfigurationError`, `SessionClosedError`) outside the session open, THEN THE Call_Handler SHALL return `internal_error`. IF opening the session raises any `Exception`, THEN THE Call_Handler SHALL return `host_unavailable`. In both cases the `message` is the fixed text of the code and the `error` object holds no member beyond `code` and `message`.
5. THE Publisher SHALL map every one of the 13 Reason_Codes and every one of the 9 Publisher_Codes to exactly one HTTP status, and SHALL define that table in the design document. THE Publisher SHALL map every Error_Code to an MCP result with `isError` true and the same Error_Body as `structuredContent` (Property 4).
6. THE `error` object of `input_invalid` SHALL hold a `message` equal to the `str()` of the `FlowInputError` (Requirement 4, criterion 2), and no other `message` SHALL depend on a runtime value.
7. THE Call_Handler SHALL read none of the attributes `S3270Error.data_lines`, `S3270Error.status_line`, `ParseError.raw`, and SHALL NOT call `str()` or `repr()` on any exception that is not a `FlowInputError`, so that Host_Data cannot reach a response.
8. WHEN a `BaseException` that is not an `Exception` leaves `run_flow` or `close` (for example `KeyboardInterrupt`), THE Call_Handler SHALL tear down the session (Requirement 3, criterion 3), release the Slot and let that exception propagate unchanged, and SHALL NOT convert it to an Error_Body.
9. THE REST_Front_End SHALL replace every default error handler of its web framework, including the validation handler (the default 422 response echoes submitted values), the not-found handler, the method-not-allowed handler and the unhandled-exception handler, with handlers that return an Error_Body of this requirement.
10. THE REST_Front_End SHALL wrap the whole application in the Crash_Guard, the outermost ASGI layer, because replacing the handlers is not enough: the web framework sends the response of the replaced unhandled-exception handler and then re-raises the exception, so that the HTTP server would log a traceback that holds the exception text. IF an `Exception` reaches the Crash_Guard, THEN THE Crash_Guard SHALL catch it, SHALL ensure that the client receives the `internal_error` Error_Body, and SHALL write one log record with a fixed text and no exception text, no traceback and no `exc_info`. Cancellation and other `BaseException` that is not an `Exception` SHALL pass through the Crash_Guard.

### Requirement 7: Secrets and Host Data Never Leave

**User Story:** As a security reviewer, I want a guarantee, proven by property tests, that no input value, secret or host data can be read back from the Publisher.

#### Acceptance Criteria

1. FOR ALL Published_Flows, all valid Input values (Probe_Values), all Bound_Values (Probe_Values set through Binding_Variables) and all outcomes of the Fake_Host (success, every Reason_Code, every injected failure), no HTTP body, HTTP header or MCP result (`content` text and `structuredContent`) returned by the Publisher SHALL contain any Leak_Forms of any supplied Input value or of any Bound_Value. This holds as long as the screens of the Fake_Host do not contain the value, because Output text and Redacted_Summary rows legitimately repeat screen content. For the screen of `sentinel_password_screen`, which holds a residual password, the test SHALL supply that sentinel as the password and the rule still holds (Property 5).
2. FOR ALL the same generated Calls, including the startup and the shutdown of the Publisher with the generated Bound_Values set, no log record at any level, from any logger, including the root logger and the loggers `greenscreen`, `uvicorn`, `starlette`, `mcp`, `anyio`, `asyncio`, SHALL contain any Leak_Form of any supplied Input value or of any Bound_Value in its message, in any element of `args`, in `exc_text` or in `stack_info`. The test SHALL capture all loggers at DEBUG (Property 6).
3. FOR ALL generated failures injected by the Fake_Host, namely an `S3270Error` whose `data_lines` hold a marker, a `ConnectorTimeoutError`, a `ParseError` whose `raw` holds a marker, a `ConfigurationError`, a `SessionClosedError` and an arbitrary `Exception` whose message holds a marker, neither a response nor a log record SHALL contain the marker, the text `Traceback`, a file path of a frame, a `Screen` or `Field` repr, or the cell text of a hidden field (Property 7).
4. FOR ALL generated Calls, no Audit_Summary and no Redacted_Summary in a response SHALL contain a Leak_Form of an Input value, and the Redacted_Summary SHALL show every hidden cell as `*` (Property 8).
5. FOR ALL generated requests whose body or MCP arguments fail validation (wrong type, too long, regex violation, undeclared name, missing Input, malformed JSON, duplicate key, oversized body), the response SHALL contain no Leak_Form of any submitted value and no `input` member echoing a submitted value (Property 9).
6. WHEN an exception leaves a function of `greenscreen.publisher` (a cancellation, a `BaseException`, or an exception injected into the test seam), THE Publisher SHALL ensure that no traceback frame of module `greenscreen.publisher` holds in its locals an Input value, a Bound_Value, the Input mapping (supplied or merged with the Bound_Values), a Secret_Value, a `Screen` or a container that holds one, and that `"".join(traceback.format_exception(err))` with chain contains no Leak_Form of an Input value or of a Bound_Value (Property 10). The BoundValues_Store, and the objects of the Flow_Registry that are built from it, are the only permitted long-lived holders of Bound_Values between Calls; a frame may reference the BoundValues_Store, which has a `repr` that shows no value, but no value taken from it, and the BoundValues_Store SHALL NOT be logged or placed in an exception message or attribute. Everything transient (the supplied values, the merged mapping, a `Screen`, the request body, the parsed JSON, the MCP arguments) stays covered by this criterion.
7. THE Publisher SHALL NOT serialise, log, return or place in an exception message or attribute any of: an Input value, a Bound_Value, a Secret_Value, a `Screen` object, `S3270Error.data_lines`, a traceback, a frame local.
8. THE Publisher SHALL return no value of any Input and no Bound_Value in the OpenAPI document, in the output of `tools/list`, in the response of `/health`, in any message of a startup failure, or in any log record written at startup or at shutdown.
9. THE Publisher SHALL set the response header `Cache-Control: no-store` on every REST response.
10. THE Publisher SHALL NOT read `TK5_USERNAME` or `TK5_PASSWORD` and SHALL NOT read any file that can hold a credential. The Binding_Variables of Requirement 22 are the only way to supply an Input from the environment.

### Requirement 8: Logging

**User Story:** As an operator, I want a call log that tells me what happened and how long it took, without values.

#### Acceptance Criteria

1. THE Publisher SHALL write log records only through the standard `logging` module, under the logger name `greenscreen.publisher`.
2. WHEN a Call ends, THE Publisher SHALL write one Call_Log_Record at INFO level, whose `extra` fields are only: `call_id` (the Call_Id), `flow` (the Flow_Name, or `unknown` when the Flow is not published), `transport` (`rest` or `mcp`), `outcome` (`ok`, an Error_Code, or `cancelled`, criterion 8), `duration_ms` (an integer), `step_index` (an integer, present only on a failure that has one), `close_failed` (a boolean, present only when true) and `session_clean` (a boolean, present only when false, Requirement 23).
3. THE Publisher SHALL write every other log record from `greenscreen.publisher` with only these fields: a Flow_Name, an Error_Code, an integer count, a duration in milliseconds, the name of an environment variable, a file name, or a fixed message text.
4. THE Publisher SHALL NOT log a request body, a request header, a query string, an MCP argument, a response body, the API_Key, or the text of any exception.
5. THE Publisher SHALL start the HTTP server with its access log disabled, and SHALL NOT start it with a log level below INFO for `uvicorn`, `starlette`, `mcp`, `anyio` and `httpx2`, so that third-party records written at DEBUG cannot carry request data.
6. WHILE the transport is stdio, THE Publisher SHALL write all log records to stderr and SHALL write nothing to stdout except MCP protocol messages (Requirement 14, criterion 9). THE source of `greenscreen.publisher` SHALL contain no call of `print` unless the call passes a keyword argument `file` whose value is the attribute `sys.stderr`; a bare `print(...)` and `print(..., file=sys.stdout)` are not allowed. A static test checks this with the `ast` module (decision of 2026-11-17).
7. THE Publisher SHALL install on its stderr log handler a filter that replaces the traceback of any record, from any logger, by one fixed line that names only the exception class, the file name, the line number and the function of the innermost frame, with no exception message and no frame local. This is a defence for a future defect in a dependency; no requirement of this document relies on it, and the tests of Requirements 7 and 20 capture the records before this filter.
8. THE Publisher SHALL use the `outcome` value `cancelled` in a Call_Log_Record only, WHEN a Call in flight is cancelled while the Publisher is not shutting down (Requirement 23, criterion 3). `cancelled` is NOT an Error_Code: it SHALL NOT appear in a response body, an Error_Body, the OpenAPI document, an MCP result or the HTTP status table, and it SHALL NOT change the 13 Reason_Codes or the 9 Publisher_Codes.
9. WHEN a Call ends before a session is opened (a request rejected by the REST_Front_End before the Call_Handler runs, such as a wrong media type, malformed JSON, a duplicate key, a non-finite number, a body that is not a JSON object, an oversize body or any other `request_invalid` or `request_too_large`; an unknown Flow; a Call refused with `shutting_down`, `input_invalid` or `busy`), THE Publisher SHALL still write exactly one Call_Log_Record for it, with only the fields of criterion 2 that apply: `call_id`, `flow` (the Flow_Name when the Flow is published, otherwise `unknown`), `transport`, `outcome` (the Error_Code) and `duration_ms`, and no `step_index`, no `close_failed` and no `session_clean`. The record SHALL contain no submitted value, no part of the body and no header.
10. A request rejected by the Auth_Guard (Requirement 13, criterion 3) is not a Call, and THE Publisher SHALL write no Call_Log_Record for it. A request to a path that is not a Flow route (`/health`, `/openapi.json`, `/docs`, an unknown path) is not a Call either and writes no Call_Log_Record.
11. WHEN a `BaseException` that is not an `Exception` stored by the worker is re-raised after teardown (Requirement 6, criterion 8), THE Publisher SHALL write the Call_Log_Record with the `outcome` `internal_error`, which is an Error_Code and so is already one of the values of criterion 2.

### Requirement 9: Concurrency Limit

**User Story:** As an operator, I want a hard cap on simultaneous host sessions, so that a burst of calls cannot start unlimited s3270 processes or exhaust the host.

#### Acceptance Criteria

1. THE Limiter SHALL allow at most `GS_MAX_CONCURRENCY` Calls in flight, counted over REST and MCP together, in one Limiter that both front ends share.
2. WHEN a Call needs a Slot and `GS_MAX_CONCURRENCY` Slots are held, THE Call_Handler SHALL reject the Call at once with `busy`, SHALL NOT queue it, SHALL NOT wait for a Slot, and SHALL call the Session_Factory zero times.
3. THE Limiter SHALL release a Slot only after the session of the Call has been closed or torn down (Requirement 3, criterion 3), so that the number of live s3270 processes started by Calls never exceeds `GS_MAX_CONCURRENCY`.
4. THE Limiter SHALL release the Slot of every acquired Slot on every outcome, including success, any Error_Code, cancellation, and a `BaseException`.
5. THE Config_Loader SHALL read `GS_MAX_CONCURRENCY` as an integer from 1 to 64 with the default 1. The default of 1 avoids two simultaneous logons of the same user id, because the host allows one TSO session per user id (verified 2026-11-17, mainframe-host steering): a second logon is refused with `IKJ56425I LOGON REJECTED, USERID <id> IN USE`, and a Flow that logs on then stops with `unknown_screen` at the Expect of `tso-password-prompt` (Open items, item 1). With a limit above 1 and the same Bound_Values for the user id and password, a concurrent Call therefore fails in this way.
6. FOR ALL generated sequences of concurrent Calls with generated outcomes, the count of Calls in flight SHALL never exceed the limit, the count of Slots held SHALL return to zero when all Calls ended, and every rejected Call SHALL have opened no session (Property 11).

### Requirement 10: Call Timeout

**User Story:** As an operator, I want every call to end within a known time, even when the host or s3270 hangs.

#### Acceptance Criteria

1. THE Config_Loader SHALL read `GS_CALL_TIMEOUT` as a number of seconds from 1 to 900 with the default 180.
2. THE Call_Handler SHALL compute the Call_Deadline of a Call as the smaller of `GS_CALL_TIMEOUT` and the sum of `Flow.timeouts.run`, `Flow.timeouts.finally_` and 30 seconds (the allowance for opening the session), and SHALL start measuring it when the Slot is acquired.
3. WHEN the Call_Deadline elapses before the Call has ended, THE Call_Handler SHALL call `abort()` of the session (Glossary, Session_Factory) from outside the worker thread, SHALL wait for the worker thread to end, SHALL release the Slot only after that, and SHALL return `call_timeout`, so that no s3270 process of that Call remains running. `abort()` is the only operation that the Call_Handler performs on the session from another thread, and it does not use the send path of the session. Design shows why this is safe for a Connector that is not documented as thread-safe.
4. AFTER `abort()` of a session has been called, no Session call of that session SHALL succeed, and THE Publisher SHALL NOT leave a worker thread of an expired Call able to send any further key to the host after `call_timeout` was returned.
5. WHEN a Call has ended by `call_timeout`, THE Publisher SHALL return the Error_Body without `step_index`, `summary` or `audit`, because the worker has not returned them.
6. WHEN a Call ends by `call_timeout`, THE Publisher SHALL NOT run the `finally` steps of the Flow, and the user id on the host may stay logged on (Assumptions; Requirement 23).

### Requirement 11: REST API

**User Story:** As a developer of a modern application, I want a plain HTTP endpoint for each Flow.

#### Acceptance Criteria

1. THE REST_Front_End SHALL serve `POST /flows/{name}` for each Published_Flow, whose JSON request body is the Input mapping of the Flow and whose response body is a Success_Body or an Error_Body with media type `application/json`.
2. IF the request does not have the media type `application/json`, THEN THE REST_Front_End SHALL return `request_invalid`.
3. IF the path is `/flows/{name}` and `{name}` is not the name of a Published_Flow (this includes a Loaded_Flow that the Publish_List leaves out, Requirement 1, criterion 15), THEN THE REST_Front_End SHALL return `unknown_flow` after the API_Key check and before any body parsing. `unknown_flow` is returned for no other path.
4. THE REST_Front_End SHALL serve `GET /health`, which returns a JSON object with exactly the members `status` (the text `ok`) and `flows` (the number of Published_Flows, which excludes every Loaded_Flow that the Publish_List leaves out), SHALL call the Session_Factory zero times, SHALL read no host setting, and SHALL NOT return a host name, a port or a Flow_Name.
5. THE REST_Front_End SHALL serve no route beyond `POST /flows/{name}`, `GET /health`, `GET /openapi.json`, the optional docs page (Requirement 12, criterion 6) and the MCP mount (Requirement 14, criterion 5). WHEN a request, after the API_Key check, names any other path, THE REST_Front_End SHALL return an Error_Body with the Error_Code `request_invalid`. The HTTP status is the one that the design table of Requirement 6, criterion 5 gives for `request_invalid`, because that table allows one status per code.
6. THE REST_Front_End SHALL answer a request to a Flow route with a method other than `POST` with an Error_Body of `request_invalid`, with the same HTTP status as in criterion 5.
7. THE REST_Front_End SHALL return every response of a Call as exactly one of a Success_Body or an Error_Body.

### Requirement 12: OpenAPI Document

**User Story:** As an integrator, I want generated API documentation that matches what the endpoints really accept.

#### Acceptance Criteria

1. THE REST_Front_End SHALL serve `GET /openapi.json`, an OpenAPI 3.1 document generated at startup from the Flow_Registry.
2. THE OpenAPI document SHALL contain one path item `/flows/<Flow_Name>` per Published_Flow, with a `post` operation whose `operationId` is the Flow_Name, whose `summary` is the Flow description (or the fixed text `Run flow <Flow_Name>.` when the description is empty), whose request body schema is the Input_Schema and whose `200` response schema is the Success_Schema.
3. THE OpenAPI document SHALL describe, for each Error_Code that has an HTTP status in the table of Requirement 6, criterion 5, a response with the schema of the Error_Body, and SHALL list the Error_Codes of that status.
4. THE OpenAPI document SHALL declare two security schemes, one of type `apiKey` in the header `X-API-Key` and one of type `http` with scheme `bearer`, and SHALL list them as alternatives on every Flow operation, as two security requirement objects with one scheme each. THE `GET /health` operation SHALL declare no security requirement.
5. THE OpenAPI document SHALL be valid under the OpenAPI 3.1 JSON Schema dialect checks of the Test_Suite, and every schema it embeds SHALL equal the schema returned by the Schema_Generator for the same Flow (Property 1).
6. WHERE `GS_ENABLE_DOCS` is `true`, THE REST_Front_End SHALL serve an interactive documentation page at `/docs`, protected by the same API_Key check. Otherwise THE REST_Front_End SHALL serve no documentation page. A browser navigation cannot send the key header, so the page is usable only by a client that can set a header; this is a known limitation, and the page is off by default.
7. THE OpenAPI document SHALL contain no value, no default and no example of any Input (Requirement 2, criterion 7).

### Requirement 13: Authentication

**User Story:** As an operator, I want every Flow call protected by a key that lives in the environment, so that no secret is in the repository.

#### Acceptance Criteria

1. THE Config_Loader SHALL read the API_Key only from the environment variable `GS_API_KEY`, and the Publisher SHALL read no key from a file, a command line argument or the repository.
2. WHILE the transport is `http` and `GS_AUTH_DISABLED` is not the exact text `true`, THE Auth_Guard SHALL require a valid API_Key in a Key_Carrier on every route except `GET /health`, including `GET /openapi.json`, `/docs` and the MCP endpoint. A key in the header `X-API-Key` and a key in the header `Authorization` with the form `Bearer <key>` are equally valid.
3. IF a request to a protected route presents no key, a key that differs from the API_Key, or a key in a form that criterion 11 rejects, THEN THE Auth_Guard SHALL return `unauthorized` with the same fixed body in every one of these cases, SHALL not open a session and SHALL not parse the body.
4. THE Auth_Guard SHALL compare every presented key and the API_Key with a constant-time comparison (`hmac.compare_digest` on UTF-8 bytes).
5. IF the transport is `http`, `GS_AUTH_DISABLED` is not `true` and `GS_API_KEY` is unset or has fewer than 16 characters, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names `GS_API_KEY` and the rule, without any value.
6. IF `GS_AUTH_DISABLED` is `true` and `GS_PUBLISH_HOST` is not a loopback address (`127.0.0.0/8`, `::1` or `localhost`), THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names `GS_AUTH_DISABLED` and `GS_PUBLISH_HOST`.
7. WHILE `GS_AUTH_DISABLED` is `true`, THE Auth_Guard SHALL return `unauthorized` for a request whose `Host` header does not name a loopback host, so that a web page in a browser cannot reach the Publisher through DNS rebinding.
8. THE Publisher SHALL NOT write the API_Key, any supplied key, the `X-API-Key` header or the `Authorization` header into a log record, a response, an exception message or the OpenAPI document.
9. FOR ALL generated key strings that differ from the API_Key, in either Key_Carrier, for ALL generated pairs of differing values in both Key_Carriers, for ALL generated malformed `Authorization` headers, and for a present but empty `X-API-Key` header with or without a valid `Authorization` header, a request to a Flow route SHALL return `unauthorized`, SHALL leave the Fake_Host session count at zero and SHALL put no Input value and no Bound_Value in the response. The valid API_Key in either Key_Carrier, or in both when the two values are equal, SHALL be accepted (Property 13).
10. WHILE the transport is `stdio`, THE Publisher SHALL ignore `GS_API_KEY` and require no key, because the caller owns the process.
11. THE Auth_Guard SHALL extract the presented key by these rules, and a request that breaks one of them is `unauthorized`:
    - the `X-API-Key` header value is the key; a present but empty `X-API-Key` header is malformed, and the request is `unauthorized` even when a valid `Authorization: Bearer` header is also presented;
    - the `Authorization` header must consist of the scheme word `Bearer`, matched case-insensitively (RFC 9110), one or more spaces, and credentials of at least 1 character without whitespace, and the credentials are the key; any other `Authorization` header, including another scheme or a missing credential, is malformed;
    - a header that occurs more than once in the request is invalid;
    - IF both Key_Carriers are present, THEN both SHALL be well formed and equal to each other, and the common value SHALL equal the API_Key; a pair that differs, or a malformed `Authorization` header next to a valid `X-API-Key`, is `unauthorized`;
    - a malformed `Authorization` header without an `X-API-Key` header is `unauthorized`.
12. THE Auth_Guard SHALL apply criteria 2 to 4 and 11 identically to the REST routes, `GET /openapi.json`, `/docs` and the MCP endpoint, so that an MCP client can send either Key_Carrier.

### Requirement 14: MCP Server

**User Story:** As an AI-agent builder, I want each Flow as an MCP tool over stdio or HTTP, with a schema my agent can read.

#### Acceptance Criteria

1. THE MCP_Front_End SHALL serve one tool per Published_Flow, with `name` equal to the Flow_Name, `description` equal to the Flow description (or the fixed text `Run flow <Flow_Name>.` when empty), `inputSchema` equal to the Input_Schema and `outputSchema` equal to the Success_Schema.
2. WHEN `tools/call` names a Published_Flow, THE MCP_Front_End SHALL run the Call_Handler with the arguments of the call and return a Success_Body as `structuredContent` and as one text content block that holds the same JSON.
3. IF the Call_Handler returns an Error_Body, THEN THE MCP_Front_End SHALL return a result with `isError` true, the Error_Body as `structuredContent` and as one text block holding the same JSON.
4. IF `tools/call` names a tool that is not published (including a Loaded_Flow that the Publish_List leaves out), THEN THE MCP_Front_End SHALL return an error result with the code `unknown_flow` and no argument value.
5. THE MCP_Front_End SHALL support the transports `stdio` and Streamable HTTP, both fed from the same Flow_Registry and the same Call_Handler. WHEN the transport is `http`, THE Publisher SHALL serve the MCP endpoint at the path `/mcp` of the same ASGI application, on the same port as the REST_Front_End, protected as in Requirement 13.
6. THE MCP_Front_End SHALL catch every `Exception` that a tool call can raise inside the Call_Handler and convert it to an Error_Body, so that no exception reaches the SDK error path. In the low-level `Server` that path writes an ERROR record with the traceback (whose frames hold the values) in every protocol era, and sends the exception text to a client of the 2025 handshake era and `Internal server error` to a client of the 2026-07-28 era (Documentation checked). Cancellation is the only exception that propagates (Requirement 3, criterion 6).
7. THE MCP_Front_End SHALL return the same Success_Body or the same Error_Body as the REST_Front_End for the same Flow, the same Input values and the same behaviour of the host, with only the envelope differing (Property 3).
8. THE MCP_Front_End SHALL NOT register any resource, prompt or tool other than the published Flows.
9. WHILE the transport is `stdio`, THE Publisher SHALL write only MCP protocol messages to stdout, with nothing else on any byte of stdout, including during startup, shutdown and failures.
10. THE MCP_Front_End SHALL use the low-level `mcp.server.lowlevel.Server` of `mcp` 2.x with hand-written tool schemas (the Input_Schema and the Success_Schema), and SHALL NOT use `MCPServer`, because `MCPServer` validates arguments with a model built from the function signature and its validation error text, which the client receives, echoes the submitted value. THE MCP_Front_End SHALL pass transport options (host, port, paths) to the transport entry points, as the SDK requires.
11. WHILE the transport is `stdio`, THE Publisher SHALL, before it starts serving, duplicate the standard input and output descriptors for the protocol streams, point the descriptor 1 and `sys.stdout` at stderr, and give the SDK only the duplicated streams, so that a `print` or a write to descriptor 1 anywhere in the process goes to stderr. This is required because the SDK's own redirection was not effective on Windows (design, "Documentation checked").

### Requirement 15: Configuration

**User Story:** As an operator, I want the Publisher configured only through the environment, with clear errors, so that no config file can hold a credential.

#### Acceptance Criteria

1. THE Config_Loader SHALL read exactly these environment variables:
   - the mainframe settings read by `ConnectorConfig`: `GS_HOST`, `GS_PORT`, `GS_S3270_BINARY`;
   - the Publisher settings: `GS_PUBLISH_HOST` (default `127.0.0.1`), `GS_PUBLISH_PORT` (default 8080, range 1 to 65535), `GS_TRANSPORT` (`http` or `stdio`, default `http`), `GS_API_KEY`, `GS_AUTH_DISABLED`, `GS_MAX_CONCURRENCY`, `GS_CALL_TIMEOUT`, `GS_FLOWS_DIR`, `GS_MAX_BODY_BYTES` (default 65536, range 1024 to 1048576), `GS_ENABLE_DOCS`, `GS_SHUTDOWN_GRACE` (seconds, default 10, range 1 to 120), `GS_PUBLISH_FLOWS` (comma-separated Flow names, no default; unset or empty publishes every Loaded_Flow; parsed and checked under Requirement 1, criteria 9 to 15);
   - the family of Binding_Variables with the prefix `GS_BIND_` (Requirement 22), and no other variable. `GS_MAX_CONCURRENCY` has the default 1 (Requirement 9, criterion 5).
2. THE Publisher SHALL use `GS_HOST` and `GS_PORT` only for the mainframe and `GS_PUBLISH_HOST` and `GS_PUBLISH_PORT` only for the address it listens on, and no variable for both.
3. THE Config_Loader SHALL read each variable once at startup, and SHALL treat an unset and an empty variable alike. For `GS_PUBLISH_FLOWS`, an unset or empty (zero-length) value publishes every Loaded_Flow, and a value that holds only whitespace is not empty and is rejected under Requirement 1, criterion 11.
4. IF a variable is invalid (an integer that is out of range or not an integer, a transport that is neither `http` nor `stdio`, a boolean that is neither `true` nor `false`), THEN THE Config_Loader SHALL stop the startup with a non-zero exit code and a message on stderr that names the variable and the violated rule and holds no value of the variable. THE CLI SHALL print the message with `print(..., file=sys.stderr)` (Requirement 8, criterion 6).
5. WHEN the Publisher starts, THE Config_Loader SHALL build a `ConnectorConfig` once, so that a missing `GS_HOST` or `GS_S3270_BINARY` (a `ConfigurationError`) stops the startup with a message that names the parameter, and THE Publisher SHALL NOT open a session to the host at startup.
6. THE Publisher SHALL read no configuration file and SHALL define no file format that can hold a credential.
7. THE repository MAY hold a `.env.example` that lists variable names with empty values and comments, and SHALL NOT hold a file with a non-empty `GS_API_KEY`, a non-empty Binding_Variable, a host credential or a Probe_Value.
8. WHEN the Config_Loader has read the environment, THE Publisher SHALL remove `GS_API_KEY` and every Binding_Variable from the process environment, so that the s3270 processes that the Publisher starts do not inherit them.

### Requirement 16: Startup and Shutdown

**User Story:** As an operator, I want the Publisher to stop cleanly and leave no s3270 process behind.

#### Acceptance Criteria

1. WHEN the Publisher receives SIGTERM or SIGINT (or the stdio input closes), THE Publisher SHALL stop accepting Calls and answer new Calls with `shutting_down`.
2. WHEN shutdown has begun, THE Publisher SHALL wait up to `GS_SHUTDOWN_GRACE` seconds for Calls in flight to end, and then SHALL tear down every session that is still open (Requirement 10, criterion 3).
3. THE Publisher SHALL exit only after every session of every Call has been closed or torn down, so that no s3270 process started by the Publisher remains running.
4. IF a startup check of Requirement 1, 13, 15 or 22 fails, THEN THE Publisher SHALL exit with a non-zero code before it binds a port or reads from stdin, and SHALL have started no s3270 process.
5. IF the packages of the `publish` extra are not installed, THEN THE `greenscreen-publish` command SHALL exit with a non-zero code and a message that names the missing module and the extra `publish`, and importing `greenscreen.flow`, `greenscreen.connector` and `greenscreen.recognizer` SHALL NOT import `mcp`, `fastapi`, `starlette` or `uvicorn`.

### Requirement 17: ScreenView Caching Decision

**User Story:** As a maintainer, I want the open item from the flow-runtime design (decision table, row 18) closed with data, so that nobody adds a cache that could leak.

#### Acceptance Criteria

1. THE Publisher SHALL NOT cache a `ScreenView` or the result of `recognize`, and SHALL NOT add a cache key to the public API of `greenscreen.recognizer`.
2. THE decision records these measurements, taken on 2026-11-17 against the captures with the 7 bundled Signatures: `ScreenView` construction has a median of 0.81 ms (`ispf-primary-menu`) and 0.53 ms (`tk5-logon`), and `recognize` has a median of 0.81 ms and 0.56 ms, so view construction is almost the whole cost of `recognize`. A live read uses `ReadBuffer` through s3270 and polls every 0.1 s by default, so 0.8 ms is under 1% of a poll cycle. The earlier figure of "far above 0.72 ms" was not reproduced and was probably taken under property-test load.
3. THE reason for the decision is that a cache key would have to be derived from Screen contents, and those can include the text of hidden fields (Requirement 7).
4. THE Test_Suite SHALL include one test marked `@pytest.mark.perf` that recognizes each of the captures `tk5-logon`, `tso-password-prompt`, `ispf-primary-menu` and `tso-ready` 200 times with the bundled Signatures and fails when the median of one `recognize` call on any of them is above 5 ms. The test is a regression guard, not a benchmark.
5. IF a measurement on a live run shows a per-call overhead of `recognize` above 5% of the Poll_Interval (5 ms at the default 0.1 s) on the median, THEN a later spec MAY revisit this decision, and this spec does not.

### Requirement 18: Packaging and Dependencies

**User Story:** As a maintainer, I want the web and MCP dependencies kept out of the core library and approved before they are added.

#### Acceptance Criteria

1. THE Publisher SHALL be the package `greenscreen.publisher`, started by the console script `greenscreen-publish` (entry point under `[project.scripts]`), for Python 3.11 or later.
2. THE following dependencies were approved by the user on 2026-11-17 and SHALL be added to `pyproject.toml` when the packaging task runs: `mcp>=2.3,<3` (brings `starlette`, `uvicorn`, `pydantic`, `anyio`, `httpx2` and `jsonschema`) and `fastapi>=0.163,<1` (adds `annotated-doc`). The approval covers their transitive dependencies. The design lists the full set that pip resolved on 2026-11-17, 31 packages (more than the names above, for example `mcp-types`, `pyjwt`, `cryptography`, `sse-starlette` and `python-multipart`), all under permissive licenses. No other direct runtime dependency is approved.
3. WHEN the packaging task runs, THE `pyproject.toml` SHALL list the approved dependencies only under `[project.optional-dependencies]` in an extra named `publish`, and SHALL leave `dependencies` unchanged, so that the library keeps its `pyyaml`-only footprint. THE `dev` extra SHALL also pull the `publish` extra, because the publisher tests import `mcp` and `fastapi`.
4. THE Test_Suite SHALL use the ASGI test client of Starlette with `httpx2` (installed with `mcp`), `jsonschema` (installed with `mcp`), `hypothesis` and `pytest`, and no other test dependency.
5. THE dependencies and their transitive dependencies SHALL be under licenses compatible with MIT (the repository license), and THE design document SHALL list the license of each new package, direct and transitive.
6. THE `.kiro` directory SHALL NOT be git-ignored, and the Publisher SHALL add no entry to `.gitignore` that hides it.

### Requirement 19: Test Seam and Unit Tests

**User Story:** As a developer, I want to test the Publisher without a mainframe.

#### Acceptance Criteria

1. THE Publisher SHALL take the Session_Factory, and optionally a `clock` and a `poll_interval` for `run_flow`, as arguments of the function that builds the application, so that tests can pass a Fake_Host, and SHALL provide no environment variable, command line option or file that selects a Session_Factory. The sessions of the Session_Factory SHALL implement `open()`, `close()`, `abort()` and the Session protocol (Glossary, Session_Factory). The Startup_Signatures are loaded by the application at startup (Requirement 1, criterion 8), and the tests SHALL NOT patch `load_bundled_signatures` or any other loader.
2. THE Test_Suite SHALL provide the Fake_Host in `tests/publisher_support.py`, built on `ScriptedSession`, `FakeClock` and the capture helpers of `tests/flow_support.py`, with injectable failures at open, at each Session call and at close, and with a count of sessions opened, closed and aborted. Its sessions SHALL implement `abort()` (thread-safe, idempotent), and a session that was aborted SHALL raise from every later Session call and from a Session call that is blocked at the time of the `abort()`.
3. THE Test_Suite SHALL include unit tests in `tests/unit/` that pass without a terminal host and cover: each criterion of Requirements 1, 3, 4, 6, 8, 9, 10, 11, 13, 22 and 23; each of the 13 Reason_Codes and each Publisher_Code mapped to its Error_Body; the `GET /health` route with a Session_Factory that fails the test when called; the OpenAPI document of the three bundled Flows; `tools/list` and `tools/call` for the three bundled Flows; the replaced default error handlers (including a 422 case); the cases of Requirement 13, criterion 11, including a present but empty `X-API-Key` header next to a valid Bearer header; the answer of `/mcp` to an oversize body (Requirement 4, criterion 5); an unknown path and a wrong method (Requirement 11, criteria 5 and 6); the Crash_Guard with a real HTTP server and a captured log (no traceback, no exception text); and the `stdio` run with a check that every line of stdout parses as a JSON-RPC message, also when a handler prints and writes to descriptor 1.
4. THE Test_Suite SHALL include one unit test for the constant-time comparison (Requirement 13, criterion 4) that fails when `==` is used on the key.
5. THE Test_Suite SHALL include one unit test for each startup failure of Requirements 1, 13, 15, 16 and 22, each asserting a non-zero exit code, the message and that stdout and stderr hold no environment variable value, and for each startup failure of Requirement 22 that they hold no Leak_Form of the Bound_Value.
6. THE Test_Suite SHALL include one unit test that runs `tk5-system-info` through both front ends against the Fake_Host with screens from `captures/` and compares the Success_Bodies.
7. THE Test_Suite SHALL include one unit test for the shutdown of Requirement 16 with a Fake_Host whose session count shows that every opened session was closed.
8. THE Test_Suite SHALL include example-based unit tests (not property tests) for Requirement 23, one for each of the cases of its criteria 1 to 5: `unknown_screen` in the steps, `unknown_screen` in the `finally` phase, `timeout`, `call_timeout`, cancellation while the Publisher is not shutting down (`outcome` `cancelled`, asserted to appear in no response), cancellation while the Publisher is shutting down and shutdown teardown (`outcome` `shutting_down`), and the cases without a marker (a success, `unexpected_screen`, `loop_limit`, `host_unavailable`), each asserting the presence or absence of `session_clean` and that the record holds no value and no screen text.
9. THE Test_Suite SHALL include one unit test that calls `abort()` while a Session call of the Fake_Host is blocked, and asserts that the blocked call raises, that no Session call succeeds afterwards, that `abort()` called twice has the effect of one call, and that `close()` after `abort()` returns.
10. THE Test_Suite SHALL include example-based unit tests for the allow-list, one for each of Requirement 1, criteria 9 to 15, and for Requirement 22, criterion 7 (rule `flow_not_published`): unset and empty `GS_PUBLISH_FLOWS` publish every Loaded_Flow; a valid list publishes exactly the named Flows in loading order; whitespace around names is trimmed; a trailing comma, two adjacent commas and a whitespace-only value each stop the startup with the rule `empty_item`; a duplicate name stops it with `duplicate_name`; an unknown name stops it with `unknown_flow`; each failure asserts a non-zero exit code, a message that names `GS_PUBLISH_FLOWS`, no session opened and no port bound; an invalid Flow file in `GS_FLOWS_DIR` that the list would leave out still stops the startup; an unpublished Flow is absent from the routes, the OpenAPI document, `tools/list` and the `/health` count, and a call to it through REST and through MCP gives the same `unknown_flow` body as an unknown name; a `GS_BIND_*` variable for a Loaded_Flow that is not published stops the startup naming the variable and `flow_not_published`.
11. THE Test_Suite SHALL include one example-based unit test for each kind of rejection of Requirement 8, criterion 9 (wrong media type, malformed JSON, duplicate key, non-finite number, non-object body, oversize body with `Content-Length`, oversize chunked body, unknown Flow, `input_invalid` over REST and over MCP, `busy`, `shutting_down`), asserting that exactly one Call_Log_Record is written, that it has only the allowed fields (`call_id`, `flow`, `transport`, `outcome`, `duration_ms`) with the Error_Code as `outcome` and `unknown` as `flow` for an unpublished Flow, and that it holds no submitted value, no part of the body and no header. One further test asserts that a request rejected by the Auth_Guard, `GET /health` and an unknown path write no Call_Log_Record (Requirement 8, criterion 10).

### Requirement 20: Property-Based Tests

**User Story:** As a maintainer, I want every "never" rule and every generated contract checked on generated data.

#### Acceptance Criteria

1. THE Test_Suite SHALL include one Hypothesis property test for each of the 14 properties below, each as exactly one `@given` test with `@settings(max_examples=100, deadline=None)` or a higher `max_examples`, each starting with the comment `# Feature: publisher, Property N: <title>`.
2. Property 1, schema validity: FOR ALL valid Flows, the Input_Schema, the Output_Schema and the Success_Schema are valid draft 2020-12 JSON Schemas, equal Flows give equal schemas, `writeOnly` is `true` exactly on the secret Inputs, no schema contains `default`, `examples`, `example`, `const` or `enum`, and the OpenAPI document embeds the same schemas.
3. Property 2, schema and runtime agree: FOR ALL Flows and all generated JSON mappings (valid values, wrong types, booleans, floats, overlong strings, undeclared names, missing Inputs), the Input_Validator is the authority and the agreement is one-directional. Every mapping that the Input_Validator accepts also validates against the Input_Schema. For the other direction, the property restricts itself to mappings that violate the `type`, `required`, `additionalProperties` or `maxLength` rule in a way that JSON Schema also rejects, and those are rejected by both; it excludes integral floats such as `1.0` and `1e3`, which the Input_Schema may accept for an `integer` property and which the Input_Validator rejects with the rule `type` (a unit test covers that case). The same property covers generated sets of Bound_Inputs: the reduced Input_Schema accepts every mapping that the Input_Validator accepts over the Inputs that are not Bound_Inputs, a mapping that supplies a Bound_Input name is rejected by both, and a Flow with all Inputs bound has a schema with empty `properties` and no `required` that accepts only `{}`.
4. Property 3, front-end parity and success shape: FOR ALL Published_Flows and generated Input values, the same Fake_Host behaviour gives through REST and through MCP the same outputs, or the same Error_Code with the same `step_index`, `kind`, `expected`, `summary` and Audit_Summary, and every Success_Body validates against its Success_Schema.
5. Property 4, error mapping totality: FOR ALL Reason_Codes and all injected exception classes (`FlowError`, `FlowInputError`, `FlowDefinitionError`, `S3270Error`, `ConnectorTimeoutError`, `ParseError`, `ConfigurationError`, `SessionClosedError`, `OSError`, `RuntimeError`, an arbitrary `Exception` subclass), the response has exactly one Error_Code, exactly one HTTP status and an MCP `isError` result, the same `message` text for the same code (except `input_invalid`), and no member outside the allowed members of Requirement 6. The scenarios include a `BaseException` that is not an `Exception` raised at the Session_Factory, at `open` and at `close` (as well as by a Session call): it is re-raised unchanged after the session was closed and the Slot released, and no Error_Body is built for it.
6. Property 5, no value in responses (Requirement 7, criterion 1), generated over supplied Input values and over Bound_Values, with the Bound_Input marked secret and not marked secret.
7. Property 6, no value in logs (Requirement 7, criterion 2), generated over supplied Input values and over Bound_Values, including the log records of startup and shutdown.
8. Property 7, no Host_Data in responses and logs (Requirement 7, criterion 3).
9. Property 8, audit and summary free of secrets (Requirement 7, criterion 4).
10. Property 9, validation errors never echo (Requirement 7, criterion 5). The strategy draws undeclared Input names from an alphabet disjoint from the Probe_Value alphabet, because the `input_invalid` message may name an undeclared Input by design (Glossary, Probe_Value).
11. Property 10, no values in exception frames (Requirement 7, criterion 6), generated over supplied Input values and over Bound_Values and over the merged mapping. The frame scan treats the BoundValues_Store and the Flow_Registry objects as opaque, as Requirement 7, criterion 6 permits.
12. Property 11, Limiter (Requirement 9, criterion 6).
13. Property 12, session lifecycle: FOR ALL generated outcomes of the Fake_Host (success, every failure at open, at each Session call, at close, a timeout and a cancellation), every opened session is closed exactly once, the Slot count returns to zero, a Call that was rejected before the Slot (Requirements 4 and 13) opened zero sessions, and after `abort()` of a session no Session call of that session succeeds.
14. Property 13, authentication (Requirement 13, criterion 9), generated over wrong keys in either Key_Carrier, both Key_Carriers with differing values, malformed `Authorization` headers, a present but empty `X-API-Key` header with and without a valid Bearer header, and over the valid key in either Key_Carrier or in both when equal.
15. Property 14, binding variables (Requirement 22, criterion 12): FOR ALL generated sets of Flows and Binding_Variables (valid ones, names with a missing or empty part, empty values, unknown Flows or Inputs, Flows that a generated `GS_PUBLISH_FLOWS` leaves unpublished, generated allow-lists with empty items, duplicates and unknown names, normalised-name collisions, `-` and `_` variants, values that violate type, `max_length`, printable ASCII or `regex`), the Publisher either starts, with every Bound_Input absent from every schema, from the OpenAPI document and from `tools/list`, and with every Bound_Value accepted by the Input_Validator over the full `InputSpec`, or stops the startup with a message that names the variable, the Flow or the variable family and the rule, and holds no Leak_Form of any Bound_Value. In both cases no session was opened, no Bound_Value appears in any log record of startup and shutdown (at DEBUG, all loggers), in the response of `/health`, in the OpenAPI document or in the output of `tools/list`, and the outcome equals the outcome of a small independent model of Requirement 22.
16. THE Test_Suite SHALL place the property tests in `tests/property/test_publisher_*.py` and the shared strategies in `tests/property/_publisher_strategies.py`, and SHALL draw Probe_Values and Leak_Forms from those strategies.
17. THE Test_Suite SHALL complete the publisher property modules together in under 120 seconds, using the Fake_Host, the `FakeClock` and an in-process ASGI client (the Startup_Signatures are loaded once, so no loader is patched), and the whole of `tests/property` in under 240 seconds, with zero network connections and zero subprocesses started. These limits were raised from 25 and 115 seconds to 60 and 150 seconds on 2026-11-17 by the user's decision, after the measurements of Properties 12 and 13, and then to 120 and 240 seconds on the same day by the user's decision, after a clean serial run of the 14 publisher property modules took 74.7 s (pytest-reported) and `pytest -m "not integration"` took 301 s on a loaded machine. The 240 seconds replace the limit of flow-runtime Requirement 19, criterion 9 for the whole `tests/property` total. THE Test_Suite SHALL NOT be trimmed to meet the limits, and `max_examples` SHALL NOT be lowered below 100.
18. THE Test_Suite SHALL treat each of the 14 property tests as a required task.

### Requirement 21: Integration Test Against the Live Host

**User Story:** As a developer, I want one end-to-end test of the published endpoint against the real TK5 host.

#### Acceptance Criteria

1. THE Test_Suite SHALL include one test in `tests/integration/test_publisher_live.py`, marked `@pytest.mark.integration`, that starts the application with the default Session_Factory and the Flow `tk5-system-info`, and calls `POST /flows/tk5-system-info` through the ASGI test client.
2. IF `TK5_USERNAME` or `TK5_PASSWORD` is unset or empty, THEN THE test SHALL skip with a message that names each missing variable and SHALL NOT connect to the host. The test, and not the Publisher, reads these variables. The test passes them either as Input values of the call or as Binding_Variables set for the application under test (Requirement 22).
3. IF the `host_reachable` fixture of `tests/conftest.py` reports that the host is not reachable, THEN THE test SHALL skip with a message that states so.
4. WHEN the test runs, THE Publisher SHALL return a Success_Body whose `USERID` equals `TK5_USERNAME` under a case-insensitive comparison and whose `SYSTEMID` and `RELEASE` each have at least 1 non-whitespace character.
5. WHEN the test has finished, THE test SHALL assert that `TK5_PASSWORD` occurs in no response and in no log record captured at DEBUG from all loggers, in plain text and, when the password has at least 4 characters, in the Leak_Forms hex, base64 and URL-encoded.
6. WHEN the test has finished, THE test SHALL assert that no s3270 or ws3270 process started by the test is still running.

### Requirement 22: Bound Inputs

**User Story:** As an operator, I want to supply an Input such as the host user id or password from the environment, so that the caller never sends it and an AI agent never sees it.

#### Acceptance Criteria

1. THE Schema_Generator, the OpenAPI document and `tools/list` SHALL omit every Bound_Input: the Bound_Input is absent from the `properties` of the Input_Schema and from its `required` list, and no description, name or value of a Bound_Input appears anywhere in a schema, in the OpenAPI document or in the output of `tools/list`.
2. WHEN a caller supplies the name of a Bound_Input, THE Call_Handler SHALL return `input_invalid` exactly as for a name that no Input declares (the rule `undeclared`), SHALL call the Session_Factory zero times, and SHALL put no submitted value in the response.
3. THE Config_Loader SHALL identify the Binding_Variables by scanning the environment for names that start with the exact, case-sensitive prefix `GS_BIND_`, and SHALL split the rest of each name at the FIRST occurrence of two consecutive underscores `__` into a flow part and an input part. A variable that has no `__`, an empty flow part or an empty input part is invalid. A Binding_Variable that is empty is treated as unset (Requirement 15, criterion 3) and does not bind.
4. THE Config_Loader SHALL match names as follows: the normalised form of a Flow_Name or of an Input name is the name in upper case with every `-` replaced by `_`, and a Binding_Variable binds the Input of the Published_Flow whose normalised Flow_Name equals the flow part and whose normalised Input name equals the input part. The flow part is matched against the Loaded_Flows and not only against the Published_Flows, so that a variable for a Loaded_Flow that the Publish_List leaves out is reported as `flow_not_published` (criterion 7). The Config_Loader SHALL parse a Bound_Value by the declared type of its Input: for type `str` the value is the variable text verbatim, and for type `int` a text that matches `-?[0-9]+` (ASCII digits only) becomes an `int` and any other text is invalid.
5. WHEN the Publisher starts, THE Config_Loader SHALL apply the rules of the Input_Validator (type, `max_length`, printable ASCII and `regex`, each against the full `InputSpec` of the declaration) to every Bound_Value, so that a Bound_Value is accepted at startup exactly when the Input_Validator would accept it as a caller value.
6. WHEN a Call has passed the Input validation of Requirement 4 against the declaration reduced by the Bound_Inputs, THE Call_Handler SHALL merge the Bound_Values into the mapping handed to `run_flow`. A required Input that is bound is satisfied by its Bound_Value, a bound optional Input is always supplied, and a caller value SHALL NOT replace a Bound_Value because the caller cannot supply a bound name (criterion 2).
7. IF a Binding_Variable is invalid (criterion 3), names no Loaded_Flow (rule `unknown_flow`), names a Loaded_Flow that is not a Published_Flow (rule `flow_not_published`), names no Input of the matched Published_Flow, or holds a value that criterion 4 or 5 rejects, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message on stderr that names the variable and the violated rule, SHALL NOT include the value or any Leak_Form of it, and SHALL publish no Flow.
8. IF two Loaded_Flows have the same normalised Flow_Name, or two Inputs of one Published_Flow have the same normalised Input name, and a Binding_Variable has that flow part or that input part, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names the variable family (`GS_BIND_<flow part>__` or `GS_BIND_<flow part>__<input part>`) and the rule `ambiguous_name`, and SHALL NOT include any value.
9. IF at least one Binding_Variable is set and the normalised Flow_Name of a Published_Flow contains `__` or ends with `_`, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names the Flow_Name and the rule `ambiguous_name`, because the first `__` of a variable name could not then be told apart from a part of the Flow_Name.
10. THE Publisher SHALL treat every Bound_Value as a Secret_Value, whether or not the Input has `secret` true, in every requirement and every property of this document: the Bound_Value SHALL NOT appear in a response, a header, a log record of any level (including the records of startup and shutdown), an exception message or attribute, a traceback frame local (the BoundValues_Store of Requirement 7, criterion 6 excepted), the OpenAPI document, the output of `tools/list`, the response of `/health`, or a message of a startup failure (Requirement 7).
11. THE Publisher SHALL read Inputs from the environment only through Binding_Variables, and SHALL read no other environment variable for an Input (Requirement 7, criterion 10).
12. FOR ALL generated sets of Binding_Variables and Flows, the Publisher SHALL either start with every Bound_Input removed from every schema, or stop the startup under criterion 7, 8 or 9, and SHALL open no session at startup.

### Requirement 23: Session Clean Marker

**User Story:** As an operator, I want a call log marker for the calls after which the TSO user id may still be logged on, so that I can see why the next call fails with `unknown_screen`.

#### Acceptance Criteria

1. IF a Call ends with the Error_Code `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout` or `session_error`, whether the Flow stopped in its steps or in its `finally` phase, THEN THE Publisher SHALL write the Call_Log_Record with the field `session_clean` set to `false`. These are the reasons for which the flow runtime skips the `finally` steps and that reach the Publisher as a Flow stop. THE Publisher SHALL derive this set from the flow runtime's public `FINALLY_SKIP_REASONS` and SHALL NOT copy the reason names.
2. IF a Call ends with the Error_Code `call_timeout`, THEN THE Publisher SHALL write the Call_Log_Record with the field `session_clean` set to `false`, because the Flow's `finally` steps do not run after `abort()` (Requirement 10, criterion 6).
3. IF a Call is cancelled while it is in flight, THEN THE Publisher SHALL tear down the session as in Requirement 10, criterion 3 and SHALL write the Call_Log_Record with the field `session_clean` set to `false`. WHILE the Publisher is not shutting down (for example because the client disconnected), the `outcome` of that record SHALL be `cancelled`. WHILE the Publisher is shutting down, the `outcome` SHALL be `shutting_down` (criterion 4).
4. IF a Call in flight is torn down by the shutdown of Requirement 16, criterion 2, or is cancelled while the Publisher is shutting down, THEN THE Publisher SHALL write the Call_Log_Record with `outcome` `shutting_down` and the field `session_clean` set to `false`.
5. THE Publisher SHALL NOT set `session_clean` for any other outcome, including `ok`, `unexpected_screen`, `loop_limit`, `bad_target`, `secret_target`, `host_unavailable`, `input_invalid` and every other Error_Code outside the set of criteria 1 and 2. (`cancelled` and `shutting_down` as outcomes of a Call in flight are set under criteria 3 and 4; `shutting_down` for a Call rejected before it started has no `session_clean`.) The Publisher makes no claim about the state of the user id for those outcomes, and the absence of the field SHALL NOT be read as "clean".
6. THE field `session_clean` SHALL be a boolean that is present only with the value `false` (as `close_failed` is present only with `true`), SHALL be written as an `extra` field of the Call_Log_Record of Requirement 8, criterion 2, and SHALL carry no Input value, no Bound_Value, no screen text and no Host_Data.
7. THE Publisher SHALL NOT attempt to recover a user id that is logged on, SHALL NOT send `RECONNECT` and SHALL NOT retry a Call. Recovery of a user id left logged on at the ISPF primary option menu, at `READY`, at the cleared screen or at a ` REENTER -` prompt is done by the bundled Flows (the logon steps shared by all of them), which send `RECONNECT` when the host answers `IN USE`, not by the Publisher.
