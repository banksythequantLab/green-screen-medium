# Implementation Plan: publisher

## Overview

Implement the `greenscreen.publisher` Python 3.11+ package from `requirements.md` and `design.md` in this folder. One process loads every Flow and publishes each as an MCP tool and a REST endpoint. Both front ends call one `CallService`. The plan is sized for three working days (about 25 hours) and builds the cheapest vertical slice first: one Flow over REST and MCP on the Fake_Host by the end of day one.

### Estimates and order

| # | Top-level task | Hours | Day |
|---|---|---|---|
| 1 | Foundation: packaging, vault, config, registry and schemas, Fake_Host | 3.0 | 1 |
| 2 | Call service: limiter, error mapping, worker, timeout, `session_clean` | 3.0 | 1 |
| 3 | Vertical slice: REST, MCP, app wiring, `tk5-system-info` over both | 2.5 | 1 |
| 4 | Checkpoint, end of day one (demo slice) | 0.5 | 1 |
| 5 | Hardening: auth, crash guard, handlers, OpenAPI, bindings, wiring | 4.0 | 2 |
| 6 | CLI, stdio hygiene, shutdown, startup-failure tests | 2.0 | 2 |
| 7 | Property tests, group A: Properties 1, 2, 3, 4, 11, 12, 13, plus shared test helpers and the worker fixes 7.0 and 7.0b (7.0b adds 0.25 h) | 3.75 | 2 to 3 |
| 8 | Property tests, group B: Properties 5, 6, 7, 8, 9, 10, 14 | 3.5 | 3 |
| 9 | Checkpoint, end of the properties (timing and count) | 0.5 | 3 |
| 10 | Perf test, live integration test, static rule tests | 2.0 | 3 |
| 11 | Final checkpoint (added 2026-11-17, 0.25 h) | 0.25 | 3 |
| | **Total** | **25.0** | |

Day one is tasks 1 to 4 (9.0 hours, the slice). Day two is tasks 5 and 6, then the start of task 7. Day three is the rest of 7, then 8, 9, 10 and 11.

### Rules for every task

- The Fake_Host (`tests/publisher_support.py`, built on `ScriptedSession`, `FakeClock` and `tests/flow_support.py`) serves every test except the integration test of task 10.2. No unit or property test needs the live host, starts a real host session or opens a network connection (the stdio test of task 6.2 and the real-`uvicorn` Crash_Guard test of task 5.2 are the stated exceptions, and they use the Fake_Host only).
- The Startup_Signatures are loaded once by `prepare` and passed to `run_flow`. No test patches `load_bundled_signatures` or any other loader (Requirements 1.8, 19.1), except the one registry unit test that simulates the `signatures: load_failed` failure (accepted exception, design "Implementation notes").
- Screens come only from `captures/` through `tests/flow_support.py` helpers. No task captures, writes or adds a screen that holds a typed password. No task writes a credential, an API key or a Probe_Value into any file. `TK5_USERNAME` and `TK5_PASSWORD` are read only by the integration test (task 10.2). `.kiro` is never git-ignored.
- The Publisher does not recover a locked TSO user id and adds no `RECONNECT`, retry or reaper (Requirement 23.7). Nothing in this plan builds anything under "What this design deliberately does not build". The design does not call for a README section, so none is planned.
- Every property test is exactly one `@given` test with `@settings(max_examples=100, deadline=None)` or more, and its first line is the comment `# Feature: publisher, Property N: <title>`. Every property test task is required.
- Time budget (Requirement 20.17): the publisher property modules take under 120 seconds together and the whole `tests/property` suite under 240 seconds. The limits were raised from 25 and 115 seconds to 60 and 150 seconds on 2026-11-17 by the user's decision, after the Property 12 and 13 measurements, and to 120 and 240 seconds the same day, after a clean serial run of the 14 publisher property modules took 74.7 s (pytest-reported; slowest: Property 6 15.2 s, Property 14 13.4 s, Property 11 9.0 s) and the user's `pytest -m "not integration"` run gave 1940 passed, 4 skipped, 0 failed in 301 s on a loaded machine. No test is trimmed and `max_examples` is never lowered below 100 to save time.
- One-off mutation checks (tasks 7.8, 8.1, 8.2) change production code temporarily. They are verification steps, not permanent tests. The executor records the file hash (or `git diff` state) before, restores the file afterwards, verifies that the file is byte-identical to its state before the mutation, and reports the result. A production file left changed is a failure of the task.
- `pyproject.toml` is touched in task 1.1 only. The 31-package `publish` extra is approved; the environment install happens in task 1.1 only.
- The demo runs with `GS_PUBLISH_FLOWS=tk5-system-info`, because `tk5-logon` leaves the user id logged on and locked. Unset or empty `GS_PUBLISH_FLOWS` still publishes every Loaded_Flow. Tests set the variable through the injected environment mapping and never rely on the process environment.
- `cancelled` is a Call_Log_Record outcome only (Requirements 8.2, 8.8). It is never an Error_Code and never appears in a response, the OpenAPI document or `tools/list`.
- New publisher code follows the sibling conventions: `from __future__ import annotations`, frozen slotted dataclasses, the logger `greenscreen.publisher`, exceptions and log records that carry no values.

## Tasks

