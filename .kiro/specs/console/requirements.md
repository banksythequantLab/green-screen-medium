# Requirements Document

## Introduction

The console is one web page, served by the existing Publisher in HTTP mode, where a hackathon judge runs a published Flow against the live mainframe and sees what happened. It is the public face of the demo (served behind a tunnel at a host name that this spec does not hard-code) and it will be on screen in the demo video. The page lists the published Flows, runs one through the existing `POST /flows/{name}`, shows outputs, elapsed time and the audit trail, explains every error code in plain words, and shows a `curl` command and an MCP client config for the same call.

The console adds no execution path. Every call goes through `CallService.execute` exactly as a REST client's call does, whether the page reaches it through `POST /flows/{name}` or through the existing `POST /mcp` endpoint. The console adds only: a switch (`GS_ENABLE_CONSOLE`), six read-only routes that serve packaged static files, one narrow exemption in the API key check for exactly those routes, and a set of security headers on those routes.

Owner feedback after the first browser run was that the page "feels more like an emulator": nothing on screen showed the mainframe-to-MCP connection. Requirement 18 (MCP-visible Run) answers it. By default, Run performs a real MCP exchange against the Publisher's own `/mcp` endpoint (initialize, the initialized notification, `tools/list`, `tools/call`) and shows each JSON-RPC message in a wire transcript (one readable line per message, each line expanding to the full JSON), a strip of the three stages with counts taken from that run's audit as the first element of the result, and the MCP client configuration next to the Flow. The REST path stays available and unchanged.

### Findings from reading the code

**Finding 1: the REST response already carries the audit trail. No change to any response is needed.** Checked in `greenscreen/publisher/calls.py`: `CallService._finish` builds the success body as `{"flow", "outputs", "audit"}` (lines 618 to 622, `"audit": audit_to_list(res.value.audit)`), and `error_body(...)` for a Flow stop carries `audit` too (`FLOW_STOP_MEMBERS`, lines 102 to 108; `flow_error_data`, lines 251 to 261). `audit_to_list` (lines 234 to 248) is already the allow-listed projection the console would otherwise have to propose: it copies exactly seven members of an `AuditRecord` (`greenscreen/flow/model.py`, lines 188 to 196) and nothing else. The OpenAPI document declares the same seven members with `additionalProperties` false (`greenscreen/publisher/registry.py`, around lines 215 to 226). Properties 3 and 8 of the publisher spec already test this (`tests/property/test_publisher_parity.py`, `tests/property/test_publisher_audit_summary.py`, where `AUDIT_KEYS` pins the seven names over hostile Probe_Values and the residual-password screen). So this spec proposes no new projection and no additive field. It reuses the existing one and states what the audit can and cannot carry.

**Finding 2: what each audit member can carry (checked against `greenscreen/flow/runner.py`).** None can carry a typed value, an Input value, a hidden-field value or a screen cell.

| Member | Source in the runner | Can it carry a typed or hidden value? |
|---|---|---|
| `step_index` | integer from `plan(flow)` (`model.py`, lines 153 to 178) | No. An integer. |
| `kind` | `item.step.kind`, one of `expect`, `type`, `key`, `extract`, `handle` (`_EXECUTORS`, `runner.py`, line 638) | No. Five fixed words. |
| `phase` | `"steps"` or `"finally"` | No. |
| `iteration` | integer or `None` | No. |
| `signature` | `done.signature` from the recognizer, a name from `load_bundled_signatures()` (publisher Requirement 1.8), or `None` | No. A fixed vocabulary of ten names such as `tk5-logon`. A caller cannot add a Signature (publisher Assumptions: custom Signatures are out of scope). |
| `status` | `"ok"`, `"skipped"` or `"failed"` | No. |
| `duration_seconds` | float from the clock | No. |

The audit does not say which key was pressed, which field was typed into, or what text was typed. The trail therefore reads "step 3, expect, screen `tk5-logon`, ok, 0.4 s", and for `type`, `key` and `extract` steps only the kind and the status. That is the honest limit of the audit; the console does not try to enrich it.

**Finding 3: other parts of a response that the console must not render.** The Flow-stop error body also carries `summary`, the `RedactedSummary.to_dict()` of the failing screen (`greenscreen/recognizer/summary.py`), with `row_text` and field geometry. Hidden-field cells are masked there, but non-hidden cells are shown as they are on the host screen, and a screen can echo typed non-secret text (for example the user id typed at `Logon ===>`). The publisher spec accepts that today (Requirement 7.1, "as long as the screens of the Fake_Host do not contain the value"). The console does not read `summary`, so it adds no new exposure. The server still sends `summary` to every REST client, as before. Whether that is acceptable on a public demo is flagged in "Open decisions" (decision 8).

**Finding 4: what the success `outputs` of the demo Flow contain.** `tk5-system-info` declares `USERID`, `SYSTEMID`, `RELEASE` and `TERMINAL` as outputs (`greenscreen/flow/flows/tk5-system-info.yaml`). `USERID` equals the user id that the operator bound with `GS_BIND_TK5_SYSTEM_INFO__USERID`. A Bound_Value counts as a Secret_Value in the publisher spec (Requirement 22.10), but an Output is a declared result and has always been returned (Requirement 5.1; the live test asserts `USERID` equals the bound user id, Requirement 21.4). The console shows outputs as returned, so the demo account's user id appears on screen. Flagged in "Open decisions" (decision 7).

**Finding 5: what `GET /` does today.** There is no route for `/`. `AuthMiddleware._allowed` (`greenscreen/publisher/auth.py`, lines 114 to 125) lets only `GET /health` pass without a key. So today `GET /` without a key gets the fixed `unauthorized` body (HTTP 401, `WWW-Authenticate: Bearer`). With a valid key, the request reaches FastAPI, finds no route, and the replaced `StarletteHTTPException` handler (`rest.py`, `request_invalid_handler`) answers `request_invalid` with HTTP 400 (publisher Requirement 11.5; `tests/unit/test_publisher_stack.py`, `test_unknown_path_with_a_key_is_request_invalid_not_unauthorized`). With `GS_AUTH_DISABLED=true`, the answer depends only on the loopback `Host` rule (Requirement 13.7). When the console is off, `GET /` keeps all three behaviours.

**Finding 6: which endpoint lists the Flows.** The existing `GET /openapi.json` (`rest.py`, `openapi_json`, built by `build_openapi`) lists every Published_Flow as a path `/flows/<name>` with `summary` (the Flow description or `Run flow <name>.`), the Input_Schema as the request body schema (each property has `type`, `maxLength`, `pattern`, `description`, and `writeOnly` for secret Inputs) and the Success_Schema. It already omits every Bound_Input (publisher Requirement 22.1). It always needs the API key (`_allowed` passes only `GET /health`; `tests/unit/test_publisher_stack.py` lists `GET /openapi.json` among the routes that answer `unauthorized` without a key). It is not behind `GS_ENABLE_DOCS`: that variable gates only `GET /docs` (`rest.py`, `if settings.enable_docs`). `GET /health` returns only `{"status", "flows"}` and no Flow metadata (Requirement 11.4). So the page lists the Flows by fetching `/openapi.json` with the key after the judge has supplied it. No new endpoint is needed, and no unauthenticated endpoint exposes Flow metadata.

**Finding 7: screen replay is not safe in two days (decision recorded in "Not in scope").** `run_flow` keeps no `Screen` after it returns, and by design no frame of `greenscreen.publisher` may hold one (publisher Requirements 3.9 and 7.6, Property 10). An `AuditRecord` has no screen member. The only screen that leaves a run today is the single `RedactedSummary` of a failing step. Replaying every screen would need a change inside `greenscreen/flow/runner.py` to snapshot each screen, a masking step that also removes cells equal to Bound_Values and typed values (the steering notes that `Screen.text_grid` does NOT blank hidden fields, and a non-hidden cell such as the echoed user id would still reveal a Bound_Value, which publisher Requirement 22.10 forbids), a new response member (a contract change for REST, MCP, OpenAPI and `tools/list`) and new property tests over all of it. That is not a two-day piece of work next to the page itself, so it is left out.

**Finding 8: how existing tests constrain this work.** The aim is that no existing test changes. Checked:

- `tests/unit/test_publisher_auth.py` (`test_every_path_protected` over `/flows/x`, `/openapi.json`, `/docs`, `/mcp`, `/nothing`; `/health/` stays unauthorized) and `tests/unit/test_publisher_stack.py` (`ROUTES`, including `GET /nope`) build the stack with the console off. They keep passing if `AuthMiddleware` takes its new parameter as an optional keyword with an empty default (Requirement 3).
- `tests/unit/test_publisher_config.py` and `tests/unit/test_publisher_cli.py` read `Settings` through `load_settings` and match the log line `publishing 1 of 8`. No test constructs `Settings(...)` directly (searched). Adding a field and a separate log record keeps them passing.
- `tests/unit/test_publisher_packaging.py` and the pyproject pins in `tests/unit/test_flow_packaging.py` (`EXPECTED_DEPENDENCIES`, `EXPECTED_OPTIONAL`, the `greenscreen.flow.flows` entry), `tests/unit/test_recognizer_packaging.py` (`test_package_data_entries`) and `tests/unit/test_fixtures.py` check named `package-data` keys, not the whole table. A new `package-data` key and no change to `dependencies` or the extras keep them passing. The existing wheel test `test_wheel_contains_exactly_the_eight_flow_yaml_files` filters on the prefix `greenscreen/flow/flows/` and stays valid.
- `tests/unit/test_publisher_openapi.py`, `tests/property/test_publisher_schema.py` and the parity tests compare the OpenAPI document with the schemas. The console adds no path to the document (Requirement 4.5), so they stay valid.

Result: no existing test needs to change. A test that does fail is a defect to report (Conventions).

**Finding 9: what the `/mcp` endpoint requires and returns (recorded 2026-11-18; probed in-process over ASGI against the real application with the Fake_Host; throwaway scripts outside the repository, deleted afterwards).** The Publisher mounts the MCP Python SDK's Streamable HTTP application at `/mcp` (`greenscreen/publisher/rest.py`, one `Route`, all methods) behind the same `AuthMiddleware` as every other route, so `/mcp` needs `X-API-Key` and the console exemption does not cover it. `greenscreen/publisher/mcp_server.py` builds the manager with `stateless=True` and `json_response=True`. Installed: `mcp` 2.3.0, `mcp-types` 2.3.0, Starlette 1.6.0. Evidence for each row is in the design, "Recorded /mcp behaviour".

