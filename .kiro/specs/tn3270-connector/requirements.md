# Requirements Document

## Introduction

The tn3270-connector is a Python 3.11+ library that manages a headless IBM 3270 terminal session by driving the `s3270` (or `ws3270` on Windows) binary as a subprocess. It provides a clean, typed API for opening connections, sending keystrokes and text, waiting for host output, capturing structured screen snapshots, and closing sessions cleanly. This library is Core Piece 1 of Green Screen Medium: the deterministic, auditable runtime bridge between modern callers and legacy mainframe/AS400 hosts.

The library is consumed by the Green Screen Medium runtime and recorder. At runtime, no LLM is involved — the connector must behave deterministically for every action it performs.

## Glossary

- **Connector**: The Python library described by these requirements, responsible for lifecycle and I/O of one s3270 subprocess.
- **s3270**: The scriptable, display-less IBM 3270 terminal emulator from the x3270 suite (v4.3+). On Windows the binary is named `ws3270`; both are functionally identical.
- **Session**: A single active subprocess running s3270 with an open TN3270 connection to a host.
- **Host**: An IBM mainframe or compatible system reachable via TN3270 (e.g., MVS 3.8j TK5 on Hercules).
- **Action**: A single s3270 scripting command sent to the subprocess over its standard input (e.g., `Connect(host:port)`, `Enter()`, `Ascii()`).
- **Response**: The output s3270 emits for one action: zero or more `data: ` lines, one status line, then the string `ok` or `error`.
- **Status Line**: A single line with 12 blank-separated fields that s3270 appends to every response (keyboard state, screen formatting, field protection, connection state, emulator mode, model number, rows, columns, cursor row, cursor column, window ID, command execution time).
- **Screen**: A complete snapshot of the terminal display at a point in time, including the text grid and all field metadata.
- **Screen_Object**: A structured Python object representing one Screen, as returned by the Connector after each action or on demand.
- **Field**: A contiguous range of character positions on a Screen that shares a single field attribute (start row, start column, length, protected/unprotected flag, modified flag).
- **Screen_Parser**: The component that converts raw `Ascii()` and `ReadBuffer(Ascii)` output into a Screen_Object.
- **Screen_Renderer**: The component that serializes a Screen_Object back into the `ReadBuffer(Ascii)` representation — one `data:` line per row containing two-digit hex cell codes and `SF(c0=xx)` tokens — matching the format observed in the `/captures` fixtures.
- **Fixture**: A file containing recorded s3270 output (data lines + status line + ok/error) used in place of a live subprocess during unit testing.
- **Timeout**: A maximum number of seconds the Connector will wait for a host response before raising an exception.
- **Config**: A `ConnectorConfig` dataclass or equivalent typed object holding all runtime parameters (binary path, host, port, model, timeout defaults).

## Requirements

### Requirement 1: Configuration

**User Story:** As a developer integrating Green Screen Medium, I want all runtime parameters in one typed configuration object so that I can change the binary path, host address, or timeout without touching library internals.

#### Acceptance Criteria

1. THE Connector SHALL accept a Config object that specifies, at minimum: the path to the s3270 binary, the target host address, the target port number (valid range 1–65535, default `23`), the terminal model string (default `3279-2`), and a default timeout in seconds (valid range 1–3600, default `30`).
2. IF a Config field that accepts an environment variable fallback is absent or set to an empty string, THEN THE Connector SHALL read that field's value from its corresponding environment variable (`GS_S3270_BINARY` for the binary path, `GS_HOST` for the host address, `GS_PORT` for the port number).
3. IF the Config object omits a field that has no environment variable fallback and no built-in default, THEN THE Connector SHALL raise a `ConfigurationError` at construction time before any subprocess is started.
4. THE Connector SHALL never read host credentials (username or password) from source code; credentials are supplied only through environment variables or the Config object.

---

### Requirement 2: Session Lifecycle

**User Story:** As a caller, I want to open and close a TN3270 session through a simple API so that the library handles subprocess management transparently.

#### Acceptance Criteria