- [x] 1. Foundation: packaging, vault, config, registry and schemas, Fake_Host (about 3.0 h, day 1)
  - [x] 1.1 Packaging: the `publish` extra, the console script and the package skeleton
    - In `pyproject.toml` add under `[project.optional-dependencies]` the extra `publish = ["mcp>=2.3,<3", "fastapi>=0.163,<1"]`, make the `dev` extra also pull it (`greenscreen-connector[publish]`), and add `[project.scripts] greenscreen-publish = "greenscreen.publisher.cli:main"`; leave `dependencies` unchanged and add nothing else. Package discovery (`include = ["greenscreen*"]`) already covers `greenscreen.publisher`; check it and change it only if it does not
    - Create `greenscreen/publisher/__init__.py` that imports neither `mcp`, `fastapi`, `starlette` nor `uvicorn` at module level (it exports names lazily or not at all until task 3.3)
    - Install into the project environment with `pip install -e ".[dev]"`. This is the only task that installs packages, and the 31 packages resolved on 2026-11-17 are approved
    - Create `tests/unit/test_publisher_packaging.py`: `pyproject.toml` lists `mcp` and `fastapi` only under `publish`, `dependencies` is unchanged, `dev` pulls `publish`, the console script is declared; a subprocess check that importing `greenscreen.flow`, `greenscreen.connector` and `greenscreen.recognizer` leaves `mcp`, `fastapi`, `starlette` and `uvicorn` out of `sys.modules`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.6, 16.5_

  - [x] 1.2 Implement `greenscreen/publisher/vault.py`
    - `SecretBox` (`adopt`, `mapping`, `merged`, `clear`; `repr` shows names only; not iterable, not hashable) and `BoundValues` (`for_flow`, `names_for`, `repr` is `BoundValues(flows=N)`, no pickling) as in the design
    - Create `tests/unit/test_publisher_vault.py`: `adopt` empties the adopted dict on `clear`, `merged` returns a fresh dict that `clear` also empties, no value appears in `repr`, `str` or an attempted iteration of a box or a store
    - _Requirements: 3.9, 7.6, 7.7, 22.6, 22.10_

  - [x] 1.3 Implement `greenscreen/publisher/config.py` (settings only)
    - `StartupError`, the frozen `Settings` and `load_settings(environ)` reading exactly the variables of Requirement 15.1 with the ranges and defaults of the design, empty treated as unset, `ConnectorConfig` built once from the injected mapping with the `GS_HOST` / `GS_PORT` / `GS_S3270_BINARY` name mapping, and the rules for `GS_API_KEY` (at least 16 characters), `GS_AUTH_DISABLED` with a non-loopback `GS_PUBLISH_HOST`, and stdio ignoring the key. `parse_bindings` is task 5.4
    - `Settings.publish_flows` keeps the raw `GS_PUBLISH_FLOWS` text (`None` when unset or zero-length; a whitespace-only value is kept and rejected later), and `parse_publish_list(text)` returns `None` (publish all) or the tuple of trimmed names, checking in this order: an empty item gives `GS_PUBLISH_FLOWS: empty_item`, a repeated name gives `GS_PUBLISH_FLOWS: duplicate_name (<flow>)`. Names match exactly and case-sensitively. The third check, `unknown_flow`, needs the Loaded_Flows and lives in `select_published` (task 1.4)
    - Every `StartupError` message names the variable and the rule and holds no value; no function opens a session or a port
    - Create `tests/unit/test_publisher_config.py`: defaults, each range edge and each invalid case (out-of-range integer, bad transport, bad boolean, missing `GS_HOST`, short or missing key, auth disabled on a non-loopback host), asserting the message names the variable and holds none of the supplied values; `parse_publish_list` for unset, empty, a valid list, whitespace around names (trimmed), a trailing comma, adjacent commas and a whitespace-only value (each `empty_item`), and a duplicate name (`duplicate_name`), each message naming `GS_PUBLISH_FLOWS`
    - _Requirements: 1.9, 1.10, 1.11, 1.12, 9.5, 10.1, 13.1, 13.5, 13.6, 13.10, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 16.4, 19.10_

  - [x] 1.4 Implement `greenscreen/publisher/registry.py`
    - `load_flows` (every Loaded_Flow: bundled Flows, then `GS_FLOWS_DIR` in ascending file order; duplicates and bad files stop the startup with a `StartupError`, and ALL Flows are loaded and validated before any allow-list is applied), `select_published(loaded, names)` (returns `loaded` unchanged for `None`; otherwise raises `GS_PUBLISH_FLOWS: unknown_flow (<flow>)` for the first unknown name in list order and returns the named Flows in loading order, not list order), `load_startup_signatures` (one call of `load_bundled_signatures()`, failure becomes `signatures: load_failed` with `from None`), `_Decl`, `check_inputs` (message returned after the `except` block), `build_schemas` (the one pure Schema_Generator with the `_ecma_safe` pattern rule), `PublishedFlow` and `build_registry` (Published_Flows only, deadline of Requirement 10.2, immutable mapping)
    - Create `tests/unit/test_publisher_registry.py`: `select_published` with `None`, a valid list (loading order, not list order) and an unknown name (`unknown_flow`, no session); an invalid file in `GS_FLOWS_DIR` that the list would leave out still stops the startup; the registry holds only the selected Flows; the three bundled Flows load without a session; each failure of Requirement 1 (missing directory, bad file, duplicate name with both sources named, signature loading failure); `prepare_inputs` accepts `_Decl`; the schema rules of Requirement 2 on the bundled Flows (`writeOnly` only on secrets, int bounds, no `default`, `examples`, `example`, `const` or `enum`, a bound name absent); `check_inputs` returns `str(FlowInputError)` and a bound name gives the rule `undeclared`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.13, 1.14, 1.15, 19.10, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 4.1, 4.2, 10.2, 22.1, 22.2_

  - [x] 1.5 Create `tests/publisher_support.py` (Fake_Host) and test it
    - `HostSession` over `ScriptedSession` (`echo_typing=True`) implementing `open`, `close`, `abort` (thread-safe, idempotent; an aborted session raises from every later call and from a blocked call), a session factory with injectable failures (at the factory, at `open`, at the n-th call of each Session method, at `close`, with a chosen exception class or a `BaseException`), a blocking mode (the n-th `read_screen` waits on an event that `abort()` releases by raising), counters (sessions created, opened, closed, aborted, live) and an ordered call list with sequence numbers and thread ids; the `MINI` Flow of the design (`expect tk5-logon`, type userid, enter, `expect ispf-primary-menu`, extract `RELEASE`, optional secret `password` and optional `int` Input) and a helper that scripts the `tk5-system-info` capture chain
    - Create `tests/unit/test_publisher_fake_host.py`: the example test of Requirement 19.9 (`abort()` while a call is blocked raises in the blocked call, no later call succeeds, two `abort()` calls act as one, `close()` after `abort()` returns), the counters and the failure injection
    - Leave the `LogCapture`, frame scanner and leak helpers to task 7.1 (same file, later wave)
    - _Requirements: 19.1, 19.2, 19.9_

