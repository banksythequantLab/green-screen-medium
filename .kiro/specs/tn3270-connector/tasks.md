# Implementation Plan: tn3270-connector

## Overview

Implement the `greenscreen.connector` Python 3.11+ library that drives an `s3270`/`ws3270` subprocess to maintain a headless IBM 3270 terminal session. The build proceeds in strict dependency order: scaffold → value objects → I/O layer → parser → renderer → connector → testing harness → tests.

## Tasks

- [x] 1. Scaffold package structure and project configuration
  - Create `greenscreen/connector/__init__.py` and `greenscreen/connector/testing/__init__.py` with empty exports
  - Create `pyproject.toml` declaring the `greenscreen-connector` package with `requires-python = '>=3.11'`; list `pyyaml>=6.0.3` as the only runtime dependency under `[project.dependencies]`; add an `[project.optional-dependencies]` group named `dev` containing `hypothesis>=6.170.15`, `pytest>=8.0`, and `pyyaml>=6.0.3`; do NOT include `pytest-mark` (marks are built into pytest, not a separate package)
  - Create `pytest.ini` (or `[tool.pytest.ini_options]`) registering the `integration` mark and setting `testpaths = tests`
  - Create empty `tests/unit/`, `tests/property/`, `tests/integration/` directories with `__init__.py` files
  - Create `tests/conftest.py` with the session-scoped `host_reachable` fixture (TCP probe to `GS_HOST`:`GS_PORT`, `pytest.skip` on failure)
  - _Requirements: 2.1, 8.1, 10.2, 10.3_

- [ ] 2. Implement exception hierarchy and core value objects
  - [ ] 2.1 Implement `exceptions.py` with the full `ConnectorError` hierarchy
    - Define `ConnectorError(Exception)` as base
    - Define `ConfigurationError(ConnectorError)` with `.parameter_name: str`
    - Define `S3270Error(ConnectorError)` with `.action: str`, `.data_lines: list[str]`, `.status_line: StatusLine | None`, `.exit_code: int | None`
    - Define `ConnectorTimeoutError(ConnectorError)` with `.operation: str`, `.deadline: float`
    - Define `ParseError(ConnectorError)` with `.raw: str`
    - Define `SessionClosedError(ConnectorError)`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ] 2.2 Implement `models.py` with all data model classes
    - Implement `SFToken(frozen=True)` with `c0: int`
    - Implement `SAToken(frozen=True)` with `value: int`
    - Define `CellValue = Union[int, SFToken]` type alias
    - Implement `StatusLine(frozen=True)` with all 12 named attributes and `serialize() -> str` method
    - Implement `Field(frozen=True)` with `start_row`, `start_col`, `protected`, `modified`
    - Implement `Screen` dataclass (not frozen) with `rows`, `columns`, `cursor_row`, `cursor_col`, `cell_grid`, `sa_tokens`, derived `text_grid` property (SFToken and 0x00 → `' '`), derived `fields` property (from SFToken positions, wrapping across rows), `text_at(row, col, length) -> str` (raises `ValueError` on out-of-bounds), `find_field(row, col) -> Field | None`, and `__eq__` defined on `cell_grid` and `sa_tokens` only
    - Implement `Response(frozen=True)` with `success: bool`, `data_lines: list[str]`, `status: StatusLine`
    - _Requirements: 5.2, 5.3, 5.6, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 3. Implement cross-platform pipe I/O
  - [ ] 3.1 Implement `_io.py` with `PipeReader`
    - Implement `PipeReader.__init__` accepting a binary readable pipe, creating a `queue.Queue[bytes | None]`, and starting the daemon reader thread named `"gs-pipe-reader"`
    - Implement `_reader_loop` to call `readline()` in a loop, stripping `\r\n` with `rstrip(b"\r\n")` before enqueuing, and putting `None` sentinel on EOF
    - Implement `readline(timeout: float) -> bytes` that calls `queue.get(timeout=timeout)`, raises `ConnectorTimeoutError` on `queue.Empty`, and raises `S3270Error` (with `exit_code`) when the `None` sentinel is received
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ] 3.2 Write unit tests for `PipeReader`
    - Test data-arrives-before-deadline path using an in-process pipe or mock
    - Test deadline-expires path: verify `ConnectorTimeoutError` is raised
    - Test EOF/sentinel path: verify `S3270Error` is raised with `exit_code` set
    - _Requirements: 11.4_

