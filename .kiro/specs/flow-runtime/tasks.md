# Implementation Plan: flow-runtime

## Overview

Implement the `greenscreen.flow` Python 3.11+ package, which loads recorded transactions (Flows) from YAML and replays them against a Session with the screen check of `greenscreen.recognizer` before every key. The order of work is:

1. Connector action redaction, the prerequisite from `tn3270-connector` Requirement 12 (tasks 1 and 2). No flow task starts before the checkpoint in task 2 passes.
2. Package skeleton and errors, data model and validator, YAML loader and serializer.
3. Test support, runner core, the three shipped flows with their package-data entry.
4. Unit tests, the eight flow-runtime property tests, the integration test, and the final checkpoint.

Every task is required, including every property test. Tests are Python with pytest and Hypothesis; the only third-party packages used are `pyyaml`, `hypothesis` and `pytest`, and no entry is added to `dependencies` or `optional-dependencies` of `pyproject.toml`. All paths are repo-relative.

Rules that apply to every task below:

- Screens come only from `captures/*.readbuffer.txt` through `load_capture_screen` and `make_screen` in `tests/screen_support.py`. No fake s3270 and no subprocess in unit or property tests (the packaging wheel test in task 10.18 is the one stated exception).
- The TK5 password appears in no file (tracked, untracked or ignored), test output or log; the stock TK5 user id appears in screen captures and in the tests and specs that quote them, by design. `TK5_USERNAME` and `TK5_PASSWORD` are read only from the environment, and only by the integration test (task 12.1).
- No capture of the screen that holds the typed password is ever written. The residual-password screen exists only in memory, built by `sentinel_password_screen` from a sentinel that occurs in no file under `captures/`.
- Each property test is exactly one `@given` test with `@settings(max_examples=100, deadline=None)` or more, and its first line is the comment `# Feature: flow-runtime, Property N: <title>` (for the connector property: `# Feature: tn3270-connector, Property 10: String text never leaves the Connector`).
- Every runner test uses the fake Clock. No test sleeps for real.
- Do not edit `.kiro/specs/tn3270-connector/tasks.md`. The redaction tasks live in this list only.

## Tasks