- [x] 2. Call service: limiter, error mapping, worker, timeout, `session_clean` (about 3.0 h, day 1)
  - [x] 2.1 Implement the limiter, outcome types and error mapping in `greenscreen/publisher/calls.py`
    - `Limiter` (event-loop confined, no `await` between check and increment), `CallOutcome` with `code: ResponseCode` (`ok` or an Error_Code) whose `__post_init__` raises `ValueError` for any other code, the separate `LogOutcome` (a `ResponseCode` or `cancelled`) and `LOG_ONLY_OUTCOMES = frozenset({"cancelled"})` used only by the log writer, the `Session` protocol with `abort()`, the `MESSAGES`, `HTTP_STATUS` and `error_body` tables for the 13 Reason_Codes and 9 Publisher_Codes exactly as in the design table, and the plain-data copy of a `FlowError` (`reason`, `step_index`, `kind`, `expected`, `summary.to_dict()`, `audit`)
    - Create `tests/unit/test_publisher_error_table.py`: the table is total over `REASON_CODES` and the nine Publisher_Codes, each code has one status and one fixed message, allowed members per code, the Limiter accepts exactly its limit; `HTTP_STATUS` and `MESSAGES` have exactly the 22 Error_Codes as keys, `cancelled` is in neither, `LOG_ONLY_OUTCOMES` is disjoint from the codes, and `CallOutcome("cancelled", {})` raises `ValueError`
    - _Requirements: 5.2, 6.1, 6.2, 6.4, 6.5, 6.6, 8.8, 9.1, 9.2, 19.3_

  - [x] 2.2 Implement `CallService` in `greenscreen/publisher/calls.py`
    - `precheck`, `execute` (the step order of Requirement 3.1), the worker thread with the `_Guarded` Session wrapper and no secret bound to a local, the Call_Deadline with `abort()` from outside the worker and the 5 second grace, cancellation and `BaseException` handling with shielded teardown, `begin_shutdown`, `drain`, and the single Call_Log_Record writer, which takes a `LogOutcome` from its own local variable and never from a `CallOutcome`, with `session_clean` (false only for `unknown_screen`, `call_timeout`, a cancelled call and a shutdown teardown). On cancellation `execute` reads `closing` once: `outcome` is `cancelled` when the Publisher is not shutting down (client gone), and `shutting_down` for a `drain` teardown or a cancellation while `closing`. The cancellation path builds no `CallOutcome`, so `cancelled` can never reach a response
    - The worker reads no attribute of `S3270Error` or `ParseError` and calls `str()` or `repr()` only on `FlowInputError`; the `finally` of `execute` drops every reference to the box, the merged mapping and any `Screen` before the response is built
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 6.3, 6.7, 6.8, 8.1, 8.2, 8.8, 8.3, 8.4, 9.2, 9.3, 9.4, 10.2, 10.3, 10.4, 10.5, 10.6, 16.1, 16.2, 16.3, 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

  - [x] 2.3 Implement `ConnectorSession` in `greenscreen/publisher/calls.py`
    - The default Session_Factory product: a `Connector` built with a `process_factory` that records the `Popen`, and `abort()` that sets the flag and kills and waits the process without touching the Connector; no change to `greenscreen.connector`
    - Create `tests/unit/test_publisher_connector_session.py` with a stand-in process that never answers `ReadBuffer`: `abort()` unblocks the worker with an error, `close()` afterwards returns at once, a later `enter()` raises `SessionClosedError`, and `abort()` before `open()` makes `open()` raise
    - _Requirements: 10.3, 10.4, 19.1_

  - [x] 2.4 Write the `CallService` unit tests
    - Create `tests/unit/test_publisher_calls.py` against the Fake_Host and `FakeClock`: lifecycle order (close before Slot release, one session per Call, `close` raising sets `close_failed`, open failure gives `host_unavailable` with the session closed); validation before any factory call; `busy` without queueing; the deadline path with a blocked read (`call_timeout`, session aborted, no later key, no `step_index`); cancellation and a `BaseException` re-raised unchanged after teardown; `run_flow` runs off the event-loop thread; `drain` tears down an open call and the call logs `shutting_down`
    - Example tests for `session_clean` with `caplog` at INFO on `greenscreen.publisher` (Requirement 19.8): `unknown_screen` in the steps, `unknown_screen` in the `finally` phase, `call_timeout`, cancellation while not shutting down (outcome `cancelled`), cancellation while `closing` and a `drain` teardown (both outcome `shutting_down`) all carry `session_clean` false; a success, `unexpected_screen`, `timeout` and `host_unavailable` carry no such key; every record holds no value and no screen text
    - A cancelled call produces no response; assert that the text `cancelled` appears in no response body, header or `CallOutcome` of any test in this file
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 4.1, 4.2, 6.8, 8.2, 8.8, 9.2, 10.3, 10.4, 10.5, 16.2, 19.3, 19.8, 23.1, 23.2, 23.3, 23.4, 23.5, 23.6_

- [x] 3. Vertical slice: REST, MCP, app wiring, `tk5-system-info` over both (about 2.5 h, day 1)
  - [x] 3.1 Implement `greenscreen/publisher/rest.py` (routes only)
    - `build_rest(service, registry, settings, mcp_asgi)`: `POST /flows/{name}` taking the raw `Request` (order: `precheck`, media type check, `read_json`, `execute`), `GET /health` (exactly `status` and `flows`, where `flows` counts Published_Flows only; no factory call), the `/mcp` `Route`, `read_json` (`Content-Length` check, streamed read stopping at the limit, duplicate-key and non-finite-number hooks, flag set in the `except` block and the outcome returned after it, `SecretBox.adopt`), `Cache-Control: no-store` on every response, and the Error_Body responses with the HTTP status table. Auth, `CrashGuard`, replaced framework handlers and OpenAPI come in tasks 5.2, 5.3 and 5.5
    - Create `tests/unit/test_publisher_rest.py`: the `MINI` Flow through the ASGI client (success and one Flow stop), wrong media type, malformed JSON, duplicate key, `NaN`, array body, `1.0` for an `int` Input giving `input_invalid`, `true` for an `int` Input, oversize with and without `Content-Length`, `/health` with a factory that fails the test if called and with a registry of fewer Flows than were loaded (the count is the published count), and `POST /flows/<name>` for an unpublished Loaded_Flow giving the same `unknown_flow` body as an unknown name
    - _Requirements: 1.15, 4.3, 4.4, 4.5, 4.7, 5.1, 7.9, 11.1, 11.2, 11.3, 11.4, 11.7, 6.4_

  - [x] 3.2 Implement `greenscreen/publisher/mcp_server.py`
    - `build_mcp_server` (low-level `mcp.server.lowlevel.Server`, hand-written schemas, `on_list_tools` prebuilt, `on_call_tool` wrapped in one `try/except Exception` returning an `internal_error` result, `SecretBox.adopt(arguments or {})`, one text block plus `structuredContent`, `isError` for every error), `build_manager` (stateless, JSON responses, `security_settings=None`, `max_request_body_size=GS_MAX_BODY_BYTES`) and `run_stdio`; no resource, prompt or other tool
    - Create `tests/unit/test_publisher_mcp.py` with the in-memory `Client` in both `legacy` and `auto` modes: `tools/list` for the bundled Flows (schemas equal the generator output), `tools/call` success and failure, an unknown tool and an unpublished Loaded_Flow both giving the same `unknown_flow` error result with no argument value (and `tools/list` omitting the unpublished Flow), no `cancelled` in any result or listing, no resource or prompt capability, an `isError` result with `outputSchema` declared accepted by the SDK client
    - _Requirements: 1.15, 4.6, 4.7, 6.5, 8.8, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.8, 14.10, 19.3_

  - [x] 3.3 Implement `greenscreen/publisher/app.py` and run the day-one slice
    - `Prepared`, `prepare(environ)` (in this order: settings, `load_flows`, `parse_publish_list` and `select_published`, startup signatures, an empty `BoundValues` for now, `build_registry` over the Published_Flows; `Prepared` also holds `loaded_count`; no port, no session), `build_app(prepared, *, session_factory=None, clock=None, poll_interval=0.1)` returning `PublisherApp` (`asgi`, `service`, `server`, `lifespan`), the lifespan that enters the MCP session manager and drains the `CallService` on exit, and `limit_third_party_loggers()` (clamps `uvicorn`, `starlette`, `mcp`, `anyio`, `httpx2`, `httpcore2` and `asyncio` to INFO). The default factory builds `ConnectorSession`; no environment variable or option selects a factory. Update `greenscreen/publisher/__init__.py` to export `build_app`, `prepare`, `Settings` and `StartupError` without importing the web packages at module level
    - Create `tests/unit/test_publisher_slice.py`: run `tk5-system-info` through REST and through MCP against the Fake_Host with screens from `captures/` and assert the two Success_Bodies are equal (Requirement 19.6); this is the demo slice
    - _Requirements: 1.8, 3.1, 8.5, 14.7, 16.4, 19.1, 19.3, 19.6_