| Question | Observed |
|---|---|
| Authentication | No key or a wrong key: HTTP 401, the fixed `unauthorized` body (not JSON-RPC). The key goes only in `X-API-Key`. |
| Session | Stateless. No `Mcp-Session-Id` header is issued on `initialize`. A request that carries an unknown `Mcp-Session-Id` is served as if the header were absent. A request needs no prior `initialize`. |
| Reply format | Every request gets `Content-Type: application/json` with one JSON-RPC message. No `text/event-stream` reply was observed for `initialize`, `tools/list` or `tools/call`. |
| `Accept` | `application/json, text/event-stream` and `*/*` are accepted. `application/json` alone is accepted. `text/event-stream` alone, or no `Accept` header, gets HTTP 406 with a JSON-RPC error `-32600`. |
| `Content-Type` of the request | `application/json` is required. A missing one gets HTTP 400 with the plain text `Invalid Content-Type header`. |
| `notifications/initialized` | HTTP 202, empty body, with or without `MCP-Protocol-Version`. |
| `MCP-Protocol-Version` | Accepted on follow-up requests: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`. A value the SDK does not know gets HTTP 400 and a JSON-RPC error (`-32602` or `-32022`). The header is not required. |
| `initialize` version negotiation | The result echoes the requested `protocolVersion` when it is one of the four above, otherwise `2025-11-25`. The result carries `capabilities.tools`, `protocolVersion` and `serverInfo` (`greenscreen-publisher`, a version). |
| `tools/list` | One tool per published Flow with `name`, `description` (the Flow description), `inputSchema` (the Input_Schema, Bound_Inputs omitted) and `outputSchema` (the Success_Schema, with the seven-member audit). No `annotations` and no `title`. |
| `tools/call`, success | HTTP 200, `result.content` (one `text` block holding the JSON text of the Success_Body), `result.structuredContent` (the same Success_Body: `flow`, `outputs`, `audit`) and `result.isError` false or absent. |
| `tools/call`, any Flow or call error | Still HTTP 200. `result.isError` is `true`. `structuredContent` is the same Error_Body that REST sends (`error.code`, `message`, and for a Flow stop `step_index`, `kind`, `expected`, `audit`, `summary`). The `text` block is the same JSON. An HTTP status or a `Retry-After` header is not sent, so a `busy` call arrives as a tool error with HTTP 200. |
| Protocol-level errors | A bad method gives HTTP 200 and a JSON-RPC `error` (`-32601`). Unparseable JSON gives HTTP 400 and `-32700`. |
| Other methods | `GET /mcp` answers 200 `text/event-stream` with no events in the probe; `DELETE /mcp` answers 405. The page uses neither. |
| Origin | A foreign `Origin` header was accepted (the manager is built without transport security; the Publisher applies its own key and Host rule). The page is same-origin, so `Origin` is not an issue for it. |

Consequences for the page: it has to send `Content-Type` and `Accept` itself, it has to read a JSON reply and may meet an SSE reply from another MCP server version, it must treat HTTP 202 with an empty body as success for the notification, it receives the audit trail inside `tools/call` (so no server change is needed), and a tool error message and the `summary` member arrive in the same `structuredContent` as REST (so the page needs the same "never read `summary`" rule). No server change is needed.

### Conventions

- IF the work finds a defect in production code outside the files this spec names, THEN the implementer SHALL stop and report it instead of fixing it silently.
- No test, log, message, snippet or spec text prints a secret (`GS_API_KEY`, `TK5_PASSWORD`, `TK5_USERNAME`, a Bound_Value or the host address). Test keys are generated per test and never written to a file.
- DO NOT COMMIT anything. The executor leaves every change in the working tree and the reviewer commits. No requirement or task of this spec asks for a commit, a staged file or a branch.
- No new dependency is added. `dependencies` and the extras of `pyproject.toml` stay unchanged. The page uses no framework, no build step, no CDN, no external font, script or image.
- Production code outside the files this spec names is never changed. The files it names are: `greenscreen/publisher/config.py` (the new setting), `greenscreen/publisher/auth.py` (the exemption), `greenscreen/publisher/rest.py` (the routes and headers), `greenscreen/publisher/app.py` (wiring), `greenscreen/publisher/cli.py` (the startup report only), the new package `greenscreen/publisher/console/` (static files and a loader), `pyproject.toml` (package data only) and `.env.example` (one commented variable name).
- The `.kiro/steering` directory is not edited.
- Before the executor writes code that uses any library API, the executor SHALL check the current documentation of that library (web search or fetch) and record the page, the version and the date in `design.md` or in the task notes. This applies to Starlette and FastAPI response classes and headers, `importlib.resources`, and, for the page, the browser APIs it uses (`history.replaceState`, `fetch`, `sessionStorage`, `AbortController`, `URLSearchParams`, `prefers-reduced-motion`, Content-Security-Policy directives, ES module loading under `script-src 'self'`). This is a rule for the design and tasks stages. The requirements stage did not need new library calls and checked none.
- The final report of the executor gives the test counts before and after, lists every test file added, states that no existing test file was edited (or names each one and why), and lists everything not verified.

### Not in scope

- **Screen replay (the stretch idea) is left out, explicitly.** See Finding 7. No requirement below depends on it.
- The recorder, editing Flows, user accounts, more than one page, a second language, server-side sessions, cookies, and any change to the Flow runtime, the Connector, the recognizer, MCP behaviour, or the response bodies of existing routes.
- Real-time progress of a running call. The page shows the result when the call returns.
- Cancelling a call from the page. Closing the page while a call runs cancels the HTTP request, and the Publisher handles that as it does for any client (publisher Requirement 3.6, 23.3).

## Glossary

- **Console**: The feature of this spec: the Console_Page, the Console_Assets and the routes that serve them.
- **Console_Page**: The single HTML document served at `GET /`.
- **Console_Assets**: The files under `greenscreen/publisher/console/` that the routes serve: `index.html`, `console.css`, `console.js`, `snippets.js`, `codes.json`, `favicon.svg`.
- **Console_Routes**: The six `GET` routes of Requirement 2, criterion 1.
- **Console_Switch**: The environment variable `GS_ENABLE_CONSOLE`.
- **Publisher**: The `greenscreen.publisher` package and process (publisher spec).
- **API_Key**: The value of `GS_API_KEY` (publisher Glossary).
- **Typed_Key**: The API_Key as the judge enters it in the page or passes it in the URL fragment.
- **Key_Fragment**: A URL fragment of the form `#key=<Typed_Key>`.
- **Flow_Listing**: The parsed `GET /openapi.json` response that the page uses to list Flows.
- **Caller_Input**: An Input that appears in the `properties` of a Flow's Input_Schema in the Flow_Listing. A Bound_Input is never a Caller_Input (publisher Requirement 22.1).
- **Secret_Input**: A Caller_Input whose schema property has `writeOnly` true.
- **Audit_Summary**: The list of seven-member audit entries in a Success_Body or Error_Body (publisher Glossary).
- **Codes_Table**: The Console_Asset `codes.json`: one entry per Error_Code with its HTTP status and its plain-words text, plus the page-side conditions of Requirement 8, criterion 5.
- **Error_Code**: As in the publisher Glossary: one of the 22 values of `ERROR_CODES` in `greenscreen/publisher/calls.py` (13 Reason_Codes and 9 Publisher_Codes).
- **Console_CSP**: The `Content-Security-Policy` header value of Requirement 2, criterion 5.
- **Snippets_Module**: The Console_Asset `snippets.js`, a pure module that builds the `curl` text and the MCP config text, formats the audit lines and the `Retry-After` text, and (Requirement 18) builds the JSON_RPC_Messages, parses MCP_Endpoint replies, projects and formats the Wire_Transcript and counts the Run_Strip numbers.
- **Placeholder_Key**: The literal text `<YOUR_API_KEY>`.
- **Theme_Tokens**: The CSS custom properties of `console.css` whose names start with `--fg-`, `--bg-` or `--ui-`.
- **Seance_Art**: The static ASCII picture of a seance table, a crystal ball and two candles in `index.html` (Requirement 11, criteria 10 to 18).
- **Contrast_Test**: The test of Requirement 11, criterion 5 that computes WCAG contrast ratios from the Theme_Tokens.
- **Tunnel_Allow_List**: The list of exact paths that the operator opens in the tunnel (section "Routes").
- **Test_Suite**: The pytest and Hypothesis tests under `tests/`.
- **MCP_Endpoint**: The existing `POST /mcp` route of the Publisher (Finding 9). The console adds nothing to it.
- **JSON_RPC_Message**: One JSON-RPC 2.0 request, notification, response or error object that the page sends to or reads from the MCP_Endpoint.
- **MCP_Run**: The four sequential requests to the MCP_Endpoint that one press of Run makes while Call_Via is MCP: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`.
- **Call_Via**: The control of Requirement 18 that selects `MCP` or `REST`. The initial value is `MCP`.
- **Wire_Transcript**: The list of JSON_RPC_Messages of one MCP_Run, in order, each shown in the page as one Transcript_Line that expands to the full message.
- **Transcript_Line**: The one-line text of one Wire_Transcript entry, built by `formatTranscriptEntry` of the Snippets_Module from the grammar of Requirement 18, criterion 24: direction, method and one short fact. It is the text of the entry's `summary` element.
- **Expand_Control**: The one button of Requirement 18, criterion 25 that opens or closes every entry of the Wire_Transcript.
- **Fit_Limit**: The smaller of 720 and `window.innerHeight`, in CSS pixels (720 when `innerHeight` is not a positive number). Requirement 18, criterion 26 compares the bottom of the transcript list with it.
- **Reply_Parser**: The pure function `parseMcpReply` of the Snippets_Module that turns the text of an MCP_Endpoint reply (JSON or SSE) into JSON_RPC_Messages.
- **Run_Strip**: The three-stage line of Requirement 18, criterion 15, built from the data of one run.
- **Step_Count** and **Screen_Count**: The numbers `n` and `m` of the Run_Strip (Requirement 18, criterion 15).
- **Tool_Name**: The name of a Flow as `tools/list` reports it. It is equal to the Flow name.

## Requirements

### Requirement 1: The console switch

**User Story:** As an operator, I want the console off unless I turn it on, so that a deployment without the page behaves exactly as before.

#### Acceptance Criteria

1. THE Config_Loader SHALL read `GS_ENABLE_CONSOLE` once at startup with the same parser as `GS_ENABLE_DOCS` (`_bool` in `greenscreen/publisher/config.py`): an unset or empty value is `false`, the exact text `true` is `true`, the exact text `false` is `false`.
2. IF `GS_ENABLE_CONSOLE` has any other value, THEN THE Config_Loader SHALL stop the startup with a non-zero exit code and a message on stderr that names `GS_ENABLE_CONSOLE` and the rule `not_a_boolean (true or false)`, without the value.
3. THE `Settings` object SHALL hold the parsed value in a boolean field `enable_console`, and its `repr` SHALL stay free of any setting that is not already in it.
4. WHERE `GS_ENABLE_CONSOLE` is `true` and `GS_TRANSPORT` is `http`, THE Publisher SHALL serve the Console_Routes.
5. WHERE `GS_ENABLE_CONSOLE` is `true` and `GS_TRANSPORT` is `stdio`, THE Publisher SHALL ignore the setting, SHALL serve no HTTP route, and SHALL behave exactly as in stdio mode without the setting (publisher Requirement 13.10 treats `GS_API_KEY` in the same way).
6. WHEN the Publisher starts with the Console_Switch `true` and the transport `http`, THE Publisher SHALL write one INFO record on the logger `greenscreen.publisher` with the fixed text `console enabled` and no other field, in addition to the existing record `publishing %d of %d flows over %s`, which SHALL stay unchanged. THE `greenscreen/publisher/cli.py` module SHALL write both records from one helper, `_report_startup(prepared)`, which writes the existing record first with the same arguments and then, only when the console is on, the fixed record.
7. WHILE the Console_Switch is `false` or unset, THE Publisher SHALL write no record about the console.
8. THE `.env.example` file SHALL gain one commented line naming `GS_ENABLE_CONSOLE` with an empty value and a one-line comment, and no other change.
9. WHILE the Console_Switch is `false` or unset, THE Publisher SHALL answer `GET /` as it does today (Finding 5): `unauthorized` with HTTP 401 for a missing or wrong key, `request_invalid` with HTTP 400 for a valid key, and the loopback Host rule under `GS_AUTH_DISABLED=true`. THE Publisher SHALL answer every path of the Console_Routes other than `GET /` in the same way (an unknown path).

### Requirement 2: Console routes and response headers

**User Story:** As an operator, I want the page served from a short, exact list of paths with strict security headers, so that I can open only those paths in the tunnel and the page cannot load or run anything it did not ship with.

#### Acceptance Criteria

1. WHERE the Console_Switch is `true` and the transport is `http`, THE Publisher SHALL serve exactly these routes, each with the method `GET` only: `/`, `/console/console.css`, `/console/console.js`, `/console/snippets.js`, `/console/codes.json` and `/console/favicon.svg`. Each route is registered by its exact path. THE Publisher SHALL NOT register a wildcard, a path parameter, a directory mount or a static-files handler for the console.
2. THE Publisher SHALL serve each Console_Asset from bytes that it read from the installed package at startup (`importlib.resources` on the package `greenscreen.publisher.console`), so that a request reads no file and no request path reaches the file system.
3. IF a Console_Asset is missing from the installed package at startup, THEN THE Publisher SHALL stop the startup with a non-zero exit code and a message that names the missing file and no path of the machine.
4. THE Publisher SHALL answer each Console_Route with HTTP 200 and these media types: `text/html; charset=utf-8` for `/`, `text/css; charset=utf-8` for `console.css`, `text/javascript; charset=utf-8` for both scripts, `application/json` for `codes.json` and `image/svg+xml` for `favicon.svg`.
5. THE Publisher SHALL add to every response of a Console_Route exactly these security headers, and no `Content-Security-Policy` header to any other route:
   - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: no-referrer`
   - `Cache-Control: no-store, no-transform` (`no-store` is already added to every REST response by `_NoStore`, publisher Requirement 7.9; `no-transform` stops a CDN or proxy from rewriting the body, which would break the Console_CSP). The value on every response that is not a Console_Route SHALL stay exactly as it is today (Requirement 15).
6. THE Console_CSP SHALL contain no `'unsafe-inline'`, no `'unsafe-eval'`, no `data:` and no `blob:` source, and no host name. `connect-src 'self'` is needed so that `fetch` can call `/openapi.json` and `/flows/{name}` on the same origin. `style-src 'self'` is needed so that the stylesheet loads. `img-src 'self'` is needed for the icon. `base-uri`, `form-action` and `frame-ancestors` are listed because they do not fall back to `default-src`.
7. THE Console_Assets SHALL contain no inline script, no inline style, no `on*` event attribute, no `style` attribute, no `<style>` element, no `<form>` element (a form submission could put the Typed_Key in a URL), no reference to a URL on another origin, and no `<script>` element without a `src` attribute. The only absolute URL allowed anywhere in the files is the XML namespace attribute of `favicon.svg`.
8. THE Console_Page SHALL link its icon with `<link rel="icon" href="/console/favicon.svg">`, so that a browser does not request `/favicon.ico`.
9. THE Publisher SHALL answer a request to a Console_Route with any method other than `GET` as it answers an unknown method on an unknown path today (the API_Key check first, then `request_invalid`), and SHALL leave the behaviour of `HEAD /` and `OPTIONS /` (and of `HEAD` and `OPTIONS` on the other Console_Routes) to the framework default. THE design SHALL record the status, the `Allow` header and the authentication outcome that `HEAD /` and `OPTIONS /` actually return, observed with the Console_Switch on and with it off, and SHALL NOT add them to the exempt pairs.
10. THE Test_Suite SHALL contain tests that, for each Console_Route, assert the status, the media type, the exact Console_CSP string, `nosniff`, `no-referrer`, the exact `Cache-Control` value `no-store, no-transform` and the body equal to the packaged file, and a test that scans the Console_Assets for every pattern of criteria 7 and 8.

