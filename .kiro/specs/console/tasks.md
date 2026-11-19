# Implementation Plan: console

## Overview

Build the console described in `requirements.md` and `design.md` in this folder: six static files served by the Publisher in HTTP mode, a `GS_ENABLE_CONSOLE` switch, one exact-pair exemption in `AuthMiddleware`, fixed security headers on the six routes, and a plain HTML, CSS and ES-module page. The work has two halves with a checkpoint between them. Tasks 1 and 2 finish the server side with placeholder assets and have it green (Requirement 17.2). Task 3 is the checkpoint. Task 4 writes the page and replaces the placeholders. Task 5 is the final check and report. Tasks 1 to 5 are done: the reviewer ran checklist steps 1 to 12 in headless Chrome 157 at 1280x720 against the live host (pass, no CSP violation, no script error) and the Linux suite gave 2416 passed, 0 failed, 15 Node tests skipped (no Node on that machine). Task 6 is a small polish after that run (no scroll on focus, denser audit lines, `1 second`, a plain-name `summary` scan); it touches page files and their tests only. Task 7 adds a static ASCII seance table with a crystal ball to the screen before any Flow has run (Requirement 11, criteria 10 to 18; design "Seance art (task 7)"); it touches `index.html`, `console.css` and one new test file only. Task 8 answers the owner's feedback that the page "feels more like an emulator": Run goes through the existing `/mcp` endpoint by default and the page shows the JSON-RPC messages as one-line entries that expand to the full JSON, a three-stage strip as the first element of the result and the MCP client config (Requirement 18; design "Recorded /mcp behaviour" and "MCP-visible Run (task 8)"). It changes the four page files `index.html`, `console.css`, `console.js` and `snippets.js` and adds tests; it touches no server file, route, header or setting, and exactly one existing test line (the allowed request paths in `tests/unit/test_console_assets.py`). Section "Reviewer-only items" lists what the executor does not run.

The production files touched are `greenscreen/publisher/config.py`, `auth.py`, `rest.py`, `app.py`, `cli.py` (startup report only), the new package `greenscreen/publisher/console/`, `pyproject.toml` (one `package-data` key) and `.env.example` (one commented name). Every path is repo-relative. The executor works on Windows with Python 3.11.9. No task needs the live host or a browser. Every task is verified on Windows only; what Windows cannot show is listed in Notes.

### Estimates and order

Two-day budget, about 19 hours of work for tasks 1 to 5, plus about 2.5 hours for the polish of task 6, 2 hours for task 7 and about 10 hours for task 8. If task 8 runs short, cut in this order and report each cut: the example tests of `prettyJson` edge cases and of the SSE multi-line `data:` case (keep Property 4), the open state of the `tools/list` entry (keep the entries); never the allow-list projection, the masking or the key rules.

| # | Top-level task | Hours |
|---|---|---|
| 1 | Library documentation checks (record only) | 0.75 |
| 2 | Server side: switch, loader, routes, headers, auth exemption, startup record, packaging, tests, Properties 1 and 2 | 8.15 |
| 3 | Checkpoint: server side green | 0.5 |
| 4 | Page: snippets, codes, CSS, HTML, JS, Node test with Property 3, static scans, contrast test | 9.0 |
| 5 | Final checkpoint and report | 0.75 |
| 6 | Polish after the reviewer's browser run | 2.5 |
| 7 | Seance art: markup, CSS, tests, final run | 2.0 |
| 8 | MCP-visible Run: checks, snippets and tests, markup and CSS, page script, static tests, final run | 10.0 |
| | **Total** | **33.65** |

If time runs short, cut in this order and report each cut: the contrast test details of 4.9 (keep the token check), the optional `Retry` polish in 4.5, then the example-based extras of 4.7 (keep Property 3). Nothing in tasks 1 to 3 is cut.

### Rules for every task

- DO NOT COMMIT and do not stage anything. Leave every change in the working tree. The reviewer commits.
- No secret is printed or written: no `TK5_PASSWORD`, `TK5_USERNAME`, host address, `GS_API_KEY` value or Bound_Value in code, tests, logs, assertion messages or notes. Test keys are generated per test and never written to a file.
- No new dependency. `dependencies`, the extras and `[build-system]` in `pyproject.toml` stay unchanged. No framework, no build step, no `npm`, no CDN, no external font, script or image.
- Stop and report a production defect found outside the files named in the Overview. Do not fix it silently.
- Existing tests keep passing, unmodified. New tests go in new files, or as new functions beside the existing ones they parallel. No existing test body, fixture or assertion changes. If an existing test fails, stop and report the test and the cause (Requirement 13.6).
- No task needs the live host or a browser. Tests use the Fake_Host (`tests/publisher_support.py`), static files, `httpx2` over `ASGITransport` or a raw ASGI scope. Tests that need `node` skip with the fixed reason when it is absent.
- Before any task that writes code using a library API, re-check that API's row in the design's "Library documentation checks" table and the dated lines task 1.1 appended. If the installed version differs from the recorded one, or the row is missing, check the page again and append a dated line (page, version, date) to the same section of `design.md`. Tasks that do this say so.
- `.kiro/steering` is never edited. `.kiro` is never git-ignored.
- Every task is required. Nothing is marked optional with `*`. Property tests are sub-tasks of the code they test.
- Placeholder assets written in task 2.2 are flagged by the comment or text `PLACEHOLDER` and are replaced in task 4. No test written in task 2 pins their content beyond "equals the packaged file".
- Python version: the executor runs everything on 3.11.9. The Node version found on PATH is recorded in the report (the design ran v24.19.0 only).

### Decisions carried from the design

- Routes are registered with `add_api_route(..., methods=["GET"], include_in_schema=False, response_model=None)`, not with a Starlette `Route`, so no `HEAD` is added (design D2).
- `_NoStore` is not changed; the console handler sets `Cache-Control: no-store, no-transform` itself.
- Property 3 is a Hypothesis test with one `node` process per example, and example tests cover the literal shapes (design D9).
- The page shows a third snippet block, the `claude mcp add` command; `buildMcpConfig` and `buildClaudeCodeCommand` take only the origin (design D5, requirements 9.1 and 9.5).
- `codes.json` entries may carry `show_message` (`input_invalid` only) (design D7, requirement 8.1).

## Tasks

- [x] 1. Library documentation checks (about 0.75 h; record only; no live host; Windows only)
  - [x] 1.1 Record page, version and date for every API the work uses
    - Edit `.kiro/specs/console/design.md` only, in the section "Library documentation checks": reuse the existing table and append dated lines (format `Checked <date>: <page URL>, <version>, <conclusion>`).
    - Fill the gaps the table marks as not verified: `fetch` (request with method, headers, body; response `ok`, `status`, `headers.get`, `text()`) on MDN; `FastAPI.add_api_route` and returning a `Response` directly; Starlette `Response` with `headers` and `media_type`; Starlette/FastAPI `HEAD` behaviour for `add_api_route` (re-run the check of design D2 in a throwaway script outside the repo and delete it); `importlib.resources.files(...).joinpath(...).read_bytes()` on Python 3.11; the Node invocation `node --input-type=module -e <script>` with a `data:` URL import (run it once with `node --version` and a one-line module, print nothing secret); `shlex.split` POSIX mode; `history.replaceState`, `Clipboard.writeText`, `prefers-reduced-motion` re-read for any version note; Hypothesis `@given` with `subprocess` per example (no library change, note only).
    - Record the installed versions printed by `python -m pip list` for `fastapi`, `starlette`, `uvicorn`, `httpx2` (or the HTTP test client the repo uses), `hypothesis`, `pytest`, and `node --version`. If a version differs from the design's table, append a line saying so.
    - Make NO change to any file other than `design.md`. Verify with `git diff --name-only` listing only `.kiro/specs/console/design.md` and the spec files already pending.
    - Run `validate_spec_format` on `design.md` and report the result.
    - _Requirements: Conventions (library documentation rule), 17.4_