- [x] 4. Checkpoint - day-one vertical slice
  - Run `pytest tests/unit -k publisher` and the full `pytest -m "not integration"`; require that the slice test of task 3.3 passes and no pre-existing test fails.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Hardening: auth, crash guard, handlers, OpenAPI, bindings, wiring (about 3.5 h, day 2)
  - [x] 5.1 Implement `greenscreen/publisher/auth.py`
    - `extract_key(headers)` on the raw ASGI header list (the rules of Requirement 13.11, including the empty `X-API-Key` next to a valid Bearer header) and the pure ASGI `AuthMiddleware` (constant-time comparison with `hmac.compare_digest` on UTF-8 bytes, one fixed `unauthorized` body for every cause, sent before any body is read, `GET /health` open, the loopback `Host` rule when auth is disabled; not installed for stdio). Wiring is task 5.5
    - Create `tests/unit/test_publisher_auth.py`: each rule of Requirement 13.11, either carrier and both, repeated headers, the disabled-auth Host cases, and the constant-time unit test of Requirement 19.4 (a key object whose `__eq__` raises, plus a spy that `hmac.compare_digest` is the comparison used)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.7, 13.8, 13.10, 13.11, 13.12, 19.4_

  - [x] 5.2 Add the crash guard and replaced framework handlers to `rest.py`
    - Replace the `RequestValidationError`, `StarletteHTTPException` and `Exception` handlers with Error_Body handlers (`request_invalid` 400 for validation, unknown paths and wrong methods; `internal_error` 500), and add `CrashGuard`, the outermost pure ASGI layer that catches every `Exception` for `http` scopes, writes one fixed-text log record with no exception text, traceback or `exc_info`, sends the `internal_error` body when the response has not started, and passes cancellation through
    - Create `tests/unit/test_publisher_crash_guard.py`: a 422 case that does not echo the value, unknown path and wrong method, and the real-`uvicorn` case with a route that raises `RuntimeError` holding a marker (`log_config=None`, `access_log=False`, loopback port, Fake_Host only): the client gets the `internal_error` body and no log record holds the marker or a traceback
    - Rejection log records (Requirement 8.9, 8.10): add the public hook `CallService.log_rejection(flow, transport, code, started)` to `calls.py`, which writes one Call_Log_Record through the existing single writer (`_Record` and `_write_log`) with only `call_id`, `flow` (the Flow_Name when published, else `unknown`), `transport`, `outcome` and `duration_ms`; `rest.py` takes `started = time.monotonic()` at the top of the Flow route and calls the hook once for each rejection before `execute` (wrong media type, malformed JSON, duplicate key, non-finite number, non-object body, oversize by `Content-Length` or streamed, any other `request_invalid` or `request_too_large`). `precheck` and `execute` already log their own rejections (including MCP argument-validation failures), so MCP needs no hook. No record for an Auth_Guard rejection, `/health` or an unknown path
    - Create `tests/unit/test_publisher_rejection_log.py` (Requirement 19.11): one test per rejection kind (wrong media type, malformed JSON, duplicate key, `NaN`, array body, oversize with `Content-Length`, oversize chunked, unknown Flow, `input_invalid` over REST and MCP, `busy`, `shutting_down`) asserting exactly one `greenscreen.publisher` record at INFO with only the allowed fields, `flow` equal to `unknown` for an unpublished Flow, and no submitted value; plus a test that an Auth_Guard rejection (once task 5.1 is in), `/health` and an unknown path write none. Update the existing `test_publisher_rest.py` cases that would now see an extra record only if they assert on the log
    - Remove the dead fields `call_timeout` and `shutdown_grace` from `CallService` and its constructor (design, "Implementation notes"): `drain(grace)` keeps its argument, `run_stdio` gets the keyword `grace` instead of reading `service.shutdown_grace`, and the constructor callers are updated: `app.py` (`build_app`), `mcp_server.py` (`run_stdio`), and the tests `tests/unit/test_publisher_calls.py` (its `make` helper keeps `call_timeout` as a `build_registry` argument only), `tests/unit/test_publisher_mcp.py` and `tests/unit/test_publisher_rest.py`. `Settings.call_timeout` and `Settings.shutdown_grace` stay
    - Re-run the leak checks (validation echo, unhandled-exception traceback, access log) on the installed starlette 1.6.0 and uvicorn 0.38.0 and report. If behaviour differs from the versions in the design's "Documentation checked" section (starlette 1.10.0, uvicorn 0.54.0), propose minimum version pins to the user for approval, and do NOT edit `pyproject.toml`
    - _Requirements: 6.4, 6.9, 6.10, 8.9, 8.10, 8.11, 11.5, 11.6, 19.3, 19.11_

  - [x] 5.3 Add the OpenAPI builder and the docs page to `rest.py`
    - `build_openapi(registry, version)` (OpenAPI 3.1.0, one path item per Flow with the registry schemas embedded unchanged, one response per HTTP status of the table listing its codes, the two security schemes as alternatives, `security: []` on `/health`, no value, default or example), `GET /openapi.json`, and `GET /docs` only when `GS_ENABLE_DOCS` is true
    - Create `tests/unit/test_publisher_openapi.py`: the document of the three bundled Flows passes `fastapi.openapi.models.OpenAPI.model_validate`, embedded schemas equal the generator output, the security entries, no `/docs` route by default, no path for a Loaded_Flow left out of the registry, and the text `cancelled` appears nowhere in the document
    - _Requirements: 1.15, 8.8, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 6.5_

  - [x] 5.4 Implement `parse_bindings` in `greenscreen/publisher/config.py`
    - Signature `parse_bindings(environ, loaded, published)`: the flow part is matched against ALL Loaded_Flows, and a match that is not in `published` raises `<variable>: flow_not_published` (checked before the Input match). Inputs are then matched on the published Flow only
    - The Requirement 22 algorithm in the order of the design: scan `GS_BIND_` names in ascending order, split at the first `__`, apply the Flow-name rule for names containing `__` or ending in `_`, match normalised names, report `ambiguous_name` for collisions, parse by type, apply the Input_Validator against the full `InputSpec`, and reject a second binding of one Input. Every `StartupError` is raised with `from None` after the local value dict is cleared and never holds a value
    - Create `tests/unit/test_publisher_bindings.py`: one example per rule (format error, empty value is unset, unknown Flow, a Loaded_Flow that `GS_PUBLISH_FLOWS` leaves out giving `flow_not_published`, unknown Input, ambiguous Flow name, ambiguous Input name, `int` text rules, `max_length`, printable ASCII, `regex`, duplicate binding), asserting the message names the variable or family and the rule and holds no value
    - _Requirements: 19.10, 22.3, 22.4, 22.5, 22.7, 22.8, 22.9, 22.10, 22.11, 22.12, 15.1_

  - [x] 5.5 Wire auth, crash guard, OpenAPI and bindings into `app.py` and test the whole stack
    - `prepare` calls `parse_bindings(environ, loaded, published)` after the allow-list; `build_app` builds the registry with the bound names, then returns `CrashGuard(AuthMiddleware(FastAPI))` (no auth layer for stdio); the Bound_Values are merged in `execute`
    - Create `tests/unit/test_publisher_stack.py`: every route and `/mcp` answer `unauthorized` without a key and open with either carrier, `GET /health` stays open, an MCP call over HTTP in both eras with the key, a body over `GS_MAX_BODY_BYTES` on `/mcp` gets the SDK plain-text 413 with no part of the body and zero factory calls (Requirement 4.5), bound Inputs are absent from schemas, `tools/list` and the OpenAPI document, a Call with a bound Input supplied by the caller gives `input_invalid`, and the Bound_Value reaches `run_flow`; with `GS_PUBLISH_FLOWS=tk5-system-info` (the demo setting) `tk5-logon` and `tk5-logoff` are absent from the OpenAPI document, `tools/list` and the `/health` count (1), and a call to either gives the same `unknown_flow` body as an unknown name over REST and over MCP, while an unset variable publishes all three
    - _Requirements: 1.9, 1.14, 1.15, 11.3, 11.4, 14.4, 19.10, 4.5, 6.10, 12.4, 13.2, 13.3, 13.12, 14.5, 22.1, 22.2, 22.6, 19.3_