- [ ] 4. Implement `ScreenParser`
  - [ ] 4.1 Implement `parser.py` with `ScreenParser`
    - Implement `parse_status_line(raw: str) -> StatusLine`: split on whitespace, assert exactly 12 tokens, parse integer fields 7–10, raise `ParseError(raw=raw)` on wrong count or non-integer
    - Implement `_escape_s3270_string(text: str) -> str` and `_unescape_s3270_string(escaped: str) -> str` (backslash before double-quote in escape order; for testing only)
    - Implement `_tokenize(data_lines, rows, cols)`: iterate all rows as a flat sequence, classify each token as hex cell (`[0-9a-fA-F]{2}`), `SF(c0=xx)`, or `SA(42=xx)`, advance `col_index` for hex and SF tokens only (SA does not advance), store `SFToken` in `cell_grid`, store `SAToken` in `sa_tokens`, raise `ParseError(raw=token)` on unrecognised tokens
    - Implement `parse_readbuffer(response: Response) -> Screen`: extract dimensions and cursor from `response.status`, call `_tokenize`, return `Screen`
    - Confirm that the `protected` flag = `bool(c0 & 0x20)` and `modified` flag = `bool(c0 & 0x01)` for all fixture values (`c8`, `e0`, `e8`, `f0`, `f8`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.9, 5.10, 5.11, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ] 4.2 Write property test for `StatusLine` serialize–parse round-trip (Property 3)
    - **Property 3: StatusLine serialize–parse round-trip**
    - Generate arbitrary 12-token status line strings (non-empty printable ASCII tokens, no spaces within tokens); assert `parse_status_line(raw).serialize() == raw`
    - Use `@settings(max_examples=500)`
    - **Validates: Requirements 9.3, 6.1, 6.2, 6.3, 6.4, 6.5**

  - [ ] 4.3 Write property test for `c0` attribute byte flag correctness (Property 5)
    - **Property 5: `c0` attribute byte protected-flag correctness**
    - Generate all byte values 0x00–0xFF; assert `SFToken(c0=n).protected == bool(n & 0x20)` and `SFToken(c0=n).modified == bool(n & 0x01)` as derived by the parser
    - **Validates: Requirements 5.9**

  - [ ] 4.4 Write property test for `data:` prefix stripping (Property 9)
    - **Property 9: `data:` prefix stripping preserves content**
    - Generate arbitrary `list[str]`; wrap each with `"data: "`, pass through the response parser, assert `Response.data_lines` equals the original list
    - **Validates: Requirements 3.2**

- [ ] 5. Implement `ScreenRenderer`
  - [ ] 5.1 Implement `renderer.py` with `ScreenRenderer`
    - Implement `render(screen: Screen) -> list[str]`: iterate `cell_grid` row by row; before each cell check `sa_tokens[row]` for `SAToken` at that column and emit `SA(42=xx)` first; emit `int` cells as lowercase zero-padded two-digit hex; emit `SFToken` cells as `SF(c0=xx)` using the raw `c0` byte verbatim (never recompute from flags); join tokens per row with single space
    - _Requirements: 9.1, 9.2_

  - [ ] 5.2 Write property test for screen parse→render→parse round-trip (Property 1)
    - **Property 1: Screen parse–render round-trip**
    - Generate arbitrary `Screen` objects via Hypothesis strategy (random SF positions, raw byte cells, SA tokens, cursor within bounds); assert `ScreenParser().parse_readbuffer(Response(..., data_lines=ScreenRenderer().render(screen), status=...)) == screen`
    - Use `@settings(max_examples=200)`
    - **Validates: Requirements 9.1, 5.2, 5.3**

  - [ ] 5.3 Write property test for render-is-left-inverse-of-parse (Property 2)
    - **Property 2: Render is left inverse of parse**
    - Generate arbitrary valid `ReadBuffer(Ascii)` line lists (rows 1–24, cols 10–80, mix of hex tokens and `SF(c0=xx)` tokens); assert `ScreenRenderer().render(ScreenParser().parse_readbuffer(response)) == raw_lines`; also run explicitly on the data from every file in the `captures/` directory at the repo root
    - Use `@settings(max_examples=200)`
    - **Validates: Requirements 9.2, 5.1**