1. WHEN `Connector.open()` is called, THE Connector SHALL start the s3270 binary as a subprocess with no host argument on the command line and with stdin, stdout, and stderr each connected to a pipe.
2. WHEN `Connector.open()` is called, THE Connector SHALL send `Connect(host:port)` as the first and only command before any other action, where `host` and `port` come from the Config object.
3. IF the `-model` flag is set in the Config, THEN THE Connector SHALL pass that model string as a command-line argument to s3270 (e.g., `-model 3279-2`) when starting the subprocess.
4. WHEN `Connector.close()` is called on an open Session, THE Connector SHALL send `Disconnect()` followed by `Quit()` to the subprocess, then wait for the subprocess to exit with a timeout of 5 seconds.
5. IF the subprocess does not exit within 5 seconds of receiving `Quit()`, THEN THE Connector SHALL terminate the subprocess forcibly and emit a warning-level log entry through the standard Python `logging` module under the library's logger.
6. THE Connector SHALL implement the Python context-manager protocol (`__enter__` / `__exit__`) so that a `with` statement calls `open()` on entry and `close()` on exit, and `__exit__` SHALL re-raise any exception that propagated from the `with` block without suppressing it.
7. WHEN `Connector.close()` is called on a Session whose subprocess is no longer running or has already been closed, THE Connector SHALL return without raising an exception.
8. IF the s3270 binary is not found at the configured path, THEN THE Connector SHALL raise a `ConnectorError` with a message that includes the attempted path.
9. IF `Connector.open()` is called on a Connector that is already open, THEN THE Connector SHALL raise a `ConnectorError` indicating that the session is already open without starting a second subprocess.
10. IF `Connect(host:port)` returns an error response from s3270, THEN THE Connector SHALL raise a `ConnectorError` that includes the host and port from the Config object, and SHALL terminate the subprocess before raising.

---

### Requirement 3: Sending Actions

**User Story:** As a caller, I want to send individual s3270 actions and receive the parsed response so that I can build deterministic flow execution on top of this library.

#### Acceptance Criteria