- [x] 6. CLI, stdio hygiene, shutdown, startup-failure tests (about 2.0 h, day 2)
  - [x] 6.1 Implement `greenscreen/publisher/cli.py` and `.env.example`
    - `main()`: check that `mcp`, `fastapi` and `uvicorn` import (message names the module and the extra `publish`, exit 2); `prepare(os.environ)` with `StartupError` printed to stderr only (exit 2, before any port or stdin use); remove `GS_API_KEY` and every Binding_Variable from `os.environ` afterwards; the stderr handler with the `StripTraceback` filter; `uvicorn.Server` subclass whose `handle_exit` calls `begin_shutdown()` (`log_config=None`, `access_log=False`, `timeout_graceful_shutdown=GS_SHUTDOWN_GRACE`); the stdio path that duplicates fds 0 and 1, points fd 1 and `sys.stdout` at stderr, passes the duplicated streams to `run_stdio(..., stdin=, stdout=, grace=Settings.shutdown_grace)`, which hands them to `stdio_server`, turns SIGTERM into `KeyboardInterrupt`; a final `drain(0)` on every exit path
    - Create `.env.example` with variable names and comments only and no values, including `GS_PUBLISH_FLOWS=` with a comment that the demo sets it to `tk5-system-info` (the name `tk5-system-info` is a Flow name, not a secret) and that unset publishes every Loaded_Flow
    - _Requirements: 8.5, 8.6, 8.7, 14.9, 14.11, 15.4, 15.5, 15.7, 15.8, 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x] 6.2 Write the startup, shutdown and stdio unit tests
    - Create `tests/unit/test_publisher_cli.py`: one test per startup failure of Requirements 1 (including `GS_PUBLISH_FLOWS` `empty_item`, `duplicate_name` and `unknown_flow`, and `flow_not_published` for a binding), 13, 15, 16 and 22 asserting exit code 2, the message, and that stdout and stderr hold no environment variable value (and no Leak_Form of a Bound_Value for Requirement 22); a failing signature load exits 2 before a port is bound; the missing-extra message (module import blocked in a subprocess); `GS_API_KEY` and `GS_BIND_*` removed from `os.environ` after `prepare`; the shutdown test of Requirement 19.7 (every opened session was closed after `drain`); the `StripTraceback` filter output; the stdio test in a subprocess against the Fake_Host seam through a test-only entry point that cannot select a factory from the environment, asserting every stdout line parses as JSON-RPC also when a handler prints and writes to descriptor 1 (Requirement 14.11)
    - _Requirements: 1.11, 1.12, 1.13, 8.7, 13.5, 13.6, 14.9, 14.11, 15.4, 15.5, 15.8, 16.1, 16.2, 16.3, 16.4, 16.5, 19.5, 19.7, 19.10, 22.7_