- [ ] 6. Checkpoint — parser and renderer complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement s3270 string escaping helpers and `ConnectorConfig`
  - [ ] 7.1 Implement `config.py` with `ConnectorConfig`
    - Implement `ConnectorConfig` dataclass with `binary`, `host`, `port`, `model`, `default_timeout` fields and `__post_init__` applying env-var fallbacks (`GS_S3270_BINARY`, `GS_HOST`, `GS_PORT`) and `_validate()` raising `ConfigurationError` with `.parameter_name` on missing or out-of-range values
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 7.2 Write property test for s3270 string escaping round-trip (Property 4)
    - **Property 4: s3270 string escaping round-trip**
    - Generate arbitrary printable ASCII strings (U+0020–U+007E, length 0–3000); assert `_unescape_s3270_string(_escape_s3270_string(text)) == text`
    - Use `@settings(max_examples=500)`
    - **Validates: Requirements 9.6, 3.6**

- [ ] 8. Implement `Connector`
  - [ ] 8.1 Implement `connector.py` — subprocess lifecycle (`open` / `close`)
    - Implement `Connector.__init__` storing config, initialising `_proc = None`, `_reader = None`, `_closed = False`
    - Implement `open()`: build command line `[config.binary, "-model", config.model]`; `subprocess.Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)`; wrap `proc.stdout` in `PipeReader`; start daemon thread to drain and discard `proc.stderr`; send `Connect(host:port)` as first command; on error response terminate subprocess and raise `ConnectorError`; raise `ConnectorError` if already open
    - Implement `close()`: if closed or proc is None return silently; send `Disconnect()` then `Quit()`; `proc.wait(timeout=5)`; on `TimeoutExpired` call `terminate()`, `wait(5)`, then `kill()` if needed; log warning; set `_closed = True`
    - Implement `__enter__` / `__exit__` (context manager; `__exit__` always re-raises)
    - Accept an optional `process_factory` parameter in `Connector.__init__` (default: `subprocess.Popen`); the factory is called with the same arguments as `Popen` and must return an object with `.stdin`, `.stdout`, `.stderr`, `.wait(timeout)`, `.terminate()`, `.kill()`, and `.poll()` attributes; this allows tests to inject `FakeS3270` without monkeypatching
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [ ] 8.2 Implement `connector.py` — `send`, action helpers, and screen capture
    - Implement `_write(action: str)`: write `action + "\n"` to `proc.stdin` encoded as bytes; log at DEBUG with `direction="sent"`
    - Implement `_read_response(action: str, timeout: float) -> Response`: call `PipeReader.readline(timeout)` in a loop collecting `data:` lines, status line, and `ok`/`error`; strip `data: ` prefix; call `parse_status_line`; return `Response` on `ok`; raise `S3270Error` on `error`; raise `SessionClosedError` if `_closed`; log at DEBUG with `direction="received"`
    - Implement `send(action: str) -> Response`: validate non-empty, no newline; call `_write` then `_read_response` using `default_timeout`; on `ConnectorTimeoutError` terminate subprocess
    - Implement `_send_with_deadline(action, deadline) -> Response` for wait methods
    - Implement `enter()`, `pf(n)`, `pa(n)`, `clear()` (validate 1–24 for pf/pa)
    - Implement `string(text)` calling `_escape_s3270_string`, raising `ValueError` if `len(text) > 3000`
    - Implement `move_cursor(row, col)` raising `ValueError` for negative coordinates
    - Implement `wait_for_output`, `wait_for_field`, `wait_for_unlock` using `_resolve_timeout` and `_send_with_deadline` with `WAIT_GRACE_SECONDS = 5.0` added to deadline
    - Implement `snap_save()`
    - Implement `read_screen() -> Screen` (sends only `ReadBuffer(Ascii)`, passes response to `ScreenParser().parse_readbuffer`)
    - Implement `ascii() -> Response` (sends `Ascii()`)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 7.6, 7.7, 7.8_

  - [ ] 8.3 Write property test for `pf`/`pa` `ValueError` boundary (Property 7)
    - **Property 7: `pf`/`pa` raises `ValueError` iff `n` is out of `[1, 24]`**
    - Use `FakeS3270` stub; generate arbitrary integers; assert `ValueError` raised iff `n < 1` or `n > 24` for both `pf` and `pa`
    - **Validates: Requirements 3.5**

  - [ ] 8.4 Write property test for wait timeout substitution (Property 8)
    - **Property 8: Wait timeout substitution**
    - Generate `default_timeout` and optional `timeout` values in `(0.0, 3600.0]`; use `FakeS3270` to capture the command string; assert `Wait(N,...)` contains the exact numeric value passed (or `default_timeout` when `timeout=None`)
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ] 8.5 Write property test for `text_at` correctness (Property 6)
    - **Property 6: `text_at` extracts the correct substring**
    - Generate arbitrary `Screen` objects with valid `(row, col, length)` triples; assert `screen.text_at(row, col, length) == screen.text_grid[row][col:col+length]`
    - **Validates: Requirements 5.6**