1. THE Connector SHALL expose a `send(action: str) -> Response` method that writes the action string followed by a newline to the s3270 subprocess stdin and reads lines from stdout until a line equal to `ok` or `error` is received, treating that line as the final response token; IF the action string is empty or contains a newline character, THEN THE Connector SHALL raise a `ValueError` before writing to stdin.
2. WHEN s3270 returns `ok` as the final response token, THE Connector SHALL return a `Response` object with `success=True`, the list of data lines with the `data: ` prefix stripped (an empty list when no data lines precede the token), and the parsed `StatusLine`.
3. WHEN s3270 returns `error` as the final response token, THE Connector SHALL raise a `S3270Error` that includes the action string, the data lines with the `data: ` prefix stripped, and the parsed `StatusLine`.
4. WHILE reading the response, THE Connector SHALL enforce the configured default timeout (a positive number of seconds, greater than 0); IF no new data arrives within that duration, THEN THE Connector SHALL raise a `ConnectorTimeoutError` containing the action string, discard any partially read data, and attempt to terminate the subprocess; IF the subprocess does not exit within 5 seconds of the termination attempt, THE Connector SHALL forcibly kill it.
5. THE Connector SHALL expose convenience methods `enter()`, `pf(n: int)`, `pa(n: int)`, and `clear()` that call `send()` with the corresponding s3270 AID actions; IF `n` is outside the range 1–24 inclusive for `pf` or `pa`, THEN THE Connector SHALL raise a `ValueError` before calling `send()`.
6. THE Connector SHALL expose a `string(text: str)` method that encodes `text` for s3270 by wrapping it in double quotes and backslash-escaping every embedded double quote (`"` → `\"`) and every backslash (`\` → `\\`), then sends `String("escaped_text")` to s3270; IF `text` exceeds 3,000 characters, THEN THE Connector SHALL raise a `ValueError` before sending.
7. THE Connector SHALL expose a `move_cursor(row: int, col: int)` method that calls `send(f"MoveCursor({row},{col})")` using zero-origin coordinates; IF `row` or `col` is negative, THEN THE Connector SHALL raise a `ValueError` before calling `send()`.

---

### Requirement 4: Wait Operations

**User Story:** As a caller, I want to block until the host has finished updating the screen so that I do not read a partial or stale screen.

#### Acceptance Criteria

1. WHEN `wait_for_output` is called with `timeout` set to a value greater than 0.0 and at most 3600.0 seconds, THE Connector SHALL send `Wait(N,Output)` to s3270 where `N` is that timeout value in seconds; IF `timeout` is `None`, THEN THE Connector SHALL substitute the `default_timeout` value from Config as `N`.
2. WHEN `wait_for_field` is called with `timeout` set to a value greater than 0.0 and at most 3600.0 seconds, THE Connector SHALL send `Wait(N,InputField)` to s3270 where `N` is that timeout value in seconds; IF `timeout` is `None`, THEN THE Connector SHALL substitute the `default_timeout` value from Config as `N`.
3. WHEN `wait_for_unlock` is called with `timeout` set to a value greater than 0.0 and at most 3600.0 seconds, THE Connector SHALL send `Wait(N,Unlock)` to s3270 where `N` is that timeout value in seconds; IF `timeout` is `None`, THEN THE Connector SHALL substitute the `default_timeout` value from Config as `N`.
4. WHEN a wait action times out at the s3270 level, THE Connector SHALL raise a `ConnectorTimeoutError` whose message includes the name of the wait type (one of `Output`, `InputField`, or `Unlock`) and the numeric timeout value that was used.
5. WHEN `snap_save` is called, THE Connector SHALL send `Snap(Save)` to s3270 and return only after s3270 acknowledges the command.
6. IF `timeout` is zero or negative, THEN THE Connector SHALL raise a `ValueError` before sending any command to s3270.
7. IF s3270 returns an error response to a wait command for a reason other than timeout expiry, THEN THE Connector SHALL raise a `S3270Error` whose message includes the error text returned by s3270.

---

### Requirement 5: Screen Capture and Parsing

**User Story:** As a caller, I want each screen returned as a structured object so that I can inspect fields, detect screen identity, and extract data without string-slicing raw text.

#### Acceptance Criteria

1. THE Connector SHALL expose a `read_screen() -> Screen_Object` method that sends only `ReadBuffer(Ascii)` to the s3270 subprocess and returns a fully populated Screen_Object; the text grid is derived from the raw cell data returned by `ReadBuffer(Ascii)`, making the snapshot atomic. THE Connector SHALL also expose a separate `ascii() -> Response` method that sends `Ascii()` and returns the raw response for callers that need the human-readable text form independently.
2. THE Screen_Parser SHALL populate the Screen_Object with: the number of rows (a positive integer), the number of columns (a positive integer), the cursor row as a zero-origin integer in the range [0, rows-1], the cursor column as a zero-origin integer in the range [0, cols-1], the full text grid as a list of exactly `rows` strings each padded to exactly `cols` characters, and a list of Fields (zero or more entries).
3. FOR EACH Field in the Screen_Object, THE Screen_Parser SHALL record: `start_row` and `start_col` as zero-origin integers; `byte_length` as the number of cells between the SF token (exclusive) and the next SF token (exclusive), wrapping across row boundaries; `protected` (`bool(c0 & 0x20)`); `numeric` (`bool(c0 & 0x10)`); `hidden` (`(c0 & 0x0C) == 0x0C`, indicates a non-display / password field); `modified` (`bool(c0 & 0x01)`); `c0` as the raw attribute byte; and `text` as the field's cells decoded to exactly `byte_length` characters (0x00 and SFToken cells → `' '`, other bytes → `chr(byte)`). Components that use Field objects MUST check `hidden` before logging or storing `text`; hidden fields contain passwords and must never appear in logs or persistent storage. Bit definitions sourced from the IBM 3270 Data Stream Programmer's Reference.
4. THE Screen_Parser SHALL derive row count, column count, cursor row, and cursor column exclusively from the Status Line that accompanies each s3270 response, and SHALL NOT use fixed constants for any of these four values.
5. IF the s3270 subprocess returns a response whose Status Line is absent or does not contain parseable row count, column count, cursor row, and cursor column values, THEN THE Connector SHALL raise a `ParseError` and SHALL NOT return a partially populated Screen_Object.
6. THE Screen_Object SHALL expose a `text_at(row: int, col: int, length: int) -> str` method that extracts a substring of exactly `length` characters from the text grid starting at zero-origin position (row, col), where `length` is a positive integer and the range [col, col+length-1] must not exceed [0, cols-1] on the given row.
7. IF `text_at` is called with a `row` outside [0, rows-1], a `col` outside [0, cols-1], a `length` less than 1, or a range [col, col+length-1] that exceeds the row boundary, THEN THE Screen_Object SHALL raise a `ValueError` indicating the out-of-bounds argument.
8. THE Screen_Object SHALL expose a `find_field(row: int, col: int) -> Field | None` method that returns the Field whose range contains the given zero-origin position; on a formatted screen (one with at least one SF token) every cell position resolves to exactly one Field; `find_field` SHALL return `None` only on an unformatted screen (a screen with no SF tokens at all).
9. WHEN the Screen_Parser receives a `ReadBuffer(Ascii)` line containing `SF(c0=nn)`, THE Screen_Parser SHALL decode the `c0` attribute byte `nn` as a two-digit hexadecimal value and set the following flags: `protected` = `bool(c0 & 0x20)` (bit 5); `numeric` = `bool(c0 & 0x10)` (bit 4); `hidden` = `(c0 & 0x0C) == 0x0C` (bits 3,2 both set, non-display intensity); `modified` = `bool(c0 & 0x01)` (bit 0). The raw `c0` byte SHALL be stored verbatim on the Field. The following values MUST decode correctly as validated against the fixtures in `/captures`: `c8` → unprotected, not hidden (the logon input field); `e0` → protected; `e8` → protected; `f0` → protected; `f8` → protected. Bit definitions sourced from the IBM 3270 Data Stream Programmer's Reference (verified 2026-11-15).
10. WHEN the Screen_Parser encounters an `SA(42=xx)` token (a color attribute) in a `ReadBuffer(Ascii)` line, THE Screen_Parser SHALL store the token on the `Screen` object as a `(row, col_index, value)` tuple in `Screen.sa_tokens` at its exact row and position, and SHALL NOT treat the token as a character cell and SHALL NOT store it in Field metadata; SA tokens do NOT occupy a cell (verified by counting the captures: every row in both ReadBuffer captures has exactly 80 non-SA tokens, including logon rows that carry up to 8 SA tokens); the implementation SHALL include a regression test using the logon-screen fixture from `captures/` that asserts each row has exactly 80 non-SA tokens.
11. IF the Screen_Parser encounters a `SF(c0=nn)` token where `nn` is not a valid two-digit hexadecimal value, THEN THE Screen_Parser SHALL raise a `ParseError` indicating a malformed attribute byte and SHALL NOT add a Field entry for that token.

---

### Requirement 6: Status Line Parsing

**User Story:** As a caller, I want structured access to the s3270 status line so that I can check connection state and keyboard lock without parsing raw strings.

#### Acceptance Criteria

1. THE Screen_Parser SHALL parse every s3270 status line into a `StatusLine` object with named attributes for all 12 fields: `keyboard_state`, `screen_formatting`, `field_protection`, `connection_state`, `emulator_mode`, `model_number`, `rows`, `columns`, `cursor_row`, `cursor_col`, `window_id`, `command_time`.
2. THE StatusLine.keyboard_state attribute SHALL contain the exact token string from field 1 of the status line without modification.
3. THE StatusLine.connection_state attribute SHALL contain the exact token string from field 4 of the status line without modification.
4. THE StatusLine.rows and StatusLine.columns attributes SHALL be integers parsed from fields 7 and 8 of the status line respectively, where the integer value equals the decimal numeric value of the token.
5. THE StatusLine.cursor_row and StatusLine.cursor_col attributes SHALL be integers parsed from fields 9 and 10 of the status line respectively, where the integer value equals the decimal numeric value of the zero-origin token as reported by s3270.
6. IF a status line does not contain exactly 12 blank-separated tokens, THEN THE Screen_Parser SHALL raise a `ParseError` containing the raw status line string.
7. IF any of fields 7, 8, 9, or 10 of the status line contains a token that is not a decimal integer, THEN THE Screen_Parser SHALL raise a `ParseError` containing the raw status line string and identifying the offending field by name.

---

### Requirement 7: Error Handling and Observability

**User Story:** As a caller building deterministic flows, I want every failure to produce a typed, descriptive exception so that callers can distinguish s3270 errors from timeouts from parsing failures.

#### Acceptance Criteria

1. THE Connector SHALL define a base exception class `ConnectorError` from which all library-specific exceptions inherit.
2. THE Connector SHALL raise `ConfigurationError(ConnectorError)` when a configuration value is missing, is of the wrong type, or falls outside its documented valid range, and the exception message SHALL identify the offending parameter name.
3. THE Connector SHALL raise `S3270Error(ConnectorError)` when s3270 returns a response with status `error`, and the exception SHALL carry the name of the offending action and all data lines returned by s3270 in that response.
4. IF a read or wait operation exceeds its configured deadline, THEN THE Connector SHALL raise `ConnectorTimeoutError(ConnectorError)` identifying the operation name and the deadline value that was exceeded.
5. THE Connector SHALL raise `ParseError(ConnectorError)` when the Screen_Parser cannot interpret s3270 output.
6. THE Connector SHALL raise `SessionClosedError(ConnectorError)` when any method is called on a Session that has already been closed.
7. WHEN the s3270 subprocess exits before `close()` is called on the Session, THE Connector SHALL raise `S3270Error` on the next attempted action, and the exception SHALL include the subprocess exit code.
8. THE Connector SHALL emit log messages at DEBUG level using the Python `logging` module with logger name `greenscreen.connector`, and each log record SHALL include the action name, the direction (sent or received), and the full raw s3270 response string.

---

### Requirement 8: Unit Testing with Fixtures and Fake Host

**User Story:** As a contributor, I want a test harness that never requires the live mainframe so that the test suite runs anywhere, any time.

#### Acceptance Criteria

1. THE Connector library SHALL ship a `testing` subpackage that provides a `FakeS3270` class accepting the same stdin command strings and emitting the same stdout response lines as the real s3270 subprocess, without opening a network connection.
2. THE FakeS3270 SHALL accept a sequence of scripted `(command_pattern, response_lines, status_line, ok_or_error)` tuples where `command_pattern` is a Python regular expression matched against the full incoming command string, `response_lines` is a list of zero or more data line strings, `status_line` is a single string, and `ok_or_error` is one of the literal strings `"ok"` or `"error"`; tuples SHALL be replayed in order and IF the incoming command does not match the current tuple's `command_pattern`, THEN THE FakeS3270 SHALL raise `AssertionError` indicating the expected pattern and the actual command received.
3. THE testing subpackage SHALL provide a `load_fixture(path: str) -> list[FixtureFrame]` function that reads a YAML or JSON file where each fixture frame contains exactly three fields: `data_lines` (a list of strings), `status_line` (a string), and `result` (one of the literal strings `"ok"` or `"error"`), and returns them as a list of `FixtureFrame` objects in file order.
4. THE testing subpackage SHALL ship at least two fixture files built directly from the raw capture data in `d:\greenMachine\captures`: one representing the Hercules/TK5 logo screen (using `tk5-logo.ascii.txt` for the text grid and `tk5-logo.readbuffer.txt` for field data) and one representing the MVS logon screen (using `tk5-logon.ascii.txt` and `tk5-logon.readbuffer.txt`); fixture data SHALL NOT be invented or approximated — it must reproduce the exact data lines and status lines from those files, and each fixture SHALL be loadable by `load_fixture` without error.
5. WHEN the FakeS3270 exhausts its scripted tuples and receives an additional command, THE FakeS3270 SHALL raise `AssertionError` with a message that includes the full text of the unexpected command and states that no scripted response remains.

---

### Requirement 9: Property-Based Tests

**User Story:** As a contributor, I want property-based tests that prove the Screen_Parser and Screen_Renderer are inverses of each other so that regressions in parsing or serialization are caught automatically.

#### Acceptance Criteria

1. THE test suite SHALL include a Hypothesis-based property test that generates arbitrary `Screen_Object` values and asserts that `Screen_Parser.parse(Screen_Renderer.render(screen))` produces a `Screen_Object` that compares equal to the original under `Screen_Object.__eq__` (field-by-field equality across all public attributes); `Screen_Renderer.render()` SHALL emit the `ReadBuffer(Ascii)` representation — one `data:` line per row containing two-digit hex cell codes and `SF(c0=xx)` tokens — matching the format observed in `/captures`, and the round-trip SHALL be defined on that representation.
2. THE test suite SHALL include a Hypothesis-based property test that generates arbitrary valid `ReadBuffer(Ascii)` output — using Hypothesis `strategies.integers` to generate `rows` (1–99) and `cols` (1–999), constructing exactly `rows` lines where each line is a space-separated sequence of exactly `cols` cell tokens (each token is either a two-digit hex code or an `SF(c0=xx)` token), with an accompanying generated status line consistent with Req 5.4 — and asserts that for any such input `x`, `ScreenRenderer.render(ScreenParser.parse_readbuffer(x))` equals `x` (the renderer is the left inverse of the parser on the `ReadBuffer(Ascii)` representation). This property MUST pass on the actual data in every file in `/captures`.
3. THE test suite SHALL include a Hypothesis-based property test that generates arbitrary `StatusLine`-compatible strings consisting of exactly 12 space-delimited tokens, where each token is a non-empty string of printable ASCII characters (U+0020–U+007E, excluding space), and asserts that parsing then re-serializing the `StatusLine` reproduces the original 12-token sequence with identical token values in identical order.
4. THE property tests SHALL use `hypothesis.strategies` to generate inputs and SHALL NOT require any network connection or subprocess.
5. THE property tests SHALL be runnable with `pytest` and SHALL complete in under 60 seconds on a machine with at least a dual-core CPU at 2 GHz and 4 GB RAM.
6. THE test suite SHALL include a Hypothesis-based property test that generates arbitrary printable text strings (characters U+0020–U+007E of length 0–3000) and asserts that applying the s3270 string escaping from Req 3.6 — wrapping in double quotes and backslash-escaping embedded double quotes and backslashes — produces a string that, when unescaped by the inverse operation, recovers the original text exactly.

---

### Requirement 10: Integration Tests Against Live Host

**User Story:** As a developer verifying the full end-to-end path, I want integration tests that exercise the real TK5 host so that I know the library works against the actual mainframe.

#### Acceptance Criteria

1. THE test suite SHALL include at least one integration test that reads the target host and port from the `GS_HOST` environment variable (default `192.168.68.72`) and the `GS_PORT` environment variable (default `3270`), connects to that host and port, reads the initial Hercules/TK5 logo screen, sends `Enter()` followed by `Wait(8, Output)` where 8 is in seconds, reads the resulting screen, and asserts the screen text contains `Logon ===>`.
2. WHEN the session-scoped reachability fixture attempts a TCP connection to the host and port resolved from `GS_HOST` (default `192.168.68.72`) and `GS_PORT` (default `3270`) and receives no successful connection within 5 seconds, THE integration tests SHALL skip automatically using `pytest.mark.skip` or `pytest.mark.skipif`.
3. THE integration tests SHALL be isolated in a file or directory marked with a `pytest` mark (e.g., `@pytest.mark.integration`) so they can be excluded from the default test run with `-m "not integration"`.
4. Integration tests that only connect and read the logon screen (without submitting credentials) SHALL NOT skip when `TK5_USERNAME` or `TK5_PASSWORD` are unset; only integration tests that actually submit credentials to log in SHALL skip when either `TK5_USERNAME` or `TK5_PASSWORD` is unset, with a skip message identifying which variable is missing.

---

### Requirement 11: Cross-Platform Pipe I/O with Timeout

**User Story:** As a developer running Green Screen Medium on both Windows and Linux, I want the library to read s3270 pipe output with a timeout that works on both platforms so that the same code runs correctly with ws3270 on Windows and s3270 on Linux.

#### Acceptance Criteria

1. THE Connector SHALL implement pipe reading with timeout in a way that does not use `select.select()` on subprocess pipes on Windows, as `select.select()` does not support pipes on that platform.
2. THE Connector SHALL use a background reader thread or `asyncio` with `asyncio.subprocess` to read from the s3270 stdout pipe with a deadline, so that the timeout mechanism works identically on Windows (ws3270) and Linux (s3270).
3. THE Connector SHALL detect the current platform at runtime and use the appropriate pipe-reading strategy; IF the strategy cannot be determined, THE Connector SHALL raise a `ConfigurationError` at startup.
4. THE unit tests for pipe I/O timeout SHALL run without a live s3270 process, using `FakeS3270` or a mock pipe, and SHALL cover both the case where data arrives before the deadline and the case where the deadline expires.
5. THE Connector's timeout behavior SHALL be documented in its public API as working on Windows (ws3270 v4.5+) and Linux (s3270 v4.3+), consistent with the verified facts in the steering document.