- [x] 7. Property tests, group A (about 3.0 h, days 2 to 3)
  - [x] 7.1 Add shared test helpers and strategies
    - Extend `tests/publisher_support.py` with `LogCapture` (root logger at level 1 plus a recording handler on every non-propagating logger in `logging.root.manager.loggerDict`, recording the formatted message, `args`, `exc_text`, `stack_info` and formatted `exc_info`), the frame scanner of the design (walks the traceback and its chain, treats `BoundValues` and `PublishedFlow` as opaque, flags a probe in any local or container, and identity with a recorded mapping), and a clients helper (ASGI `httpx2` client inside the lifespan, in-memory MCP `Client` for `legacy` and `auto`)
    - Create `tests/property/_publisher_strategies.py`: `probes()` (at least 4 printable ASCII characters, alphabet disjoint from fixed text; `int` probes of at least 4 digits), `leak_forms(v)` (plain, JSON-escaped, URL-quoted and quote-plus, hex lower and upper with and without spaces, base64 and URL-safe base64 with and without padding), `bound_sets`, `fake_host_plans`, `bad_requests`, `key_headers`, `binding_envs`
    - Create `tests/unit/test_publisher_helpers.py` (task 1.5 owns the Fake_Host test file): the leak forms of a known value are spelled out literally, `LogCapture` sees records from a non-propagating logger, the frame scanner flags a planted probe and ignores a `BoundValues`
    - _Requirements: 7.1, 7.2, 7.6, 20.1, 20.10, 20.16_

  - [x] 7.2 Write property test for schema validity (Property 1)
    - **Property 1: Schemas are valid, deterministic, free of values and embedded unchanged**
    - `tests/property/test_publisher_schema.py`, drawing `flows()` from `tests/property/_flow_strategies.py` and bound subsets; assert draft 2020-12 validity, determinism, `writeOnly` exactly on secrets, no forbidden keys, and equality with the OpenAPI document and `tools/list` schemas
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 2.10, 2.11, 2.12, 12.2, 12.5, 12.7, 22.1**

  - [x] 7.3 Write property test for schema and validator agreement (Property 2)
    - **Property 2: The schema never rejects what the validator accepts**
    - `tests/property/test_publisher_schema_agree.py`, generated JSON mappings over `flows()` and bound subsets (fractional floats only; integral floats are covered by a unit test in `tests/unit/test_publisher_registry.py`); one-directional agreement as in Requirement 20.3, and the all-bound Flow accepting only `{}`
    - **Validates: Requirements 2.8, 20.3, 22.1, 22.2**

  - [x] 7.4 Write property test for front-end parity (Property 3)
    - **Property 3: Both front ends return the same body, and a success body fits its schema**
    - `tests/property/test_publisher_parity.py`, over `MINI` and `chain_scripts()` outcomes through REST and MCP; same outputs or same code, `step_index`, `kind`, `expected`, `summary` and Audit_Summary; every Success_Body validates against its Success_Schema
    - **Validates: Requirements 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 11.1, 11.7, 14.2, 14.7**

  - [x] 7.5 Write property test for error mapping totality (Property 4)
    - **Property 4: Error mapping is total, single-valued and fixed-text**
    - `tests/property/test_publisher_errors.py`, over all Reason_Codes, Publisher_Codes and injected exception classes at open, at each Session call and at close; one code, one status, `isError` result with the same body, fixed message except `input_invalid`, allowed members only, `cancelled` in no body, status table or message table, no `mcp` ERROR record, a `BaseException` re-raised unchanged after close and Slot release
    - Follow-up (the test file already exists; done as an edit inside `tests/property/test_publisher_errors.py`): the scenario list is extended with a `BaseException` that is not an `Exception` raised at the Session_Factory, at `open` and at `close` (as well as at a Session call). Each is re-raised unchanged after the session was closed (when one exists) and the Slot released, builds no Error_Body, and a `BaseException` from `close` leaves `close_failed` absent. This follow-up needs the fix of task 7.0 for the `close` case and of task 7.0b for the `open` case
    - Follow-up (depends on task 7.0b): one `@example` per base injection point (factory, open, close, read_screen, string, enter) on both front ends, and one `@example` per Publisher_Code, so every run covers them
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 8.8, 14.3, 14.6**

  - [x] 7.6 Write property test for the limiter (Property 11)
    - **Property 11: The Limiter never lets more than the limit through**
    - `tests/property/test_publisher_limiter.py`, limits 1 to 64, concurrent Calls over REST and MCP with generated outcomes; in-flight never above the limit, Slots and live sessions return to zero, rejected Calls are `busy` and opened no session
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.6**

  - [x] 7.0 Fix the worker done event (defect found by Property 12)
    - Numbering: inserted as sub-task `7.0` of top-level task 7 so that no existing id changes. It is done BEFORE 7.7 (7.7 depends on it, see the dependency graph).
    - Defect: in `calls._worker`, a `BaseException` (not an `Exception`) raised by `session.close()` in the `finally` block skips `run.loop.call_soon_threadsafe(run.done.set)`, so `execute` waits until the Call_Deadline and returns `call_timeout` for a Call that ended
    - Change in `greenscreen/publisher/calls.py` `_worker` only: `done.set` runs on every exit path (its own inner `finally`, as in the design "Worker" sketch); `except Exception` around `close()` still sets `close_failed`; a new `except BaseException` stores it in the result slot (`kind` `base`, `base` the exception, unless `run_flow` already stored one) and does NOT set `close_failed`; `execute` then re-raises it after teardown and Slot release exactly as for one from `run_flow` (existing `_finish` path)
    - Add to `tests/unit/test_publisher_calls.py` a unit test for a `BaseException` raised by `close` (a Fake_Host `close` failure with a `BaseException` subclass): the same exception object is re-raised by `execute`, after `close` was called and after the Slot was released (`Limiter.in_flight` is 0), the Call_Log_Record has no `close_failed` key and `outcome` `internal_error`, the worker's `done` event was set, and the call returns promptly (a `FakeClock` or a short real deadline far above the test's own timeout proves there is no wait for the deadline). Keep the existing `Exception`-from-`close` test (`close_failed` true) unchanged
    - Re-run `tests/unit -k publisher` and the Property 12 test file; no other production file changes
    - _Requirements: 3.3, 3.5, 6.8, 9.4_

  - [x] 7.0b Re-raise a BaseException from session.open() (defect found by Property 4)
    - Defect: in `calls._worker`, a `BaseException` (not an `Exception`) raised by `session.open()` returned `internal_error` and escaped the worker thread unstored
    - Change in `greenscreen/publisher/calls.py`: store it in the result slot (`kind` `base`) so `execute` re-raises it after `close` and Slot release, like the `run_flow` and `close` cases (Requirement 6.8). `close_failed` stays absent
    - Standing approval (user, 2026-11-17): any other path in `calls._worker` or `CallService.execute` that lets a `BaseException` escape the worker thread unstored, or returns an error body where Requirement 6.8 requires propagation, is fixed the same way with a unit test. List each such fix in the report
    - Unit test in `tests/unit/test_publisher_calls.py`: a Fake_Host `open` raising a `BaseException` subclass; the same object is re-raised by `execute` after `close` and after Slot release (`Limiter.in_flight` is 0), the record has `outcome` `internal_error`, and the call returns promptly. Also cover the factory case if it is not already covered
    - Time: adds 0.25 h to task 7 (3.5 to 3.75 h; total about 24.75 h)
    - _Requirements: 3.3, 3.4, 6.8, 9.4_

  - [x] 7.7 Write property test for the session lifecycle (Property 12)
    - Depends on task 7.0 (the worker `done` event fix): the plan injects a `BaseException` at `close`
    - Also depends on task 7.0b: the plan injects a `BaseException` at `open` and at the factory
    - **Property 12: Session lifecycle**
    - `tests/property/test_publisher_lifecycle.py`, Fake_Host plans including failures at every point, blocked reads with deadline expiry, cancellation and a `BaseException`; each created session closed exactly once before the Slot is released, no reuse, zero sessions for a Call rejected before the Slot, and no key after `call_timeout` was returned
    - Follow-up (depends on task 7.0b): also assert the re-raise for a `BaseException` at open and at the factory
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.3, 9.4, 10.3, 10.4**

  - [x] 7.8 Write property test for authentication (Property 13)
    - **Property 13: Authentication**
    - `tests/property/test_publisher_auth.py`, over wrong keys in either carrier, differing pairs, malformed `Authorization`, empty and repeated `X-API-Key`, valid keys, and the disabled-auth Host header cases, against `extract_key` as the model; zero sessions, no body read, no value in the response, over Flow routes, `/openapi.json`, `/docs` and `/mcp`
    - Follow-up, one-off mutation check (not a permanent test): record the hash of `greenscreen/publisher/auth.py`, temporarily make the key comparison always succeed, run `tests/property/test_publisher_auth.py` and confirm that Property 13 FAILS, restore the file, verify with `git diff` or the hash that `auth.py` is byte-identical to its state before, and report the result (the failing example and the verification)
    - **Validates: Requirements 13.2, 13.3, 13.7, 13.9, 13.11, 13.12**