- [ ] 9. Implement testing harness
  - [ ] 9.1 Implement `testing/fake.py` with `FakeS3270`
    - Define `ScriptedResponse` dataclass with `command_pattern: str`, `response_lines: list[str]`, `status_line: str`, `result: str`
    - Implement `FakeS3270.__init__` accepting `list[ScriptedResponse]`; expose `stdin`, `stdout`, `stderr`, `wait(timeout)`, `terminate()`, `kill()`, and `poll()` attributes so that `FakeS3270` satisfies the same interface that `Connector` expects from `subprocess.Popen` and can be passed directly as the `process_factory` argument
    - Implement `_handle_command(command)`: match against current `ScriptedResponse.command_pattern` with `re.fullmatch`; raise `AssertionError` on mismatch or exhaustion; write `data: {line}\n`, status line, and result to stdout pipe
    - _Requirements: 8.1, 8.2, 8.5_

  - [ ] 9.2 Implement `testing/fixtures.py` and YAML fixture files
    - Implement `FixtureFrame` dataclass with `data_lines: list[str]`, `status_line: str`, `result: str`
    - Implement `load_fixture(path: str) -> list[FixtureFrame]` using `pyyaml`
    - Create `testing/fixtures/tk5-logo.yaml` with the data lines from `captures/tk5-logo.readbuffer.txt` and status line `U F P C(127.0.0.1) I 2 24 80 0 0 0x0 0.006`
    - Create `testing/fixtures/tk5-logon.yaml` with the data lines from `captures/tk5-logon.readbuffer.txt` and status line `U F U C(127.0.0.1) I 2 24 80 22 11 0x0 0.000`
    - Fixture data must be transcribed verbatim from the capture files; do not invent or approximate any tokens
    - In `pyproject.toml`, declare `testing/fixtures/*.yaml` as package data under `[tool.setuptools.package-data]` (or equivalent) so that `load_fixture` works from an installed wheel, not just from the source tree
    - Add a unit test that calls `load_fixture` using a path resolved via `importlib.resources` (or `importlib.resources.files`) from the installed `greenscreen.connector.testing` package, and asserts the two bundled frames load without error; this test must pass both when running from source and from an installed package
    - _Requirements: 8.3, 8.4_