### Requirement 3: The key check exempts only the console routes

**User Story:** As a security reviewer, I want the API key check to stay in force for everything except the six static routes, so that the page can load without a key and nothing else opens.

#### Acceptance Criteria

1. THE `AuthMiddleware` SHALL take a new optional keyword argument, a frozenset of `(method, path)` pairs, with the default empty set. WHERE the set is empty, THE `AuthMiddleware` SHALL behave exactly as before.
2. WHERE the Console_Switch is `true` and the transport is `http`, THE application builder SHALL pass the six `("GET", path)` pairs of Requirement 2, criterion 1, and no other pair.
3. WHILE `GS_AUTH_DISABLED` is not `true`, THE `AuthMiddleware` SHALL let a request pass without a key only when the pair `(method, path)` equals one pair of the set, or is `GET /health` (as today). The comparison SHALL be an exact string comparison: `/console/console.css/`, `/console/`, `//` and a path with a query string in the path component are not in the set.
4. WHILE `GS_AUTH_DISABLED` is `true`, THE `AuthMiddleware` SHALL apply the loopback Host rule to the Console_Routes as it does to every other path (publisher Requirement 13.7), so that a request with a foreign `Host` header gets `unauthorized`.
5. THE `AuthMiddleware` SHALL NOT read, store or log any header value on the exempt path beyond what it does today.
6. IF a request to a Flow route, `/openapi.json`, `/docs` or `/mcp` carries no key or a wrong key, THEN THE Publisher SHALL answer `unauthorized` with HTTP 401 and the fixed body, with the Console_Switch on or off.
7. THE Test_Suite SHALL contain a property test (one `@given` test, `max_examples` of at least 100, first line `# Feature: console, Property 1: Only the six console routes are open without a key`) that generates methods, paths (including trailing slashes, case changes, percent-encodings, double slashes, `..` segments and the six exact paths) and header sets, and asserts that, with the console on and a valid key absent, the response is not `unauthorized` exactly for the six exact pairs and `GET /health`.

### Requirement 4: The page lists the published Flows from `/openapi.json`

**User Story:** As a judge, I want to see the published Flows with their descriptions and the inputs I must supply, so that I know what I am about to run.

#### Acceptance Criteria