- [x] 1. Connector action redaction (prerequisite, tn3270-connector Requirement 12)
  - [x] 1.1 Create `greenscreen/connector/_redact.py` and update the `_unescape_s3270_string` docstring
    - Add `redact_action(action: str) -> str` exactly as in the "Action Redaction" section of `.kiro/specs/tn3270-connector/design.md`: the `_STRING_NAME` and `_WELL_FORMED` regular expressions with explicit `[Ss][Tt][Rr][Ii][Nn][Gg]` classes (no `re.IGNORECASE`), N from `len(_unescape_s3270_string(body))`, the literal `String(<? chars>)` for a malformed String_Action, and the input returned unchanged for every other Action
    - Import only `re` and `_unescape_s3270_string` from `greenscreen/connector/parser.py`; do not export the helper from `greenscreen/connector/__init__.py`
    - In `greenscreen/connector/parser.py` change only the docstring of `_unescape_s3270_string`, which now says "For testing only", so that it says the function is also used by `_redact.py` to count the Decoded_Length; no code in `parser.py` changes
    - _Requirements: tn3270-connector 12.1, 12.9, 12.10, 12.11, 12.12, 12.13, 12.14_

  - [x] 1.2 Apply `redact_action` at the seven call sites in `greenscreen/connector/connector.py`
    - In each site call `redact_action(action)` on the original Action and use the result (`shown`) as the design table says: (1) the `ValueError` for an invalid Action in `_send_with_deadline`; (2) the `ConnectorTimeoutError` message and `operation` in `_send_with_deadline`; (3) the `direction=sent` DEBUG record in `_write`, both arguments; (4) the `S3270Error` message and `action` for a rejected write in `_write`; (5) the `S3270Error` message and `action` for a subprocess exit in `_read_response`; (6) the `direction=received` DEBUG record in `_read_response`, with `element.replace(action, shown)` applied to every response element only when `shown != action`; (7) the final `S3270Error` message and `action` for an error response in `_read_response`
    - Keep the real Action text unchanged for the write to s3270 stdin, keep `Response`, `Response.data_lines`, `S3270Error.data_lines`, `status_line`, `exit_code` and `deadline` as they are, keep every non-String Action rendering character for character, and change no public signature, attribute or exception class
    - Do not change any other connector behaviour and do not edit `greenscreen/connector/_io.py`
    - _Requirements: tn3270-connector 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.14, 12.15, 12.16, 12.17, 12.18_

  - [x] 1.3 Create `tests/connector_support.py`
    - Provide `ScriptedProc`, `RecordingFake` (a `FakeS3270` subclass that records every command and stays silent when its script is exhausted) and `BrokenPipeProc` (first write succeeds, later writes raise `BrokenPipeError(32, "Broken pipe")` after recording the attempted bytes), plus a `LogCapture` handler, `collect_exception_text(exc)` (`str`, `repr`, every `args` item and every `vars(exc)` value, and the same for the `__cause__` and `__context__` chain with a visited set) and `collect_record_text(record)` (`msg`, every element of `args`, and `getMessage()`)
    - Copy `ScriptedProc` and `RecordingFake` from `tests/unit/test_connector.py`; do not edit that file or any other existing test file
    - _Requirements: tn3270-connector 12.19, 12.20, 12.25_

  - [x] 1.4 Write unit tests for `redact_action`
    - Create `tests/unit/test_redact_action.py`
    - Cover: `\"` and `\\` each count as one character; an empty body renders `String(<0 chars>)`; an unterminated body, a trailing lone backslash, two arguments, an unquoted argument and text after the closing `)` render `String(<? chars>)`; `Strings("x")`, `StringX(1)` and `Enter()` come back unchanged; every non-String Action of tn3270-connector Requirement 12.14 comes back unchanged; `\u017fTRING("x")` and a Kelvin-sign variant are not String_Actions; `string(`, `STRING(`, `sTrInG(`, `  String(` and `String (` are redacted
    - Assert every String_Action result matches `^String\(<(0|[1-9][0-9]*|\?) chars>\)$`, that `redact_action(f'String("{_escape_s3270_string(t)}")')` renders `String(<len(t) chars>)`, and that `re.fullmatch(r"\s", chr(c)) is not None` equals `chr(c).isspace()` for every code point up to `sys.maxunicode`
    - _Requirements: tn3270-connector 12.9, 12.10, 12.11, 12.12, 12.13, 12.14, 12.22_

  - [x] 1.5 Write unit tests for redaction through the Connector
    - Create `tests/unit/test_connector_redaction.py` using `tests/connector_support.py`
    - One test per place of tn3270-connector Requirement 12.19, calling `Connector.string(sentinel)` with a sentinel such as `'pw"\\x-unlikely'` extended with non-ASCII letters, asserting the sentinel is absent and `String(<len(sentinel) chars>)` is present: the DEBUG record for the sent Action, the DEBUG record for the received response (plus a variant whose scripted response line is an exact copy of the Action, where the logged line holds the Redacted_Action and `data_lines` still holds the copy), an `S3270Error` for an error response, an `S3270Error` for a broken pipe, an `S3270Error` for a subprocess exit with `exit_code == 7`, a `ConnectorTimeoutError` for a send timeout, and a `ValueError` for an Action with a newline (and a carriage return variant) with nothing written after the Connect command
    - One test per place that checks the exception through `collect_exception_text` (`str`, `repr`, `args`, `action`, `operation`, `data_lines`, `status_line`, `exit_code`, `deadline`, and the `__cause__` and `__context__` chain)
    - Parametrized tests that call `send()` directly with `string(`, `STRING(`, `sTrInG(`, `  String(` and `String (`, once with `ok` and once with `error`, asserting the Redacted_Action in the log records and in the `S3270Error` and that `RecordingFake.commands[-1]` equals the original text
    - For each of `wait_for_output`, `wait_for_field` and `wait_for_unlock`, after a `string()` call, once with an s3270 error response and once with a pipe timeout (`conn._config.default_timeout = 0.05` and `conn.WAIT_GRACE_SECONDS = 0.05` on the instance), assert the message, `action` and `operation` equal what the existing wait tests expect and the sentinel is absent
    - No example waits one second or more
    - _Requirements: tn3270-connector 12.3, 12.15, 12.16, 12.17, 12.19, 12.20, 12.21, 12.23_

  - [x] 1.6 Write property test for Property 10 (connector)
    - **Property 10: String text never leaves the Connector**
    - Create `tests/property/test_string_redaction.py`, one `@given` test starting with `# Feature: tn3270-connector, Property 10: String text never leaves the Connector`, using `@settings(max_examples=100, deadline=None)` or more
    - Draw a text of 0 to 3000 characters as a marker (8 to 16 non-ASCII printable characters from an alphabet that shares no character with any fixed text, digit, Redacted_Action word, binary path, host, `"`, `'` or `\`) followed by a body of 0 to 2984 printable ASCII (including `"` and `\`) and non-ASCII printable characters, and draw a failure mode from success, error response, timeout, subprocess exit and broken pipe
    - Run `Connector.string(text)` against `RecordingFake`, `ScriptedProc` or `BrokenPipeProc`; assert the whole text, the whole marker, every marker-alphabet character that occurs in the text and the `ascii()` escaped marker appear in no log record (`msg`, every `args` element and `getMessage()`, at every level) and in no exception raised by the Connector (`str`, `repr`, `args`, every attribute, and the `__cause__` and `__context__` chain)
    - Assert the unmodified Action text reached the fake host and that in the success mode the returned `Response` equals the scripted response; no example waits for a real deadline of one second or more and the module finishes within the 60-second budget of tn3270-connector Requirement 9.5
    - **Validates: tn3270-connector Requirements 12.24, 12.25, 12.26, 12.27, 12.28**

  - [x] 1.7 Run the one-time live check of s3270 echo for `String(...)` errors and record the result
    - Create `tests/integration/test_live_string_echo.py`, marked `@pytest.mark.integration`, using the session-scoped `host_reachable` fixture, so it is skipped unless the host is reachable; read the binary, host and port from `GS_S3270_BINARY`, `GS_HOST` and `GS_PORT` with the defaults the existing integration tests use
    - Send `String(...)` through a `Connector` with a non-secret sentinel (for example `echo-probe-7q`) in a state that makes s3270 return an `error` response, chosen by whoever runs the check and recorded; no TK5 credential is read or typed; end the session with `Disconnect()` and `Quit()` through the Connector context manager
    - Report with `record_property` whether any data line or status line of the error response contains the sentinel, the unescaped argument or the whole Action, and the exact response lines with the sentinel visible (the sentinel is not a secret); the test records a measurement and does not fail on either outcome
    - After a run with the host reachable, record the result and the state used in the connector spec documents: replace the "Open item: does s3270 echo a `String(...)` action in error responses?" text in `.kiro/specs/tn3270-connector/design.md` and the "Out of scope, s3270 output" bullet in `.kiro/specs/tn3270-connector/requirements.md` with the observed behaviour and the date; if the host is unreachable, leave both documents as they are and say so in the task log
    - Do not edit `.kiro/specs/tn3270-connector/tasks.md` and do not change connector code in this task
    - _Requirements: tn3270-connector 12.3, 12.17 (scope and open items of Requirement 12)_

- [x] 2. Checkpoint - connector redaction complete, all existing tests pass
  - Run the entire existing suite with `pytest -m "not integration"` and require that every pre-existing test passes, with no edit to any pre-existing test file. Do not hard-code a count; there were 595 existing tests at the time of writing, and the redaction tests of tasks 1.4 to 1.6 add to that number.
  - No flow task (task 3 onward) starts until this checkpoint passes.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: tn3270-connector 12.18_

- [x] 3. Create the flow package skeleton and errors
  - [x] 3.1 Create `greenscreen/flow/` with `errors.py`, `clock.py` and the `flows` data package
    - Create `greenscreen/flow/__init__.py` (empty for now), `greenscreen/flow/flows/__init__.py` (empty, so setuptools finds the directory as a package), `greenscreen/flow/errors.py` and `greenscreen/flow/clock.py`
    - In `errors.py` define `REASON_CODES` (the 13 Reason_Codes in the design order), `FlowError(Exception)` with keyword-only `step_index`, `kind`, `expected`, `summary`, `audit`, `detail` and attributes `reason`, `step_index`, `expected` (sorted tuple), `summary`, `audit`; its message is one line of at most 500 characters in the form `{reason} at step {step_index|none} ({kind|none}): expected {names|none} ({count})[; {detail}]`; `FlowInputError(FlowError)` with `reason` `input_invalid`, no step, no summary, empty audit and detail `input NAME violates RULE` (the name is shown only when it matches `[A-Za-z][A-Za-z0-9_]{0,31}`, otherwise `<invalid name>`); `FlowDefinitionError(Exception)`
    - None of the three classes derives from `ConnectorError` or `RecognizerError`; none stores a `Screen`, `Field` or input value
    - In `clock.py` define the `Clock` protocol (`monotonic`, `sleep`) and `SystemClock` over `time.monotonic` and `time.sleep`
    - Do not change `[tool.setuptools.package-data]` yet (task 8.1)
    - _Requirements: 1.7, 12.4, 14.1, 14.4, 14.5, 21.1_

- [x] 4. Implement the data model and the Flow_Validator
  - [x] 4.1 Implement `greenscreen/flow/model.py`
    - Define the frozen, slotted dataclasses `InputSpec`, `OutputSpec`, `Timeouts` (`step` 10.0, `run` 120.0, `finally_` 30.0), `ExpectStep`, `TypeStep`, `KeyStep`, `ExtractStep`, `HandleStep` (each with a `kind` class variable), `Flow` (fields `name`, `steps`, `description`, `inputs`, `outputs`, `finally_steps`, `timeouts`), `AuditRecord` and `FlowResult`
    - `Flow.__post_init__` turns lists into tuples, turns `Timeouts` numbers, Step `timeout` and `settle` into `float`, and then calls `structural_violations` from `validate.py` through a local import, raising `FlowDefinitionError` for the first violation so that no invalid `Flow` exists; assigning to or deleting a field raises `FrozenInstanceError`
    - Add `PlanItem` and `plan(flow)`: the depth-first Step_Index numbering over `steps` then `finally_steps`, with a Handle_Step taking its index before its body
    - `FlowResult.outputs` is a `types.MappingProxyType` over a dict in declaration order; override `FlowResult.__repr__` to show the flow name, the Output names and the number of audit records, never an Output value; `AuditRecord` holds names, integers and a float only
    - Add `Flow.to_yaml()` and `Flow.from_yaml(text, signatures=None)` as thin delegates to `yamlio` through local imports
    - _Requirements: 1.1, 1.2, 1.4, 1.6, 15.1, 15.2, 15.3, 15.5_

  - [x] 4.2 Implement `greenscreen/flow/validate.py` (Flow_Validator)
    - Define `Violation`, `structural_violations(flow)`, `reference_violations(flow, names)` and `check_flow(flow, signatures)` with the algorithm of the design: Flow fields and bounds (description 0 to 500, at most 20 inputs and outputs, 1 to 200 steps and 0 to 50 finally Steps counting handle bodies, Timeouts ranges 0.1 to 60, 1 to 600, 1 to 120); Inputs (name pattern, case-sensitive uniqueness, `type`, `required`, `max_length` with `type(v) is int` from 1 to 255, `regex` of 1 to 200 characters accepted by `re.compile`, `secret` only with `type: str`, description 0 to 200); Outputs (name, uniqueness, `type`, `row` 0 to 23, `col` 0 to 79, `length` 1 to 80, `col + length` at most 80); every Output named by exactly one Extract_Step, and Extract_Steps only in `steps` outside handle bodies
    - Arming rule: walk `plan(flow)` with `armed` and `arming` state; an Expect_Step arms; a Key_Step needs `armed` and clears it; a Type_Step needs `armed`; a Handle_Step body starts armed and the Handle_Step leaves nothing armed afterwards; an Extract_Step needs an arming Expect_Step whose `signatures` contain the Output signature; no nested Handle_Step at any depth; handle body holds only Type_Steps and Key_Steps (1 to 50); `max_count` 1 to 20, `settle` 0 to 10
    - Secret rules: a Secret_Input is referenced only by the `input` field of a Type_Step, and no Type_Step `text` literal contains `${`; a `text` of 1 to 255 printable ASCII characters; Type_Step has exactly one of `text` or `input`, and `input` names a declared Input
    - `reference_violations` reports every Signature_Name of an Expect_Step (`signatures`, `tolerate`), Handle_Step or Output that is not in `names`
    - Order several violations as the design says (Step violations by `(step_index, requirement, criterion)` first, then the rest by `(requirement, criterion, field)`); messages contain only the Step_Index, Step kind, field names, fixed rule text, Flow_Name, Signature_Names and Input or Output names; the validator reads no environment variable, file or Session
    - _Requirements: 1.1, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14, 5.15, 16.5_

- [x] 5. Implement YAML serialization and loading
  - [x] 5.1 Implement `greenscreen/flow/yamlio.py`
    - Implement `to_yaml(flow)`, `from_yaml(text, signatures=None)` and `load_flow(path, signatures=None)` for schema version 1 with the fixed key order of the design: `version` first (`type(v) is int and v == 1`; `true`, `"1"`, `1.0` and a missing key are rejected), then `name`, `description`, `inputs`, `outputs`, `timeouts`, `steps`, `finally`; optional keys (`regex`, `description` of an Input, `tolerate`, `timeout`, `n`) are emitted only when they differ from their default
    - Parse with `yaml.safe_load` only and emit with `yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=False, width=10_000, indent=2)` only
    - Check key sets and value types in document order and raise `FlowDefinitionError` naming the key and, for list items, the zero-origin index (for example `steps[3]: unknown key 'foo'`); report a YAML syntax error as `malformed YAML at line L, column C` from `problem_mark`; echo an unsupported Step kind only when it matches `[A-Za-z0-9_-]{1,32}`, else `<invalid>`; never include another YAML scalar in a message; use `type(v) is int` for every integer field; empty or whitespace-only text raises an error that says the document is not a mapping
    - `load_flow` raises `FlowDefinitionError` stating the file could not be read and naming the path for a missing file, a directory, a permission or I/O error, or invalid UTF-8; every `FlowDefinitionError` for a YAML or file problem is raised after the `except` block ends, so `__cause__` and `__context__` are `None`
    - `from_yaml` and `load_flow` run `check_flow` against the given Signatures (default `load_bundled_signatures()`); the loader reads no environment variable
    - _Requirements: 1.3, 1.5, 5.1, 5.13, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 16.5, 21.7_

- [x] 6. Build the flow test support
  - [x] 6.1 Create `tests/flow_support.py`
    - Define `FakeClock` (starts at 0.0, `sleep(s)` adds exactly `s` and returns at once, records `sleeps`), `ScriptedState` (`screen`, `stale_reads` 0 to 10, `repaints`) and `ScriptedSession` implementing `read_screen`, `string`, `enter`, `clear`, `pf`, `pa` and `close`, recording every call in order as `("read",)`, `("string", text)`, `("enter",)`, `("clear",)`, `("pf", n)`, `("pa", n)`, `("close",)`
    - A key call advances to the next state and stays on the last one without error; for the first `stale_reads` reads after a key the previous state's Screen is served, then each repaint once, then the state's own Screen; `read_screen` returns a copy; `echo_typing=True` makes `string` write the text into the cursor field of the served screen
    - Screens come only from `load_capture_screen` (cached at import) or `make_screen`; no subprocess and no fake s3270
    - Helpers: `typed_screen(screen, text, *, mdt=False, cursor="inside" | "outside")`, `pause_variant(i)` (distinct `tso-pause` screens), `partial_repaint(name, i)` (cell changes that keep the recognized name, found once at import by scanning cells and calling `recognize`), `blank_screen()`, `sentinel_password_screen(sentinel)` (a copy of `tso-password-prompt` whose hidden cells hold a sentinel of 1 to 8 characters; assert at import that the sentinel is absent from every file under `captures/`), and `live_connector_config()` repeating the binary and host lookup of the existing integration tests (`GS_S3270_BINARY`, `GS_HOST`, `GS_PORT`, same defaults) without editing those tests
    - Never write a screen to `captures/` or to any file
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.10, 20.4_

  - [x] 6.2 Create `tests/property/_flow_strategies.py`
    - Provide `flows()` (valid Flows of all five Step kinds, Inputs with every option, Outputs, with an Expect_Step inserted before every key by construction), `chain_scripts()` (a chain of 2 to 6 capture names with adjacent names different, an optional typed literal per screen, the matching Flow, and per-state stale reads, partial repaints and blank screens), `handle_counts()` (N from 1 to 20, k from 0 to 20, forever), `typed_cases()` (capture name, printable ASCII text, MDT flag, with the length bounds of Property 8) and `secrets()` (1 to 8 characters from an alphabet used in no other generated text)
    - Strategies draw small integers and indexes into cached Screens, not Screens, so the Hypothesis health checks stay quiet; the shared module is imported by every `tests/property/test_flow_*.py`
    - _Requirements: 19.10, 19.11_

  - [x] 6.3 Write self-tests for `ScriptedSession` and `FakeClock`
    - Create `tests/unit/test_flow_support.py`
    - Assert the call log order, key advance and staying on the last state, the stale-read rule (previous Screen for N reads, own Screen from read N+1), repaints served once each, read copies, the fake Clock (starts at 0.0, advances by exactly the slept seconds, never waits), `sentinel_password_screen` (sentinel in the hidden cells, absent from every `captures/` file) and that no helper writes a file
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.10_

- [x] 7. Implement the runner core
  - [x] 7.1 Implement `greenscreen/flow/inputs.py`
    - Implement `PreparedInputs` and `prepare_inputs(flow, supplied)`: for each declared Input in declaration order check missing (when required), `type(v) is str` or `type(v) is int` (a `bool` is not an `int`), rendered length (`str()` for an `int`), printable ASCII U+0020 to U+007E, and `re.fullmatch` of `regex`; then check supplied names that no Input declares, in sorted order; the first failure raises `FlowInputError` naming the Input and the rule
    - The result holds the rendered values of supplied non-secret Inputs and only the names of supplied Secret_Inputs; no error message or attribute contains any supplied value
    - _Requirements: 2.6, 2.7, 2.8, 2.9, 10.8, 16.1_

  - [x] 7.2 Implement `greenscreen/flow/screens.py`
    - The only module of the package that reads `Screen.cell_grid`; it never reads `Screen.text_grid`, `Screen.fields`, `Screen.find_field` or `Field.text`
    - Implement `geometry(screen)` (size and the start positions of `SFToken` cells with `c0 & ~0x01`, so the MDT bit is cleared on both sides and the protected bit `0x20` is not masked), `build_comparison(pre, current, typed)` (copy the row lists of the Pre_Key_Screen, restore the data cells of every Typed_Field `(start_row, start_col, byte_length)` from the Current_Screen with the same wrap arithmetic as `Screen._build_field`, keep the Pre_Key_Screen cursor), `read_region(screen, view, row, col, length)` (returns `None` when any cell is hidden; an `SFToken` and `0x00` are spaces) and `same_screen(a, b)` (cells, `sa_tokens` and cursor)
    - _Requirements: 8.9, 8.10, 8.12, 8.19, 10.7, 11.4, 16.3_

  - [x] 7.3 Implement the `run_flow` entry, run state, Session access and polling in `greenscreen/flow/runner.py`
    - Define the `Session` protocol, `_RunState` (Current_Screen as `_Accepted`, Pre_Key_Screen, Pre_Key_Name, Typed_Fields, audit list, phase start), `_Failure` and `_Halt`, and `run_flow(flow, session, inputs, *, signatures=None, clock=None, poll_interval=0.1)`; a `poll_interval` outside 0.01 to 1 raises `ValueError` before any Session call; resolve the Flow_Signatures (the bundled or given Signatures whose names the Flow references; a missing name raises `FlowDefinitionError`), call `prepare_inputs` before the first Session call, and never call `session.close`
    - Session access through `_read`, `_string` and `_key`, each of which first runs `_budget()` (halts with `run_timeout` before the call) and converts `ConnectorError` and `OSError` to a `session_error` failure holding only the exception class name; time is read and slept only through the Clock; no network, subprocess or file I/O of its own
    - Implement polling and the Expect_Step as in the design: at least one attempt, `recognize` once per attempt against the Flow_Signatures, sleep `poll_interval` between attempts, accept a name in `signatures`, tolerate `tolerate`, the Pre_Key_Name (only while a key was sent and no screen accepted since, never added to `expected`) and unknown screens until the Step timeout, treat a screen equal to the Pre_Key_Screen in cells and cursor as "no answer yet", halt at once with `ambiguous_screen` or `unexpected_screen` (the first Expect_Step applies no implicit tolerance), halt with `unknown_screen` or `timeout` after the Step timeout as the design table says, and turn `SignatureError` and `TypeError` from `recognize` into a `FlowDefinitionError` without sending a key; `accept` clears the Pre_Key_Screen, Pre_Key_Name and Typed_Fields
    - Build the Redacted_Summary only with `greenscreen.recognizer.summary.build_summary(ScreenView(screen))` or the summary carried by `UnknownScreenError`; the single `greenscreen.flow` logger writes only the four DEBUG record shapes of the design; `FlowError` is built from a returned `_Failure` and raised with `from None` outside any `except` block after `release()` has dropped every Screen
    - _Requirements: 2.6, 7.1, 7.2, 7.3, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.12, 8.13, 8.15, 8.16, 8.20, 8.21, 12.1, 12.2, 12.4, 12.5, 14.1, 14.2, 14.6, 14.7, 16.2, 16.3, 16.4_

  - [x] 7.4 Implement the Type_Step and the Key_Step with the pre-key check
    - Type_Step: skip an optional Input that was not supplied (record `skipped`, no Session call); find the cursor field with `ScreenView.containing_field` on the Current_Screen cursor, `bad_target` when it is missing or protected, `secret_target` for a Secret_Input into a field that is not hidden, never read the text of a hidden field; call `session.string` exactly once with the literal, the rendered non-secret value or the Secret_Value; add `(start_row, start_col, byte_length)` to the Typed_Fields; hold the Secret_Value only in a local of `_type_secret` that is deleted in a `finally` block, and convert any `Exception` raised by the Session in a secret Type_Step to `session_error` with the class name only
    - Key_Step: call `read_screen` exactly once for the Pre_Key_Screen; compare `geometry` with the Current_Screen (a difference raises `unexpected_screen` without calling `recognize`); otherwise build the Comparison_Screen, call `recognize`, delete the Comparison_Screen on every path, raise `unknown_screen`, `ambiguous_screen` or `unexpected_screen` with the Redacted_Summary of the Pre_Key_Screen as read when the result is not the Current_Screen name, and only then send exactly one of `enter()`, `clear()`, `pf(n)`, `pa(n)`; then store the Pre_Key_Screen and Pre_Key_Name, clear the Current_Screen and the Typed_Fields; send no key while the Current_Screen is absent
    - _Requirements: 7.4, 7.5, 8.9, 8.10, 8.11, 8.14, 8.15, 8.17, 8.18, 8.19, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 16.7_

  - [x] 7.5 Implement the Extract_Step and the Handle_Step
    - Extract_Step on the Current_Screen without calling `read_screen`, in this order: the Current_Screen name must equal the Output `signature` (`unexpected_screen`, no cell read); the screen must be at least 24 by 80 (`screen_size`); no cell of the region may be hidden (`hidden_output`, no cell read); read the cells and remove leading and trailing U+0020; return `str` text as is (empty string allowed) and convert `int` text with `int()` only when it matches `[0-9]{1,18}` (`output_type`, the text never put in the error); the result has exactly one entry per declared Output
    - Handle_Step: reuse the Current_Screen when present, else poll with every name accepted; apply the `settle` rule (read and recognize every `poll_interval` on the Clock for up to `settle` seconds, continue on unknown, stop early when the name changes); run the body Steps with the normal executors and the pre-key check, with audit `iteration` starting at 1; after each body obtain the next recognized screen with a restarted Step timeout, treating a screen identical to the Pre_Key_Screen as "no answer yet"; end `ok` with the iteration count when the name differs; halt with `loop_limit` when the handled screen is still shown after `max_count` iterations; run at most `max_count` body iterations
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 11.1, 11.2, 11.3, 11.4, 12.6_

  - [x] 7.6 Implement the finally phase, audit trail and result in `greenscreen/flow/runner.py`
    - One `AuditRecord` per Step that begins (`step_index`, `kind`, `phase`, `iteration`, `signature`, `status` of `ok`, `skipped` or `failed`, and `duration_seconds` from the Clock; `0.0` for a skipped Step); a failed Step is recorded `failed` and no record is created for a later Step
    - Finally phase with its own budget (`timeouts.finally_`, exceeding it halts with `run_timeout`): run the Finally_Steps after a successful main phase and after a failure that leaves a Current_Screen recognized as a known name, with the same rules as the main Steps; skip all of them (zero keys, a `skipped` record for every Step_Index of the flattened finally plan including handle bodies) after `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error` or `input_invalid` or when no Current_Screen is held; a failing Finally_Step ends the phase and every later one is `skipped`; the main FlowError wins over a Finally failure, a Finally failure after a successful main phase is raised, and nothing returns or raises before every Finally_Step has a recorded status
    - Return a `FlowResult` with the Flow_Name, the Output values and the audit trail; the audit trail and `FlowError.audit` hold the records of all Steps that began, in execution order; the error path drops `state`, `inputs` and `prepared` before any `FlowError` is built
    - _Requirements: 12.2, 12.3, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 14.1, 14.2, 14.3, 14.6, 14.7, 14.8, 15.1, 15.2, 15.4, 15.6, 16.1, 16.8_

- [x] 8. Ship the three flows and wire the public API
  - [x] 8.1 Create the bundled flows, `bundled.py` and the package-data entry
    - Create `greenscreen/flow/flows/tk5-logon.yaml`, `tk5-logoff.yaml` and `tk5-system-info.yaml` as written in the design, in the exact text `to_yaml()` emits (block style); `tk5-system-info` repeats the 10 Steps of `tk5-logon`, then the four Extract_Steps in the order `USERID`, `TERMINAL`, `RELEASE`, `SYSTEMID`, then the 7 Steps of `tk5-logoff`, and declares the three Finally_Steps of Requirement 17.15; Output regions: `USERID` row 2 col 71 length 8, `TERMINAL` row 4, `RELEASE` row 10, `SYSTEMID` row 12, all col 71 length 8, `str`, from `ispf-primary-menu`
    - No literal userid or password and no `${` in any file; credentials are referenced only through the Inputs `userid` and `password`
    - Create `greenscreen/flow/bundled.py` with `load_bundled_flows(signatures=None) -> dict[str, Flow]` that reads the three files in fixed order through `importlib.resources.files("greenscreen.flow.flows")`, checks each Flow_Name against the file name, raises `FlowDefinitionError` naming the file for a missing, unreadable, unparsable or invalid file, returns no partial dict and keeps no module-level cache
    - Add `"greenscreen.flow.flows" = ["*.yaml"]` under `[tool.setuptools.package-data]` in `pyproject.toml` and change nothing under `dependencies` or `optional-dependencies`
    - _Requirements: 1.5, 16.6, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 17.11, 17.12, 17.13, 17.15, 17.18, 17.19, 21.2, 21.3, 21.4_

  - [x] 8.2 Populate `greenscreen/flow/__init__.py`
    - Export exactly nine names in `__all__`: `Flow`, `load_flow`, `load_bundled_flows`, `run_flow`, `FlowResult`, `AuditRecord`, `FlowError`, `FlowInputError`, `FlowDefinitionError`
    - Do not export the Session protocol, the Clock or the validator
    - _Requirements: 21.1_

- [x] 9. Checkpoint - package, runner and shipped flows complete
  - Run `pytest tests/unit -k "flow"` and the full `pytest -m "not integration" tests/unit`, and confirm that every task of groups 3 to 8 behaves as described and no pre-existing test fails.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Connector response-data redaction (checkpoint-9 review, group A, tn3270-connector Requirement 12 criteria 29 to 45 and 7.8)
  - [x] 14.1 Redact response data in `greenscreen/connector/connector.py` and test `_status_for_log`
    - In `_read_response` replace the received DEBUG record by `logger.debug("direction=received action=%s lines=%d status=%s result=%s", shown, len(data_lines), _status_for_log(status_raw), line)` where `line` is `ok` or `error`; log no response line and delete the `element.replace(action, shown)` step, as in the "Received record and status-line guard" section of `.kiro/specs/tn3270-connector/design.md`
    - Add the module-level `_status_for_log(line)` of that design: it returns the parsed status text only when the line has the exact 12-token shape the design describes and otherwise `<unparsed status, N chars>` with `N == len(line)`, copying no character of an unexpected line
    - In `_wait` stop copying `" ".join(exc.data_lines)` into messages: the text is used only to classify the error, and the re-raised `S3270Error` and the `ConnectorTimeoutError` messages carry no response text (`s3270 returned error for {shown!r}`, `Wait(Output) timed out after Ns`); `data_lines` stays on `S3270Error` and on the chained `__cause__`
    - In the `ParseError` path for an unrecognised ReadBuffer token use the message `Unrecognised ReadBuffer token at row R, index I, length L` and `raw=""`; edit `greenscreen/connector/parser.py` only for that message and `raw`
    - Keep `Response.data_lines`, `S3270Error.data_lines`, `status_line`, `exit_code`, `deadline`, every public signature and every String_Action redaction of group 1 unchanged
    - Create `tests/unit/test_status_for_log.py`: a parsed status passes through; 11 tokens, 13 tokens, 12 tokens with field 7 `ab`, field 9 `-1`, the empty line and a long line each give `<unparsed status, N chars>` with the exact N and none of the line's characters in the result
    - _Requirements: tn3270-connector 7.8, 12.29, 12.30, 12.31, 12.32, 12.33, 12.34, 12.35, 12.36, 12.37, 12.38, 12.39_

  - [x] 14.2 Extend `tests/connector_support.py` with the hidden-cell helpers and test them
    - Add `hidden_runs(screen)`, `forms_of_run(run)` and `forbidden_forms(screen)` as in "Hidden-cell helpers" of the connector design: `hidden_runs` finds the Hidden_Cells with its own linear scan of `Screen.cell_grid` (an `SFToken` with `(c0 & 0x0C) == 0x0C` starts a hidden run), independent of `Screen.fields` and `Field.hidden`; `forms_of_run` returns the Plain_Form and the four Hex_Forms (lowercase and uppercase, each with and without a space between bytes) of a run of 4 or more bytes; `forbidden_forms(screen)` returns the forms of every whole run and of every run of 4 or more bytes within one row
    - Change `collect_exception_text(exc, exclude_attrs=frozenset())` so that a name in `exclude_attrs` (for example `data_lines`) is skipped in `vars(exc)` at every level of the `__cause__` and `__context__` chain; the default keeps every existing caller unchanged
    - Create `tests/unit/test_connector_support_helpers.py`: runs found on a screen with two hidden fields, a hidden run shorter than 4 bytes yields no forms, the five forms of `b"s3Cr3t!x"` are spelled out literally in the test, `exclude_attrs` skips `data_lines` on the exception and on its `__cause__`, and the default still returns it
    - Add no edit to any existing test file
    - _Requirements: tn3270-connector 12.19, 12.40, 12.41, 12.42, 12.43_

  - [x] 14.3 Update the five existing tests (the only allowed edit of pre-existing test files in this group)
    - Edit exactly these five tests and no other pre-existing test, with the old and new assertions of "Existing tests that change" in `.kiro/specs/tn3270-connector/design.md`:
      - `tests/unit/test_connector.py::test_wait_other_error_raises_s3270error_with_text`, renamed `test_wait_other_error_raises_s3270error_without_response_text`: replace `assert "Not connected" in str(ei.value)` by `assert str(ei.value) == "s3270 returned error for 'Wait(5,Output)'"`, `assert "Not connected" not in str(ei.value) and "Not connected" not in repr(ei.value)`, `assert ei.value.data_lines == ["Not connected"]` and `assert ei.value.action == "Wait(5,Output)"`
      - `tests/unit/test_connector_redaction.py::test_wait_error_response_after_string_is_unchanged`, renamed `test_wait_error_response_after_string_has_no_response_text`: replace `assert str(exc) == f"s3270 returned error for {wait!r}: Not connected"` by `assert str(exc) == f"s3270 returned error for {wait!r}"` and add `assert "Not connected" not in str(exc) and "Not connected" not in repr(exc)`; keep `exc.action == wait`, `exc.data_lines == ["Not connected"]` and the leak checks
      - `tests/unit/test_connector_redaction.py::test_received_record_replaces_echo_of_action_but_data_lines_keep_it`, renamed `test_received_record_has_no_response_line_but_data_lines_keep_echo`: keep the `Response.data_lines` assertion, assert `rec.args == ("String(<N chars>)", 1, STATUS, "ok")` for the one `direction=received` record and `echo_line not in text` for every string of `collect_record_text` of every record
      - `tests/unit/test_parser.py::test_readbuffer_bad_token_raises`: replace `assert exc.value.raw == bad` by `assert exc.value.raw == ""` and `assert str(exc.value) == f"Unrecognised ReadBuffer token at row 0, index 1, length {len(bad)}"`
      - `tests/property/test_string_redaction.py`, `_FIXED_STRINGS`: replace the element `"direction=received action=%s raw=%s"` by `"direction=received action=%s lines=%d status=%s result=%s"` and keep `"direction=sent action=%s raw=%s"`; the import-time precondition loop of that module must still pass
    - No other pre-existing test file or test function changes; `tests/unit/test_connector.py::test_debug_logging_records_sent_and_received` and `tests/integration/test_live_wait_format.py` must pass unchanged
    - Verify with `pytest tests/unit/test_connector.py tests/unit/test_connector_redaction.py tests/unit/test_parser.py tests/property/test_string_redaction.py`
    - _Requirements: tn3270-connector 12.18, 12.30, 12.34, 12.35_

  - [x] 14.4 Write unit tests for criteria 29 to 39 and 40 to 41 in `tests/unit/test_connector_redaction.py`
    - Append new tests to the file (after the edits of task 14.3), using `RecordingFake`, `ScriptedProc` and `LogCapture` at `DEBUG` on the `greenscreen.connector` logger with the logger level restored afterwards, and the table "Unit tests for criteria 29 to 41" of the connector design: Received_Record shape for `ok` (`args == ("Enter()", 2, STATUS, "ok")`, `getMessage()` exact text) and for `error`; a data line equal to the String_Action text (`args[0] == "String(<N chars>)"`, `Response.data_lines` keeps the line); an unparseable status line `Keyboard locked` (`<unparsed status, 15 chars>`, then `ParseError`); the parametrized status guard variants through the Connector; `_wait` error with `Not connected` and `_wait` timeout response with `Timed out waiting` (messages, `operation`, `deadline`, `data_lines` kept on the exception and on `__cause__`); a ReadBuffer token `["41 zz 42"]` through `read_screen()` and through the parser (`raw == ""`, `zz` absent); a whole-session record scan of `open()`, `string()`, `enter()`, `read_screen()` with a hidden field, `wait_for_text` and `close()`; the exception chain check
    - Hidden-cell tests of criteria 40 and 41: use `ScreenRenderer` to render a screen with one hidden field holding the known bytes `b"s3Cr3t!x"`, script it as the `ReadBuffer(Ascii)` response of `FakeS3270`, and cover the plain form, the hex form in lowercase and uppercase, each with and without spaces between bytes (name all five forms literally in the test next to `forbidden_forms(screen)`); for `ok` assert the returned `Screen` equals the rendered one and no record holds any form; for `error` assert `S3270Error` with `collect_exception_text(exc, exclude_attrs={"data_lines"})` and the same for `__cause__` and `__context__` free of every form, `exc.data_lines == scripted lines`, and no record holds a form
    - No new test waits one second or more (use `conn._config.default_timeout = 0.05` and `conn.WAIT_GRACE_SECONDS = 0.05` where a timeout is needed)
    - _Requirements: tn3270-connector 12.29, 12.30, 12.31, 12.32, 12.33, 12.34, 12.35, 12.36, 12.37, 12.38, 12.39, 12.40, 12.41, 12.45_

  - [x] 14.5 Write property test for Property 11 in `tests/property/test_response_redaction.py`
    - **Property 11: Hidden cell data never leaves the Connector**
    - One required `@given` test whose first line is `# Feature: tn3270-connector, Property 11: Hidden cell data never leaves the Connector`, with `@settings(max_examples=100, deadline=None)` or more; draw a `Screen` with generated field layouts that include at least one hidden field (`c0` with `(c0 & 0x0C) == 0x0C`) holding 4 to 32 Hidden_Bytes, and a mode from `ok` and `error`; render it with `ScreenRenderer`, script it as the `ReadBuffer(Ascii)` response of a `RecordingFake` and call `read_screen()` once
    - Assert that `forbidden_forms(screen)` (the Plain_Form and four Hex_Forms of every whole Hidden_Bytes run and of every run of 4 or more bytes within one row) occurs in no log record (`msg`, every element of `args`, `getMessage()`, at every level) and in no `str()`, `repr()` or `args` element of the exception raised by `read_screen()` and its `__cause__` and `__context__` chain (`collect_exception_text(exc, exclude_attrs={"data_lines"})`); in `ok` mode the returned `Screen` equals the drawn one, in `error` mode `S3270Error.data_lines` equals the scripted lines
    - Discard with `hypothesis.assume` every drawn value whose Plain_Form or any Hex_Form occurs in the fixed text of the run's logs and exceptions (format strings, Redacted_Action, action names, status line, binary path, host, exception messages), so a coincidental match cannot fail the test
    - The module finishes within the 60-second budget of tn3270-connector Requirement 9.5
    - **Validates: tn3270-connector Requirements 12.38, 12.42, 12.43**

  - [x] 14.6 Write the live logon redaction test and the flow integration assertion text
    - Create `tests/integration/test_live_logon_redaction.py`, marked `@pytest.mark.integration`, using the session-scoped `host_reachable` fixture; read `TK5_USERNAME` and `TK5_PASSWORD` from the environment only; skip with a message naming each unset or empty variable, skip when the host is unreachable, and skip with `password too short for a meaningful absence check` when the password has fewer than 4 characters
    - Attach `LogCapture(logging.DEBUG)` to the `greenscreen.connector` logger and set its level to `DEBUG`, removing both in a `finally`; run the full logon of the steering document through the Connector (`wait_for_text("Logon ===>")`, `string(user)`, `enter()`, `wait_for_text("ENTER CURRENT PASSWORD")`, `string(password)`, `enter()`, the two `***` pauses, `ISPF Primary Option Menu`, `X`, `READY`, `LOGOFF`) inside `try/except BaseException`, add the exception texts to the haystack, run the absence checks, then re-raise
    - Assert that for `pw` in the password, its upper-case and lower-case forms, the Plain_Form and the four Hex_Forms from `forms_of_run(list(pw.encode("ascii")))` occur in no record text and no exception text; assertion messages name the form index and record index only and never print the password
    - Record the flow side of the same check in the existing integration task: task 12.1 gets the extra assertion bullet of Requirement 20.9 and 20.10 (see task 12.1; this task changes no other part of that task)
    - No credential appears in the file and no screen holding the typed password is captured or written
    - _Requirements: tn3270-connector 12.44, 12.45, 10.4; flow-runtime 20.9, 20.10_

- [x] 15. Checkpoint - connector response redaction complete
  - Run the whole suite with `pytest -m "not integration"` and require that every test passes, with the five edits of task 14.3 as the only changes to pre-existing test files
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: tn3270-connector 12.18, 12.45_

- [x] 16. Runner fixes in `greenscreen/flow/runner.py` (checkpoint-9 review, group B)
  - [x] 16.1 Record skipped body Steps of unmatched Handle_Steps
    - For every Unmatched_Handle in `steps` or `finally`, append exactly one `skipped` AuditRecord per Body_Step (`duration_seconds` 0.0, `iteration` None, `signature` None) immediately after the Handle_Step's own record (`ok`), in depth-first order, on a returning run, a `FlowError` run and a `FlowDefinitionError` run; append none for a Body_Step that ran (k at least 1, one record per iteration) and none after `loop_limit`; a Handle_Step that fails inside a body iteration in `finally` gets `skipped` records only for Body_Steps with no record; add no duplicate for a Step that `_skip_finally` already recorded
    - Create `tests/unit/test_flow_runner_fixes_skipped.py`: an Unmatched_Handle in `steps` and one in `finally`, each on a returning and on a failing run; the k at least 1 case; the `loop_limit` case; the `_skip_finally` case with no duplicate `(step_index, iteration)` pair; the real `tk5-logon` and `tk5-system-info` bundled Flows run on a `ScriptedSession` built from the captures with the logo and pause Handle_Steps unmatched, asserting `skipped` records for Step_Index 1 and 3 and for every Step_Index of the finally plan as `plan(flow)` numbers them
    - _Requirements: 13.10, 13.11, 13.12, 13.13, 13.14, 15.7, 14.8, 18.21_

  - [x] 16.2 Convert every `Exception` of a Session call to `session_error`
    - Wrap `_read`, `_string` and `_key` so that any `Exception` that is not a `FlowError` becomes a `_Failure` holding only `type(exc).__name__`; stop executing Steps, call `release()` first, then raise `FlowError` with reason `session_error`, `from None`, outside any `except` block; let a `FlowError` pass through unchanged; let a `BaseException` that is not an `Exception` (`KeyboardInterrupt`, `SystemExit`) propagate as the same object after the Run_State is released, with no key sent afterwards and no Finally_Step run
    - Create `tests/unit/test_flow_runner_fixes_session_error.py`: for each of `read_screen`, `string` (a secret Type_Step), `enter`, `clear`, `pf` and `pa` a `ScriptedSession` raises `RuntimeError(sentinel)` with the sentinel in the message and in `args`; assert reason `session_error`, the Step_Index, a message holding the class name `RuntimeError` and no other exception text, `__cause__` and `__context__` `None`, the sentinel absent from `str`, `repr`, `args` and every attribute, from `"".join(traceback.format_exception(err))` with chain, and from the locals of every traceback frame of module `greenscreen.flow` (no local is a `Screen`, a `Field`, the inputs mapping or a string or container holding the sentinel; build the verdict as a boolean list so a failure cannot print the sentinel); a `FlowError` raised by a Session double passes through unchanged; a `KeyboardInterrupt` test asserts identity of the exception, zero keys afterwards, no Finally_Step, and no Screen or inputs mapping in `greenscreen.flow` frames
    - _Requirements: 7.6, 7.7, 7.8, 7.9, 14.9, 14.10, 16.9, 18.17, 18.18, 18.19_

  - [x] 16.3 Return outputs in declaration order
    - Build `FlowResult.outputs` from `flow.outputs` in declaration order (not Extract_Step execution order) over the `MappingProxyType` of a dict with one entry per Output
    - Create `tests/unit/test_flow_runner_fixes_outputs_order.py`: a generated Flow whose Extract_Steps run in an order different from the declaration order returns `list(result.outputs)` equal to the declaration order with the right values; the bundled `tk5-system-info` run on captures returns `list(result.outputs) == ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]` as Requirement 17.20 fixes (report in the task log if the shipped file declares another order, and fix the shipped file only through its own task, not here)
    - _Requirements: 3.10, 15.8, 17.20, 18.20_

  - [x] 16.4 Make the Extract_Step mismatch carry `expected` and the Redacted_Summary
    - When the Current_Screen name differs from the Output `signature`, raise `unexpected_screen` with `step_index` of the Extract_Step, `expected == (output.signature,)` and `summary` the Redacted_Summary of the Current_Screen (`None` when no Current_Screen exists), without reading any cell of the Output region
    - Create `tests/unit/test_flow_runner_fixes_extract_mismatch.py`: spy on `greenscreen.flow.screens.read_region` (monkeypatch with a counting wrapper) and assert zero calls on the mismatch path, one call on the matching path; assert `step_index`, `expected`, a non-empty `summary` and the absent-Current_Screen case giving `summary is None`
    - _Requirements: 11.3, 14.11, 18.23_

  - [x] 16.5 Skip Finally_Steps after a definition error and locate the typing target through `containing_field`
    - After a `FlowDefinitionError` raised during the run, run no Finally_Step, send zero keys in the Finally phase and record every Finally_Step Step_Index as `skipped`; the Type_Step finds its target with `ScreenView.containing_field` on the Current_Screen cursor
    - Create `tests/unit/test_flow_runner_fixes_definition.py`: a Flow whose Expect_Step names a Signature that `recognize` reports through `SignatureError` raises `FlowDefinitionError`, no key is sent in the Finally phase and every Step_Index of the finally plan has a `skipped` record
    - Create `tests/unit/test_flow_runner_fixes_containing_field.py`: wrap `ScreenView.containing_field` with a recording spy and assert a Type_Step calls it with the Current_Screen cursor row and column; assert that `Field.text` of a hidden field is never read (spy on the property); for every capture in `captures/` that holds no password, compare `containing_field` with `Screen.find_field` used only as the test-side oracle for start position, length, `protected` and `hidden`
    - _Requirements: 10.1, 10.7, 13.3, 18.22, 18.24_

- [x] 17. Check that requirements, design and code agree (checkpoint-9 review, group C)
  - [x] 17.1 Write a short consistency test for the review items
    - Create `tests/unit/test_flow_spec_consistency.py` with one grep-style check per item, reading `.kiro/specs/flow-runtime/requirements.md`, `.kiro/specs/flow-runtime/design.md`, `.kiro/specs/tn3270-connector/requirements.md`, `.kiro/specs/tn3270-connector/design.md` and the source files as text:
      - Requirement 10.1 wording: the criterion says the Type_Step finds the target with `ScreenView.containing_field` on the Current_Screen cursor, the same call exists in `greenscreen/flow/runner.py`, and `runner.py` and `screens.py` hold no `find_field`
      - Requirement 13.3 `definition`: the criterion lists the FlowDefinitionError during the run among the reasons that skip every Finally_Step, and the design says the same, and the runner code path of task 16.5 exists
      - tn3270-connector 7.8 and 12.34 to 12.37: 7.8 states the received DEBUG record has the format of Requirement 12 and carries no response data lines; 12.34 to 12.37 forbid response text in exception messages; `connector.py` holds no `" ".join(exc.data_lines)` in a message
      - Requirement 13.10 to 13.14 and 14.9 to 14.11 appear in the design and in the tests of tasks 16.1, 16.2 and 16.4 (a test file for each exists)
    - The test reads files only, uses no network and no subprocess, and fails with a message that names the file and the missing item
    - _Requirements: 10.1, 13.3, 13.10, 14.9, tn3270-connector 7.8, 12.34, 12.35, 12.36, 12.37_

- [x] 18. Trim the `flows()` strategy (checkpoint-9 review, group D)
  - [x] 18.1 Trim `flows()` in `tests/property/_flow_strategies.py`
    - Before the change measure and note the time of 100 `flows()` draws and of 100 draws with the YAML round trip (`Flow.from_yaml(flow.to_yaml(), signatures)`), best of three, with `time.perf_counter`
    - Implement "Trimmed `flows()`" of `.kiro/specs/flow-runtime/design.md`: bounds of at most 6 top-level `steps`, 2 Inputs, 2 Outputs, handle bodies of 1 to 2 Steps and 2 `finally` Steps; module-level pools built once at import (`FLOW_NAMES`, `TEXT_POOL`, `INPUT_POOL` and `INPUT_SETS`, `OUTPUT_POOL` and `OUTPUT_SETS`, `EXPECT_SHAPES` and `EXPECT_FOR`, `KEYS`, `HANDLE_BODIES`, `TIMEOUT_SETS`); `flows()` is a single `PARTS.map(build_from_parts)` draw with no `@st.composite` and no `draw` calls; `build_from_parts(parts, *, unarm=None)` is pure, never drops an Output block and builds the `Flow` once; cached Screens through `functools.lru_cache` prototypes in `tests/flow_support.py` helpers; no regex, `re.compile`, `Timeouts` or `InputSpec` construction and no recognizer call inside a strategy
    - Keep `chain_scripts()`, `handle_counts()`, `typed_cases()` and `secrets()` behaviour and ranges; keep the `unarm` keyword for `tests/property/test_flow_arming.py`; no edit to any other file except where a helper cache is added to `tests/flow_support.py`
    - After the change measure again and record before and after timings in the task completion notes
    - _Requirements: 19.8, 19.9, 19.10, 19.11_

  - [x] 18.2 Write `tests/unit/test_flow_strategy_cost.py` and register the `perf` marker
    - `pyproject.toml` already registers `integration` under `[tool.pytest.ini_options] markers`, so add one entry `"perf: timing assertion that a slow machine can deselect with -m 'not perf'"` to that list; this is not a dependency change and `dependencies` and `optional-dependencies` stay as they are
    - An unmarked test draws examples with `@settings(max_examples=100, deadline=None, database=None, derandomize=True)` and asserts every drawn Flow has at most 6 top-level Steps, at most 2 Inputs, at most 2 Outputs and handle bodies of 1 to 2 Steps; an unmarked test asserts 300 draws are valid `Flow` objects (they pass `check_flow` against the bundled Signatures) and that `Flow.from_yaml(flow.to_yaml(), signatures) == flow` for each
    - A test marked `@pytest.mark.perf` times 100 draws including the round trip with `time.perf_counter`, takes the best of three runs and asserts the best is under 1.5 s
    - Record the measured before and after timings of task 18.1 in the docstring of the module
    - _Requirements: 19.8, 19.9, 19.10, 19.11_

- [x] 19. Re-run of checkpoint 9 (checkpoint-9 review, group E)
  - [x] 19.1 Run the checkpoint-9 checks and report counts
    - Run `pytest -m "not integration"` and `pytest tests/unit -k flow` and require zero failures; report the number of tests passed, failed, skipped and deselected for each command
    - Run the checks that task 9 lists: every task of groups 3 to 8 behaves as described and no pre-existing test fails; the only edits of pre-existing test files are the five of task 14.3
    - Confirm `pyproject.toml` `dependencies` and `optional-dependencies` are unchanged and that the TK5 password is absent everywhere (every tracked, untracked and ignored file, test output and logs); the stock TK5 user id appears in screen captures and in the tests and specs that quote them, by design
    - Task 9 itself is not edited and its status is not changed by this task
    - _Requirements: 19.8, 21.2; tn3270-connector 12.18_

  - [x] 19.2 Measure property and flow module timings
    - Run `pytest tests/property --durations=10` and record the total time of the suite and the ten slowest tests; run the flow modules (`tests/unit/test_flow_*.py` and `tests/property/test_flow_*.py`) with `--durations=10` and record their total times separately
    - Require the whole `tests/property` suite under 90 seconds and the eight flow property modules under 35 seconds; if either is missed, fix the generators as in task 18.1 and rerun, never lowering `max_examples` below 100
    - Report the counts and timings in the completion notes of the task
    - _Requirements: 19.8, 19.9, 19.10_

- [x] 20. Fixes found while writing the group 10 tests
  - [x] 20.1 Fix yamlio whitespace handling
    - In `greenscreen/flow/yamlio.py` treat `text.strip() == ""` (empty or whitespace-only text, including tab-only and tab-containing documents) as `document is not a mapping` BEFORE calling `yaml.safe_load`, so that Requirement 6.9 holds; change nothing else in `yamlio.py`
    - Production edit allowed: `greenscreen/flow/yamlio.py` only
    - The existing red test `tests/unit/test_flow_yaml.py::test_whitespace_only_with_tab_is_not_a_mapping` must pass
    - Add cases to `tests/unit/test_flow_yaml.py` for `"\t"`, `"\t\n"`, `"  \t\n"` and `"\n\t  \n"`, each reporting `document is not a mapping`, and one non-whitespace, tab-containing malformed document that must still report `malformed YAML at line L, column C`, so the fix is not too broad
    - Run the full unit suite (`pytest -m "not integration" tests/unit`) after the change and require no regression
    - _Requirements: 6.6, 6.9_

  - [x] 20.2 Name an unknown step kind in the Flow constructor error
    - When `Flow(...)` receives a Step object whose `kind` is not one of the five kinds, the `FlowDefinitionError` names the kind in the form `step N: kind: unknown_kind 'NAME'`; `NAME` is echoed only when it matches `[A-Za-z0-9_-]{1,32}` (full match), otherwise `<invalid>`
    - First check how `model.py`, `validate.py` and `yamlio.py` handle this today (`validate.py` adds the violation `unknown_kind` without a name; `yamlio.py` holds the `_KIND_ECHO` pattern and the `<invalid>` fallback) and reuse one helper for the sanitising and the length cap instead of duplicating it; the only permitted `yamlio.py` change is replacing its local echo logic by that helper, with the existing message text unchanged
    - Production edit allowed: `greenscreen/flow/model.py`, `greenscreen/flow/validate.py`, and a shared helper module only if needed; not `runner.py` and not `connector.py`
    - Strengthen the unsupported-kind test (the direct constructor case) in `tests/unit/test_flow_model.py` to assert the kind is named; add hostile cases (a kind string with a newline, quotes, 200 characters, `${x}` and non-ASCII characters) asserting that the raw string never appears in `str`, `repr` or `args` of the error and that `<invalid>` is shown
    - Run the full unit suite (`pytest -m "not integration" tests/unit`) after the change and require no regression
    - _Requirements: 1.3, 4.9, 5.15_

- [x] 21. Release caller inputs on every run_flow exit (Requirement 14.7)
  - [x] 21.1 Release inputs and values on the input_invalid, definition and poll_interval exits
    - Requirement 14.7: when `FlowInputError` leaves `run_flow`, no `greenscreen.flow` traceback frame may hold the caller's inputs mapping, a supplied value or a rendered value. The same guarantee applies to the `FlowDefinitionError` raised from `run_flow` (for example a Flow that names a Signature that is missing) and to the `ValueError` raised for a `poll_interval` outside 0.01 to 1
    - `greenscreen/flow/runner.py`, this defect only: bring `prepare_inputs` under the same cleanup as the rest of `run_flow`. On each of the three exits release the run state, clear the finished `greenscreen.flow` frames, `del inputs` and `del prepared`, and then re-raise the same exception object (identity, type and args unchanged, `__cause__` and `__context__` still `None`). Make no other change to `runner.py`
    - `greenscreen/flow/inputs.py`: `prepare_inputs` drops its local references `supplied`, `value` and `rendered` before it raises `FlowInputError`
    - `greenscreen/connector/connector.py` is not touched
    - `tests/unit/test_flow_runner_errors.py::test_no_screen_is_reachable_from_the_error[input_invalid]` must go green unchanged; do not edit that file
    - Create `tests/unit/test_flow_runner_fixes_frames.py` with one test per exit: `FlowInputError`, `FlowDefinitionError` (a Flow whose Expect_Step names a Signature_Name missing from the given Signatures, raised from `run_flow`) and the `poll_interval` `ValueError`. Each test walks every traceback frame of module `greenscreen.flow` and builds boolean verdicts only (never print or format a value, so a secret is never shown on failure): no frame local is the inputs mapping (identity), none is or contains a supplied or rendered value (use a secret sentinel as an input value, including as a `str` and as an `int`-rendered text), and none is a `Screen`. Each test also asserts the same exception object is the one raised (identity, type and `args` unchanged) and that the `ScriptedSession` call log is empty
    - Run the full unit suite (`pytest -m "not integration" tests/unit`) after the change and require no regression
    - _Requirements: 14.7, 16.9, 2.9_

- [x] 10. Write the flow unit tests
  - [x] 10.1 Write unit tests for the model (`tests/unit/test_flow_model.py`)
    - Cover immutability (assign and delete raise and leave the field unchanged), every bound of Requirement 1 (description 501 characters, 21 inputs, 21 outputs, 0 and 201 steps, 51 finally Steps), the five Step kinds (one test per kind), an unsupported kind naming the kind, and that `FlowError`, `FlowInputError` and `FlowDefinitionError` do not derive from `ConnectorError` or `RecognizerError`
    - Assert that `pyproject.toml` `dependencies` and `optional-dependencies` equal the lists present when this task starts
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 10.2 Write unit tests for Inputs (`tests/unit/test_flow_inputs.py`)
    - One test per rule of Requirement 2.6 to 2.9: missing required Input, wrong type (including `bool` for `int`), length above `max_length` after `str()`, `regex` mismatch, non-printable-ASCII character, undeclared name; assert each raises `FlowInputError` naming the Input and the rule, that the `ScriptedSession` call log is empty, and that no message or attribute contains the supplied value, secret or not
    - _Requirements: 2.6, 2.7, 2.8, 2.9_

  - [x] 10.3 Write unit tests for the validator (`tests/unit/test_flow_validate.py`)
    - One test per rule of Requirements 2 to 5: Input rules (name pattern, duplicate, `type`, `required`, `max_length` bool and range, `regex`, `secret` with `int`, extra key, description length); Output rules (name, duplicate, type, row, col, length, `col + length`); Step rules (Expect counts and duplicates, `tolerate` overlap, `timeout` range, Type_Step both or neither of `text` and `input`, `text` length and characters, Key_Step `n` rules, Extract placement and one per Output, Handle bounds and body kinds); load-time rules (unknown Signature_Name in `signatures`, `tolerate`, Handle_Step and Output; undeclared `input`; unarmed key and Type_Step; Handle_Step leaves no arming Step; nested Handle_Step; Output signature not in the arming Expect_Step; Secret_Input outside a Type_Step `input`; `${` in a literal; Timeouts ranges)
    - Assert the ordering rule when several violations exist, that each message names the Step_Index (when a Step applies), the field and the rule, and that no message contains a YAML scalar other than field name, Step kind, Flow_Name, Signature_Name, Input name or Output name
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14, 5.15_

  - [x] 10.4 Write unit tests for the YAML loader (`tests/unit/test_flow_yaml.py`)
    - One test per YAML error of Requirement 6: malformed YAML, not a mapping, empty and whitespace-only text, unknown key, missing required key, wrong value type, `version` as `true`, `"1"`, `1.0`, a missing `version` and `2`, with the key name and list index in the message; a missing file, a directory, a permission error, invalid UTF-8, each naming the path; `__cause__` and `__context__` are `None` for every one; `version` is the first emitted key and equals the integer 1; the loader reads no environment variable
    - _Requirements: 6.1, 6.2, 6.3, 6.6, 6.7, 6.8, 6.9, 16.5_

  - [x] 10.5 Write unit tests for the Expect_Step and polling (`tests/unit/test_flow_runner_expect.py`)
    - Cover: one `read_screen` and one `recognize` per attempt with the fake Clock sleeping `poll_interval` between attempts and read and sleep counts; accepted name; `tolerate`; unknown screen tolerated until the timeout and then `unknown_screen`; `ambiguous_screen` and `unexpected_screen` raised before any further read or sleep; `timeout` after a tolerated name, the Pre_Key_Name or a screen equal to the Pre_Key_Screen, with the Step_Index, sorted `expected` and a Redacted_Summary; the stale-read rule (a screen equal to the Pre_Key_Screen in cells and cursor adds no key); the partial repaint served as the Pre_Key_Name and then the expected screen succeeds with no extra key (Requirement 18.13); a tolerated Pre_Key_Name until the Step timeout raises `timeout` (Requirement 18.14); the first Expect_Step before any key meets a name in neither `signatures` nor `tolerate` and raises `unexpected_screen` (Requirement 18.15); the Pre_Key_Name in `signatures` is accepted; a `SignatureError` or `TypeError` from `recognize` raises `FlowDefinitionError` and sends no key
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.12, 8.13, 8.15, 8.16, 8.20, 8.21, 12.1, 12.5, 18.7, 18.13, 18.14, 18.15_

  - [x] 10.6 Write unit tests for each typed screen of the shipped flows (`tests/unit/test_flow_runner_typed_screens.py`)
    - Four tests, each building the Pre_Key_Screen in memory from the accepted capture with `typed_screen` (the typed text written into the cursor field cells) and asserting the following key is sent and no `FlowError` is raised: the userid typed at `tk5-logon`; the password typed at `tso-password-prompt` (a hidden field, using a sentinel as the typed text); `X` typed at `ispf-primary-menu`; `LOGOFF` typed at `tso-ready`
    - In the password-prompt test assert that the sentinel appears in no `FlowError`, log record, `AuditRecord` or `FlowResult` of the run (capture caplog at all levels)
    - _Requirements: 8.9, 8.17, 8.19, 10.4, 10.5, 18.11, 18.16_

  - [x] 10.7 Write unit tests for the MDT bit, changed geometry and the full-field case (`tests/unit/test_flow_runner_typed_fields.py`)
    - The four typed-screen cases of task 10.6 run with the MDT bit set (`c9`) and clear (`c8`); a `tk5-logon` screen against a copy whose input field attribute is `c9` passes the geometry check, and a copy whose field is `e8` (protected) instead of `c8` fails it
    - A typed screen whose field geometry differs from the Current_Screen (a changed field start position, length or attribute) raises `unexpected_screen` and zero key calls reach the `ScriptedSession`, and `recognize` is not called for that Key_Step (Requirement 18.12)
    - Typing exactly the number of data cells left in the `tk5-logon` and `ispf-primary-menu` cursor fields with the cursor outside the field raises `unknown_screen` and sends zero keys; the same for `tso-ready` passes because that signature has no cursor matcher; typing twice into one field gives one Typed_Field entry; the Typed_Fields are emptied when a screen is accepted and when a key is sent
    - _Requirements: 8.9, 8.10, 8.17, 8.18, 8.19, 18.11, 18.12_

  - [x] 10.8 Write unit tests for typing and key rules (`tests/unit/test_flow_runner_type_key.py`)
    - Cover: `bad_target` for a missing or protected cursor field with `Session.string` called zero times and the Current_Screen unchanged; `secret_target` for a Secret_Input into a visible field; a Secret_Input into a hidden field calls `string` exactly once; a non-secret Input into a hidden field is allowed; an optional Input not supplied skips each Type_Step that references it, recorded `skipped`; `string` receives the declared text unchanged; `pf(n)` and `pa(n)` call exactly once with `n`; at most one key per accepted screen; no key while the Current_Screen is absent; `close` is never called, also when `run_flow` raises
    - _Requirements: 7.2, 7.4, 7.5, 8.14, 8.15, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 15.4_

  - [x] 10.9 Write unit tests for the Handle_Step (`tests/unit/test_flow_runner_handle.py`)
    - Cover: zero iterations when the first screen is not the handled name; one iteration then a different screen; the `settle` rule (a different name within `settle` runs no body, unknown screens during `settle` are ignored, the body runs when the handled screen is still shown at the end, `settle` measured on the fake Clock); the Current_Screen reused without `read_screen`; `loop_limit` after exactly `max_count` keys with the Handle_Step recorded `failed`; the Step timeout restarts for each wait; pre-key rules apply to body Steps with `iteration` starting at 1; a Handle_Step accepts the Pre_Key_Name as the next screen
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 18.7_

  - [x] 10.10 Write unit tests for the Extract_Step (`tests/unit/test_flow_runner_extract.py`)
    - Cover: leading and trailing spaces trimmed; empty `str` result; `int` conversion and the `[0-9]{1,18}` limit; `output_type` without the text in the error; `hidden_output` without reading the hidden field; `screen_size` for a screen under 24 by 80; `unexpected_screen` when the Current_Screen name differs from the Output `signature` with no cell read; no `read_screen` call for an Extract_Step; `FlowResult.outputs` has exactly one entry per Output with the declared types
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 11.1, 11.2, 11.3, 11.4, 18.7_

  - [x] 10.11 Write unit tests for the finally rules (`tests/unit/test_flow_runner_finally.py`)
    - Cover: finally runs after success with the carried Current_Screen; finally runs after `unexpected_screen`, `loop_limit`, `bad_target` and `secret_target` when a Current_Screen is held; finally is skipped with zero keys and a `skipped` record for every Step_Index of the finally plan (including handle bodies) after `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error` and `input_invalid` and when no Current_Screen is held; the main FlowError wins over a failed Finally_Step; a failed Finally_Step after success is raised; a failed Finally_Step makes later Steps `skipped` with zero keys; the finally budget raises `run_timeout`; every Finally_Step has a recorded status before return or raise; the audit trail holds every Step that began, in order, with `duration_seconds` from the fake Clock
    - _Requirements: 12.2, 12.3, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 14.8, 15.2, 15.4, 18.7_

  - [x] 10.12 Write unit tests for every Reason_Code (`tests/unit/test_flow_runner_errors.py`)
    - One test per Reason_Code (`input_invalid`, `timeout`, `run_timeout`, `unknown_screen`, `ambiguous_screen`, `unexpected_screen`, `loop_limit`, `bad_target`, `secret_target`, `hidden_output`, `output_type`, `screen_size`, `session_error`), asserting `reason`, `step_index`, sorted `expected`, `summary` and `audit` against the design table; `session_error` once for each Session method (`read_screen`, `string`, `enter`, `clear`, `pf`, `pa`) with only the class name and Step_Index in the message and `__cause__` and `__context__` `None`, and for a secret Type_Step with a non-`ConnectorError` exception whose message holds the sentinel
    - Assert the message is one line of at most 500 characters in the documented form, that `str()` and `repr()` of the three error classes hold no Secret_Value and no hidden-cell content, that no `Screen`, `cell_grid` or `Field` is reachable from a raised error (attributes, `args`, traceback frame locals inside `greenscreen.flow`, `gc.get_referrers`), that the Comparison_Screen is released before any error is raised, that every error has `__cause__` and `__context__` `None`, that `poll_interval` outside 0.01 to 1 raises `ValueError`, and that any `Exception` raised by a Session method, not only `ConnectorError` and `OSError`, is converted to `session_error` (Requirement 7.6), both in a secret Type_Step and elsewhere, while a `FlowError` passes through unchanged (test at least `RuntimeError` and `ValueError` in addition to `ConnectorError` and `OSError`)
    - _Requirements: 7.6, 8.19, 12.5, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 16.8, 18.7_

  - [x] 10.13 Write unit tests for loading the bundled flows (`tests/unit/test_flow_bundled.py`)
    - Cover: exactly three entries keyed `tk5-logon`, `tk5-logoff`, `tk5-system-info`, also when called from another working directory; every bundled Flow passes the validator against `load_bundled_signatures()`; the structure required by Requirement 17.4 to 17.13 and 17.15 (Inputs, no Outputs, `settle` of at least 3 on the `tk5-logo` Handle_Step, the `tso-input-not-recognized` Handle_Step with `clear`, the `tso-pause` Handle_Step with `max_count` 5, the exact seven Steps of `tk5-logoff`, the four Outputs and regions, the three Finally_Steps); the shipped YAML text equals `to_yaml()` of the loaded Flow; a broken, missing or invalid file (through a patched `importlib.resources` lookup) raises `FlowDefinitionError` naming the file and returns no dict; two calls return distinct dict objects (no cache); no bundled file contains a literal credential or `${`
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 17.11, 17.12, 17.13, 17.15, 17.18, 17.19, 21.3, 21.4_

  - [x] 10.14 Write the scripted `tk5-logon` sequence tests (`tests/unit/test_flow_logon_script.py`)
    - With the `ScriptedSession` serving the screens `tk5-logo`, `tk5-logon`, `tso-password-prompt`, two distinct `tso-pause` variants and `ispf-primary-menu` in that order, run `tk5-logon` and assert the recorded keystroke calls are exactly, in order, `enter`, `string(userid)`, `enter`, `string(password)`, `enter`, `enter`, `enter`, and that the run ends with the `ispf-primary-menu` Screen; use the sentinel for the password and a fake userid, never a real credential
    - Starting at `tso-input-not-recognized`, assert the first recorded key call is `clear`
    - Add the variants with `stale_reads` after each key and with the logon screen served directly, and assert the same key sequence apart from the skipped logo Enter
    - _Requirements: 17.4, 17.5, 17.6, 17.7, 17.8, 18.8, 18.9_

  - [x] 10.15 Write the scripted `tk5-system-info` tests against the captures (`tests/unit/test_flow_system_info_script.py`)
    - Run `tk5-system-info` on a `ScriptedSession` built from the captures through logon, the menu, `X`, READY, `LOGOFF` and the logon screen, and assert the result has exactly the keys `USERID`, `SYSTEMID`, `RELEASE` and `TERMINAL`, each equal to the capture text at its Output region with leading and trailing whitespace removed, read from `captures/ispf-primary-menu.readbuffer.txt` on every run through `load_capture_screen`; assert the final Screen is recognized as `tk5-logon` and the audit trail holds the four Extract_Steps in order
    - Add a variant that fails after the Extract_Steps and assert the Finally_Steps log off
    - _Requirements: 17.11, 17.12, 17.15, 17.16_

  - [x] 10.16 Write the capture facts tests for the flow package (`tests/unit/test_flow_captures.py`)
    - Assert each of the four Output regions of `tk5-system-info` lies within the screen bounds of `captures/ispf-primary-menu`, is not in a hidden field, and that the text at col 60 of the same row is the label (`USERID   :`, `TERMINAL :`, `RELEASE  :`, `SYSTEMID :`)
    - Assert that `ScreenView.containing_field` and `Screen.find_field` agree on start position, length, `protected` and `hidden` for the cursor of every capture; this test may read `Screen.find_field` and `Field.text` only on captures that hold no password
    - Assert `captures/*.readbuffer.txt` still holds exactly the seven names used by the recognizer capture inventory and no capture of the screen with the typed password exists, and that the sentinel of `sentinel_password_screen` occurs in no file under `captures/`
    - _Requirements: 8.17, 10.7, 17.13, 17.14, 18.5, 18.10_

  - [x] 10.17 Write the flow-sync test (`tests/unit/test_flow_sync.py`)
    - Load the three bundled Flows and assert the first Steps of `tk5-system-info` equal the Steps of `tk5-logon`, the Steps after the four Extract_Steps equal the Steps of `tk5-logoff`, the `inputs` of `tk5-system-info` equal the `inputs` of `tk5-logon`, and the Steps between are exactly the four Extract_Steps, so the three Flows cannot drift
    - _Requirements: 17.11, 17.12, 17.17_

  - [x] 10.18 Write the packaging tests (`tests/unit/test_flow_packaging.py`)
    - Assert `pyproject.toml` declares `"greenscreen.flow.flows" = ["*.yaml"]` and that `dependencies` and `optional-dependencies` equal the lists present when this task starts
    - Copy the repository to a temporary directory, run `pip wheel . --no-deps --no-build-isolation` there with network access disabled, and assert the wheel's file list contains exactly the three Flow YAML files under `greenscreen/flow/flows/`; a failed build or a missing file fails the test and the message carries the build error or the names of the missing files
    - This is the only test in the flow suite that starts a subprocess
    - _Requirements: 21.2, 21.5, 21.6_

  - [x] 10.19 Write the public API test (`tests/unit/test_flow_public_api.py`)
    - Assert `from greenscreen.flow import <name>` succeeds for each of the nine names and that `__all__` holds exactly those nine names
    - _Requirements: 21.1_

  - [x] 10.20 Write the static rule tests (`tests/unit/test_flow_static.py`)
    - Read the source of `greenscreen/flow/screens.py` and `greenscreen/flow/runner.py` and assert they contain no `Field.text`, `text_grid`, `.fields` or `find_field` use (the scan is for those; the TypeStep literal `step.text` in `runner.py` is a Flow definition field and is allowed, `screens.py` has no allowance); assert no `os.environ` or `getenv` use anywhere in `greenscreen/flow`; assert `yaml.safe_load` and `yaml.safe_dump` are the only YAML entry points; assert no `time.monotonic`, `time.sleep`, `datetime` or `random` use outside `clock.py`; assert no `subprocess`, `socket` or `open(` use in the runner; assert no shipped YAML file contains a credential
    - _Requirements: 6.2, 7.7, 8.19, 10.7, 12.4, 16.3, 16.5, 16.6, 17.19_

- [x] 11. Write the flow-runtime property tests
  - [x] 11.1 Write property test for Property 1
    - **Property 1: YAML round trip and determinism**
    - Create `tests/property/test_flow_yaml_roundtrip.py`, one `@given` test starting with `# Feature: flow-runtime, Property 1: YAML round trip and determinism`, `@settings(max_examples=100, deadline=None)`, drawing from `flows()`
    - Assert `Flow.from_yaml(flow.to_yaml(), signatures) == flow` for Flows with all five Step kinds, Inputs with every option and Outputs, with strings that contain quotes, backslashes, colons, `#`, leading and trailing spaces, YAML-special words, non-ASCII characters and the empty string; assert two `to_yaml()` calls return identical strings and that the first emitted key is `version` with the integer value 1
    - **Validates: Requirements 1.1, 6.3, 6.4, 6.5**

  - [x] 11.2 Write property test for Property 2
    - **Property 2: Runs are deterministic and terminate**
    - Create `tests/property/test_flow_determinism.py`, one `@given` test starting with `# Feature: flow-runtime, Property 2: Runs are deterministic and terminate`, `@settings(max_examples=100, deadline=None)`, drawing from `chain_scripts()` with an optional failure point
    - Run the same Flow twice with fresh `ScriptedSession` and `FakeClock` objects; assert equal `outputs` or equal `reason`, `step_index` and `expected`, the same ordered Session call log, audit trails equal in every field except `duration_seconds`, and a finite number of Session calls bounded by the Step timeouts, `max_count` and the Step count
    - **Validates: Requirements 3.9, 8.4, 12.6, 15.6**

  - [x] 11.3 Write property test for Property 3
    - **Property 3: No secret or hidden content leaves the runner**
    - Create `tests/property/test_flow_secret_leak.py`, one `@given` test starting with `# Feature: flow-runtime, Property 3: No secret or hidden content leaves the runner`, `@settings(max_examples=100, deadline=None)`, drawing a Flow that types a Secret_Input, a sentinel from `secrets()` and a script that ends in success or in each Reason_Code, including the residual-password Screen, unknown screens and a Session that raises exceptions whose messages contain the sentinel
    - Assert the sentinel appears in none of the `FlowResult` fields and `repr`, every `AuditRecord`, the `str`, `repr`, `args` and attributes of every raised error including its Redacted_Summary, and the message and arguments of every `greenscreen.flow` log record; assert every error has `__cause__` and `__context__` `None` and a one-line message of at most 500 characters with the Reason_Code and Step_Index; assert every log record is DEBUG and matches one of the four record shapes
    - **Validates: Requirements 10.9, 14.4, 14.5, 14.6, 15.3, 15.5, 16.1, 16.2, 16.4, 16.8**

  - [x] 11.4 Write property test for Property 4
    - **Property 4: A key is sent only after a verified screen, and an unknown screen stops the run**
    - Create `tests/property/test_flow_unknown_stops.py`, one `@given` test starting with `# Feature: flow-runtime, Property 4: A key is sent only after a verified screen, and an unknown screen stops the run`, `@settings(max_examples=100, deadline=None)`, drawing from `chain_scripts()` with a persistent blank screen or a screen that two Signatures match (a synthetic alias Signature named in the Flow)
    - Assert that when the run raises `unknown_screen` or `ambiguous_screen` the Session receives no `string` call and no key call after the read that caused the error and that no Finally_Step sends a key; assert for every key sent that the Pre_Key_Screen geometry equaled that of the Current_Screen and that a test-side model of the Comparison_Screen (typed fields restored from the Current_Screen) is recognized as the Current_Screen name; assert the number of key calls never exceeds the number of accepted screens
    - **Validates: Requirements 8.7, 8.9, 8.11, 8.14, 13.3**

  - [x] 11.5 Write property test for Property 5
    - **Property 5: A Handle_Step runs at most max_count iterations**
    - Create `tests/property/test_flow_handle_bound.py`, one `@given` test starting with `# Feature: flow-runtime, Property 5: A Handle_Step runs at most max_count iterations`, `@settings(max_examples=100, deadline=None)`, drawing from `handle_counts()`
    - Assert that for a Session showing the handled screen forever or k greater than N times (distinct variants, so the stale-read rule does not apply) the run raises `loop_limit` after exactly N body iterations, sends exactly N keys, records the Handle_Step `failed` and sends no further key; and that for k from 0 to 20 with k at most N the run sends exactly k keys and returns
    - **Validates: Requirements 9.2, 9.3, 9.4, 9.6, 9.7, 12.6**

  - [x] 11.6 Write property test for Property 6
    - **Property 6: Stale reads and partial repaints add no key**
    - Create `tests/property/test_flow_stale_reads.py`, one `@given` test starting with `# Feature: flow-runtime, Property 6: Stale reads and partial repaints add no key`, `@settings(max_examples=100, deadline=None)`, drawing from `chain_scripts()` with 0 to 5 stale reads after each key and 0 to 3 partial repaints recognized as the Pre_Key_Name that differ from the Pre_Key_Screen in cell content
    - Assert the run sends exactly the same key and `string` calls and returns the same `outputs` as the baseline run with no stale reads and no repaints, and raises no `FlowError`
    - **Validates: Requirements 8.12, 8.14, 8.20**

  - [x] 11.7 Write property test for Property 7
    - **Property 7: Every Key_Step and Type_Step needs an arming Step**
    - Create `tests/property/test_flow_arming.py`, one `@given` test starting with `# Feature: flow-runtime, Property 7: Every Key_Step and Type_Step needs an arming Step`, `@settings(max_examples=100, deadline=None)`, drawing from `flows()` with one unarmed Key_Step or Type_Step injected in `steps` or `finally` (outside a handle body), including directly after a Handle_Step
    - Assert the validator raises `FlowDefinitionError` naming the Step_Index of the first such Step, and that inserting an Expect_Step immediately before that Step makes the Flow valid
    - **Validates: Requirements 5.6, 5.7, 5.8**

  - [x] 11.8 Write property test for Property 8
    - **Property 8: Typing never blocks the following key**
    - Create `tests/property/test_flow_typing_never_blocks.py`, one `@given` test starting with `# Feature: flow-runtime, Property 8: Typing never blocks the following key`, `@settings(max_examples=100, deadline=None)`, drawing from `typed_cases()`: an accepted screen of `tk5-logon`, `tso-password-prompt`, `ispf-primary-menu` or `tso-ready` from `captures/`, printable ASCII text of length 1 to L, and any MDT state of the typed field, where L is the smaller of 255 and the data cells from the cursor to the end of the field minus one for the three screens whose Signature has a `cursor_field` matcher, and the smaller of 255 and that number of cells for `tso-ready`
    - Build each typed Pre_Key_Screen in memory by writing the text into the cursor field cells, run the Type_Step and Key_Step on a `ScriptedSession`, and assert the key is sent and no `FlowError` is raised; never write a typed screen to `captures/` or any file
    - **Validates: Requirements 8.9, 8.17, 8.19, 10.4, 10.5**

  - [x] 11.9 Measure the property suite time
    - Run `pytest tests/property --durations=0` once, with the fake Clock in every flow test, and record the total and the sum of the eight `tests/property/test_flow_*.py` modules
    - Fail the task if the whole `tests/property` suite (connector, recognizer and flow) takes more than 90 seconds or the flow modules take 35 seconds or more; if over, shorten the chains in `chain_scripts()` or the cached Screens, never lower `max_examples` below 100
    - Confirm zero network connections and zero subprocesses in the property suite
    - _Requirements: 19.8, 19.9, 19.10_

- [x] 12. Write the live integration test
  - [x] 12.1 Write `tests/integration/test_flow_live_system_info.py`
    - One test marked `@pytest.mark.integration` that runs `tk5-system-info` through a `Connector` in a `with` block, using `live_connector_config()` (`GS_HOST`, `GS_PORT`, `GS_S3270_BINARY`, same names and defaults as the existing integration tests) and the session-scoped `host_reachable` fixture of `tests/conftest.py`
    - Read `TK5_USERNAME` and `TK5_PASSWORD` from the environment only; if either is unset or an empty string, skip with a message that names each missing or empty variable before any connection is attempted; if `host_reachable` reports the host did not accept a connection within 5 seconds, skip with a message that the host is unreachable
    - Assert `SYSTEMID` and `RELEASE` each contain at least one non-whitespace character, `USERID` equals `TK5_USERNAME` ignoring case, and the final screen is recognized as `tk5-logon`; capture log records at DEBUG with `caplog` and assert the value of `TK5_PASSWORD` does not occur in `repr(result)`, in `str()` of any raised or returned error, or in the `message` of any log record captured at all levels (this depends on the redaction of group 1)
    - Also capture the DEBUG records of the `greenscreen.connector` logger and of all loggers (root logger at level DEBUG) during the full logon of `tk5-system-info` and assert that `TK5_PASSWORD` in plain text and as hex (lowercase and uppercase, each with and without a space between bytes, of the ASCII bytes) occurs in no record `msg`, no element of `args` and no `getMessage()` result; skip only the hex checks when `TK5_PASSWORD` is shorter than 4 characters (Requirement 20.9 and 20.10, the flow-side check of tn3270-connector Requirement 12.44; use `forms_of_run` from `tests/connector_support.py`, task 14.2)
    - Record with `record_property` the host cursor position after a field is filled if the run observes it; no code depends on it
    - No credential appears in the file, and no screen holding the typed password is captured or written
    - _Requirements: 16.6, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 20.10_

- [x] 13. Final checkpoint - whole suite and property timing
  - Run the entire suite with `pytest -m "not integration"` and require zero failures, including every pre-existing test and every new connector, recognizer and flow test
  - Run `pytest tests/property --durations=0` and confirm the whole `tests/property` suite finishes in under 90 seconds and the eight flow property modules finish in under 35 seconds; if either limit is missed, fix the generators as in task 11.9 and rerun
  - Confirm `pyproject.toml` `dependencies` and `optional-dependencies` are unchanged and that the TK5 password is absent everywhere (every tracked, untracked and ignored file, test output and logs); the stock TK5 user id appears in screen captures and in the tests and specs that quote them, by design
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 19.8, 19.9, 19.10, 21.2_

## Notes

- Every task is required, and no sub-task is optional. Each task references the requirement clauses it satisfies; each property task names its design property number, its test file and the clauses it validates. Connector tasks reference `tn3270-connector` Requirement 12 by that prefix.
- The redaction tasks of group 1 are implemented from `.kiro/specs/tn3270-connector/requirements.md` (Requirement 12) and the "Action Redaction" section of `.kiro/specs/tn3270-connector/design.md`. They live in this list only; `.kiro/specs/tn3270-connector/tasks.md` is not edited. The checkpoint in task 2 gates every flow task.
- The live check of task 1.7 is a measurement and is skipped unless the host is reachable. Its result is recorded in the connector spec documents (`requirements.md` and `design.md`), not in any tasks file.
- The packaging wheel test (task 10.18) starts a subprocess and is the only flow test that does. Property tests and the other unit tests start no subprocess and open no socket.
- The unit test files for the scripted `tk5-logon` and `tk5-system-info` runs (tasks 10.14 and 10.15) are separate from `test_flow_bundled.py` so that no two tasks write the same file.
- Where the cursor goes after a field is completely filled on the real host is not verified. The runner does not depend on it, Property 8 stays one cell short of a full field for screens whose Signature has a `cursor_field` matcher, and the integration test only records the observation.
- No Signature exists for the `IKJ56700A ENTER USERID` screen; `tk5-logon` stops with `unknown_screen` and sends no key when it meets it (Known Limits of the requirements).
- Run the property suite with `pytest tests/property --hypothesis-seed=0` for reproducibility.
- Numbering of the checkpoint-9 review groups: tasks 10 to 13 are referenced elsewhere and keep their numbers, so the new groups take the top-level numbers 14 to 19, which follow the last existing number (13). They are written in the file between task 9 and task 10 because they execute in that position. Execution order: 14 (group A, connector response redaction), 15 (checkpoint for A), 16 (group B, runner fixes), 17 (group C, consistency check), 18 (group D, strategy trim), 19 (group E, re-run of checkpoint 9), then 10, 11, 12 and 13. The Task Dependency Graph encodes this: tasks 14 to 19 follow task 8.2 (the end of the work that checkpoint 9 covers), and every task of groups 10, 11 and 12 sits in a wave after task 19.2.
- Task 14.3 is the only place where pre-existing test files change: `tests/unit/test_connector.py`, `tests/unit/test_connector_redaction.py`, `tests/unit/test_parser.py` and `tests/property/test_string_redaction.py` (five tests or constants, listed in the task). Every other new test goes into new files, except that task 14.4 appends new tests to `tests/unit/test_connector_redaction.py` after task 14.3 has edited it. Task 12.1 gets one extra assertion bullet (Requirement 20.9 and 20.10) and nothing else changes in groups 10 to 13.
- The connector design maps Property 11 to `tests/property/test_hidden_cell_redaction.py`; task 14.5 uses `tests/property/test_response_redaction.py` as requested. Align the design's file name when the task is done.
- Tasks of group B (16.1 to 16.5) all edit `greenscreen/flow/runner.py`, so each sits in its own wave. Their tests live in new `tests/unit/test_flow_runner_fixes_*.py` files so they do not clash with the group 10 files.
- `pyproject.toml` already registers pytest markers, so task 18.2 adds the `perf` marker there; no dependency changes.
- Numbering of group 20: tasks 10 to 13 keep their numbers and groups 14 to 19 follow the last number then in use, so the fixes found while writing the group 10 tests take the next free top-level number, 20. Like groups 14 to 19 they are written in the file before task 10 because they execute before the remaining group 10 work. Execution order: 20.1, then 20.2 (separate waves because 20.2 may touch `yamlio.py`), then the group 10 tasks, 11 and 12. Task 10.1 is already completed and task 20.2 strengthens its test in `tests/unit/test_flow_model.py`; task 10.4 is in progress and is finished after task 20.1 so that its YAML tests see the whitespace fix.
- Numbering of group 21: the next free top-level number after 20 is 21, so the input-release fix (Requirement 14.7) is task 21.1. It is written before task 10 because it executes before the remaining group 10 work. In the Task Dependency Graph it sits alone in wave 27, directly after 20.2, so it runs before the incomplete group 10 tasks (10.12, which is in progress and finishes after 21.1, 10.15, 10.16, 10.18 to 10.20) and before groups 11, 12 and 13. The waves that followed (old 27 to 31) are now 28 to 32 with the same task lists. Task 21.1 is the only task that edits `greenscreen/flow/runner.py` and `greenscreen/flow/inputs.py` after group 16, and `test_no_screen_is_reachable_from_the_error[input_invalid]` in task 10.12's file is expected to go green because of it.
- Task 10.12 correction: any `Exception` raised by a Session call is converted to `session_error` (Requirement 7.6), not only `ConnectorError` and `OSError`; the task's test list says so.
- Timing limit change: the limit for the eight flow property modules together is 35 seconds (was 25), in Requirement 19.9, the design budget table and tasks 11.9, 13 and 19.2. Measured on a loaded machine, best of three: flow modules 28.2 s wall (runs 29.5, 28.2, 31.5), whole `tests/property` 84.5 s (runs 84.5, 97.0, 84.8; 123 tests). The 90 s limit for `tests/property` stays and its margin is thin. No test was trimmed, `max_examples` was not lowered and no `addopts` was added; the `perf` test (passed 3 of 4 runs, one failed under load; 1.5 s limit unchanged) is now opt-in and is skipped unless `GS_RUN_PERF=1` is set.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.5", "1.6", "1.7"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["4.1", "6.1"] },
    { "id": 5, "tasks": ["4.2", "6.3", "7.2"] },
    { "id": 6, "tasks": ["5.1", "7.1"] },
    { "id": 7, "tasks": ["6.2", "7.3", "8.1"] },
    { "id": 8, "tasks": ["7.4"] },
    { "id": 9, "tasks": ["7.5"] },
    { "id": 10, "tasks": ["7.6"] },
    { "id": 11, "tasks": ["8.2"] },
    { "id": 12, "tasks": ["14.1", "14.2"] },
    { "id": 13, "tasks": ["14.3"] },
    { "id": 14, "tasks": ["14.4", "14.5", "14.6"] },
    { "id": 15, "tasks": ["16.1"] },
    { "id": 16, "tasks": ["16.2"] },
    { "id": 17, "tasks": ["16.3"] },
    { "id": 18, "tasks": ["16.4"] },
    { "id": 19, "tasks": ["16.5"] },
    { "id": 20, "tasks": ["17.1"] },
    { "id": 21, "tasks": ["18.1"] },
    { "id": 22, "tasks": ["18.2"] },
    { "id": 23, "tasks": ["19.1"] },
    { "id": 24, "tasks": ["19.2"] },
    { "id": 25, "tasks": ["20.1"] },
    { "id": 26, "tasks": ["20.2"] },
    { "id": 27, "tasks": ["21.1"] },
    { "id": 28, "tasks": ["10.1", "10.3"] },
    { "id": 29, "tasks": ["10.2", "10.4"] },
    { "id": 30, "tasks": ["10.17", "11.1", "11.7"] },
    { "id": 31, "tasks": ["10.5", "10.6", "10.7", "10.8", "10.9", "10.10", "10.11", "10.12", "10.13", "10.14", "10.15", "10.16", "11.2", "11.3", "11.4", "11.5", "11.6", "11.8"] },
    { "id": 32, "tasks": ["10.18", "10.19", "10.20", "11.9", "12.1"] }
  ]
}
```