- [x] 8. Property tests, group B (about 3.5 h, day 3)
  - [x] 8.1 Write property test for no value in responses (Property 5)
    - **Property 5: No Input value or Bound_Value in any response**
    - `tests/property/test_publisher_no_leak_responses.py`; probes as Inputs and as Bound_Values (bound Input secret and not secret), all Fake_Host outcomes, bodies, headers, MCP results, `/openapi.json`, `tools/list` and `/health`; the `sentinel_password_screen` case with the sentinel supplied as the password
    - One-off mutation check (not a permanent test): record the hash of the production file you change, temporarily put one supplied Input value into a response body (for example into the `message` of an error or the Success_Body), run this test and confirm that Property 5 FAILS, restore the file, verify with `git diff` or the hash that it is byte-identical to its state before, and report the result
    - **Validates: Requirements 7.1, 7.7, 7.8, 7.9, 22.10**

  - [x] 8.2 Write property test for no value in logs (Property 6)
    - **Property 6: No Input value or Bound_Value in any log record**
    - `tests/property/test_publisher_no_leak_logs.py`; same Calls plus startup and shutdown with Bound_Values set, `LogCapture` at DEBUG on all loggers, message, `args`, `exc_text`, `stack_info` and formatted `exc_info`; every `greenscreen.publisher` record has only the permitted fields; the API key never appears
    - One-off mutation check (not a permanent test): record the hash of the production file you change, temporarily log one supplied Input value in production code (for example in the Call_Log_Record or a debug record), run this test and confirm that Property 6 FAILS, restore the file, verify with `git diff` or the hash that it is byte-identical to its state before, and report the result
    - **Validates: Requirements 7.2, 7.7, 8.2, 8.3, 8.4, 13.8, 22.10**

  - [x] 8.3 Write property test for no Host_Data (Property 7)
    - **Property 7: No Host_Data in responses or logs**
    - `tests/property/test_publisher_no_hostdata.py`; injected `S3270Error` with marker `data_lines`, `ConnectorTimeoutError`, `ParseError` with marker `raw`, `ConfigurationError`, `SessionClosedError` and an arbitrary `Exception` with a marker message; no marker, `Traceback`, frame path, `Screen` or `Field` repr or hidden cell text in a response or a record
    - **Validates: Requirements 6.7, 7.3, 7.7**

  - [x] 8.4 Write property test for audit and summary (Property 8)
    - **Property 8: Audit entries and summaries are free of secrets and mask hidden cells**
    - `tests/property/test_publisher_audit_summary.py`; Calls ending in each Reason_Code and the residual-password screen; no Leak_Form in any Audit_Summary or Redacted_Summary and every hidden cell shown as `*`
    - **Validates: Requirements 7.4, 22.10**

  - [x] 8.5 Write property test for validation errors (Property 9)
    - **Property 9: Validation errors never echo a submitted value**
    - `tests/property/test_publisher_validation_echo.py`; `bad_requests()` over REST and MCP (wrong type, too long, regex violation, undeclared and bound names from an alphabet disjoint from the probes, missing Input, malformed JSON, duplicate key at any depth, `NaN`, non-object, oversize, wrong media type); no Leak_Form, no `input` member, zero factory calls
    - The shared `bad_requests()` strategy targets `MINI`, which has no `regex` Input, so it cannot generate a regex-violation request. This test builds, locally in its own test file, a Flow with a regex-constrained `str` Input (and uses it for the regex-violation cases), and does NOT edit `tests/property/_publisher_strategies.py` or `tests/publisher_support.py`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.7, 7.5, 11.2, 22.2**

  - [x] 8.6 Write property test for exception frames (Property 10)
    - **Property 10: No traceback frame of the publisher holds a value**
    - `tests/property/test_publisher_frames.py`; probes and bound sets with a cancellation, a `BaseException` from the Session, an exception injected into the test seam and a failing `parse_bindings`; the frame scanner and `traceback.format_exception` with chain
    - **Validates: Requirements 3.6, 3.9, 6.8, 7.6, 22.10**

  - [x] 8.7 Write property test for binding variables (Property 14)
    - **Property 14: Binding variables either start cleanly or stop the startup**
    - `tests/property/test_publisher_bindings.py`; `binding_envs()` over generated Flows, generated `GS_PUBLISH_FLOWS` values (valid, empty items, duplicates, unknown names, Flows left unpublished) and variables compared with a small independent model of Requirements 1.9 to 1.15 and 22 (including `flow_not_published`); an accepted run's registry holds exactly the selected Flows in loading order; accepted runs have no bound name in any schema, `tools/list` or OpenAPI document; stopped runs name the variable, Flow or family and the rule; no Leak_Form in startup stdout and stderr, in DEBUG records of startup and shutdown, or in `/health`; no session in either case
    - **Validates: Requirements 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 22.1, 22.3, 22.4, 22.5, 22.6, 22.7, 22.8, 22.9, 22.10, 22.12, 7.8**