- [ ] 10. Write unit tests
  - [ ] 10.1 Write unit tests for `ConnectorConfig` and `exceptions.py`
    - Test construction with all fields explicit
    - Test env-var fallback for `GS_S3270_BINARY`, `GS_HOST`, `GS_PORT`
    - Test `ConfigurationError` raised (with `.parameter_name`) when required fields are missing
    - Test port out-of-range (0 and 65536) raises `ConfigurationError`
    - Test `default_timeout` out-of-range raises `ConfigurationError`
    - _Requirements: 1.1, 1.2, 1.3, 7.2_

  - [ ] 10.2 Write unit tests for `Connector` lifecycle and `send` via `FakeS3270`
    - Test `open()` and `close()` happy path using `FakeS3270`
    - Test context-manager `__enter__`/`__exit__` calls `open`/`close`; verify exception propagates
    - Test `send()` success path returns `Response` with `success=True`
    - Test `send()` raises `S3270Error` when s3270 returns `error`
    - Test `send()` raises `ValueError` for empty string and string containing newline
    - Test `string()` escaping: backslash → `\\`, double-quote → `\"`, mixed input, 3001-char raises `ValueError`
    - Test `move_cursor()` with negative row/col raises `ValueError`
    - Test `pf()`/`pa()` boundary values: n=1, n=24 succeed; n=0, n=25 raise `ValueError`
    - Test `wait_for_output`/`wait_for_field`/`wait_for_unlock` with explicit timeout and with `timeout=None` (uses `default_timeout`)
    - Test `wait_for_*` raises `ValueError` for timeout ≤ 0
    - Test calling any method after `close()` raises `SessionClosedError`
    - _Requirements: 2.1, 2.4, 2.5, 2.6, 2.9, 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.6, 7.3, 7.6_

  - [ ] 10.3 Write unit tests for `ScreenParser`
    - Test `parse_status_line` with valid 12-token input
    - Test `parse_status_line` raises `ParseError` for 11 and 13 tokens
    - Test `parse_status_line` raises `ParseError` when rows/cols/cursor fields are non-integer
    - Test `ReadBuffer(Ascii)` decoding: SF tokens stored as `SFToken` in `cell_grid`
    - Test SA token storage: `SA(42=xx)` placed in `sa_tokens`, does not occupy cell position
    - Test `ParseError` raised for invalid hex token
    - Test `c0` decoding for all five fixture values: `c8` (unprotected), `e0`, `e8`, `f0`, `f8` (all protected)
    - **SA cell-occupancy regression test**: count non-SA tokens per row in `tk5-logon.yaml` fixture and assert each row has exactly 80 non-SA tokens; this is a regression check confirming the settled fact (from the steering doc) that SA tokens do not occupy cells — every row in both ReadBuffer captures has exactly 80 non-SA tokens, including the 13 logon rows that carry up to 8 SA tokens each
    - _Requirements: 5.4, 5.5, 5.9, 5.10, 5.11, 6.1, 6.6, 6.7_

  - [ ] 10.4 Write unit tests for `Screen` methods and `ScreenRenderer`
    - Test `Screen.text_at` valid range extracts correct substring
    - Test `Screen.text_at` raises `ValueError` for row out-of-range, col out-of-range, length < 1, range exceeding row boundary
    - Test `Screen.find_field` returns correct `Field` for a position inside a field
    - Test `Screen.find_field` returns `None` for a position between fields
    - Test `Screen.text_grid` derived property: SFToken cells → `' '`, `0x00` → `' '`, other bytes → `chr(byte)`
    - Test `ScreenRenderer.render` on a minimal screen and verify token format
    - Test `load_fixture` loads `tk5-logo.yaml` and `tk5-logon.yaml` without error
    - **Logon `===>`  field wrap test**: using `tk5-logon.yaml`, verify that the `Logon ===>` input field (`SF c0=c8` at its known position) wraps to end-of-screen, and `find_field` returns the correct `Field` for a cell inside that span
    - _Requirements: 5.2, 5.3, 5.6, 5.7, 5.8, 8.3, 8.4_

  - [ ] 10.5 Write unit tests for `FakeS3270`
    - Test that a matching command emits the scripted response lines, status line, and `ok`
    - Test that a non-matching command raises `AssertionError` identifying expected pattern and actual command
    - Test that an extra command after all scripted responses are exhausted raises `AssertionError` with the unexpected command text
    - _Requirements: 8.2, 8.5_