1. WHEN the page holds a Typed_Key and no Flow_Listing, THE Console_Page SHALL fetch `GET /openapi.json` with the key (Requirement 5, criterion 6) and build the Flow_Listing from the response.
2. THE Console_Page SHALL list every path of the Flow_Listing whose name matches `/flows/<name>` and has a `post` operation, in the order of the document, showing the Flow name, the `summary` as the description, and one entry per Caller_Input.
3. THE Console_Page SHALL show for each Caller_Input its name, whether it is required (the schema's `required` list), its `description` when present, and its `maxLength`, and SHALL show a Secret_Input as a field that masks what is typed (`type="password"`, `autocomplete="off"`).
4. THE Console_Page SHALL NOT show, and the Console SHALL NOT request, the name or the value of any Bound_Input. This holds because the Flow_Listing already omits them (publisher Requirement 22.1), and the Console SHALL NOT use any other source for Input names.
5. THE Console SHALL add no path to the OpenAPI document and no member to any schema, and `GET /openapi.json` SHALL return the same bytes with the Console_Switch on or off for the same registry (publisher Requirement 12.7 stays true).
6. IF the Flow_Listing request returns HTTP 401, THEN THE Console_Page SHALL show the plain-words text of `unauthorized` (Requirement 8), SHALL keep the key field available, and SHALL discard the Typed_Key from memory.
7. IF the Flow_Listing request fails for any other reason, THEN THE Console_Page SHALL show the plain-words text for that status or for the network failure (Requirement 8, criterion 5) and SHALL offer a button to retry.
8. IF the Flow_Listing holds zero Flows, THEN THE Console_Page SHALL show the text `No flows are published.`.
9. THE Console_Page SHALL build every piece of text from the Flow_Listing with `textContent` or `createTextNode` and SHALL NOT interpret any of it as markup (Requirement 10, criterion 3).

### Requirement 5: API key handling in the page

**User Story:** As a judge, I want to enter the API key once, or open one link, and I want the page never to leave the key where someone could read it.

#### Acceptance Criteria

1. THE Console_Routes and the Console_Assets SHALL contain no API_Key, no Typed_Key, no Bound_Value and no credential (publisher Requirement 15.7 applies to every file in the repository).
2. THE Console_Page SHALL offer a password-type input for the Typed_Key and a button, both reachable by keyboard, and pressing Enter in the input SHALL act as pressing the button (a keydown handler, not a form). The key is never persisted: a reload asks for the key again (decided, see "Decisions").
3. WHEN the page loads with a Key_Fragment in `location.hash`, THE Console_Page SHALL, before it performs any other action, read the key from the fragment, call `history.replaceState` with a URL that holds the same path and the same query string and no fragment, and keep the key in a module-scope variable of `console.js`.
4. THE Console_Page SHALL keep the Typed_Key in memory only (that variable). THE Console_Page SHALL NOT use `localStorage`, `sessionStorage` or any other web storage for any value, and SHALL NOT write the key to a cookie, `document.cookie`, `location.search`, any query string, any other URL, the DOM (the key input is cleared after use), a `console.*` call or any log.
5. THE Console_Page SHALL NOT place the Typed_Key in any text that it displays, in the `curl` snippet, in the MCP snippet, in an error message or in the document title.
6. THE Console_Page SHALL send the Typed_Key only as the request header `X-API-Key` of its own same-origin `fetch` calls to `/openapi.json`, `/flows/{name}` and `/mcp`, built in one function of `console.js`, and in no other request.
7. WHEN the Typed_Key is rejected (HTTP 401 on any call), THE Console_Page SHALL discard the key from memory and show the key input again.
8. THE Console_Page SHALL provide a control that discards the key from memory and clears the displayed Flow_Listing and result.
9. THE Snippets_Module SHALL be a module with no `import`, no DOM access and no reference to the variable that holds the Typed_Key, and its builder functions SHALL take no key parameter.
10. THE Test_Suite SHALL contain static tests over `console.js` and `snippets.js` for criteria 3 to 9: no `localStorage`, `sessionStorage`, `document.cookie` or `console.` text (the scan fails on any occurrence of `sessionStorage`, including in a comment); `history.replaceState` appears before the first `fetch` in the source; the key variable is read in exactly one function; `snippets.js` has no `import` and no occurrence of the key variable name; `snippets.js` contains the Placeholder_Key.
11. THE Console_Page SHALL carry `<meta name="referrer" content="no-referrer">` in addition to the header, so that the rule holds if a proxy strips the header.
12. A browser keeps the fragment in the address bar until the script runs, and in any bookmark, typed-URL history or screenshot taken before that. THE Console_Page SHALL show one line of help text next to the key input that says a key in the URL is removed from the address bar but may remain in browser history, and the design SHALL record this limit.

### Requirement 6: Running a Flow through the existing endpoint

**User Story:** As a judge, I want a Run button per Flow that calls the real endpoint, so that what I see is exactly what an API client would get.

#### Acceptance Criteria

1. THE Console_Page SHALL show a Run button for each Flow in the Flow_Listing.
2. WHILE Call_Via is `REST`, WHEN the judge activates a Run button, THE Console_Page SHALL send exactly one `POST /flows/<name>` request with the header `Content-Type: application/json` and the header `X-API-Key`, whose body is the JSON object of the Caller_Input values (`{}` when there are none), and SHALL NOT call any other URL to execute a Flow. WHILE Call_Via is `MCP`, Requirement 18 governs the requests of a Run. The body text and the Caller_Input rules of criterion 3 apply to both.
3. THE Console_Page SHALL send a value of a Caller_Input of type `integer` as a JSON number and of type `string` as a JSON string, SHALL omit an optional Caller_Input that the judge left empty, and SHALL leave every other check to the server (publisher Requirement 4). The page SHALL NOT re-implement the Input_Validator.
4. WHILE a call from this page is running, THE Console_Page SHALL disable the Run buttons, show a `Calling the mainframe…` status in a polite live region, and SHALL NOT start a second call.
5. WHEN the call returns, THE Console_Page SHALL enable the Run buttons again and show the result (Requirement 7) or the error (Requirement 8).
6. THE Console SHALL add no execution path: no server route other than `POST /flows/{name}` and the `tools/call` method of `POST /mcp` runs a Flow, and the Console_Switch SHALL NOT change the status, headers or body of any response of `POST /flows/{name}`.
7. THE Test_Suite SHALL contain a property test (one `@given` test, first line `# Feature: console, Property 2: The console changes no existing response`) that, for generated Flows, Input values and Fake_Host behaviours, runs the same request against two applications built from the same environment except `GS_ENABLE_CONSOLE`, and asserts that the status, the response headers other than those of Requirement 2, criterion 5, and the body of `POST /flows/{name}`, `GET /openapi.json`, `GET /health` and a `POST /mcp` `tools/list` are equal.
8. WHEN a call has returned and the page has put its result or error into the result region, THE Console_Page SHALL move keyboard focus to the result region with `focus({ preventScroll: true })` and SHALL call no other scroll function (`scrollIntoView`, `scrollTo`, `scrollBy`, `window.scroll`) and assign no `location.hash`. THE page scroll position (`window.scrollX` and `window.scrollY`) SHALL be the same immediately after the focus move as immediately before it, so that a page at the top stays at the top and the masthead stays on screen at 1280x720.
9. THE Test_Suite SHALL scan `console.js` statically: every `.focus(` call on the result region passes the literal `{ preventScroll: true }`, and none of the scroll names of criterion 8 appears. The scroll position itself is checked by hand (manual checklist step 15).

### Requirement 7: Showing the result and the audit trail

**User Story:** As a judge, I want to see the outputs, how long it took, and the steps the Flow walked through, so that I can see that a recorded walk-through ran.

#### Acceptance Criteria

1. WHEN the response is HTTP 200 with a Success_Body, THE Console_Page SHALL show the Flow name, each output as a name and a value in the order of `outputs`, the elapsed time, and the audit trail.
2. THE Console_Page SHALL measure the elapsed time in the browser from just before the `fetch` call to just after the response headers arrive and show it as seconds with one decimal and the label `Elapsed (as seen by this browser)`. THE Console_Page SHALL NOT claim it is the host's time.
3. THE Console_Page SHALL show the audit trail as an ordered list in the order of the `audit` array, with one item per entry and no entry left out. THE Console_Page SHALL read exactly the seven members of `AUDIT_KEYS` from each entry into a plain row, and SHALL build the text of each item with the function `auditLine(row)` of the Snippets_Module. The text is the following words joined by one space, in this order:
   - the `step_index` (always);
   - the `kind` (always);
   - the `signature`, only when it is not `null`;
   - the status word for `status` (always): `OK` for `ok`, `SKIPPED` for `skipped`, `FAILED` for `failed`, `UNKNOWN` for any other value;
   - `duration_seconds` as seconds with two decimals followed by `s` (for example `0.40s`), only when it is a finite number whose two-decimal text, read as a number, is greater than 0 (so `0`, `0.004` and a negative value show nothing);
   - the word `finally`, only when `phase` is `finally`;
   - `pass N`, only when `iteration` is not `null`, with N the iteration.

   For example `12 expect tso-password-prompt OK`. Of the seven members, `step_index`, `kind` and `status` are always displayed; `signature`, `duration_seconds`, `phase` and `iteration` are displayed only under the conditions above; the page still reads all seven and no other member. A value is coerced before display: `step_index` and `iteration` as a safe integer (or `?`), `kind` as text cut to 40 characters, `signature` as text cut to 80 characters.
4. THE Console_Page SHALL mark a `failed` entry and a `skipped` entry with a word as well as a style (not by colour alone).
5. WHEN the response is an Error_Body of a Flow stop and carries an `audit` array, THE Console_Page SHALL show the same audit list above the error, so that the judge sees where the Flow stopped, and SHALL show the `step_index`, the `kind` and the `expected` screen names when present.
6. THE Console_Page SHALL read from each audit entry only the seven member names of `AUDIT_KEYS` (`step_index`, `kind`, `phase`, `iteration`, `signature`, `status`, `duration_seconds`) and SHALL ignore every other member.
7. THE Console_Page SHALL NOT read, store or display the member `summary` of an Error_Body or any member it does not display by this requirement.
8. THE Console_Page SHALL NOT show or request any hidden-field value, screen cell or screen text. THE server SHALL send none that it does not send to every REST client today (Finding 3), and the Console SHALL add no response member.
9. THE Test_Suite SHALL keep Properties 3 and 8 of the publisher spec (`tests/property/test_publisher_parity.py`, `tests/property/test_publisher_audit_summary.py`) unchanged and passing. They are the secrecy proof of the audit projection and already generate hostile Probe_Values and the residual-password screen. THE Test_Suite SHALL contain a static test that `console.js` contains the seven member names and no other audit member name, and the scan of criterion 11 for the error-body member `summary`.
10. THE Console SHALL add no projection of audit records on the server (Finding 1).
11. THE Test_Suite SHALL scan `console.js` for any read of the `summary` member of an Error_Body (criterion 7), using the word `summary` by its plain name and no spelling trick. The scan SHALL remove these four allowed forms and then SHALL fail, with the file, the line and the text, if the word `summary` (any letter case) remains anywhere in the file, including comments:
    - the tag name as the first argument of a DOM helper: `el("summary"` or `createElement("summary"`;
    - the member of the OpenAPI operation object, written `operation.summary`, where the receiver is exactly the identifier `operation` (not preceded by an identifier character, a dot or `?`);
    - the class name string `"flow-summary"`.

    Therefore `error.summary`, `err?.summary`, `body["summary"]`, `info.error.summary`, `x.operation.summary`, a destructuring pattern that names `summary`, and a variable named `summary` all fail. The scan SHALL also fail on a string literal `"sum"` or `'sum'` followed by `+`, so that the word cannot be built from parts. THE Test_Suite SHALL hold a self-check of the scan: a fixture list of source lines that must pass and lines that must fail (design, "Summary scan"), run against the scan function itself, so that a scan that matches nothing cannot pass.
12. THE Console_Page SHALL show each audit line in the form of criterion 3 so that the audit trail of a 39-step run fits in two columns of the stage at 1280x720 with no wrapped line for the lines of the demo Flow (design, "Audit line width"). The widths are an estimate from the font and column sizes; the reviewer confirms them in a browser (Requirement 16).

### Requirement 8: Every error code in plain words

**User Story:** As a judge, I want every failure explained in a sentence a person can act on, so that a failed run teaches me something instead of showing a status code.

#### Acceptance Criteria

1. THE Codes_Table SHALL hold one entry for each Error_Code of `ERROR_CODES` in `greenscreen/publisher/calls.py`, each with the members `status` (the HTTP status) and `text` (the plain-words text), and SHALL hold no entry for any other code. An entry MAY also carry the optional boolean member `show_message`; it is `true` for `input_invalid` only and absent elsewhere, and it tells the page to show the server's `error.message` (criterion 4), so that `console.js` holds no code name (criterion 8). In particular it SHALL hold no entry for `cancelled`, which is never in a response (publisher Requirement 8.8).
2. THE Codes_Table SHALL give each code the status of `HTTP_STATUS` in `greenscreen/publisher/calls.py`.
3. THE Codes_Table SHALL give each code the plain-words text of this table (the executor may refine wording but SHALL keep each text to one or two short sentences, and SHALL keep the words `busy` and `try again` in the `busy` text and the word `key` in the `unauthorized` text):

   | Error_Code | HTTP | Plain-words text |
   |---|---|---|
   | `unauthorized` | 401 | The API key is missing or wrong. Enter the key again. |
   | `request_invalid` | 400 | The publisher could not read this request. Reload the page and try again. |
   | `request_too_large` | 413 | The request was too large for the publisher. |
   | `unknown_flow` | 404 | This flow is not published. Reload the list. |
   | `input_invalid` | 422 | An input value was not accepted. The message below says which input and which rule. |
   | `busy` | 429 | The mainframe is busy with another call. Wait a moment and try again. |
   | `shutting_down` | 503 | The publisher is shutting down. Try again in a minute. |
   | `host_unavailable` | 502 | The publisher could not open a session to the mainframe. |
   | `call_timeout` | 504 | The call took too long and was stopped. The mainframe session may still be signed on. |
   | `internal_error` | 500 | The publisher failed while running the flow. |
   | `timeout` | 504 | The mainframe was too slow to answer a step. |
   | `run_timeout` | 504 | The mainframe was too slow for the whole run. |
   | `unknown_screen` | 502 | The mainframe showed a screen this flow does not know, so the flow stopped without guessing. |
   | `ambiguous_screen` | 502 | The mainframe showed a screen that matches more than one known screen, so the flow stopped. |
   | `unexpected_screen` | 502 | The mainframe showed a known screen the flow did not expect at this step, so the flow stopped. |
   | `loop_limit` | 502 | A repeated step reached its limit, so the flow stopped. |
   | `bad_target` | 502 | A step needed an input field that was not on the screen, so the flow stopped. |
   | `secret_target` | 502 | A step tried to type a secret into a field that must not receive it, so the flow stopped. |
   | `hidden_output` | 502 | An output would have been read from a hidden field, so the flow stopped. |
   | `output_type` | 502 | An output was not of its declared type, so the flow stopped. |
   | `screen_size` | 502 | The mainframe screen was not the expected size, so the flow stopped. |
   | `session_error` | 502 | The mainframe session failed during the run. |

4. WHEN the page shows an Error_Body, THE Console_Page SHALL look up `error.code` in the Codes_Table and show: the code, the HTTP status, the plain-words text, and, for `input_invalid` only, the server's `error.message` (which names the input and the rule and holds no value, publisher Requirement 4.2). For a 429 the page SHALL also show the `Retry-After` line built by `retryAfterText(value)` of the Snippets_Module from the header value (`null` when the header is absent). The rule: IF the value is 1 to 6 ASCII digits, THEN the line is `Retry after: 1 second` when the number is 1 (also for `01`), and `Retry after: N seconds` for every other number with N written without leading zeros (so `0` gives `Retry after: 0 seconds`, `007` gives `Retry after: 7 seconds`). IF the value is anything else (absent, empty, a date, a sign, a decimal point, spaces, more than 6 digits), THEN no line is shown.
5. THE Codes_Table SHALL also hold entries, with their own keys that are not Error_Codes, for the cases where no Error_Body arrives: `no_response` (the `fetch` call failed, for example a network error or a tunnel that is down), `unreadable_reply` (a response that is not a JSON Error_Body or Success_Body, for example an HTML error page from a proxy; the page shows the HTTP status and these words) and `unknown_code` (a JSON Error_Body whose `code` is not in the table). THE Console_Page SHALL show the status and the matching text for each, and SHALL NOT show the body of an unreadable reply.
6. THE Console_Page SHALL load the Codes_Table from `/console/codes.json` and SHALL hold no copy of the codes or texts in `console.js`.
7. THE Test_Suite SHALL contain a test that loads `codes.json` from the installed package and asserts: the set of Error_Code keys equals `ERROR_CODES` exactly; each `status` equals `HTTP_STATUS[code]`; each `text` is a non-empty string of at most 200 characters; the `busy` text holds `busy` and `try again` (case-insensitive); the `unauthorized` text holds `key`; the keys `no_response`, `unreadable_reply` and `unknown_code` exist and are not Error_Codes; and the table holds no key `cancelled`. Because the test reads `ERROR_CODES` and `HTTP_STATUS` from the production module, a code added to the publisher without an entry fails the test, so the page and the publisher cannot drift.
8. THE Test_Suite SHALL contain a test that `console.js` references no code name as a string literal other than the keys it reads from the loaded table (a scan for each of the 22 code names in `console.js` finds none).

### Requirement 9: `curl` and MCP snippets

**User Story:** As a developer watching the demo, I want the equivalent `curl` command and an MCP client config for the same call, so that I can repeat it from my own machine.

#### Acceptance Criteria

1. THE Snippets_Module SHALL export a function that builds the `curl` command of the selected Flow, which takes the page origin (`location.origin`), the Flow name and the list of Caller_Inputs with the values the judge typed, and two functions that build the MCP client texts of criterion 5 (`buildMcpConfig` and `buildClaudeCodeCommand`), which take only the page origin, because the server lists its tools itself and neither the Flow name nor the Inputs change the config.
2. THE `curl` snippet SHALL be: `curl -sS -X POST '<origin>/flows/<name>' -H 'Content-Type: application/json' -H 'X-API-Key: <YOUR_API_KEY>' -d '<json>'`, with the Placeholder_Key and with `<json>` the JSON object of the Caller_Input values.
3. THE Snippets_Module SHALL write the value of a Secret_Input in the snippets as the text `<SECRET>` and SHALL NOT include what the judge typed for it. A non-secret Caller_Input value SHALL appear as typed.
4. THE Snippets_Module SHALL shell-quote the JSON for a POSIX shell (a single quote inside a value becomes `'\''`), so that a value cannot end the quoted string.
5. THE MCP snippet SHALL show a Streamable HTTP server entry that holds the URL `<origin>/mcp` and the header `X-API-Key` with the Placeholder_Key, in this shape: `{"mcpServers": {"greenscreen": {"url": "<origin>/mcp", "headers": {"X-API-Key": "<YOUR_API_KEY>"}}}}`, and one line that names the tool, which is the Flow name (page text, not part of the copied JSON). THE MCP snippet area SHALL also show a third block, the Claude Code command built by `buildClaudeCodeCommand`: `claude mcp add --transport http greenscreen '<origin>/mcp' --header 'X-API-Key: <YOUR_API_KEY>'`, because the generic JSON shape is not valid for Claude Code without `"type": "http"`. THE MCP snippet area SHALL also show one line saying that MCP clients differ in how they name these settings, that the first block is the shape Kiro reads and that the second is the Claude Code command. Each of the three blocks has its own copy button (criterion 6).
6. THE Console_Page SHALL show a copy button for each snippet, reachable by keyboard, that copies the displayed text. IF the clipboard call fails, THEN THE Console_Page SHALL select the text and show `Press Ctrl+C to copy.`.
7. THE Console_Page SHALL NOT hard-code a host name: both snippets SHALL use `location.origin` at the time of display.
8. WHEN the judge changes a Caller_Input, THE Console_Page SHALL update the snippets.
9. THE Test_Suite SHALL contain a static test that `snippets.js` holds the Placeholder_Key and the text `<SECRET>`, holds no host name and no `http://` or `https://` literal, and exports no function with a parameter named like a key.
10. THE design SHALL, before the MCP snippet text is fixed, check the current documentation of at least Kiro and Claude Desktop or Claude Code for configuring a remote HTTP MCP server with a custom request header, and SHALL record for each the page URL, the product version when stated, and the date checked. IF the generic `mcpServers` shape of criterion 5 is wrong for one of them, THEN THE design SHALL adjust the snippet or the line of criterion 5 that says clients differ, and SHALL say what changed. This is design-stage evidence; the requirements stage did not verify any client (Decision 13).
11. WHILE the Flow_Listing is shown, THE Console_Page SHALL show the MCP client configuration block and the Claude Code command block of criterion 5, each with its copy button, the line `Tool name: <flow name>` and the line about client differences, outside any collapsed element, under a heading that says any MCP client can use the same tool (design: `Any MCP client can use this same tool`). THE `curl` block MAY stay in a collapsed element. The blocks, their texts and their copy behaviour stay as criteria 1 to 8 define them.

### Requirement 10: Secrecy of the page and the server

**User Story:** As a security reviewer, I want the publisher's "never leaves" rules to cover the console, so that the new page cannot become the way a secret leaks.

#### Acceptance Criteria

1. THE Console SHALL carry over publisher Requirement 7 unchanged: no Input value, Bound_Value or Host_Data in any response, log record, exception message or header. THE Console SHALL add no log record that holds a value, and the only record it adds is the fixed text of Requirement 1, criterion 6 (publisher Requirement 8.3 permits a fixed message text).
2. THE Console_Routes SHALL log nothing per request (the HTTP access log is off, publisher Requirement 8.5) and SHALL NOT write a Call_Log_Record, because a request to them is not a Call (publisher Requirement 8.10).
3. THE Console_Page SHALL NOT use `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, `setTimeout` or `setInterval` with a string argument, a `javascript:` URL, or `setAttribute` for `style` or any `on*` attribute, so that no server text can become markup or script.
4. THE Console_Page SHALL NOT call `console.log`, `console.info`, `console.warn`, `console.error` or `console.debug`, and SHALL NOT send any request except those of Requirements 4, 6, 8 and 18 (`/openapi.json`, `/flows/<name>`, `/mcp`, `/console/codes.json`, and the assets named in Requirement 2).
5. THE Console_Page SHALL NOT place a Secret_Input value, a Typed_Key or a response value in a URL, a title, a `data-` attribute or any storage.
6. WHEN the call has returned, THE Console_Page SHALL clear the Secret_Input fields.
7. THE Test_Suite SHALL contain a static test that scans `console.js` and `snippets.js` for every forbidden name of criteria 3, 4 and 5 of this requirement and of Requirement 5, criterion 10, and fails with the file, the line and the name.
8. THE Test_Suite SHALL contain a test that starts the application with the console on and a generated API_Key and Bound_Values, requests all six Console_Routes with and without a key, and asserts that no Leak_Form of the API_Key or of any Bound_Value appears in any body, any header or any log record (the existing `LogCapture` and `leak_forms` helpers in `tests/publisher_support.py` and `tests/property/_publisher_strategies.py`).

### Requirement 11: Look, keyboard use, contrast and motion

**User Story:** As a judge and as a viewer of the demo video, I want a phosphor-green terminal look that is readable and works from the keyboard, with the theme never in the way of the Run button.

#### Acceptance Criteria

1. THE Console_Page SHALL show the title `Green Screen Medium` and one tagline of no more than 12 words that carries the seance theme (for example, a seance for dead mainframe screens), and SHALL put the theme in the stylesheet (green phosphor text on black, a monospace stack of system fonts, a faint scanline or glow) and not in extra interaction steps. No Run button SHALL be hidden behind an animation, a loading screen or a typing effect.
2. THE Console_Page SHALL use system fonts only (`font-family` from a list of generic and system monospace names) and no `@font-face`, `@import` or `url(` that points outside `/console/`.
3. THE Console_Page SHALL be operable with the keyboard alone: every control is a native `<button>`, `<input>` or `<a>` in a logical DOM order, no element has a `tabindex` above 0, every `<input>` has an associated `<label>`, the status and result regions use `aria-live="polite"`, and the first focusable element after load is the key input (when no key is held) or the first Run button.
4. THE stylesheet SHALL give every focusable control a visible focus indicator through `:focus-visible` of at least 2 CSS pixels with a contrast of at least 3:1 against the adjacent colours, and SHALL NOT remove the outline without replacing it.
5. THE stylesheet SHALL define every colour once, as a six-digit hex value in a Theme_Token on `:root`, and SHALL use colours elsewhere only as `var(--fg-…)`, `var(--bg-…)` or `var(--ui-…)`. THE Contrast_Test SHALL parse the Theme_Tokens from `console.css`, compute the WCAG 2.x relative-luminance contrast ratio of every `--fg-*` token against every `--bg-*` token, and fail when any ratio is below 4.5:1, and compute the ratio of every `--ui-*` token against every `--bg-*` token and fail when any is below 3:1. The Contrast_Test SHALL also fail when `console.css` holds a colour literal (`#`, `rgb(`, `rgba(`, `hsl(`, a colour keyword other than `transparent` and `currentColor`) outside the `:root` block. No browser is needed.
6. THE stylesheet SHALL enclose every `animation`, `transition` and `@keyframes` in a form that is disabled by `@media (prefers-reduced-motion: reduce)`, with a block that sets `animation: none` and `transition: none` for every element. THE Test_Suite SHALL check statically that every `animation` or `transition` declaration appears in the file together with such a block.
7. THE Console_Page SHALL NOT use JavaScript to animate, and SHALL NOT use any animation that flashes more than three times in one second.
8. THE Console_Page SHALL set `<html lang="en">`, a `<title>`, a `<meta name="viewport" content="width=device-width, initial-scale=1">` and `<meta charset="utf-8">`, and SHALL keep each piece of its copy short (no paragraph over 40 words).
9. THE Test_Suite SHALL check the static rules of this requirement (criteria 2, 3 and 8) over `index.html` and `console.css`. The keyboard walk-through and the screen-reader behaviour are verified by hand by the reviewer, and the design lists the steps.
10. THE Console_Page SHALL show the Seance_Art (an ASCII picture of a seance table with a crystal ball and two candles) as static text in `index.html`, inside `main.stage`, as one `<div class="seance-art-wrap">` that holds one `<pre class="seance-art">`. No script writes, moves or changes it, and `console.js`, `snippets.js`, `codes.json` and `favicon.svg` stay unchanged.
11. THE wrapper SHALL carry `role="img"` and `aria-label="A crystal ball on a seance table"`, and the `<pre>` inside it SHALL carry `aria-hidden="true"`, so that assistive technology announces one short label and does not read the characters. The label text SHALL appear exactly once in `index.html`. The `<pre>` SHALL have no attribute other than `class` and `aria-hidden`, and no element inside the wrapper SHALL be focusable (no `tabindex`, link, button or input), so the keyboard order of Requirement 11, criterion 3 does not change.
12. THE Seance_Art SHALL use only the characters 0x20 to 0x7E and the line feed that separates rows (no tab, no box-drawing character, no other Unicode), SHALL have at most 60 columns and at most 20 rows, and SHALL have no blank row. IF a character that HTML treats as markup (`&`, `<`, `>`) is ever used, THEN it SHALL be written as an entity; the art of the design uses none, and the backslash, double quote and apostrophe need no escaping in text content.
13. THE Seance_Art SHALL be coloured only by static `<span>` elements inside the `<pre>`, each with exactly one attribute, `class`, whose value is `seance-ball` or `seance-dim`; spans SHALL NOT be nested; every character of the art that is not a space SHALL be inside a span; no `style` attribute and no script-built markup SHALL be used. `console.css` SHALL colour `seance-dim` with `var(--fg-dim)` and `seance-ball` with `var(--fg-bright)` and a glow of `var(--ui-glow)`, and SHALL add no Theme_Token and no colour literal (Requirement 11, criterion 5 still holds).
14. THE Seance_Art SHALL be visible while the result region is empty, that is while `div.layout` does not have the class `has-result`, including on the key screen and after the key is accepted, and SHALL be hidden with `display: none` when `div.layout` has `has-result`, and below a viewport width of 68rem (which includes the one-column breakpoint of 56rem), where the stage is too narrow for 56 columns. It SHALL NOT wrap, scroll or clip.
15. THE `<pre>` SHALL use `white-space: pre`, a font size of at least 1rem and the inherited monospace stack. At 1280x720 the Seance_Art SHALL be at most 400 CSS pixels high, SHALL stay inside `main.stage` (the key panel is in `aside.side`), and SHALL NOT move the key panel, any Run button or the status line out of view or cause a horizontal scrollbar.
16. IF the ball has a glow pulse, THEN it SHALL change only `text-shadow` blur radius, SHALL have a period of at least 4 seconds, SHALL NOT change the colour or opacity of any glyph, and SHALL be disabled by the existing single `prefers-reduced-motion: reduce` block (WCAG 2.3.1: far below three flashes per second).
17. THE Seance_Art is decorative and hidden from assistive technology, so Requirement 11, criterion 5 applies to it as a conservative bound: the Contrast_Test SHALL also compute the ratio of `--fg-dim` and `--fg-bright` against `--bg-void` and `--bg-scan` (the backdrop of the stage) and fail below 4.5:1, and `--ui-glow` against both and fail below 3:1.
18. THE Test_Suite SHALL check criteria 10 to 17 statically in a new test file beside `tests/unit/test_console_assets.py`. No existing test is edited, and the existing scans, the Contrast_Test and the reduced-motion test SHALL pass with no change of intent.

### Requirement 12: Packaging

**User Story:** As a maintainer, I want the page shipped inside the wheel as plain package data, so that an installed Publisher serves it with no build step.

#### Acceptance Criteria

1. THE Console_Assets SHALL live in the package `greenscreen/publisher/console/` (with an `__init__.py` so that the existing `[tool.setuptools.packages.find]` rule includes it) as plain files: `index.html`, `console.css`, `console.js`, `snippets.js`, `codes.json`, `favicon.svg`.
2. THE `pyproject.toml` SHALL gain one `package-data` key, `"greenscreen.publisher.console" = ["*.html", "*.css", "*.js", "*.json", "*.svg"]`, and no other change: `dependencies`, the extras, `[build-system]` and the other package-data keys stay as they are.
3. THE Test_Suite SHALL contain a new wheel test, built the same way as `test_wheel_contains_exactly_the_eight_flow_yaml_files` in `tests/unit/test_flow_packaging.py` (a temporary copy of the repository, `pip wheel . --no-deps --no-build-isolation --no-index`), that asserts the wheel holds exactly the six Console_Assets under `greenscreen/publisher/console/` plus `__init__.py`, and fails with the build output when the build fails. THE existing wheel test SHALL stay as it is. The two tests may share the helper `_wheel_workspace` by import or the new test may live in `tests/unit/test_flow_packaging.py` as an addition; the design chooses, and no existing test body changes.
4. THE Console_Assets SHALL need no build step, no `node` and no `npm`, and the Publisher SHALL import no module for the console that is not in the standard library or in the `publish` extra.
5. THE `greenscreen.publisher` package and `greenscreen.publisher.console` SHALL import without `mcp`, `fastapi`, `starlette` or `uvicorn` (the loader of the Console_Assets uses the standard library only), so the existing check in `tests/unit/test_publisher_packaging.py` (`test_core_packages_do_not_import_web_packages`) stays true.

### Requirement 13: Existing behaviour does not change

**User Story:** As the owner of the publisher, I want the console to leave every existing behaviour as it is, so that adding the page puts none of the earlier guarantees at risk.

#### Acceptance Criteria

1. WHILE the Console_Switch is `false` or unset, THE Publisher SHALL behave byte for byte as before this feature for every request, response, log record and exit code, and the existing Test_Suite SHALL pass with no change to any existing test file (Finding 8).
2. WHILE the Console_Switch is `true`, THE Publisher SHALL leave unchanged the REST routes, the MCP endpoint, the API key check for every path outside the six exact pairs, the Limiter, the Crash_Guard, the error mapping, the Call_Log_Record and the shutdown behaviour.
3. THE `CrashGuard` SHALL wrap the Console_Routes as it wraps every route.
4. WHERE the Console_Switch is `true`, THE Console_Routes SHALL carry `Cache-Control: no-store, no-transform` (Requirement 15).
5. THE Console SHALL NOT change `GS_ENABLE_DOCS` handling: `GET /docs` is served only when `GS_ENABLE_DOCS` is `true`, with or without the console, and `GET /openapi.json` is served in both cases.
6. IF an existing test fails after the change, THEN THE executor SHALL stop, report the test and the cause, and SHALL NOT edit the test without the reviewer's approval.
7. THE Test_Suite SHALL contain unit tests that, with the console off, assert that each Console_Route path answers as an unknown path does today (`unauthorized` without a key, `request_invalid` with a key) and that the startup log has no console record. These tests, and the test of Requirement 15, criterion 3, SHALL live in a new test file or as new test functions beside the existing publisher test they parallel (`tests/unit/test_publisher_stack.py`, `tests/unit/test_publisher_auth.py`), and SHALL NOT modify any existing test body (Decision 15).

### Requirement 14: The Snippets_Module runs under Node

**User Story:** As a reviewer, I want the snippet builders executed by a real JavaScript engine in the tests, so that the quoting rules are proven by running them and not by reading them.

#### Acceptance Criteria

1. THE Snippets_Module SHALL be loadable by Node.js as an ES module, with no `import`, and with no reference to `document`, `window`, `globalThis`, `self`, `location`, `navigator`, `fetch`, `localStorage`, `sessionStorage` or `console` (the browser object: the name `console` in code outside comments and string literals, so that the text `greenscreen-console` in a string is allowed), and no parameter named like a key.
2. THE Test_Suite SHALL contain a static test that scans `snippets.js` for every name of criterion 1 and fails with the file, the line and the name.
3. WHERE `node` is found on PATH (`shutil.which("node")`), THE Test_Suite SHALL run the Snippets_Module under `node` by `node --input-type=module` or a small test-only `.mjs` file under `tests/`, with no `npm`, no `package.json` and no new dependency, and the test SHALL write no permanent file.
4. IF `node` is not found on PATH, THEN THE Test_Suite SHALL skip the Node tests with the reason `node is not on PATH; the Snippets_Module was not executed`.
5. WHEN the Node tests run, THE Test_Suite SHALL assert, from the output of the real module:
   - the `curl` text for a Flow with no Caller_Inputs equals the shape of Requirement 9, criterion 2 with `-d '{}'`;
   - for a string Caller_Input holding any of: a single quote, a double quote, a backslash, a newline, `$(x)` and a backtick, the `-d` argument, split by POSIX shell rules (Python `shlex.split`), JSON-decodes to the original values;
   - a Secret_Input appears as `<SECRET>` and the typed secret text appears nowhere in either snippet;
   - an `integer` Caller_Input appears as a JSON number;
   - the MCP text parses as JSON and holds the Placeholder_Key and `<origin>/mcp`;
   - the Claude Code command, split by POSIX shell rules, is the fixed argument list `claude mcp add --transport http greenscreen <origin>/mcp --header "X-API-Key: <YOUR_API_KEY>"`, and no typed Secret_Input text appears in it.
6. THE Test_Suite SHALL implement the assertions of criterion 5 as a Hypothesis property test (one `@given` test, `max_examples` of at least 100, first line `# Feature: console, Property 3: Snippets survive a POSIX shell`) WHERE one `node` process can serve a whole batch of generated cases (cases written to its standard input as JSON, results read from its standard output). THE design SHALL state whether the property form or example-based tests were chosen and why.
7. THE Test_Suite SHALL print no Secret_Input value in a failure message.
8. THE Snippets_Module SHALL also export the two pure text functions `auditLine(row)` (Requirement 7, criterion 3) and `retryAfterText(value)` (Requirement 8, criterion 4), under the same no-import, no-global rules as criterion 1. THE Test_Suite SHALL run them under `node` with example cases (including `0.00` omission, `finally`, `pass N`, `UNKNOWN`, `Retry after: 1 second`, `0 seconds`, `007`, `1.5`, an HTTP date, `null`), skipped with the fixed reason of criterion 4 when `node` is absent. No new asset, route or Hypothesis property is added for this. The functions of Requirement 18, criterion 18 follow the same rules, and Property 4 is the one property added for them.

### Requirement 15: Cache-Control on the console routes only

**User Story:** As an operator behind a CDN, I want the console files marked as not to be transformed, so that an edge cannot rewrite them and break the content security policy, and I want every other route to stay as it is.

#### Acceptance Criteria

1. THE Publisher SHALL set `Cache-Control` to exactly `no-store, no-transform` on every response of a Console_Route.
2. THE Publisher SHALL leave the `Cache-Control` value of every response that is not from a Console_Route exactly as it is today.
3. THE Test_Suite SHALL contain a test that, with the console on and off, sends a request to each existing route and path (`/health`, `/openapi.json`, `POST /flows/{name}` for success and error, `/mcp`, an unknown path and an unauthorized request) and asserts that the `Cache-Control` header equals the value of the same request with the console absent.
4. IF the `_NoStore` middleware makes a per-route value awkward, THEN THE design SHALL say so and propose the smallest change, limited to the Console_Routes.

### Requirement 16: Manual browser checklist

**User Story:** As a reviewer, I want a written browser checklist, so that the behaviour that tests cannot reach is checked by hand before the demo.

#### Acceptance Criteria

1. THE design SHALL contain a section `Manual browser checklist` with one numbered step per item and the expected result of each step.
2. THE checklist SHALL cover: the key entered through the field; the key passed through a `#key=` link with the address bar cleaned afterwards; a wrong key; a successful run; a 429 produced by running from two tabs; a keyboard-only pass of the whole page; reduced motion turned on in the operating system; both copy buttons; and the browser developer console showing no CSP violation and no error.
3. THE reviewer SHALL run the checklist, and the executor's final report SHALL list it as not run by the executor.
4. THE checklist SHALL also cover the Seance_Art (design, steps 18 to 20): visible with no horizontal scrollbar before any run at 1280x720 with the key panel and Run button in view; hidden after a run and back after Forget key; hidden in a window narrower than 68rem; announced by a screen reader as one image with the label of Requirement 11, criterion 11.
5. THE checklist SHALL also cover the MCP-visible Run (design, steps 21 to 30): the Network tab showing four `POST /mcp` requests in order and the key only as the `X-API-Key` request header; the Run_Strip as the first element of the result, the one-line Wire_Transcript entries, Expand all and Collapse all, and the initial open state of the two `tools/call` entries; Call_Via switched to REST giving one `POST /flows/<name>`; keyboard use of Call_Via; the MCP client blocks visible without opening anything; the layout at 1280x720; the Seance_Art hidden after a run; and a reply with `text/event-stream` if a test server can produce one.

### Requirement 17: Design size and task order

**User Story:** As a maintainer, I want a small design and a safe task order, so that the server side is proven before the page depends on it.

#### Acceptance Criteria

1. THE design SHALL consist of one static-asset loader, the route registration, the authentication exemption and the headers, and SHALL use no template engine.
2. THE tasks SHALL finish the server side (setting, loader, routes, headers, authentication exemption, startup record, packaging and their tests) and have it green before any task writes page logic, with a checkpoint task between the two.
3. THE tasks SHALL need no live host: every task and every test uses the Fake_Host or static files.
4. THE tasks SHALL record the library documentation checks (page, version, date) of the Conventions before the first task that writes code that uses that library.
5. THE tasks for Requirement 18 SHALL change page files (`index.html`, `console.css`, `console.js`, `snippets.js`) and tests only, SHALL order the pure functions and their Node tests before the markup, and the markup before the page script, and SHALL end with a run of the whole suite with Node on PATH.

### Requirement 18: MCP-visible Run

**User Story:** As a judge watching the demo, I want Run to go through the Publisher's real MCP endpoint and show me the messages, so that I can see a mainframe screen flow become an MCP tool instead of guessing that it is one.

#### Acceptance Criteria

1. THE Console_Page SHALL show the Call_Via control above the Flow list as one `<div role="group" aria-label="Call via">` that holds two native `<button type="button">` elements, labelled `MCP` and `REST` in that DOM order, each with `aria-pressed` equal to `true` when selected and `false` when not. Exactly one is selected. The initial selection is `MCP`. Activating a button with the keyboard (Enter or Space) or the pointer SHALL select it, SHALL leave the displayed result and Wire_Transcript as they are, and SHALL NOT start a call. The control SHALL be hidden while no key is held and SHALL be disabled while a call runs. The selection SHALL live in a module variable of `console.js` and in no storage.
2. WHILE Call_Via is `MCP`, WHEN the judge activates a Run button, THE Console_Page SHALL perform one MCP_Run: four requests, each a `POST` to the same-origin path `/mcp`, in this order and each sent only after the reply to the previous one has been read: (1) the `initialize` request, (2) the `notifications/initialized` notification, (3) the `tools/list` request, (4) the `tools/call` request for the selected Flow. THE Console_Page SHALL send no other request to execute or list anything in an MCP_Run, SHALL make no `GET` or `DELETE` request to `/mcp`, and SHALL repeat all four requests on every Run.
3. THE Console_Page SHALL send with each of the four requests the headers `Content-Type: application/json` and `Accept: application/json, text/event-stream`, and the API key only as `X-API-Key` through the one function of Requirement 5, criterion 6. THE Console_Page SHALL add `MCP-Protocol-Version: <negotiated version>` to requests 2, 3 and 4. THE Console_Page SHALL add `Mcp-Session-Id: <value>` to requests 2, 3 and 4 only WHEN the reply to request 1 carried that header (the recorded server sends none), and SHALL keep that value in a module variable only. No header builder in the Snippets_Module SHALL take the API key or any value derived from it.
4. THE Console_Page SHALL send in request 1 a JSON-RPC `initialize` with `id` 1 and `params` of `protocolVersion` `2025-11-25`, `capabilities` `{}` and `clientInfo` `{"name": "greenscreen-console", "version": "1"}`; in request 2 `{"jsonrpc": "2.0", "method": "notifications/initialized"}` with no `id`; in request 3 a `tools/list` with `id` 2 and `params` `{}`; and in request 4 a `tools/call` with `id` 3 whose `params.name` is the Flow name and whose `params.arguments` is the same JSON object text that the REST body of Requirement 6, criterion 3 would hold (`bodyText` of the Snippets_Module with secrets unmasked), so that an `integer` Caller_Input is sent as the digits typed.
5. THE Reply_Parser SHALL turn the HTTP reply text and its media type into a list of JSON_RPC_Messages: for `application/json`, one JSON object (or an array of objects) parsed as JSON; for `text/event-stream`, one message per event, where the event's `data:` lines are joined with a line feed and parsed as JSON, and `event:`, `id:`, `retry:` and comment lines (starting with `:`) are ignored, with lines separated by `\n`, `\r\n` or `\r` and events separated by a blank line; for an empty text, an empty list. IF the text is not valid for its media type, THEN THE Reply_Parser SHALL return a problem marker and no message. THE Reply_Parser SHALL run in the Snippets_Module so that Node can test it, and THE Console_Page SHALL read the whole reply with `response.text()` before parsing (no stream reader).
6. THE Console_Page SHALL accept the `protocolVersion` of the `initialize` result only when it is `2025-11-25`, `2025-06-18`, `2025-03-26` or `2024-11-05`, and SHALL send that value as `MCP-Protocol-Version`. IF the result holds any other `protocolVersion`, or none, THEN THE Console_Page SHALL stop the MCP_Run and show the Codes_Table entry `unreadable_reply` with the HTTP status.
7. THE Console_Page SHALL read from the `tools/list` result only the members of each tool that the Wire_Transcript projection lists (Requirement 18, criterion 14) and SHALL check that a tool whose `name` equals the selected Flow name is present. IF no such tool is present, THEN THE Console_Page SHALL stop before request 4 and show the Codes_Table entry `unknown_flow`.
8. WHEN a request fails, THE Console_Page SHALL stop the MCP_Run at that step, send no later request, and map the failure like this:
   - IF `fetch` rejects or the request is aborted by the timeout of criterion 11, THEN the entry `no_response`.
   - IF the HTTP status is 401, THEN the page discards the key and shows the `unauthorized` text and the key panel (Requirement 5, criterion 7).
   - IF the status is 404 and a session id is held, THEN the page drops the session id and repeats requests 1 to 4 once, and a second 404 is an `unreadable_reply`.
   - IF the status is not 2xx (or, for request 2, not 202) and the body is a publisher Error_Body whose `error.code` is a key of the Codes_Table, THEN that entry with the HTTP status.
   - IF the status is any other non-2xx, or a 2xx reply cannot be parsed, or no message with the expected `id` is found, or the parsed message is a JSON-RPC `error` object, THEN the entry `unreadable_reply` with the HTTP status and, for a JSON-RPC `error` object, one detail line with the numeric `code` and the fixed text of criterion 15.
   The page SHALL NOT fall back to REST by itself.
9. THE Console_Page SHALL classify the reply to request 4 as follows, reading only `result.isError`, `result.structuredContent` and its members named in Requirements 7 and 8:
   - IF `result.isError` is not `true`, `structuredContent` is an object with a string `flow` and an object `outputs`, THEN a success.
   - IF `result.isError` is `true` and `structuredContent.error.code` is a string that is a key of the Codes_Table other than a page-side key, THEN that entry. The entry text, the optional `message` (only WHEN the entry has `show_message`), `step_index`, `kind`, `expected` and the audit list are shown as in Requirement 7. No HTTP status line and no `Retry-After` line are shown, because the reply carries none (Finding 9); the page SHALL show the line `Reported by the MCP tool as an error result.` instead.
   - IF `result.isError` is `true` and the code is a string not in the table, THEN `unknown_code`.
   - IN every other case (no `structuredContent`, wrong shape, or a JSON-RPC `error` object), THEN `unreadable_reply`.
   THE Console_Page SHALL NOT read `content[].text` for any decision.
10. THE Console_Page SHALL show the outcome of criterion 9 in the same result region and with the same functions as a REST outcome (Requirement 7): the same outputs, the same `Elapsed (as seen by this browser)` line, the same audit list built from the seven members of `AUDIT_KEYS`, and the same error view. The elapsed time of an MCP_Run SHALL be measured for request 4 alone, from just before `fetch` to just after the response headers arrive. THE Console_Page SHALL NOT read the member `summary` of an Error_Body in an MCP_Run (Requirement 7, criterion 7 and 11 apply unchanged). THE REST path SHALL behave as before this requirement, except that the Run_Strip of criterion 16 is also shown for it.
11. THE Console_Page SHALL abort requests 1, 2 and 3 of an MCP_Run that have not returned their response headers after 15 seconds (an `AbortController` and a `setTimeout` with a function argument), and SHALL set no page-side limit on request 4, whose duration the Publisher limits with `GS_CALL_TIMEOUT` and reports as `call_timeout`. WHILE an MCP_Run is in progress, THE Console_Page SHALL keep the Run buttons and the Call_Via control disabled and SHALL show `Calling the mainframe…` in the live region (Requirement 6, criterion 4).
12. THE Console_Page SHALL show the Wire_Transcript in the result region, below the outputs and above the audit trail, after every MCP_Run, also one that stopped early. THE Wire_Transcript SHALL list one entry for each JSON_RPC_Message sent and each JSON_RPC_Message received, in the order they occurred, each shown by default as one Transcript_Line of criterion 24 (direction, method and a short fact, on one line). A reply with status 202 and no body, and an HTTP reply that holds no message the page could read, each get a line of criterion 24. Each entry SHALL be one native `<details>` element whose `summary` element holds the Transcript_Line and whose body is a `<pre>` holding the expanded text of criteria 13 and 14 (`(no body)` or `(nothing readable)` where there is no message). The Expand_Control of criterion 25 and the initial open state of criterion 26 apply.
13. THE expanded text of a sent entry SHALL be the message as it was built, pretty-printed with two-space indentation by a function that re-indents the JSON text without parsing numbers (so that an integer is shown exactly as sent), and SHALL show the typed value of a Secret_Input in a sent `tools/call` as `<SECRET>`, exactly as the snippets do (Requirement 9, criterion 3). A Bound_Input SHALL never appear, because the page never has its name or value (Requirement 4, criterion 4). A Transcript_Line never holds a Secret_Input value or a typed value (criterion 24).
14. THE expanded text of a received entry SHALL be a projection built from an allow-list, pretty-printed from the parsed object (numbers are shown as JavaScript prints them, so `0.0` appears as `0`):
    - `initialize` result: `protocolVersion`, `capabilities`, and `serverInfo` with `name` and `version`.
    - `tools/list` result: for each tool, `name`, `description`, `inputSchema`, `outputSchema` and `annotations` when present, and no other member.
    - `tools/call` result: `isError`, and `structuredContent` projected as follows: for a success, `flow`, `outputs` and `audit` with the seven members of `AUDIT_KEYS` for each entry; for an error, `error` with `code`, `message`, `step_index`, `kind`, `expected` and `audit` (seven members per entry). The `content` blocks SHALL be omitted from the display, because they repeat `structuredContent`, and the member `summary` SHALL be omitted, as every other member that is not listed.
    - a JSON-RPC `error` object: the `jsonrpc` and `id` members and an `error` member with `code` and the fixed text of criterion 15 in place of the server's `message`, and no `data`.
    - any other received message: only `jsonrpc`, `id` and `method`.
    Whenever the projection leaves out a member that the received message held, the entry SHALL end with one line `Left out by this page: <member names>` that names the omitted members of the first level and `structuredContent` and `error` levels (for example `content, structuredContent.error.summary`).
15. THE Snippets_Module SHALL hold the fixed text of the JSON-RPC error codes that the page may meet (`-32700` parse error, `-32600` invalid request, `-32601` method not found, `-32602` invalid params, `-32603` internal error, and `unknown error code` for any other number), and the page SHALL show only that text and the number, never the `message` or the `data` of a JSON-RPC `error` object, because a protocol-level message may quote request content. THE decision on secrecy: the Wire_Transcript shows what the existing REST result would show and no more. The `tools/call` arguments are what the judge typed, with Secret_Inputs masked; the `tools/call` reply is the same Success_Body or Error_Body that REST returns (Finding 9), whose outputs and audit the page already shows, and whose `summary` (which could echo non-hidden typed text, Finding 3) is dropped by the projection. THE Wire_Transcript SHALL show no request header, no response header, no HTTP header value, no API key, no session id and no URL query.
16. WHEN a run returns a success or an error whose `audit` array is present, THE Console_Page SHALL show, as the first element of the result region (above the result title, the outputs and the Wire_Transcript), the Run_Strip, an ordered list of three stages, built only from that run's data:
    - stage 1: `MCP client (this page)` for an MCP_Run, or `REST client (this page)` for a REST run;
    - stage 2: `MCP tool <Tool_Name>` for an MCP_Run (the Tool_Name from the `tools/list` reply), or `POST /flows/<name>` for a REST run;
    - stage 3: `3270 screens: <n> steps on <m> distinct screens`.
    THE Step_Count `n` SHALL be the number of audit entries whose `status` is not `skipped` (an entry that ran, whether `ok`, `failed` or any other word). THE Screen_Count `m` SHALL be the number of distinct non-null `signature` values among those same entries, so that steps that read no screen (`signature` null) add to `n` and not to `m`. The text SHALL use `1 step` and `1 distinct screen` when the number is 1, and `0` for zero. The outputs follow the strip, shown as before. WHEN the reply holds no `audit` array, THE Console_Page SHALL show no Run_Strip.
17. THE Console_Page SHALL show for each Flow, between its name and its inputs, one short line `This screen flow is published as an MCP tool: <Flow name>.`
18. THE Snippets_Module SHALL export, besides the functions of Requirement 9 and Requirement 14, pure functions with no `import`, no DOM and no key parameter: `buildInitialize(id)`, `buildInitialized()`, `buildToolsList(id)`, `buildToolsCall(id, name, inputs, maskSecrets)`, `mcpRequestHeaders(protocolVersion, sessionId)` (the `Content-Type`, `Accept`, `MCP-Protocol-Version` and `Mcp-Session-Id` headers only), `parseMcpReply(mediaType, text)`, `findReply(messages, id)`, `classifyToolsCall(message)`, `hasTool(listMessage, name)`, `prettyJson(text)`, `formatTranscriptEntry(entry)`, `summariseRun(audit)` returning `{steps, screens}`, `stripStages(via, toolName, counts)` and `jsonRpcErrorText(code)`. Each SHALL load under Node as an ES module with the rules of Requirement 14, criterion 1.
19. THE Test_Suite SHALL run these functions under `node` WHERE `node` is on PATH, with example tests for each (initialize, notification and call shapes; JSON, SSE with several events and CRLF, comments, empty text and malformed text for the Reply_Parser; the projection of each received kind; the Run_Strip numbers for runs with skipped entries, repeated signatures and null signatures; the Transcript_Line grammar of criterion 24 for every message kind, the length cap and the character rule; the label function and the fit comparison of criteria 25 and 26) and with a Hypothesis property test (one `@given` test, `max_examples` of at least 100, one `node` process per batch, first line `# Feature: console, Property 4: The wire transcript never holds the key or a typed secret`) that, for generated API key strings, generated Secret_Input values and generated server replies that carry the key and the Secret_Input values in members outside the allow-lists (`summary`, `content` text, JSON-RPC `data` and `message`, unknown members), asserts that the key and every Secret_Input value appear in no builder output, no header object and no formatted entry, and that every Secret_Input is shown as `<SECRET>`, and that every Transcript_Line contains neither the key nor a Secret_Input value, is at most 100 characters, holds no line feed or carriage return, and consists of printable ASCII (0x20 to 0x7E) only. Failure messages SHALL print no key and no Secret_Input value.
20. THE Console SHALL change no route, no header, no response body, no setting and no server file for Requirement 18: the six Console_Routes, the Console_CSP (`connect-src 'self'` already covers `/mcp`), `AuthMiddleware`, the `/mcp` mount and every existing response stay as they are, and no dependency is added. `/mcp` is an existing route that the page now calls; it is already in the Tunnel_Allow_List (section "Routes").
21. THE Console_Page SHALL keep the masthead and the Run button of the 1280x720 viewport on screen after a run (no scroll call, Requirement 6, criteria 8 and 9), SHALL keep the Seance_Art hidden once a result is shown, SHALL keep the Wire_Transcript `<pre>` blocks scrollable with the keyboard (`tabindex="0"` and a maximum height), SHALL place the Wire_Transcript below the outputs inside the result region, and SHALL keep the focus order: key panel, Call_Via, inputs, Run, MCP client blocks, curl block, result.
22. THE Test_Suite SHALL keep every existing test passing and SHALL change an existing test only where this requirement makes it false. The only such test is `test_requests_stay_on_allowed_paths` in `tests/unit/test_console_assets.py`, whose list of allowed request path prefixes gains `/mcp`. New static scans for criteria 3, 10, 14 and 15 go in a new test file. No scan that asserts a number of `fetch` calls exists (the existing one asserts at least three literal calls), so none changes.
23. THE final report of the executor SHALL list as not run by the executor the browser behaviours of the design's "Not verifiable here" note. THE final report SHALL also list the exact strings that a viewer sees for a successful run: the three Run_Strip texts, every Transcript_Line in order, the Expand_Control text in the all-closed and the all-open state, the output names and the elapsed label. THE executor SHALL generate them by running the Snippets_Module under Node against the four replies of an MCP_Run recorded from the Fake_Host (not typed by hand), so that the reviewer can compare them with the browser.

24. THE Snippets_Module SHALL build the Transcript_Line of every Wire_Transcript entry with `formatTranscriptEntry`, from this grammar. A line is the direction word (`sent` or `received`), a space, the label, and, where the grammar says so, a colon, a space and the fact. The fact comes only from the members that criterion 14 allow-lists, from the tool name the page itself sent, or from the HTTP status; it never comes from `summary`, `content`, a JSON-RPC `message` or `data`, a header, the API key or a typed value.
    - sent `initialize`: `sent initialize: protocol <protocolVersion>` from `params.protocolVersion`, `?` if it is not one of the four known versions.
    - sent `notifications/initialized`: `sent notifications/initialized`.
    - sent `tools/list`: `sent tools/list`.
    - sent `tools/call`: `sent tools/call: <params.name>`. The tool name only: no argument name, no argument value, no count.
    - received `initialize` result: `received initialize: <serverInfo.name>, protocol <protocolVersion>` (`unknown server` when the name is absent, `?` for a protocol version that is not known). The recorded server answers with the name `greenscreen-publisher` (version `0.1.0`, shown only in the expanded text), so an offer of `2025-11-25` gives `received initialize: greenscreen-publisher, protocol 2025-11-25`.
    - received `tools/list` result: `received tools/list: <n> tool(s)`; when `n` is more than 0, then `, ` and the names of the first three tools joined by `, `, followed by `, +<k> more` when there are more than three. Example: `received tools/list: 1 tool, tk5-system-info`; `received tools/list: 0 tools`.
    - received 202 reply to the notification: `received notifications/initialized: HTTP 202, no body`.
    - received `tools/call` success: `received result: <n> output(s), <m> audit entry/entries`, where `n` is the number of members of `structuredContent.outputs` and `m` the length of `structuredContent.audit` (0 when it is not an array). Example: `received result: 4 outputs, 39 audit entries`; singular forms `1 output` and `1 audit entry`.
    - received tool error (`isError` true): `received error: <code>`, where `<code>` is `structuredContent.error.code` and nothing else, shown only when it matches `^[a-z_]{1,40}$`, otherwise `unknown`. No HTTP status is added for a tool error that arrived with HTTP 200, and the member `summary` is never read.
    - received JSON-RPC error object: `received error: JSON-RPC <code>`, the number only (a safe integer, else `?`), never its `message` or `data`. WHEN the HTTP status is not 200, `, HTTP <status>` is appended. A publisher Error_Body (a message with a string `error.code` and no `jsonrpc` member, such as the 401, 413 or 500 body) gives `received error: <code>, HTTP <status>` by the same code rule.
    - a reply with no readable message that is not the 202 case: `received <method>: nothing readable, HTTP <status>`, where `<method>` is the method of the request it answers.
    - any other received message (well-formed but not recognised, a server-initiated request or notification): `received <method>: unrecognised message`, where `<method>` is the message's own `method` when it is a string, otherwise the method of the request it answers, cut to 40 characters.
    - Limits: every name, code and method inside a line is cut to 40 characters; counts are non-negative safe integers (else `?`); the whole line is cut to 100 characters (the first 97 followed by `...`); after assembly every character outside 0x20 to 0x7E is replaced by `?`, so a line is a single line of printable ASCII with no tab, line feed or carriage return. A Secret_Input value or the API key cannot enter a line, because no line includes a request argument, a header or a field outside the allow-lists.

25. THE Wire_Transcript SHALL start with the Expand_Control: one native `<button type="button">`, placed before the list in DOM order and so first in the keyboard order of the transcript. Its text is `Expand all` while at least one entry is closed and `Collapse all` while every entry is open (a label swap; the button carries no `aria-pressed`, so its name always says what pressing it does). The text comes from `toggleAllLabel(allOpen)` of the Snippets_Module. Pressing it opens every entry or, when every entry is open, closes every entry. The page SHALL update the text whenever any single entry is opened or closed (the `toggle` event). Activating the control SHALL NOT move focus and SHALL NOT call a scroll function (Requirement 6, criteria 8 and 9).

26. WHEN the Wire_Transcript is built, every entry SHALL start closed, except that the `tools/call` sent entry and its received entry start open if and only if the whole transcript list still ends inside the Fit_Limit with those two entries open. THE page SHALL decide this once per run, after the result region is rendered and the layout has the class `has-result`, as follows: open the two entries, measure the bottom edge of the transcript list in document coordinates (the `getBoundingClientRect` bottom of the list minus the `getBoundingClientRect` top of the document element, so no scroll offset is read), and close them again unless `fitsInFirstScreen(bottom, limit)` of the Snippets_Module is true. The decision SHALL therefore consider the strip, the outputs, the elapsed line and every transcript line, and not the audit list that follows. IF the layout cannot be measured (a missing or throwing `getBoundingClientRect`, a non-finite number, a list of zero height), THEN every entry stays closed. The decision is not repeated on resize, on a toggle or on a change of Call_Via. It SHALL NOT scroll the page, SHALL leave the masthead where it is and SHALL NOT change the focus rules of Requirement 6, criteria 8 and 9. This is a browser behaviour: the test suite covers only the comparison function and the static shape of the code, and the design lists it under "Not verifiable here".

## Routes

When `GS_ENABLE_CONSOLE` is off, none of the routes in table (a) is served; each answers as an unknown path does (Finding 5). Exact paths only; no wildcard is needed or registered. The page makes no request to `/docs` or `/health`. Since Requirement 18 it calls `/mcp` (table (b)).

### (a) Routes the console adds

| Method | Path | Auth required? | Served when `GS_ENABLE_CONSOLE` is off? | Purpose |
|---|---|---|---|---|
| GET | `/` | No (exempt, exact pair) | No (401 without key, 400 with key, as today) | The Console_Page (`index.html`) |
| GET | `/console/console.css` | No | No | Stylesheet |
| GET | `/console/console.js` | No | No | Page logic: key handling, listing, run, rendering |
| GET | `/console/snippets.js` | No | No | Pure builders of the `curl` and MCP texts |
| GET | `/console/codes.json` | No | No | Codes_Table: every Error_Code with status and plain-words text |
| GET | `/console/favicon.svg` | No | No | Icon, so browsers do not request `/favicon.ico` |

### (b) Existing routes the page calls

| Method | Path | Auth required? | Served when `GS_ENABLE_CONSOLE` is off? | Purpose |
|---|---|---|---|---|
| GET | `/openapi.json` | Yes (`X-API-Key`) | Yes (always; not gated by `GS_ENABLE_DOCS`) | The Flow_Listing: Flow names, descriptions and Caller_Inputs |
| POST | `/flows/{name}` | Yes (`X-API-Key`) | Yes | Run one Flow while Call_Via is `REST`. One exact path per published Flow; the demo publishes `tk5-system-info`, so the Tunnel_Allow_List holds `/flows/tk5-system-info` |
| POST | `/mcp` | Yes (`X-API-Key`) | Yes (mounted whatever the console setting is) | The MCP_Run (Requirement 18): `initialize`, `notifications/initialized`, `tools/list`, `tools/call`. An existing route; the console adds nothing to it. The Tunnel_Allow_List already opens it (Decision 12), so no tunnel change is needed. |

### Not called by the page, listed for the Tunnel_Allow_List decision

| Method | Path | Auth required? | Note |
|---|---|---|---|
| GET, DELETE | `/mcp` | Yes | Never sent by the page (Requirement 18, criterion 2). |
| GET | `/health` | No | Not used by the page. Open it only if an external monitor needs it. |
| GET | `/docs` | Yes | Served only with `GS_ENABLE_DOCS=true`. Not needed. |

Decided (Decision 12): the reviewer owns the tunnel. The Tunnel_Allow_List opens the six Console_Routes (`GET /` and the five `GET /console/...` files), `GET /openapi.json`, `POST /flows/tk5-system-info`, `/mcp` and `/health`. `/docs` stays closed.

## Decisions

All fifteen decisions below are resolved by the reviewer. Where the list text further down says "default" or "decide", this table wins.

| # | Decision |
|---|---|
| 1, 2 | As proposed: the Flow_Listing comes from `/openapi.json` with the key; no new unauthenticated endpoint. |
| 3 | The 429 text stays as written. |
| 4 | No change to the audit. |
| 5 | The key is memory only. No `sessionStorage` anywhere; a static scan forbids it (Requirement 5). |
| 6 | One fixed `console enabled` startup record (Requirement 1, criterion 6). |
| 7 | Outputs are shown as returned. The `USERID` on screen is accepted. |
| 8 | `summary` in the error body stays as it is; out of scope. |
| 9, 10, 11 | As proposed; one origin. |
| 12 | The reviewer opens the six Console_Routes, `/mcp` and `/health` in the tunnel; `/docs` stays closed (section "Routes"). |
| 13 | Generic `mcpServers` shape plus a line saying clients differ; the design checks Kiro and Claude docs (Requirement 9, criterion 10). |
| 14 | `HEAD /` and `OPTIONS /` stay at the framework default; the design records what they return, console on and off (Requirement 2, criterion 9). |
| 15 | New tests beside the existing ones; no existing test body is edited (Requirements 12 and 13). Superseded in one place by Decision 20. |
| 16 | Run goes through MCP by default (owner feedback). The page calls the existing `/mcp` on the same origin; no server change, because the recorded endpoint is stateless, replies JSON, and returns the audit trail inside `tools/call` (Finding 9). |
| 17 | Call_Via is two toggle buttons with `aria-pressed`, not a radio group: no `<input>`, so no new label rule, and the buttons sit in DOM order MCP then REST. |
| 18 | The Wire_Transcript shows what REST would show and no more: allow-list projection, `summary` and the `content` duplicate dropped, JSON-RPC `message` and `data` never shown, Secret_Inputs as `<SECRET>`, no header values (Requirement 18, criteria 13 to 15). The page tells the viewer what it left out. |
| 19 | Step_Count is the audit entries that are not `skipped`; Screen_Count is the distinct non-null signatures among them (Requirement 18, criterion 16). The MCP handshake is repeated on every Run, although the server is stateless, because the point is to show real traffic. |
| 20 | One existing test changes: the allowed-path list of `test_requests_stay_on_allowed_paths` gains `/mcp` (Requirement 18, criterion 22). |
| 21 | Each Wire_Transcript message is one line (direction, method, one fact from allow-listed members) that expands through a native `<details>`; one Expand all / Collapse all button; the Run_Strip is the first element of the result (owner layout instruction). The lines are built in `snippets.js`, so Node tests and Property 4 cover them. |
| 22 | The two `tools/call` entries start open only when the transcript list ends inside the Fit_Limit after rendering with them open; otherwise all entries start closed, and also when layout cannot be measured. This is browser behaviour that cannot be verified here. |
| 23 | The Expand_Control swaps its label and carries no `aria-pressed`, so a screen reader hears the action, not a state that the label already states. |

## Open decisions (resolved above; original text kept for the record)

These need the reviewer's decision or could not be reconciled from the code. Each has a default that the design uses unless the reviewer says otherwise.

1. **GS_ENABLE_DOCS interplay.** The listing uses `/openapi.json`, which is always served, so the console does not depend on `GS_ENABLE_DOCS`. Default: independent. The alternative (a dedicated `/console/flows.json` that needs a key) adds a route and a second description of the Flows; not recommended.
2. **No new unauthenticated endpoint that leaks Flow metadata.** The six open routes serve only static files that are the same for every deployment (`codes.json` holds the public error codes, not Flow names). Default: confirmed by Finding 6. Flagged because the open routes are the one change to the key check.
3. **The 429 text.** Default: `The mainframe is busy with another call. Wait a moment and try again.` The limiter limit is the Publisher's `GS_MAX_CONCURRENCY` (1 for the demo), not a mainframe fact; the text says "busy" because that is what the judge should do. The reviewer may prefer wording that names the publisher.
4. **The additive audit field on the REST response.** None is proposed (Finding 1). If the reviewer wants the trail to say which key was pressed or which field was typed, that is a change to `AuditRecord`, the OpenAPI schema, MCP `outputSchema` and Properties 3 and 8, and a literal in a Flow file is not guaranteed to be non-secret. Default: not done.
5. **`sessionStorage`.** The brief allows it. Default: memory only, so a reload asks for the key again. Allowing `sessionStorage` would put the key in storage readable by any script on the origin; the strict CSP makes that low risk but not zero. Decide before the design.
6. **Startup report for the console.** `GS_ENABLE_DOCS` has no startup report today (Finding in `cli.py`: only `publishing %d of %d flows over %s`). Requirement 1, criterion 6 adds one fixed-text record, only for the console, and does not add one for docs. The reviewer may prefer to fold it into the existing record, which would change a line that `tests/unit/test_publisher_cli.py` matches (`publishing 1 of 8`); not recommended.
7. **The demo account's user id on screen.** The `USERID` output equals the bound user id (Finding 4). The stock TK5 demo account is public in the TK5 documentation, but the steering says credentials come only from the environment and never appear in code, fixtures or logs. Default: show outputs as returned. The reviewer may want the user id masked in the demo video or an output removed from the demo Flow.
8. **The `summary` member of Flow-stop errors.** The server sends it to every REST client and it can echo non-hidden typed text such as the user id (Finding 3). The console does not read it. The reviewer decides whether the public demo should keep sending it; changing it is outside this spec.
9. **The demo host URL.** Not hard-coded anywhere. The snippets use `location.origin`. Behind a tunnel that changes `Host` or the scheme, `location.origin` is still what the judge's browser used, which is the right URL for a copy-paste.
10. **Favicon requests.** Default: `/console/favicon.svg` with a `<link rel="icon">`, so `/favicon.ico` is not requested. A crawler may still ask for `/favicon.ico`; it gets `unauthorized` (console on or off). That is one more 401 in the tunnel log and does no harm.
11. **CSP for the page's `fetch` calls.** `connect-src 'self'` is in the header (Requirement 2, criterion 5). If the tunnel serves the page and the API from different origins, `'self'` would not cover the API; the design assumes one origin, as in the brief. `form-action 'none'` is safe only because the page has no `<form>`.
12. **The tunnel allow-list.** Eight exact entries (section "Routes"). The reviewer decides about `/mcp`, `/health` and `/docs`. `POST /flows/{name}` needs one entry per published Flow, so the allow-list depends on `GS_PUBLISH_FLOWS`.
13. **MCP client config shape.** The snippet uses the common `mcpServers` shape with `url` and `headers`. Clients differ (some use `type: "http"` or `serverUrl`). Not verified against any client. The design checks current documentation for the clients it names; the default shows the generic shape and one line saying so.
14. **`HEAD` and `OPTIONS` on the console routes.** Left to the framework default (Requirement 2, criterion 9). The tunnel may probe with `HEAD /`; if so, the reviewer may want `HEAD` allowed explicitly (and added to the exempt pairs).
15. **Where the wheel test lives.** A new test next to the existing one, without editing the existing body (Requirement 12, criterion 3). The reviewer may prefer a new file; no behaviour differs.

## Review record

- The reviewer ran manual browser checklist steps 1 to 12 in headless Chrome 157 at 1280x720 against the live host: pass, no CSP violation, no script error.
- Linux suite: 2416 passed, 0 failed, 15 Node tests skipped (no Node on that machine).
- Polish after that run (Requirements 6.8, 6.9, 7.3, 7.11, 7.12, 8.4, 14.8): no scroll on focus, denser audit lines, singular `1 second`, and a narrower `summary` scan. Checklist steps 13 and 14 (tunnel, CDN) were not part of that run.

## What was not verified

- Requirement 18 (written after probing `/mcp` in-process over ASGI on 2026-11-18): nothing about it has run in a browser. Not verifiable without one: the open-state decision of criterion 26 (`getBoundingClientRect` and the viewport height after render), the `toggle` events behind the Expand_Control, scroll anchoring after an expansion, `fetch` to `/mcp` with the headers of criterion 3, `response.text()` on a JSON reply and on a `text/event-stream` reply (the recorded server sends only JSON), whether `Mcp-Session-Id` is readable on a same-origin reply (none is sent by this server), `Accept` negotiation by the browser, `AbortController` with a timeout, the focus order and `aria-pressed` announcement of Call_Via, the transcript scroll areas, the layout at 1280x720, the clipboard on the new blocks, and any proxy or tunnel behaviour on `POST /mcp`. The probe also did not run `tools/call` for a `busy` result; that outcome was read from `calls.py` (it is a tool error with HTTP 200 and no `Retry-After`).
- Superseded in part by the Review record above: steps 1 to 12 of the checklist ran in headless Chrome 157. Still not run: checklist steps 13 to 17, other browsers, screen readers.

- No browser was run. The behaviour of `history.replaceState`, the CSP in a real browser, ES module loading under `script-src 'self'`, focus order, screen readers and `prefers-reduced-motion` are not verified by this stage. The design plans static tests and a manual checklist for the reviewer.
- Whether `HEAD /` or `OPTIONS /` is answered by the framework once a `GET /` route exists was not checked (decision 14).
- The MCP config shapes of specific clients were not checked (decision 13).
- The tunnel's own behaviour (headers it adds or strips, whether it caches, whether it rewrites `Host`) was not checked.
- Library documentation for Starlette, FastAPI, `importlib.resources` and the browser APIs was not checked, because this stage writes no code. The Conventions make the check a rule for the design and tasks stages.
- Edge features that inject scripts or rewrite pages (CDN or Cloudflare-style injection) would break the Console_CSP. This was not checked; the reviewer checks it at deploy. `no-transform` (Requirement 15) reduces but does not remove the risk.
- No test was run. Finding 8 comes from reading the test files, not from a run.