- [x] 9. Checkpoint - properties complete
  - Run `pytest tests/property --durations=10` and require that all 14 publisher property tests pass, that the publisher property modules take under 120 seconds together and the whole `tests/property` suite under 240 seconds with no network connection and no subprocess (limits raised from 25 and 115 seconds to 60 and 150 seconds, and then to 120 and 240 seconds, on 2026-11-17 by the user's decisions; the clean serial run of the 14 modules took 74.7 s; this replaces the whole-suite limit of flow-runtime Requirement 19.9); never trim tests and never lower `max_examples` below 100 to save time. If over budget, report it to the user instead of trimming. Record the timings in the task notes.
  - Run the full `pytest -m "not integration"` and require no failure and no edit to a pre-existing test file.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 20.1, 20.17, 20.18_

- [x] 10. Perf test, live integration test, static rule tests (about 2.0 h, day 3)
  - [x] 10.1 Write the `recognize` perf test
    - `tests/unit/test_publisher_perf.py` marked `@pytest.mark.perf` (already registered in `pyproject.toml`; follow the sibling convention that it is skipped unless `GS_RUN_PERF=1`): recognize each of `tk5-logon`, `tso-password-prompt`, `ispf-primary-menu` and `tso-ready` 200 times with the bundled Signatures and fail when the median of one call on any is above 5 ms
    - _Requirements: 17.1, 17.4_

  - [x] 10.2 Write the live integration test
    - `tests/integration/test_publisher_live.py` marked `@pytest.mark.integration`: build the app with the default Session_Factory and the Flow `tk5-system-info`, call `POST /flows/tk5-system-info` through the ASGI client; skip with a message naming each missing variable when `TK5_USERNAME` or `TK5_PASSWORD` is unset or empty, before any connection, and skip when `host_reachable` reports the host down; the test (not the Publisher) reads the variables and passes them as Input values or as Binding_Variables for the app under test; `GS_MAX_CONCURRENCY` stays 1
    - Assert `USERID` equals `TK5_USERNAME` ignoring case and `SYSTEMID` and `RELEASE` are non-blank; assert the password (and, at 4 or more characters, its hex, base64 and URL-encoded forms from `leak_forms`) is in no response and in no DEBUG record of any logger; assert no `s3270` or `ws3270` process started by the test is still running. No credential in the file, no capture of a typed-password screen, no account recovery
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 7.10_

  - [x] 10.3 Write the static rule tests
    - `tests/unit/test_publisher_static.py`, file reads only: no `TK5_USERNAME`, `TK5_PASSWORD` or other credential variable read in `greenscreen/publisher`; `os.environ` read only in `cli.py` and `config.py` (Requirement 22.11); no `traceback.print`, `logger.exception` or `exc_info=` in the package; no call of `print` in `greenscreen/publisher` unless it passes a keyword argument `file` whose value is the attribute `sys.stderr`, checked by walking each module with `ast` (decision of 2026-11-17). Self-tests on source snippets: a bare `print(x)` fails, `print(x, file=sys.stdout)` fails, `print(x, file=sys.stderr)` passes. The startup error messages in `cli.py` are printed this way; no cache of `ScreenView` or `recognize` results and no change to `greenscreen/recognizer` for caching; `.gitignore` does not hide `.kiro`; no tracked file holds a non-empty `GS_API_KEY` or `GS_BIND_` value (`.env.example` has names only, and `GS_PUBLISH_FLOWS` there is empty or holds only the Flow name `tk5-system-info`); the string `cancelled` occurs in `greenscreen/publisher` only in `calls.py` (the log-only outcome) and in no message, status or schema table
    - _Requirements: 7.7, 7.10, 8.4, 8.6, 15.4, 15.6, 15.7, 17.1, 18.6, 22.11_

- [x] 11. Final checkpoint (about 0.25 h, day 3)
  - Run `pytest -m "not integration"` and `pytest tests/property --durations=10`. Budgets: the publisher property modules under 120 seconds together and `tests/property` under 240 seconds (Requirement 20.17). Report the timings. If a budget is missed, report it to the user and never trim a test or lower `max_examples` below 100
  - Run the integration test `tests/integration/test_publisher_live.py` twice: once with `TK5_USERNAME` and `TK5_PASSWORD` set (against the live host, when reachable) and once with them unset or empty. Without them it must skip cleanly with a message naming each missing variable, and make no connection
  - Confirm that no `s3270` or `ws3270` process remains running after the runs
  - Confirm that `git diff` is empty for `greenscreen/connector`, `greenscreen/recognizer` and `greenscreen/flow`, and that `pyproject.toml` is unchanged since commit 19a5091 (`git diff 19a5091 -- pyproject.toml` is empty)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 15.6, 18.1, 18.3, 20.17, 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_

## Notes

- Every task is required, and no sub-task carries the optional `*` mark, including all 14 property tests (Requirement 20.18). This replaces the generic workflow default of optional test sub-tasks, as the user requested. The perf test (10.1) is required but skipped unless `GS_RUN_PERF=1`, as in the sibling plans.
- Each property task names its design property number, its file under `tests/property/` and the requirement clauses it validates. The Property 2 plan restricts floats to fractional ones; integral floats are a unit test of the validator.
- No tests need the live host, apart from task 10.2, which skips unless the host is reachable and `TK5_*` is set. The two subprocess or socket tests of tasks 5.2 and 6.2 use the Fake_Host only.
- `tasks.meta.json` is written by the property-test status tool when tests run, as in the sibling specs, so it is not authored here.
- Requirement 17.2, 17.3 and 17.5 (the recorded decision and measurements) and Requirement 18.5 (the licence list) are documentation already in the design; no task is needed.
- Account-lock recovery is not planned (Requirement 23.7). Task 2.2 marks the affected calls with `session_clean` only.
- Task 11, the final checkpoint after task 10, was added on 2026-11-17 and adds 0.25 h (24.75 to 25.0 h). The Task Dependency Graph gains wave 17 for it.
- Hours (earlier note): 24.0 total, up from 23.5. The allow-list and the `cancelled` outcome fit inside the existing tasks as sub-bullets. After the day-one checkpoint, task 5.2 gained sub-bullets (rejection log records and the hook `log_rejection`, removal of the dead `CallService` fields, the starlette and uvicorn re-check) and grew by 0.5 hour (3.5 to 4.0); no top-level task was added and the dependency graph is unchanged.
- Hour estimates are tight for the amount of test code; task 7 and task 8 carry most of the risk. If day three runs short, the first lever in task 9 is to draw one front end per example in Properties 3, 5 and 6.

### Points for review

- Nothing is marked optional. If the user wants to cut scope, the genuine candidates are `.env.example` (task 6.1), the `/docs` page of task 5.3 (off by default), and the perf test (task 10.1, opt-in). All three are required by the requirements, so they stay required.
- Day one is 9.0 hours, one hour over an even split, so that the slice includes the real worker thread, timeout and teardown.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.5"] },
    { "id": 2, "tasks": ["1.4"] },
    { "id": 3, "tasks": ["2.1"] },
    { "id": 4, "tasks": ["2.2"] },
    { "id": 5, "tasks": ["2.3", "2.4"] },
    { "id": 6, "tasks": ["3.1", "3.2"] },
    { "id": 7, "tasks": ["3.3"] },
    { "id": 8, "tasks": ["5.1", "5.2", "5.4"] },
    { "id": 9, "tasks": ["5.3"] },
    { "id": 10, "tasks": ["5.5"] },
    { "id": 11, "tasks": ["6.1", "7.1"] },
    { "id": 12, "tasks": ["6.2", "7.0", "7.2", "7.3", "7.4", "7.6", "7.8"] },
    { "id": 13, "tasks": ["7.0b"] },
    { "id": 14, "tasks": ["7.5", "7.7"] },
    { "id": 15, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7"] },
    { "id": 16, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 17, "tasks": ["11"] }
  ]
}
```