- [ ] 11. Checkpoint — unit tests and property tests complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Write integration tests
  - [ ] 12.1 Write integration test: logo then logon screen
    - Mark with `@pytest.mark.integration`; guard with `host_reachable` session fixture (auto-skip on no TCP connection)
    - Connect using `GS_HOST`/`GS_PORT`/`GS_S3270_BINARY`; call `read_screen()` to get logo screen; send `enter()`; call `wait_for_output(timeout=8)`; call `read_screen()` again; assert `"Logon ===>"` appears in the text grid
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ] 12.2 Write integration test: Wait timeout format acceptance (s3270 4.3 / ws3270 4.5)
    - Mark with `@pytest.mark.integration`; guard with `host_reachable`
    - After connecting and reaching an idle (no-output) state, send `Wait(1,Output)` (integer seconds) via `send()` and inspect the result:
      - If `ok` or `S3270Error` is raised with error text that is NOT a syntax/parse rejection (e.g. contains 'Timed out'), the integer format is accepted — record as passing
      - If `S3270Error` is raised with error text indicating a syntax error (e.g. 'Unknown' or 'Invalid'), the integer format is rejected — record as failing
    - Repeat with `Wait(1.0,Output)` (decimal seconds) applying the same accept/reject logic
    - Assert that at least one format is accepted by the binary under test; fail the test with a clear message if both formats are rejected (indicating a protocol error unrelated to notation)
    - Document the accepted format(s) in a comment so the `_resolve_timeout` implementation can emit the correct notation
    - _Requirements: 10.1 (timeout format verification)_

- [ ] 13. Wire up public exports and final checkpoint
  - [ ] 13.1 Populate `greenscreen/connector/__init__.py` with public API exports
    - Export `Connector`, `ConnectorConfig`, `Response`, `StatusLine`, `Screen`, `Field`, `SFToken`, `SAToken`
    - Export all exceptions: `ConnectorError`, `ConfigurationError`, `S3270Error`, `ConnectorTimeoutError`, `ParseError`, `SessionClosedError`
    - Export `ScreenParser`, `ScreenRenderer`
    - Verify that `from greenscreen.connector import Connector` works without additional imports
    - _Requirements: all_

  - [ ] 13.2 Final checkpoint — all tests pass
    - Run `pytest tests/unit tests/property -q` and confirm zero failures
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Each task references specific requirements for traceability
- The property tests in tasks 4.2–4.4, 5.2–5.3, 7.2, 8.3–8.5 correspond directly to Properties 1–9 in the design document's "Correctness Properties" section
- Fixture YAML files must be built from verbatim capture data in `captures/` at the repo root; no data may be invented
- Integration tests auto-skip when `GS_HOST`:`GS_PORT` is unreachable; credential tests additionally skip when `TK5_USERNAME` or `TK5_PASSWORD` is unset
- SA tokens do not occupy cells (settled fact, steering doc 2026-11-15): every row in both ReadBuffer captures has exactly 80 non-SA tokens. Task 10.3 carries a regression test confirming this.
- Run integration tests explicitly with `pytest -m integration tests/integration/`
- Run property tests with `pytest tests/property/ --hypothesis-seed=0` for reproducibility

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "2.2"] },
    { "id": 1, "tasks": ["3.1", "4.1", "5.1", "7.1"] },
    { "id": 2, "tasks": ["3.2", "4.2", "4.3", "4.4", "5.2", "5.3", "7.2", "9.1", "9.2"] },
    { "id": 3, "tasks": ["8.1", "8.2"] },
    { "id": 4, "tasks": ["8.3", "8.4", "8.5", "10.1", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 5, "tasks": ["12.1", "12.2", "13.1"] },
    { "id": 6, "tasks": ["13.2"] }
  ]
}
```