- [x] 2. Server side (about 8.15 h; no live host; Windows only)
  - [x] 2.1 Add the `GS_ENABLE_CONSOLE` setting and `.env.example` line
    - Re-check the Library documentation checks rows used here: none beyond the standard library. Read `greenscreen/publisher/config.py` first.
    - `Settings` gains `enable_console: bool = False` as its last field. `load_settings` sets it with the existing `_bool` call, next to `enable_docs`. The error text for a bad value is the one `_bool` already produces for the variable name: it names `GS_ENABLE_CONSOLE` and the rule `not_a_boolean (true or false)` and never the value. The custom `__repr__` is untouched.
    - `.env.example`: after the `GS_ENABLE_DOCS=` line add the comment `# true serves the web console at / (HTTP transport only, default false).` and the line `GS_ENABLE_CONSOLE=`. No other change.
    - _Requirements: 1.1, 1.2, 1.3, 1.8_

  - [x] 2.2 Create the `greenscreen/publisher/console/` package with the loader and placeholder assets
    - Read the "Components and Interfaces" section 2 of `design.md` first. Check the `importlib.resources` row (Python 3.11 behaviour, anchor passed positionally).
    - `__init__.py`: `ROUTES` (the six `(path, file, media type)` tuples), `PAIRS` (the six `("GET", path)` pairs), `HEADERS` (exactly the four headers of Requirement 2.5, `Cache-Control: no-store, no-transform`), `Asset` (frozen dataclass: `path`, `file`, `media_type`, `body`), `ConsoleAssetError(file)` (message is the file name only) and `load_assets()`. `load_assets` reads each file with `importlib.resources.files("greenscreen.publisher.console").joinpath(file).read_bytes()` and turns `FileNotFoundError`, `ModuleNotFoundError` and `OSError` into `ConsoleAssetError`. File names come only from `ROUTES`. Standard library only: the module imports none of `mcp`, `fastapi`, `starlette`, `uvicorn`.
    - Placeholder assets, each marked `PLACEHOLDER` in its text or first comment, small but valid for its media type: `index.html` (title, `lang`, charset and viewport meta, referrer meta, icon link, stylesheet link, one `<script type="module" src="/console/console.js">`, no inline code), `console.css` (a `:root` block with the Theme_Tokens of the design's palette and nothing else), `console.js` (an empty module comment), `snippets.js` (a module comment only), `codes.json` (`{}`), `favicon.svg` (a minimal SVG with the `xmlns` attribute).
    - Do not touch `pyproject.toml` here (task 2.4).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 12.1, 12.4, 12.5_

  - [x] 2.3 Add the exact-pair exemption to `greenscreen/publisher/auth.py`
    - Read the file first. `AuthMiddleware.__init__` gains the keyword `exempt: frozenset[tuple[str, str]] = frozenset()`. `_allowed` checks `(scope.get("method"), scope.get("path"))` against it with exact equality, next to the existing `GET /health` test, after the `disabled` branch (which is unchanged and returns first). No header is read on the exempt path. With the empty default, behaviour is identical to today.
    - Run the existing `tests/unit/test_publisher_auth.py` and `tests/unit/test_publisher_stack.py`. They pass with no change.
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

  - [x] 2.4 Add the `package-data` key to `pyproject.toml`
    - Add exactly `"greenscreen.publisher.console" = ["*.html", "*.css", "*.js", "*.json", "*.svg"]` to the `[tool.setuptools.package-data]` table. Change nothing else: `dependencies`, extras and `[build-system]` stay as they are.
    - Verify: `git diff -- pyproject.toml` shows one added line. Run `tests/unit/test_flow_packaging.py`, `tests/unit/test_recognizer_packaging.py`, `tests/unit/test_publisher_packaging.py` and `tests/unit/test_fixtures.py`; they pass unchanged.
    - _Requirements: 12.2_

  - [x] 2.5 Register the six routes and headers in `greenscreen/publisher/rest.py`
    - Check the Library documentation rows for `add_api_route`, FastAPI "returning a Response directly" and Starlette `Response`. Read `rest.py` first.
    - `build_rest(..., console: Sequence[Asset] = ())` registers, for each asset, `app.add_api_route(asset.path, _serve(asset), methods=["GET"], include_in_schema=False, response_model=None)`. `_serve` returns an async handler with no parameters that returns `Response(asset.body, media_type=asset.media_type, headers=HEADERS)`. No wildcard, no path parameter, no mount, no static-files handler, no logging, no `Call_Log_Record`. `_NoStore` and every other route stay unchanged.
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 4.5, 10.2, 15.1, 15.2_

  - [x] 2.6 Wire the console into `greenscreen/publisher/app.py`
    - Read the file first. `Prepared` gains `console: tuple[Asset, ...] = ()` as its last field. At the end of `prepare` (design D3), when `settings.enable_console and settings.transport == "http"`, call `load_assets()` and convert `ConsoleAssetError` into `StartupError(f"console: missing_asset ({file})")` (no machine path). `build_app` passes `console=prepared.console` to `build_rest` and `exempt=PAIRS` to `AuthMiddleware` only when `prepared.console` is non-empty. Stdio mode builds no HTTP stack and ignores the setting.
    - Run `tests/unit/test_publisher_*.py`. They pass with no change.
    - _Requirements: 1.4, 1.5, 2.3, 3.2, 13.2, 13.3_

  - [x] 2.7 Move the startup report into `_report_startup` in `greenscreen/publisher/cli.py`
    - Read the file and search `tests/` for the log text `publishing`. Add `_report_startup(prepared)` that logs the existing record `publishing %d of %d flows over %s` with the same arguments on the same logger, and then, only when `prepared.console` is non-empty, logs the fixed INFO text `console enabled` with no field. `main` calls the helper where it logs the first record today. No other change in the file.
    - Run `tests/unit/test_publisher_cli.py`: it passes unchanged.
    - _Requirements: 1.6, 1.7, 10.1_

  - [x] 2.8 Add the shared test helper `tests/console_support.py`
    - Provide: the path of the packaged assets; `build_console_app(env, console=True)` (cached `prepare`, `build_app` over `FakeHost` with the repository's `lru_cache` pattern, a generated API key per call); `call_scope(asgi, method, path, headers)` (raw ASGI scope driver, so a path reaches the middleware as generated); the six expected pairs. Reuse helpers from `tests/publisher_support.py` and `tests/property/_publisher_strategies.py`; edit neither.
    - No Node code here (task 4.7 has its own module).
    - _Requirements: 3.7, 6.7, 13.7_

  - [x] 2.9 Add the switch, startup and off-switch tests
    - `tests/unit/test_console_config.py`: `GS_ENABLE_CONSOLE` unset, empty, `true`, `false` and an invalid value (message names the variable and the rule, never the value); `Settings` repr unchanged; stdio ignores the setting; `.env.example` gains exactly one comment line and one name line; with the console off, each of the six paths answers `unauthorized` without a key and `request_invalid` with a key, and the startup log has no console record (Requirement 13.7); `GET /docs` still depends only on `GS_ENABLE_DOCS`.
    - `tests/unit/test_console_cli.py`: `_report_startup` through `caplog` (existing record unchanged, one `console enabled` record with no extra field, none when off); one subprocess smoke test through `tests/publisher_cli_entry.py`, started the way the existing graceful-stop test starts it (read `tests/unit/test_publisher_cli.py` for the pattern, do not edit it), that fetches `GET /` with the console on and sees the CSP header, then stops the child in a `finally`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 13.1, 13.5, 13.7_

  - [x] 2.10 Add the route, header, secrecy and loader tests
    - `tests/unit/test_console_routes.py`: parametrized over the six routes: status 200, media type, the exact CSP string, `nosniff`, `no-referrer`, `Cache-Control` exactly `no-store, no-transform`, body equal to the packaged file, each reachable without a key; no `Content-Security-Policy` on `/health`, `/openapi.json`, a Flow call, `/mcp` and an unknown path; `Cache-Control` of `/health`, `/openapi.json`, a Flow success and error, `/mcp`, an unknown path and an unauthorized request equals the value with the console absent (Requirement 15.3); a recorded-behaviour test that pins the `HEAD` and `OPTIONS` statuses on `/` and on `/console/console.css` with and without a key, console on and off, as the design's "Recorded responses" table records them (401 without a key; with a key 400 for the chosen registration), and asserts no `HEAD` route exists; the secrecy test of Requirement 10.8 (generated API key and Bound_Values, all six routes with and without a key, no Leak_Form in any body, header or log record, using the existing `LogCapture` and `leak_forms` helpers); no `Call_Log_Record` is written by a console request.
    - Loader: `load_assets()` returns the six assets; with the package reader made to fail for one file (the only place a library function is patched), `prepare` raises `StartupError` whose message names the file and holds no path separator or drive letter.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.9, 2.10, 10.1, 10.2, 10.8, 15.1, 15.2, 15.3_

  - [x] 2.11 Add the auth tests and Property 1
    - `tests/unit/test_console_auth.py`: empty default behaves as today; the six pairs pass when on; the exact-comparison cases (`/console/console.css/`, `/console/`, `//`, a query string inside the path, upper-case variants, `HEAD`, `OPTIONS`, `POST`); with `GS_AUTH_DISABLED=true` the loopback Host rule covers the console routes (a foreign `Host` gets `unauthorized`); Flow routes, `/openapi.json`, `/docs` and `/mcp` answer `unauthorized` without a key with the console on.
    - `tests/property/test_console_auth.py`: **Property 1: Only the six console routes are open without a key.** One `@given` test, `@settings(max_examples=100, deadline=None)`, first line `# Feature: console, Property 1: Only the six console routes are open without a key`. Strategy: methods (`GET`, `HEAD`, `OPTIONS`, `POST`, `PUT`, `DELETE`, `PATCH`, lower case, random tokens); paths built from the six exact paths, mutations of them (trailing slash, case change, `%` sequences, `//`, `..` segments, prefix and suffix) and arbitrary text; header sets limited to the invalid cases of `key_headers` in `tests/property/_publisher_strategies.py`. The test calls the real ASGI stack through `call_scope` with a hand-built scope. Oracle: the response is not `unauthorized` exactly when the pair is one of the six `GET` pairs or `GET /health`.
    - _Requirements: 3.1, 3.3, 3.4, 3.6, 3.7_

  - [x] 2.12 Add Property 2 (the console changes no existing response)
    - `tests/property/test_console_parity.py`: **Property 2: The console changes no existing response.** One `@given` test, `max_examples` at least 100, first line `# Feature: console, Property 2: The console changes no existing response`. Two `prepare` results cached per console setting (the repository's `lru_cache` pattern), two apps over `FakeHost` with the same plan and a `FakeClock`, built from the same environment except `GS_ENABLE_CONSOLE`. Reuse `fake_host_plans`, `probes` and `bad_requests` from `_publisher_strategies.py` and the `MINI` Flow and `mini_states` from `publisher_support.py`. Compare status, all response headers and body for `POST /flows/{name}`, `GET /openapi.json`, `GET /health` and a `POST /mcp` `tools/list`. Failure messages carry no value.
    - Also assert that `GET /openapi.json` returns the same bytes console on and off.
    - _Requirements: 4.5, 6.6, 6.7, 13.1, 13.2, 15.2_

  - [x] 2.13 Add the packaging tests
    - `tests/unit/test_console_packaging.py`: the `package-data` key equals the list of task 2.4 and the other keys are unchanged; the wheel test imports `_wheel_workspace` and `REPO` from `tests.unit.test_flow_packaging`, repeats the build command of `test_wheel_contains_exactly_the_three_flow_yaml_files` (`pip wheel . --no-deps --no-build-isolation --no-index` in the temporary copy), asserts the wheel holds exactly `greenscreen/publisher/console/__init__.py`, `index.html`, `console.css`, `console.js`, `snippets.js`, `codes.json`, `favicon.svg` under that prefix, and fails with the build output if the build fails; a subprocess check that `import greenscreen.publisher.console` loads none of `mcp`, `fastapi`, `starlette`, `uvicorn`. Record the wheel test's duration in the notes. If the wheel build cannot run offline on this machine, report why and keep the other checks; do not weaken the test.
    - Do not edit `tests/unit/test_flow_packaging.py`.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 3. Checkpoint: the server side is green (about 0.5 h; Windows only)
  - Run `python -m pytest -m "not integration" -p no:cacheprovider`. Expected: 0 failed. Record passed, skipped, failed, deselected, pytest time and wall time against the baseline 2120 passed, 4 skipped, 0 failed, 298.05 s. A timing difference is reported, never a failure.
  - Git checks: `git diff --exit-code -- .kiro/steering` is clean; `git diff --name-only -- greenscreen` lists only `config.py`, `auth.py`, `rest.py`, `app.py`, `cli.py` under `greenscreen/publisher/` and the new `console/` package; `git diff --name-only -- tests` lists nothing (all test files are new, untracked); `git diff --cached --name-only` prints nothing; `git log` has no new commit.
  - Write a short interim report: counts, files added, and the open items. Do not start task 4 before the suite is green.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. The page (about 9 h; no live host, no browser; Windows only)
  - [x] 4.1 Write `snippets.js` (replaces the placeholder)
    - Re-check the Node and `shlex` rows of the Library documentation checks. Read design section 10 first.
    - A pure ES module: no `import`; no reference to `document`, `window`, `globalThis`, `self`, `location`, `navigator`, `fetch`, `localStorage`, `sessionStorage` or `console`; no parameter named like a key; no `http://` or `https://` literal. Exports `PLACEHOLDER_KEY` (`<YOUR_API_KEY>`), `SECRET_TEXT` (`<SECRET>`), `shellQuote`, `bodyText(inputs, maskSecrets)`, `buildCurl(origin, flowName, inputs)`, `buildMcpConfig(origin)` and `buildClaudeCodeCommand(origin)` exactly as the design specifies: single quote becomes `'\''`; empty non-required values omitted; secrets as `<SECRET>` when masked; integers written as the typed digits when they match `^-?(0|[1-9][0-9]*)$`, any other integer text as a JSON string; names through `JSON.stringify`; flow name through `encodeURIComponent`.
    - Smoke check with `node` if present: import the module through the design's `data:` URL invocation and print the three outputs for one harmless case (no secret). Otherwise record "node absent".
    - _Requirements: 5.9, 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 14.1_

  - [x] 4.2 Write `codes.json` (replaces the placeholder)
    - One flat object: the 22 Error_Codes with `status` equal to `HTTP_STATUS[code]` and the texts of the Requirement 8.3 table (keep `busy`, `try again` in the busy text and `key` in the unauthorized text; each text one or two short sentences, at most 200 characters), plus `no_response`, `unreadable_reply` and `unknown_code` with `status: null` and the design's texts. `input_invalid` carries `"show_message": true`; no other entry has the member. No `cancelled` entry.
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

  - [x] 4.3 Write `console.css` and `favicon.svg` (replace the placeholders)
    - `console.css`: the `:root` block holds every colour once as a six-digit hex Theme_Token with the design's palette (`--bg-void`, `--bg-panel`, `--bg-field`, `--bg-scan`, `--fg-main`, `--fg-dim`, `--fg-bright`, `--fg-warn`, `--fg-bad`, `--ui-line`, `--ui-focus`, `--ui-glow`). Elsewhere only `var(--fg-…)`, `var(--bg-…)`, `var(--ui-…)`, `transparent` and `currentColor`. System monospace stack, scanline by `repeating-linear-gradient`, glow by `text-shadow`, `:focus-visible { outline: 3px solid var(--ui-focus); outline-offset: 2px; }`. A slow title flicker and a once-per-second blinking cursor, and one `@media (prefers-reduced-motion: reduce)` block setting `animation: none` and `transition: none` on `*`, `*::before` and `*::after`. No `@font-face`, `@import` or `url(`.
    - `favicon.svg`: a small green icon. The only absolute URL is the `xmlns` attribute.
    - _Requirements: 2.7, 11.1, 11.2, 11.4, 11.5, 11.6, 11.7_

  - [x] 4.4 Write `index.html` (replaces the placeholder)
    - Skeleton only, as in design section 8: `<html lang="en">`, charset, viewport and referrer meta, title `Green Screen Medium`, the tagline (five words, `Seance for dead mainframe screens.`), the icon link `<link rel="icon" href="/console/favicon.svg">`, the stylesheet link, key panel (labelled password input with `autocomplete="off"`, Connect button, Forget key button, the one line of help about a key in the URL), a polite live status region, a flow list container, a polite result region, one `<script type="module" src="/console/console.js">`. No inline script or style, no `style` or `on*` attribute, no `<form>`, no `<style>`, no `tabindex` above 0, no absolute URL, no paragraph over 40 words.
    - _Requirements: 2.7, 2.8, 5.2, 5.8, 5.11, 5.12, 11.1, 11.3, 11.8_

  - [x] 4.5 Write `console.js` (replaces the placeholder)
    - Re-check the Library documentation rows for `fetch`, `history.replaceState`, `Clipboard.writeText` and the ES module rows. Read design sections 8 to 11 first.
    - Order of the file: `takeKeyFromFragment()` (prefix `#key=`, `decodeURIComponent` with raw-text fallback, `history.replaceState(null, "", location.pathname + location.search)`) and its call first; then `apiFetch` (the only reader of the key and the only place the text `X-API-Key` appears; a 401 calls `forgetKey()`); then `loadCodes()`, `forgetKey()`, `parseListing` (pure, reads only the members of design section "Listing model"), the DOM helpers (`textContent` or `createTextNode` only; attribute names from a fixed set), `renderFlows`, `renderResult`, audit rendering from the constant array of the seven `AUDIT_KEYS` names, `renderSnippets` (three blocks with `<pre tabindex="0">`, Copy buttons, selection fallback `Press Ctrl+C to copy.`, the line `Tool name: <flow>` and the clients note), `run()`, event wiring and `start()`.
    - Behaviour: key kept in a module variable only; no web storage; key input cleared after use; Run disabled while a call runs; `Calling the mainframe…` in the live region; request body from `bodyText(flow.inputs, false)`; elapsed time labelled `Elapsed (as seen by this browser)`; Secret_Input fields cleared in a `finally`; result classification per the design's table (error codes come only from the loaded table, `show_message` read from data, `summary` never read, no code name literal anywhere); 429 shows `Retry-After` when it is digits; listing errors show the table text and a Retry button; zero Flows shows `No flows are published.`; `Could not load the error table.` when `codes.json` fails.
    - No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, string `setTimeout` or `setInterval`, `javascript:`, `setAttribute` of `style` or `on*`, no `console.*` call, no `sessionStorage`, `localStorage` or `document.cookie` text anywhere, including comments.
    - The executor cannot run this file in a browser; it checks it with the static tests of 4.8 and, if `node` is present, `node --check` on a copy outside the repo.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 4.9, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.10, 8.4, 8.5, 8.6, 9.6, 9.8, 10.3, 10.4, 10.5, 10.6, 11.3_

  - [x] 4.6 Add the codes coverage tests
    - `tests/unit/test_console_codes.py`: load `codes.json` from the installed package; the key set minus `no_response`, `unreadable_reply` and `unknown_code` equals `ERROR_CODES` imported from `greenscreen.publisher.calls`; each `status` equals `HTTP_STATUS[code]`; each `text` is a non-empty string of at most 200 characters; the `busy` text holds `busy` and `try again` (case-insensitive); the `unauthorized` text holds `key`; the three page-side keys exist and are not Error_Codes; no key `cancelled`; `show_message` is `true` for `input_invalid` only and absent elsewhere; a scan finds none of the 22 code names as a string literal in `console.js`.
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 8.7, 8.8_

  - [x] 4.7 Add the Node runner, the snippet tests and Property 3
    - `tests/console_node.py` (new module, no edit of `console_support.py`): `NODE = shutil.which("node")`, `needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH; the Snippets_Module was not executed")` and `run_snippets(cases)` as in the design's "Node test": one process, `node --input-type=module -e <runner>`, the module source and the cases passed as JSON on standard input, the module imported from a `data:` URL, results read from standard output, `timeout=30`, no file written.
    - `tests/unit/test_console_snippets.py` (all marked `needs_node`): `buildCurl` for a Flow with no Caller_Inputs equals the shape of Requirement 9.2 with `-d '{}'`; a string Caller_Input holding a single quote, a double quote, a backslash, a newline, `$(x)` and a backtick decodes back (via `shlex.split` and `json.loads`); a Secret_Input appears as `<SECRET>` and its typed text appears in none of the three outputs; an `integer` appears as a JSON number; the MCP text parses as JSON with the placeholder key and `<origin>/mcp`; the Claude Code command splits into the fixed argument list of Requirement 14.5. Failure messages never print a Secret_Input value.
    - `tests/property/test_console_snippets.py`: **Property 3: Snippets survive a POSIX shell.** One `@given` test, `@settings(max_examples=100, deadline=None)`, first line `# Feature: console, Property 3: Snippets survive a POSIX shell`, marked `needs_node`. One Hypothesis example is a list of up to 20 cases, run by one `node` process. Strings come from an alphabet that includes `'`, `"`, `\`, newline, `$`, `(`, `)`, a backtick, spaces and Unicode without surrogates; integers are digit strings and non-numeric junk; secrets are `SECRET-` plus hex. A separate Python oracle applies the rules: omit empty non-required values, mask secrets, write matching digit strings as integers and everything else as strings. Assertions as in Requirement 14.5, plus the Claude command. Record the measured duration of 100 examples in the notes.
    - Verify: with `node` present the tests run and pass; if absent they skip with the fixed reason and the report says the Snippets_Module was not executed.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 14.3, 14.4, 14.5, 14.6, 14.7_

  - [x] 4.8 Add the static scan tests for the Console_Assets
    - `tests/unit/test_console_assets.py`. Over all six files: no inline `<script>` without `src`, no `<style>`, no `style=` or `on*=` attribute, no `<form>`, no absolute URL (only the SVG `xmlns` allowed), the exact icon link, `<meta name="referrer" content="no-referrer">`, `<html lang>`, title, viewport, charset, no `tabindex` above 0, every `<input>` has a label, `aria-live="polite"` on the status and result regions, no paragraph over 40 words.
    - Over `console.js` and `snippets.js`, failing with file, line and name: no `localStorage`, `sessionStorage`, `document.cookie`, `console.`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, `javascript:`, string-argument `setTimeout` or `setInterval`, `setAttribute` of `style` or `on*`. Rules: `history.replaceState` appears before the first `fetch(`; every non-assignment use of `apiKey` lies in the body of `apiFetch`; `X-API-Key` appears exactly once in `console.js`; `console.js` contains the seven audit member names and never `summary`; `snippets.js` has no `import`, none of the names of Requirement 14.1, no parameter named like a key, and contains `<YOUR_API_KEY>` and `<SECRET>`; no host name or `http://` / `https://` literal in `snippets.js`; the page makes no request outside `/openapi.json`, `/flows/`, `/console/codes.json` and the packaged assets.
    - These tests read the files from the installed package path, not from a copy.
    - _Requirements: 2.7, 2.8, 5.3, 5.4, 5.5, 5.6, 5.9, 5.10, 5.11, 7.9, 9.9, 10.3, 10.4, 10.5, 10.7, 11.3, 11.8, 11.9, 14.1, 14.2_

  - [x] 4.9 Add the CSS contrast and motion tests
    - `tests/unit/test_console_css.py`: parse the Theme_Tokens from the `:root` block of `console.css`; compute the WCAG 2.2 relative-luminance contrast ratio of every `--fg-*` token against every `--bg-*` token and fail below 4.5, and of every `--ui-*` token against every `--bg-*` token and fail below 3.0 (the failure names the token pair and ratio only); fail on any colour literal (`#`, `rgb(`, `rgba(`, `hsl(`, a colour keyword other than `transparent` and `currentColor`) outside `:root`; no `@font-face`, `@import` or `url(`; every `animation`, `transition` or `@keyframes` is accompanied by a `prefers-reduced-motion: reduce` block that sets both `animation: none` and `transition: none` for `*`, `*::before` and `*::after`; a `:focus-visible` rule with an outline of at least 2px; the blinking cursor animation period is at least one second. No browser is needed.
    - _Requirements: 11.2, 11.4, 11.5, 11.6, 11.7, 11.9_

- [x] 5. Final checkpoint and report (about 0.75 h; Windows only)
  - [x] 5.1 Run the whole suite, check the tree and write the final report
    - Run `python -m pytest -m "not integration" -p no:cacheprovider`. Record passed, skipped, failed, deselected, pytest time and wall time against the last Windows baseline: 2120 passed, 4 skipped, 0 failed, 298.05 s. Expected: passed rises by the new tests, skipped rises by the Node tests only if `node` is absent, failed 0. A timing difference is reported, never a failure. Record the duration of the wheel test and of Property 3.
    - Git checks: `git diff --name-only` lists only these modified tracked files: `greenscreen/publisher/config.py`, `auth.py`, `rest.py`, `app.py`, `cli.py`, `pyproject.toml` (one added `package-data` line), `.env.example` and, if edited by task 1.1, `.kiro/specs/console/design.md`, plus the already-pending spec edit of `.kiro/specs/publisher/tasks.md` if one is in the tree (reported, not made by this work). New untracked files: the `greenscreen/publisher/console/` package (seven files), `tests/console_support.py`, `tests/console_node.py` and the new test files named above. `git diff --exit-code -- .kiro/steering` is clean; `git diff --exit-code` on every existing test file prints nothing (no existing test file edited); `git diff --cached --name-only` prints nothing; `git log` has no new commit; `.kiro` is not in `.gitignore`.
    - Wheel contents check: the wheel test passes and lists exactly the seven files under `greenscreen/publisher/console/`.
    - No placeholder left: search the six assets for the text `PLACEHOLDER` and report none.
    - Final report: test counts before and after; every test file added; the statement that no existing test file was edited; the Node version found or "node absent, Node tests skipped"; the library documentation lines appended; the status of every requirement ("implemented, awaiting Reviewer_Check" for Requirements 5, 7, 9, 11 and 16 where the browser is needed); and everything not verified (below), including that the manual checklist was not run.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 13.1, 13.2, 13.6, 16.3, 17.2, 17.3, 17.4_

- [x] 6. Polish after the reviewer's browser run (about 2.5 h; no live host, no browser; Windows, Node on PATH)
  - [x] 6.1 Update `console.js` and `snippets.js`
    - Re-read the design sections "Focus after a call", "Audit list", "Summary scan", "Audit line width" and Decisions D10 to D12 first. Re-open https://developer.mozilla.org/en-US/docs/Web/API/HTMLElement/focus, and replace the "date to be confirmed" line in the design's "Library documentation checks" with the page, version note and the date you read it (edit `design.md` only for that line).
    - `snippets.js`: add `export function auditLine(row)` and `export function retryAfterText(value)` exactly as the design's "Audit list" and Requirement 8.4 define them (words joined by one space; duration only when finite and `Number(value.toFixed(2)) > 0`, written `N.NNs`; `finally`, `pass N`, `UNKNOWN`, `?` and the 40 and 80 character cuts; `retryAfterText` returns `null` unless the text is 1 to 6 ASCII digits). No `import`, no forbidden global name, the word `console` nowhere (not even in a comment), no parameter named like a key, no `http://` or `https://`.
    - `console.js`: import the two functions with the existing `snippets.js` import; build each audit row from the seven `AUDIT_KEYS` only and call `auditLine(row)` (keep the class choice from `row.status`); replace the `"Retry after: " + ... + " seconds"` line by `retryAfterText(info.retryAfter)` and show nothing when it returns `null`; change `finishResult` to `refs.result.focus({ preventScroll: true })`; remove `DETAILS_HEAD_TAG` and `FLOW_TEXT_KEY`, write `el("summary", ...)`, `operation.summary` (rename the variable that holds `item.post` to `operation`) and the class string `"flow-summary"`; make sure no `scrollIntoView`, `scrollTo`, `scrollBy`, `window.scroll` or `location.hash =` appears; remove `safeText` if nothing else uses it. Do not change `index.html`, `codes.json`, the routes or `pyproject.toml`.
    - Run `node --check` on a copy of `console.js` outside the repo, if `node` is present.
    - _Requirements: 6.8, 7.3, 7.11, 8.4, 14.8_

  - [x] 6.2 Update `console.css` for the two-column density
    - Read the design section "Audit line width" first. In `.audit` set `column-width: 26rem` (unchanged) and `column-gap: 1.5rem`; in `.audit > li` set the left padding to `1.25rem` (keep `break-inside: avoid`, add `overflow-wrap: anywhere`); keep the mark at `left: 0`. The narrow-screen block (`@media (max-width: 56rem)`, `column-width: 18rem`) stays. No colour literal outside `:root`, no new animation, no font-size below 1rem.
    - Compute and write into the design, under "Audit line width", the measured line length in `ch` of the longest line of the demo Flow's 39-step trail against the column width (the table already holds the estimate; confirm it still matches the final CSS, or correct the numbers). Record the figures you used. Do not claim a browser measurement.
    - _Requirements: 7.12, 11.4, 11.5, 11.6_

  - [x] 6.3 Update and add tests
    - `tests/unit/test_console_assets.py` (the one existing test file this spec edits): replace the plain `summary` check in `test_console_js_has_seven_audit_names_and_no_summary_member` by the pure function `summary_violations(text)` of the design's "Summary scan" and a call that asserts an empty list for the real `console.js`; add a parametrized self-check over the design's fixture table (pass rows and fail rows) against the same function; add the focus scan of Requirement 6.9. Keep the other assertions of that test and every other test in the file unchanged.
    - `tests/unit/test_console_format.py` (new, marked `needs_node`, importing `NODE` and `needs_node` from `tests/console_node.py` without editing it): one helper runs `auditLine` and `retryAfterText` for a list of cases in a single `node` process with the same `data:` URL import and standard-input pattern as `run_snippets` (no file written, `timeout=30`), and the tests compare with the examples of the design's test table and a small Python reference. Skip reason: `node is not on PATH; the Snippets_Module was not executed`.
    - `tests/unit/test_console_audit_layout.py` (new, no browser): the `console.css` checks of the design's test table (column width 22rem to 28rem, gap at most 1.5rem, `list-style: none`, `.audit > li` left padding at most 1.25rem).
    - The existing scans over `snippets.js` (names of Requirement 14.1, no `import`, no host literal, contains `<YOUR_API_KEY>` and `<SECRET>`) must still pass with the two new functions; if one fails, fix `snippets.js`, not the test.
    - _Requirements: 6.9, 7.3, 7.11, 7.12, 8.4, 14.8_

  - [x] 6.4 Final run and report
    - Prepend `C:\Program Files\nodejs` to `PATH` for the shell that runs the tests (`$env:Path = "C:\Program Files\nodejs;" + $env:Path`), record `node --version`, and run `python -m pytest -m "not integration" -p no:cacheprovider`. Expected: 0 failed, no Node test skipped. Record passed, skipped, failed, deselected and times, against the Linux result 2416 passed, 0 failed, 15 skipped (Node absent) and the earlier Windows baseline of task 5.
    - Git checks: `git diff --name-only` lists only `greenscreen/publisher/console/console.js`, `snippets.js`, `console.css`, `tests/unit/test_console_assets.py`, the three spec files and, if they were already pending, the files that task 5 reported; new untracked files are `tests/unit/test_console_format.py` and `tests/unit/test_console_audit_layout.py`; `git diff --exit-code -- .kiro/steering` is clean; no other existing test file is modified; `git diff --cached --name-only` prints nothing; no new commit. `index.html`, `codes.json`, `favicon.svg`, `pyproject.toml` and every `greenscreen/publisher/*.py` are unchanged. Search the six assets for `PLACEHOLDER` and for the words `sum" + "mary`: none.
    - Final report: counts before and after, files changed and added, the statement that only `test_console_assets.py` was edited among existing tests, the library documentation line written, and what is not verified: checklist steps 15 to 17 (scroll position, audit width at 1280x720, `1 second`) are for the reviewer, and the widths are an estimate.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 13.1, 13.6, 16.3, 17.3_

- [x] 7. Seance art (about 2 h; no live host, no browser; Windows, Node on PATH)
  - [x] 7.1 Add the art, wrapper and spans to `index.html`
    - Read Requirement 11 criteria 10 to 13 and the design section "Seance art (task 7)" first. Before writing the markup, check the current documentation for the ARIA `img` role and `aria-label` naming (page, version or date) and append a dated line to the design's "Library documentation checks" (edit `design.md` for that line only).
    - Edit `greenscreen/publisher/console/index.html` only. Inside `<main class="stage">`, after the `<section class="result" ...>` element, paste the markup of the design verbatim: `<div class="seance-art-wrap" role="img" aria-label="A crystal ball on a seance table">` holding `<pre class="seance-art" aria-hidden="true">` with the 17 rows and the static `<span class="seance-ball">` and `<span class="seance-dim">` spans. The first row follows the `<pre>` start tag with no line feed, and `</pre>` follows the last row with no line feed. No other change in the file.
    - Check the pasted rows against the design: 17 rows, widest row 56 columns, ASCII only (0x20 to 0x7E), no tab, no blank row, spaces intact. No `style` attribute, no `tabindex`, no link, button or input inside the wrapper, no script change.
    - _Requirements: 11.10, 11.11, 11.12, 11.13_

  - [x] 7.2 Add the rules to `console.css`
    - Read the design's "CSS", "Glow pulse", "Layout and size at 1280x720" and "Contrast" parts first.
    - Edit `greenscreen/publisher/console/console.css` only: add `.seance-art-wrap`, `.seance-art` (`font-family: inherit`, `font-size: 1rem`, `line-height: 1.2`, `white-space: pre`, `margin: 0`), `.seance-dim` and `.seance-ball` as in the design; `@keyframes gs-pulse` beside the other keyframes (period 6 s, `text-shadow` blur 4px to 9px only); `.has-result .seance-art-wrap { display: none; }`; and `@media (max-width: 68rem) { .seance-art-wrap { display: none; } }`. Colours only through `var(--fg-dim)`, `var(--fg-bright)` and `var(--ui-glow)`. No new token, colour literal, `font-weight`, `letter-spacing`, `url(` or font. Do not edit the reduced-motion block: it already disables `.seance-ball`.
    - Write into the design, under "Layout and size at 1280x720", the figures actually in the final CSS (rows x font-size x line-height + padding). Correct the numbers if they differ from 342.4px; do not claim a browser measurement.
    - _Requirements: 11.13, 11.14, 11.15, 11.16, 11.17_

  - [x] 7.3 Add the seance tests
    - Create `tests/unit/test_console_seance.py` with the checks of the design's table "Tests (task 7.3)": label exactly once on a `div.seance-art-wrap[role=img]`; wrapper inside `main.stage`; one `pre.seance-art` with only `class` and `aria-hidden="true"`; spans only, not nested, one `class` attribute each with one of the two names; every non-space character inside a span; ASCII only; at most 20 rows and 60 columns, no blank row, no trailing space, 17 rows and a widest row of 56; ball, two `(__)` and table top present; nothing focusable inside; CSS hides under `.has-result` and under a `max-width` block of at least 56rem; `white-space: pre`, font size at least 1rem, computed height at most 400px; colour values only from the three tokens; contrast of the two text tokens at least 4.5 and of `--ui-glow` at least 3 on `--bg-void` and `--bg-scan`; the pulse is only on `.seance-ball`, at least 4 s, `text-shadow` only with blur difference at most 8px, and the reduced-motion block unchanged in effect.
    - Import the CSS helpers from `tests.unit.test_console_css` and the page reading style from `tests/unit/test_console_assets.py` without editing either. Failure messages name the check and the line or row, never a long dump.
    - Run `python -m pytest tests/unit/test_console_seance.py tests/unit/test_console_assets.py tests/unit/test_console_css.py tests/unit/test_console_audit_layout.py -p no:cacheprovider`. All pass, and no existing test is edited. If an existing scan fails because of the new markup, stop and report the test and the cause; do not change the test.
    - _Requirements: 11.10, 11.11, 11.12, 11.13, 11.14, 11.15, 11.16, 11.17, 11.18_

  - [x] 7.4 Final run and report
    - Prepend `C:\Program Files\nodejs` to `PATH` for the shell (`$env:Path = "C:\Program Files\nodejs;" + $env:Path`), record `node --version`, and run `python -m pytest -m "not integration" -p no:cacheprovider`. Expected: 0 failed, no Node test skipped. Record passed, skipped, failed, deselected and times against the result of task 6.4.
    - Git checks: `git diff --name-only` shows, for production files, only `greenscreen/publisher/console/index.html` and `greenscreen/publisher/console/console.css` from this task (plus `design.md` from 7.1 and 7.2, and any file earlier tasks already reported as pending). `console.js`, `snippets.js`, `codes.json`, `favicon.svg`, `pyproject.toml` and every `greenscreen/publisher/*.py` are unchanged: `git diff --exit-code` on each. The only new untracked file from this task is `tests/unit/test_console_seance.py`. `git diff --exit-code -- .kiro/steering` is clean, no existing test file is modified by this task, `git diff --cached --name-only` prints nothing, no new commit.
    - Wheel check: the existing wheel test passes and still lists exactly the seven files under `greenscreen/publisher/console/`. Search the six assets for `PLACEHOLDER`: none.
    - Final report: counts before and after, files changed and added, the statement that no existing test file was edited, the documentation line written, and what is not verified: checklist steps 18 to 20 (art fit and scrollbar at 1280x720, hide after a run and below 68rem, screen-reader announcement) are for the reviewer, and the heights and widths are an estimate from font metrics.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 11.18, 16.3, 16.4, 17.3_

- [x] 8. MCP-visible Run (about 10 h; no live host, no browser; Windows, Node on PATH)
  - [x] 8.1 Library documentation checks and probe record (about 0.75 h; record only)
    - Edit `.kiro/specs/console/design.md` only, in the section "Library documentation checks": append dated lines (format `Checked <date>: <page URL>, <version>, <conclusion>`) for the items the design lists as "Not checked in task 8's design stage": MDN `AbortController` and `AbortSignal` with `fetch`; MDN `Headers.get` and reading `Mcp-Session-Id` from a same-origin `Response`; MDN `<details>` and its `open` attribute; the ARIA toggle button pattern and `aria-pressed` on `<button>`; the WHATWG server-sent events line-parsing rules (https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation) against the rules of `parseMcpReply` in the design; `setTimeout` with a function argument; MDN `Element.getBoundingClientRect`, `window.innerHeight`, the `toggle` event and `open` property of `<details>`, and scroll anchoring (for the open-state decision of Requirement 18, criterion 26). If a page contradicts a rule of "snippets.js additions", change the design text and say what changed.
    - Re-run the `/mcp` probe once: a throwaway script in the system temp directory (not in the repository) that builds the app with `build_console_app` from `tests/console_support.py`, enters `app.lifespan()`, and drives `call_scope` for the rows of "Recorded /mcp behaviour" (at least rows 1, 3, 4, 6, 7, 11, 12, 14, 17, 19, 20, 21). It prints no key. Compare with the recorded table, append one dated line saying which rows were reproduced and any difference, and delete the script and its output. If a row differs in a way that makes a requirement of 18 false, STOP and report instead of continuing.
    - Record `python -m pip list` versions of `mcp`, `mcp-types`, `starlette`, `fastapi`, `hypothesis`, `pytest`, `httpx2`, and `node --version` (with `C:\Program Files\nodejs` on PATH).
    - Make NO change to any file other than `design.md`. Run `validate_spec_format` on it.
    - _Requirements: 18.2, 18.3, 18.5, 18.11, Conventions (library documentation rule), 17.4_

  - [x] 8.2 Add the MCP functions to `snippets.js`, their Node tests and Property 4 (about 3.0 h)
    - Re-read design sections "Recorded /mcp behaviour" and "snippets.js additions" and the dated lines of 8.1 first. Edit `greenscreen/publisher/console/snippets.js` only for production code.
    - Add `toggleAllLabel(allOpen)` and `fitsInFirstScreen(bottom, limit)` and the Transcript_Line grammar (design "Transcript_Line grammar"; `formatTranscriptEntry` returns `{ line, text, omitted }`, no `label`) as well as `MCP_OFFERED_VERSION`, `MCP_KNOWN_VERSIONS`, `buildInitialize`, `buildInitialized`, `buildToolsList`, `buildToolsCall`, `mcpRequestHeaders`, `parseMcpReply`, `findReply`, `hasTool`, `classifyToolsCall`, `prettyJson`, `formatTranscriptEntry`, `summariseRun`, `stripStages` and `jsonRpcErrorText` exactly as the design specifies. Existing exports stay as they are. The module keeps: no `import`; none of `document`, `window`, `globalThis`, `self`, `location`, `navigator`, `fetch`, `localStorage`, `sessionStorage`, `console`; no parameter whose name contains `key` (any letter case); no `http://` or `https://`; no host-name literal ending in `.com`, `.net`, `.org`, `.io`, `.dev`, `.app`, `.local`, `.lan` or `.invalid`; the word `summary` nowhere (the projection is an allow-list that does not name it); the text `console` followed by a dot nowhere, comments included. The word `key` MAY appear in comments and strings (a JSON-RPC member is never named that way), but do not use it as a parameter name.
    - Create `tests/console_node_mcp.py` (`run_calls(calls)`; imports `NODE`, `needs_node` and `snippets_source` from `tests/console_node.py`; edits nothing there; one `node` process per batch; source and calls as JSON on standard input; `data:` URL import; `timeout=30`; no file written).
    - Create `tests/unit/test_console_mcp_snippets.py` (`needs_node`) with the cases listed in the design's "Tests", including the `line` of every row of the Transcript_Line grammar, the 100-character cut, the character rule, `toggleAllLabel` and `fitsInFirstScreen`. Failure messages print no Secret_Input value and no key. The module must hold the word `summary` nowhere (call the one-line text `line`).
    - Create `tests/property/test_console_mcp_snippets.py`: **Property 4: The wire transcript never holds the key or a typed secret.** One `@given` test, `@settings(max_examples=100, deadline=None)`, first line `# Feature: console, Property 4: The wire transcript never holds the key or a typed secret`, marked `needs_node`, with the generators and the separately written oracle of the design, which also asserts that every Transcript_Line matches `^[\x20-\x7E]{1,100}$` and holds neither the key nor a Secret_Input value. Record the duration of 100 examples.
    - Verify: with `node` present the new tests run and pass; with it absent they skip with the fixed reason `node is not on PATH; the Snippets_Module was not executed`. Run the existing `tests/unit/test_console_assets.py` scans over `snippets.js` (`-k snippets`) and `tests/unit/test_console_snippets.py`, `tests/unit/test_console_format.py`, `tests/property/test_console_snippets.py`: they pass unchanged.
    - _Requirements: 18.3, 18.4, 18.5, 18.13, 18.14, 18.15, 18.16, 18.18, 18.19, 18.24, 18.25, 18.26, 14.1, 14.2_

  - [x] 8.3 Add the Call_Via markup and the CSS hooks (about 1.0 h)
    - Re-read design "Layout and CSS hooks (task 8.3)" first. Edit `greenscreen/publisher/console/index.html` and `console.css` only.
    - `index.html`: in `aside.side`, between `section.key-panel` and `div.flows`, add `<div class="call-via" role="group" aria-label="Call via" hidden>` holding `<button type="button" class="quiet" id="via-mcp" aria-pressed="true">MCP</button>` and `<button type="button" class="quiet" id="via-rest" aria-pressed="false">REST</button>`, in that order, and one `<p class="help">` of at most 25 words saying that MCP shows the messages the page exchanges with `/mcp` and REST calls the flow endpoint directly. No `<input>`, no `style` or `on*` attribute, no other change (the Seance_Art markup stays byte for byte).
    - `console.css`: add the rules of the design's hook table (`.call-via`, the `[aria-pressed="true"]` rule with a bold weight, a `::before` dot mark and the `--ui-focus` border, `.mcp-line`, `.mcp-clients`, `.mcp-clients-title`, `.mcp-clients .snippet pre` with `pre-wrap`, `.strip`, `.strip-stage` and the arrow rule, `.wire`, `.wire-head`, `.wire-title`, `.wire-toggle`, `.wire-note`, `.wire-list`, `.wire-entry`, `.wire-msg`, `.wire-msg > summary` (the one-line text: pointer cursor, `+ ` and `- ` ASCII markers by `::before`, wrapping allowed), the strip as the first child of the result region, `.wire-json` with `max-height: 10rem`, `overflow: auto`, `pre-wrap`, `overflow-wrap: anywhere`, `.wire-sent` and `.wire-received`). Colours only through `var(--fg-*)`, `var(--bg-*)`, `var(--ui-*)`; no new token, colour literal, animation, transition, `url(`, `@import` or font-size below 1rem; no change to `.has-result`, `.seance-*` or `.audit` rules.
    - Write into the design, under "Layout and CSS hooks (task 8.3)", the figures actually in the final CSS (heights, the strip width against 904px) and correct the estimates if they differ. Do not claim a browser measurement.
    - Verify: `python -m pytest tests/unit/test_console_assets.py tests/unit/test_console_css.py tests/unit/test_console_audit_layout.py tests/unit/test_console_seance.py -p no:cacheprovider` passes with no test change.
    - _Requirements: 18.1, 18.12, 18.16, 18.17, 18.21, 18.25, 11.4, 11.5, 11.6, 11.8, 11.17_

  - [x] 8.4 Write the MCP client, transcript, strip and Call_Via logic in `console.js` (about 4.0 h)
    - Re-read the design sections "The MCP client state machine in `console.js`", "`console.js` additions in rendering" and "Secrecy decisions" first, and the "must keep green" list of "Tests". Edit `greenscreen/publisher/console/console.js` only.
    - `apiFetch`: extend the allow-list to `path === "/openapi.json" || /^\/flows\/[^/]+$/.test(path) || path === "/mcp"` (the existing text stays in front, so the existing scan regex still matches). Nothing else about the key changes: it is still read only there, `X-API-Key` still appears once.
    - Import the new functions from `./snippets.js`. Add `callVia`, `sessionId`, `protocolVersion`, `wire`; `post(message, ...)`, `runMcp(flow)`, `mcpFailure`, `renderCallVia`, `appendStrip`, `appendWire`. Move the existing body of `run` into `runRest(flow)` with no change to its statements, and let `run` choose by `callVia`; the guard, `setRunning` and the `finally` that clears Secret_Inputs stay in `run`. `showSuccess`/`showError` build the strip first (first child of the result region, above the result title), then the title, outputs and elapsed line, then the transcript, then the audit, as the design says. The transcript is `div.wire-head` (title and the `Expand all` / `Collapse all` button, text from `toggleAllLabel`, no `aria-pressed`) and one closed `details` per entry whose `summary` text is the `line` of `formatTranscriptEntry` and whose `<pre>` is its `text`; `setAllWire` and a `toggle` listener per entry keep the button text right. Add `settleTranscript()` exactly as the design's "Transcript expansion" says: after `has-result` is set and before the focus call, open the two `tools/call` entries, measure the list bottom with `getBoundingClientRect` (list bottom minus document element top), keep them open only if `fitsInFirstScreen(bottom, Fit_Limit)` and the list height is above 0, otherwise close them; any error or missing function leaves everything closed. Write no scroll call and never the text `window.scroll` (existing focus scan); no literal `Expand all` or `Collapse all` in `console.js`. This decision cannot be run here: say so in the final report; the REST result view is otherwise unchanged.
    - Steps 1 to 3 use an `AbortController` and `setTimeout` with a function argument (15 s), cleared in a `finally`; step 4 has no timer. Read each reply once with `await response.text()`; read only the headers `Content-Type`, `Mcp-Session-Id` (and `Retry-After` in the REST path); never display a header value. No `innerHTML` family, no `console.`, no `summary` word outside the allowed forms, no scroll call, `refs.result.focus({ preventScroll: true })` unchanged, no literal wire text (`"jsonrpc"`, `"tools/call"`, `"notifications/initialized"`).
    - Flow article: add the `p.mcp-line`, the always-visible `section.mcp-clients` (heading `Any MCP client can use this same tool`, the two blocks, their Copy buttons, `Tool name: <name>`, the line about client differences) and keep the curl block inside a collapsed `details.snippets` (summary `Use this flow with curl`). `updateSnippets` updates all three blocks. Add `open` and `aria-pressed` to the allowed attribute names of `el`. Show `Call via` only while a key is held.
    - Check with `node --check` on a copy outside the repo. Run `python -m pytest tests/unit/test_console_assets.py -p no:cacheprovider`: exactly one test is expected to fail until 8.5 (`test_requests_stay_on_allowed_paths`, because of the new `"/mcp"` literal); any other failure is a defect to fix in `console.js` or to report.
    - _Requirements: 18.2, 18.3, 18.4, 18.6, 18.7, 18.8, 18.9, 18.10, 18.11, 18.12, 18.13, 18.14, 18.16, 18.17, 18.24, 18.25, 18.26, 5.6, 6.8, 9.11, 10.3, 10.4, 10.5_

  - [x] 8.5 Update the one existing test and add the static tests (about 0.5 h)
    - Edit `tests/unit/test_console_assets.py` in exactly one place: in `test_requests_stay_on_allowed_paths`, the tuple `allowed = ("/openapi.json", "/flows/", "/console/codes.json")` becomes `("/openapi.json", "/flows/", "/mcp", "/console/codes.json")`. No other line of that file changes. Report the diff (one line).
    - Create `tests/unit/test_console_mcp_assets.py` with the static checks listed in the design's "Tests" (the `console.js` checks of the design's "Tests" for `settleTranscript`, `setAllWire`, `toggleAllLabel`, `fitsInFirstScreen`, `getBoundingClientRect`, the strip built before the result title in `showSuccess` and `showError`, no `window.scroll` text and no literal `Expand all` or `Collapse all`; `apiFetch("/mcp"` only as a literal first argument and no `fetch("/mcp"`; `X-API-Key` once; no stream reader, `.body`, `response.json()`; header names read; no wire-text literals in `console.js`; `setTimeout(` with a function; `snippets.js` has no `summary` at all; the `index.html` Call_Via markup; the heading and line texts in `console.js`; the hook classes in `console.css`). Failure messages carry file, line and name only.
    - Run `python -m pytest tests/unit/test_console_assets.py tests/unit/test_console_mcp_assets.py -p no:cacheprovider`: all pass.
    - _Requirements: 18.20, 18.22, 5.10, 10.7_

  - [x] 8.6 Final run and report (about 0.75 h)
    - Prepend `C:\Program Files\nodejs` to `PATH` for the shell (`$env:Path = "C:\Program Files\nodejs;" + $env:Path`), record `node --version`, and run `python -m pytest -m "not integration" -p no:cacheprovider`. Expected: 0 failed, no Node test skipped. Record passed, skipped, failed, deselected and times against the result of task 7.4, and the duration of Property 4.
    - Git checks: `git diff --name-only` shows, for production files, only `greenscreen/publisher/console/index.html`, `console.css`, `console.js`, `snippets.js` (plus the files that earlier tasks already reported as pending, plus `design.md` from 8.1 and 8.3, and `requirements.md` and `tasks.md` if those are still pending). Every `greenscreen/publisher/*.py`, `codes.json`, `favicon.svg`, `pyproject.toml` and `.env.example` is unchanged (`git diff --exit-code` on each). The only modified existing test file is `tests/unit/test_console_assets.py`, with a one-line diff. New untracked files: `tests/console_node_mcp.py`, `tests/unit/test_console_mcp_snippets.py`, `tests/property/test_console_mcp_snippets.py`, `tests/unit/test_console_mcp_assets.py`. `git diff --exit-code -- .kiro/steering` is clean, `git diff --cached --name-only` prints nothing, no new commit.
    - Wheel check: the existing wheel test passes and lists exactly the seven files under `greenscreen/publisher/console/`. Search the six assets for `PLACEHOLDER`: none. Search `console.js` and `snippets.js` for the typed password pattern: no secret value is in any file (no `TK5_`, no key value).
    - Final report: counts before and after; files changed and added; the one-line diff of the existing test; the dated documentation lines written; the probe comparison of 8.1; and, as required by Requirement 18.23, a section "Browser behaviours not verified" copied from the design's "Not verifiable here", with checklist steps 21 to 30 listed as not run by the executor.
    - Also list, under "What a viewer sees for a successful run", the exact strings, generated rather than typed: in a throwaway script outside the repository (system temp directory, deleted afterwards, no key printed), build the app with `build_console_app`, drive the four requests of a successful run with `call_scope` against the Fake_Host (the same four replies as the design's "Recorded /mcp behaviour"), save the reply texts, and run the pure module under Node (`run_calls`) over them: the three `stripStages` texts with `summariseRun` counts for the real audit, each `line` of `formatTranscriptEntry` in the eight-entry order, the `toggleAllLabel` text for all closed and all open, the output names taken from `structuredContent.outputs` (these are the labels the page shows) and the elapsed label `Elapsed (as seen by this browser)`. Say that the values come from the Fake_Host, that the browser's open-state decision was not computed, and that the reviewer compares the list with the page.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 18.19, 18.22, 18.23, 13.1, 13.6, 16.3, 17.3_

## Reviewer-only items (the executor does NOT run these; no checkbox)

Status: steps 1 to 12 below were run by the reviewer in headless Chrome 157 at 1280x720 against the live host and passed (no CSP violation, no script error). Steps 13 and 14 were not run. Steps 15 to 17 are new for task 6.

These items need a real browser, a tunnel or a vendor product. The executor lists them in the final report as "not run by the executor" (Requirement 16.3) and does not tick anything here.

### Manual browser checklist (copied from `design.md`)

Use a real browser with the developer tools open (Console and Network tabs). Start the Publisher with `GS_ENABLE_CONSOLE=true`, a key of at least 16 characters, and `GS_PUBLISH_FLOWS=tk5-system-info`, with the live host reachable.

1. Open `/`. Expected: the page loads with the phosphor theme, the key input has focus, and the Console shows no CSP violation and no error.
2. Type a wrong key and press Enter. Expected: the `unauthorized` text appears, the key input is shown again and is empty.
3. Type the right key and press Enter. Expected: the Flow list appears with `tk5-system-info`, its description, and no field for the bound password; focus moves to the Run button.
4. Press Run. Expected: `Calling the mainframe…` shows, the buttons are disabled, then the outputs (`USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`), an elapsed time labelled as seen by this browser, and an audit list with words for each status. Network tab: exactly one `POST /flows/tk5-system-info`.
5. Reload, then open `/#key=<key>`. Expected: the address bar shows `/` with no fragment immediately, the Flow list loads without typing, and the key does not appear in any request URL or in the page.
6. Look at the history entries and the page source. Expected: the key is not in the page text, the title, any link, or `Application > Storage` (no local storage, no session storage, no cookie).
7. Open two tabs, press Run in both within a second. Expected: one finishes with outputs; the other shows the `busy` text, `429`, and a retry-after value.
8. Use only the keyboard: Tab through the whole page, press Enter on the key field, on Run and on each Copy button. Expected: the order is key panel, inputs, Run, three Copy buttons, result; every control shows a visible 3-pixel ring; no keyboard trap.
9. Turn on reduced motion in the operating system and reload. Expected: no flicker on the title and no blinking cursor.
10. Press each of the three Copy buttons and paste into a terminal or editor. Expected: the pasted text is the `curl` command, the MCP JSON and the `claude mcp add` command, each with `<YOUR_API_KEY>` and the page origin. On a plain `http://` non-localhost address, expected: `Press Ctrl+C to copy.` appears and the text is selected.
11. Stop the Publisher and press Run. Expected: the `no_response` text.
12. Check that the Console (developer tools) has no CSP violation and no error after steps 1 to 11.
13. Deploy time, tunnel. Open only these paths in the tunnel: `GET /`, `GET /console/console.css`, `/console/console.js`, `/console/snippets.js`, `/console/codes.json`, `/console/favicon.svg`, `GET /openapi.json`, `POST /flows/tk5-system-info`, `/mcp`, `/health`. Keep `/docs` closed. Expected: the page works through the public host name and `location.origin` in the snippets is the public name.
14. Deploy time, CDN or edge injection. View the page source through the public name and compare it with the packaged `index.html`; check the Console for CSP violations. Expected: no added script, no rewritten file, `Cache-Control: no-store, no-transform` still present on the six routes. If the edge injects anything (scripts, analytics, minification), turn the injecting feature off for these paths.
15. Scroll position (task 6). At 1280x720 with the page at the top, read `window.scrollY`, press Run, wait for the result, read it again. Expected: both 0, the masthead still on screen, `document.activeElement.id` is `result`.
16. Audit density (task 6). Run the demo Flow so that the trail has 39 entries at 1280x720. Expected: two columns, no wrapped line, lines like `12 expect tso-password-prompt OK`, no duration for entries under 0.005 s, a word for every failed or skipped entry. If a line wraps, report its text and the column width.
17. Retry after (task 6). Reproduce a 429 as in step 7. Expected: `Retry after: 1 second` for 1, `Retry after: N seconds` otherwise, no line for an absent or non-digit header.
18. Seance art (task 7). At 1280x720 load `/` before any run. Expected: the art is centred in the stage, no horizontal scrollbar, the key panel and Run button in view, `window.scrollY` is 0.
19. Seance art (task 7). Run a Flow, then press Forget key. Expected: the art disappears with the result and returns after Forget key; below 1088px window width it is hidden, with no horizontal scrollbar at any width.
20. Seance art (task 7). With a screen reader, read the page before any run. Expected: one image, "A crystal ball on a seance table", no characters read, and Tab never lands on the art.

### MCP-visible Run checklist (task 8; steps 21 to 30 of `design.md`, not run by the executor)

21. Network tab: four `POST /mcp` in order (200, 202, 200, 200), key only as `X-API-Key`, no `POST /flows/...` in MCP mode.
22. Strip first in the result region, above the result title and the outputs: `MCP client (this page)`, `MCP tool <name>`, `3270 screens: <n> steps on <m> distinct screens`; `n` and `m` match a hand count of the audit (not skipped; distinct screen names).
23. Transcript: eight one-line entries in order (for example `sent tools/call: tk5-system-info`, `received result: 4 outputs, <m> audit entries`), each a single line; each opens with Enter or Space to the full JSON, `tools/list` showing name, description, input and output schema; no header, key or `summary` in any line or expansion; Secret_Inputs shown as `<SECRET>`; a `Left out by this page:` line on the received `tools/call`.
24. Call via REST (keyboard: Tab to the group, Space or Enter): one `POST /flows/...`, same result panel, REST strip, no transcript, `aria-pressed` and the pressed mark correct.
25. Failures: no response, wrong key, a Flow stop (table text, `Reported by the MCP tool as an error result.`, audit, strip numbers).
26. Layout at 1280x720 after a run: masthead on screen, `window.scrollY` 0, art gone, strip, outputs and first transcript entries visible, MCP blocks readable in the side column, audit still two columns.
27. MCP blocks visible without opening anything, under `Any MCP client can use this same tool`; Copy works; curl collapsed.
28. Keyboard order (the `Expand all` button is the first stop of the transcript) and the 3-pixel ring on every stop; transcript `<pre>` scrolls with the arrow keys; if a server that answers with `text/event-stream` is available, the same run gives the same result.
29. Expand and collapse: `Expand all` opens every entry and its text becomes `Collapse all` (and back); opening entries by hand keeps the text right; focus stays on the button, `window.scrollY` is unchanged, the masthead stays on screen.
30. Initial open state: at 1280x720 report whether the two `tools/call` entries started open or closed and the pixel bottom of `ol.wire-list` (all closed, and with the two open); check it against the rule of Requirement 18, criterion 26; repeat in a tall window and with a shorter viewport.

### Other reviewer items

- Tunnel allow-list (Decision 12): confirm the ten entries of step 13 and that `/docs` stays closed. `POST /flows/{name}` needs one entry per published Flow.
- `HEAD /` from a tunnel or monitor returns 401 without a key (design open item 3). Decide whether a monitor needs it; allowing it is outside this spec.
- Confirm the wording of Requirements 9.5 and 14.5 (third block, `buildMcpConfig` takes only the origin), the `show_message` member and the `_report_startup` helper, which the alignment edit of this task list brought into `requirements.md`.
- Run the Node tests on the Node versions the project supports (only v24.19.0 was run by the design).

### Unverified items the final report must list

- Task 8 ("Not verifiable here" in `design.md`), including the open-or-closed decision for the two `tools/call` entries (`getBoundingClientRect`, `window.innerHeight`), the `toggle` event behind `Expand all` / `Collapse all` and scroll anchoring: `fetch` to `/mcp` with the page's headers in Chrome and Firefox; `response.text()` on JSON, on an empty 202 and on a `text/event-stream` reply (the recorded server sends no SSE; SSE parsing is tested under Node with synthetic texts only); `Mcp-Session-Id` exposure on a same-origin reply (none is sent); `Accept` negotiation; `AbortController` and the 15-second timer; focus order and screen-reader state of Call via; layout at 1280x720; clipboard on the MCP blocks; a tunnel or CDN in front of `POST /mcp`; `busy` over MCP (read from `calls.py`, not run); anything on the live host.

- Checklist steps 1 to 12 ran in headless Chrome 157 (reviewer, passed). Still not run in a browser by anyone: steps 13 to 17. The older line follows for the record. Nothing was run in a browser by the executor: `history.replaceState`, the CSP with a module script and its static `import`, focus order, `Clipboard.writeText`, `prefers-reduced-motion`, screen readers.
- `HEAD` and `OPTIONS` over a real uvicorn socket, and the console-on with `GS_AUTH_DISABLED=true` combination over a real socket (tests use an in-process ASGI transport).
- MCP configuration shapes for Claude Desktop, Cursor and VS Code: not checked on vendor pages. The page names only Kiro and Claude Code. Kiro and Claude Code shapes were read from vendor pages, not run in those products.
- `fetch` behaviour beyond basic use, from documentation only.
- CDN or tunnel behaviour: injected scripts, header rewriting, caching, `Host` changes.
- Node versions other than the one on the executor's PATH.

## Notes

- Windows cannot show: a real browser, the CSP in a browser, a real socket for `HEAD` and `OPTIONS`, a tunnel, a CDN, Node versions other than the installed one.
- Property tests: Properties 1, 2 and 3 are sub-tasks 2.11, 2.12 and 4.7. Each is one `@given` test with at least 100 examples and the first-line comment the requirements name.
- Task 7 writes `index.html` (7.1) and `console.css` (7.2) in the same wave because they are different files; 7.3 reads both and creates the only new test file; 7.4 runs last. Steps 18 to 20 of the checklist are for the reviewer.
- Task 6 writes `console.js` and `snippets.js` (6.1), `console.css` (6.2) and tests (6.3); 6.3 reads the files of 6.1 and 6.2, so it is in a later wave. `test_console_assets.py` is edited by 6.3 only.
- Task 8 writes `snippets.js` (8.2) and `index.html` plus `console.css` (8.3) in the same wave because they are different files; `console.js` (8.4) imports the functions of 8.2 and reads the ids of 8.3, so it follows both; 8.5 reads all four files and is the only task that edits an existing test (one line); 8.6 runs last. 8.1 may edit `design.md`; no other task of 8 does except 8.3 (the measured figures). Rule for task 8: the words `console` followed by a dot, `summary` (outside the allowed forms in `console.js`; anywhere in `snippets.js`) and any parameter name containing `key` are forbidden by existing scans, so write code and comments accordingly. The text `window.scroll` (also as the start of a scroll-position name) is forbidden in `console.js` by the focus scan: measure with `getBoundingClientRect` only.
- Dependency graph rules: `rest.py`, `app.py`, `cli.py`, `auth.py`, `config.py` are each written by one task. The placeholder files of 2.2 are rewritten only in wave 6 to 8 by 4.1 (`snippets.js`), 4.2 (`codes.json`), 4.3 (`console.css`, `favicon.svg`), 4.4 (`index.html`) and 4.5 (`console.js`). Every new test file has one writing task. Checkpoints and top-level tasks are left out of the graph.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["2.5"] },
    { "id": 3, "tasks": ["2.6"] },
    { "id": 4, "tasks": ["2.7", "2.8"] },
    { "id": 5, "tasks": ["2.9", "2.10", "2.11", "2.12", "2.13"] },
    { "id": 6, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 7, "tasks": ["4.4", "4.6", "4.7"] },
    { "id": 8, "tasks": ["4.5", "4.9"] },
    { "id": 9, "tasks": ["4.8"] },
    { "id": 10, "tasks": ["5.1"] },
    { "id": 11, "tasks": ["6.1", "6.2"] },
    { "id": 12, "tasks": ["6.3"] },
    { "id": 13, "tasks": ["6.4"] },
    { "id": 14, "tasks": ["7.1", "7.2"] },
    { "id": 15, "tasks": ["7.3"] },
    { "id": 16, "tasks": ["7.4"] },
    { "id": 17, "tasks": ["8.1"] },
    { "id": 18, "tasks": ["8.2", "8.3"] },
    { "id": 19, "tasks": ["8.4"] },
    { "id": 20, "tasks": ["8.5"] },
    { "id": 21, "tasks": ["8.6"] }
  ]
}
```
