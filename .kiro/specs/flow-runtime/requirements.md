# Requirements Document

## Introduction

The flow-runtime is the `greenscreen.flow` Python package, built on top of `greenscreen.connector` and `greenscreen.recognizer`. This is Core Piece 4 of Green Screen Medium. A Flow is a recorded terminal transaction that the Flow_Runner replays deterministically. No LLM is involved at runtime. The Flow_Runner checks the screen fingerprint (a recognized Signature name) before every keystroke and stops with a clear error on any unexpected screen. A Flow never guesses.

A Flow is a YAML document with typed Inputs, typed Outputs, a list of Steps and a `finally` list that always gets its chance to run (for example a logoff). Step kinds are `expect`, `type`, `key`, `extract` and `handle`. A `handle` Step covers optional screens such as the TSO `***` pause: "while the screen is X, do these steps", with a hard maximum count.

The Flow_Runner talks to a small Session protocol (`read_screen`, `string`, `enter`, `clear`, `pf`, `pa`, `close`) that `greenscreen.connector.Connector` already satisfies. Unit and property tests use a Scripted_Session built from Screens loaded from `captures/`, so no fake s3270 is needed.

The package ships three Flows as package data: `tk5-logon`, `tk5-logoff` and `tk5-system-info`.

Rules taken from the `mainframe-host` steering file and enforced here:

- After a key, `Wait(N,Output)` can return on a blank or partial screen, and a bare Enter-then-Wait can return before the new screen exists. The Flow_Runner therefore polls `read_screen` and never assumes that one read is the screen it wants (Requirement 8).
- Never press Enter blindly. Every key is preceded by an `expect` (Requirement 5 checks this at load, Requirement 8 checks it at run time).
- After the password is typed, the next screen still holds the password in its hidden cells. Every object the Flow_Runner stores, logs or raises must blank or omit hidden cells (Requirements 10, 11 and 16).
- Host credentials come from the environment (`TK5_USERNAME`, `TK5_PASSWORD`), never from source code, YAML or fixtures.

Interpretations made where the request leaves room (each is a normal requirement below and can be changed on review):

- **Polling and "stops at once".** While polling for an expected screen, a screen that matches no Signature is tolerated until the Step timeout, because blank and partial screens are normal right after a key. No key is sent while the screen is unknown. An ambiguous screen, or a recognized screen that the Step does not accept, stops the run immediately (Requirement 8).
- **Finally after an unknown screen.** Steps in `finally` obey the same expect-before-key rule. When the run has failed on an unknown, ambiguous or timed-out screen, no `finally` key is sent (Requirement 13). The `finally` list of each shipped Flow is therefore written as guarded `handle` Steps.
- **Screen change after a key.** After any key, a screen identical to the screen read just before that key is treated as "host has not answered yet" and polling continues (Requirement 8). A key whose correct outcome is an identical screen ends in a timeout. Because the host repaints progressively, a screen that is recognized as the screen just left is also tolerated until the Step timeout, but only after a key has been sent (Requirement 8, criteria 20 and 21).
- **Typed text and the pre-key check.** Text typed into a field changes the screen, and a typed screen can stop matching its own Signature (for example `tso-ready` once `LOGOFF` is typed at the cursor). The pre-key check therefore recognizes a Comparison_Screen in which the typed fields are restored to their accepted content, and also requires equal field geometry (Requirement 8, criteria 9 to 11 and 17 to 19).
- **Flows do not call other Flows.** `tk5-system-info` repeats the logon and logoff Steps, and a test keeps them equal to the two smaller Flows (Requirement 17).

## Glossary

- **Flow**: An immutable `Flow` object holding a Flow_Name, a description, Inputs, Outputs, Steps, Finally_Steps and Timeouts. Created by the Flow_Loader.
- **Flow_Name**: String of 1 to 64 characters from `a-z`, `0-9`, `-` and `_`.
- **Flow_Loader**: The functions `load_flow(path)`, `Flow.from_yaml(text)` and `load_bundled_flows()` that turn YAML into validated Flows.
- **Flow_Validator**: The load-time checks of Requirement 5, run by the Flow_Loader and on construction of a `Flow`.
- **Flow_Serializer**: The functions `Flow.to_yaml()` and `Flow.from_yaml(text)`.
- **Flow_Runner**: The function `run_flow(flow, session, inputs, *, signatures=None, clock=None, poll_interval=0.1) -> FlowResult` that executes a Flow.
- **Session**: The protocol with methods `read_screen() -> Screen`, `string(text: str)`, `enter()`, `clear()`, `pf(n: int)`, `pa(n: int)` and `close()`. Return values of the key and typing methods are ignored.
- **Scripted_Session**: A test Session that serves a predefined sequence of Screens loaded from `captures/` and records every call (Requirement 18).
- **Clock**: A test-injectable object with `monotonic() -> float` and `sleep(seconds: float)`. The default Clock wraps `time.monotonic` and `time.sleep`. A fake Clock advances its time on `sleep` and never waits.
- **Signature**: A `greenscreen.recognizer.ScreenSignature` with a Signature_Name.
- **Flow_Signatures**: The Signatures that `run_flow` passes to `recognize`: the Signatures from `signatures` (default `load_bundled_signatures()`) whose names the Flow references.
- **Input**: A declared Flow parameter with a name, a type (`str` or `int`), a `required` flag, a `max_length`, an optional regular expression and a `secret` flag.
- **Secret_Input**: An Input whose `secret` flag is true.
- **Secret_Value**: A value supplied at run time for a Secret_Input.
- **Output**: A declared Flow result with a name, a type (`str` or `int`), a Signature_Name and a region (`row`, `col`, `length`) read from the Screen recognized as that Signature, with leading and trailing spaces removed.
- **Step**: One element of `steps`, `finally` or a handle body. Kinds: Expect_Step, Type_Step, Key_Step, Extract_Step and Handle_Step.
- **Expect_Step**: `kind: expect` with `signatures` (1 to 5 Signature_Names), optional `tolerate` (0 to 5 Signature_Names) and optional `timeout`.
- **Type_Step**: `kind: type` with exactly one of `text` (a literal) or `input` (an Input name).
- **Key_Step**: `kind: key` with `key` equal to `enter`, `clear`, `pf` or `pa`, and `n` (1 to 24) for `pf` and `pa` only.
- **Extract_Step**: `kind: extract` with `output` (an Output name).
- **Handle_Step**: `kind: handle` with `signature`, `max_count` (1 to 20), optional `settle` (seconds) and `steps` (the handle body: Type_Steps and Key_Steps only).
- **Finally_Steps**: The `finally` list of a Flow.
- **Step_Index**: The zero-origin position of a Step in the depth-first flattening of `steps` followed by `finally`. A Handle_Step takes an index before the Steps of its body.
- **Current_Screen**: The Screen, with its recognized Signature_Name, that the Flow_Runner read after the most recent key and accepted. It is absent after a key until a new screen is read and accepted.
- **Pre_Key_Screen**: The Screen that the Flow_Runner reads immediately before it sends a key.
- **Pre_Key_Name**: The Signature_Name recognized on the Current_Screen when the most recent key was sent, which is the Current_Screen name at that moment. It is absent until the first key of the run is sent, and it is cleared whenever a screen is accepted after that key.
- **Typed_Fields**: The set of fields that Type_Steps typed into since the Current_Screen was accepted, each identified by its field geometry on the Current_Screen, that is its start position (row and column) and its length.
- **Comparison_Screen**: The Screen that the Flow_Runner builds from the Pre_Key_Screen at a Key_Step by restoring the cells of every Typed_Field to their content on the Current_Screen. Its cursor position is that of the Pre_Key_Screen. It exists only inside the Flow_Runner for the duration of the pre-key check.
- **Redacted_Summary**: The `greenscreen.recognizer` Redacted_Summary of a Screen, with every hidden cell shown as `*`.
- **FlowError**: The exception raised when a run stops. Attributes: `reason` (one of the Reason_Codes), `step_index` (int or None), `expected` (sorted tuple of Signature_Names), `summary` (Redacted_Summary or None), `audit` (tuple of Audit_Records so far).
- **FlowDefinitionError**: The exception raised when a Flow cannot be loaded or validated. `run_flow` also raises it during a run when `recognize` raises `SignatureError` or `TypeError` (Requirement 8, criterion 16), and before the first Session call when a referenced Signature_Name is missing from the Signature set. It is an exception class and not a Reason_Code. Internally the runner carries such a failure as the plain value `definition` until it raises the exception.
- **Run_State**: Everything `run_flow` holds for one run: the inputs mapping copy, the Current_Screen, the Pre_Key_Screen, the Comparison_Screen, cached views, the Typed_Fields and the Pre_Key_Name. Releasing the Run_State drops every one of these references.
- **Body_Step**: A Step inside the `steps` list of a Handle_Step.
- **Unmatched_Handle**: A Handle_Step that ran zero body iterations (Requirement 9, criteria 3, 5 and 6), including a Handle_Step in `finally` that was skipped.
- **FlowInputError**: A subclass of FlowError with `reason` `input_invalid`, raised before any call to the Session.
- **Reason_Code**: One of `input_invalid`, `timeout`, `run_timeout`, `unknown_screen`, `ambiguous_screen`, `unexpected_screen`, `loop_limit`, `bad_target`, `secret_target`, `hidden_output`, `output_type`, `screen_size` and `session_error`.
- **FlowResult**: A frozen object with `flow` (Flow_Name), `outputs` (mapping of Output name to `str` or `int`) and `audit` (tuple of Audit_Records).
- **Audit_Record**: A frozen object with `step_index`, `kind`, `phase` (`steps` or `finally`), `iteration` (Handle_Step body iteration number or None), `signature` (recognized Signature_Name or None), `status` (`ok`, `skipped` or `failed`) and `duration_seconds` (float). It holds no screen text and no input value.
- **Timeouts**: The three Flow settings `step` (seconds per Step, default 10), `run` (seconds for `steps`, default 120) and `finally` (seconds for Finally_Steps, default 30).
- **Poll_Interval**: Seconds that the Flow_Runner sleeps between reads, default 0.1.
- **Test_Suite**: The pytest and Hypothesis tests of this feature under `tests/`.

## Known Limits

These are known limits of the shipped Flows, not requirements. No Signature exists yet for the `IKJ56700A ENTER USERID` screen, so `tk5-logon` does not recover from it. When a logon abandoned midway leaves that screen up on the next connection, the run ends with `unknown_screen` and no key is sent.

## Requirements

### Requirement 1: Flow Definition Model

**User Story:** As a flow author, I want a small typed definition format so that every recorded transaction is reviewable in version control.

#### Acceptance Criteria

1. THE Flow_Loader SHALL provide an immutable `Flow` type with these fields: `name` (Flow_Name), `description` (0 to 500 characters), `inputs` (0 to 20 Inputs), `outputs` (0 to 20 Outputs), `steps` (1 to 200 Steps counting Handle_Step bodies), `finally_steps` (0 to 50 Steps counting Handle_Step bodies) and `timeouts` (Timeouts).
2. THE Flow_Loader SHALL accept exactly the five Step kinds `expect`, `type`, `key`, `extract` and `handle`.
3. IF a Step has a kind other than `expect`, `type`, `key`, `extract` or `handle`, THEN THE Flow_Loader SHALL raise `FlowDefinitionError` naming the unsupported kind and SHALL NOT create the Flow.
4. WHEN a `Flow` instance exists and any code attempts to assign to or delete one of its fields, THE Flow_Loader SHALL reject the attempt by raising an exception and SHALL leave the field value unchanged.
5. THE Flow_Loader SHALL use only the existing packages `pyyaml`, `hypothesis` and `pytest`, and SHALL add no entry to the `dependencies` or `optional-dependencies` of `pyproject.toml`.
6. IF a Flow field is outside the bounds of criterion 1 (including a `description` longer than 500 characters, more than 20 `inputs`, more than 20 `outputs`, 0 `steps`, more than 200 `steps`, or more than 50 `finally_steps`), THEN THE Flow_Loader SHALL raise `FlowDefinitionError` whose message names the offending field and SHALL NOT create the Flow.
7. THE Flow_Loader SHALL NOT make `FlowError` or `FlowDefinitionError` a subclass of `ConnectorError` or `RecognizerError`.

### Requirement 2: Inputs

**User Story:** As a flow author, I want inputs with a type, a length limit and an optional pattern so that bad values never reach the host.

#### Acceptance Criteria

1. THE Flow_Validator SHALL require each Input name to match `[A-Za-z][A-Za-z0-9_]{0,31}` and to be unique within the Flow, using case-sensitive comparison.
2. THE Flow_Validator SHALL require each Input to declare `type` equal to `str` or `int`, `required` as a boolean, `max_length` as an integer from 1 to 255 (a `bool` is not an integer), `secret` as a boolean (default false) and optionally `regex` as a string of 1 to 200 characters accepted by `re.compile`.
3. THE Flow_Validator SHALL reject any Input key other than `name`, `type`, `required`, `max_length`, `regex`, `secret` and `description` (a string of 0 to 200 characters), so that an Input has no `default` and no example value.
4. WHERE an Input has `secret` true, THE Flow_Validator SHALL require `type` equal to `str`.
5. IF the Flow_Validator rejects an Input under criteria 1 to 4, THEN THE Flow_Validator SHALL report a validation error that names the Input (by name, or by position in the Flow when the name is invalid or duplicated) and the violated rule, and SHALL accept no Flow containing that Input.
6. WHEN `run_flow` is called, THE Flow_Runner SHALL validate all supplied Input values against the declared Inputs before the first call to the Session.
7. IF an Input value is missing for an Input with `required` true, has a type other than its declared type (a `bool` is not an `int`), has a rendered length above `max_length`, does not satisfy `re.fullmatch` of its `regex`, contains a character outside printable ASCII (U+0020 to U+007E), or is supplied for a name that no Input declares, THEN THE Flow_Runner SHALL raise `FlowInputError` that names the Input and the failed rule and SHALL make no call to the Session.
8. THE Flow_Runner SHALL render an `int` Input value with `str()` and SHALL measure `max_length`, `regex` and the printable ASCII check on that string.
9. THE `FlowInputError` message and attributes SHALL NOT contain the supplied value of any Input, whether `secret` is true or false.

### Requirement 3: Outputs

**User Story:** As an API consumer, I want typed, named outputs so that a flow result is structured data and not raw screen text.

#### Acceptance Criteria

1. THE Flow_Validator SHALL require each Output name to match `[A-Za-z][A-Za-z0-9_]{0,31}` and to be unique within the Flow, and SHALL require each Output to declare `type` equal to `str` or `int`, `signature` as a Signature_Name, `row` from 0 to 23, `col` from 0 to 79, `length` from 1 to 80 and `col` + `length` at most 80.
2. IF an Output in a Flow has a name that does not match `[A-Za-z][A-Za-z0-9_]{0,31}`, has a duplicate name, has a `type` other than `str` or `int`, or has a `row`, `col`, `length` or `col` + `length` outside the ranges in criterion 1, THEN THE Flow_Validator SHALL reject the Flow with an error naming the offending Output and the violated field, and SHALL NOT start a run of that Flow.
3. WHEN an Extract_Step runs, THE Flow_Runner SHALL read the Output region from the Screen that the preceding expect recognized, using the cell text of the `length` cells starting at `row` and `col` with null cells as spaces, and SHALL remove all leading and trailing space characters (U+0020) from the text.
4. WHERE an Output has `type` `str`, THE Flow_Runner SHALL return the trimmed text as the Output value, and SHALL return an empty string when the trimmed text is empty.
5. WHERE an Output has `type` `int`, THE Flow_Runner SHALL convert the trimmed text with `int()` only when the text matches `[0-9]{1,18}`.
6. IF the trimmed text of an `int` Output does not match `[0-9]{1,18}`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `output_type` naming the Output, SHALL NOT include the text in the error, and SHALL NOT return a `FlowResult`.
7. IF any cell of an Output region belongs to a hidden field, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `hidden_output` naming the Output, SHALL NOT read the text of that field, and SHALL NOT return a `FlowResult`.
8. IF the Screen under extraction has fewer than 24 rows or fewer than 80 columns, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `screen_size` naming the Output, and SHALL NOT return a `FlowResult`.
9. WHEN a run finishes without error, THE Flow_Runner SHALL return a `FlowResult` whose `outputs` has exactly one entry for each declared Output, keyed by Output name, with an `int` value for `int` Outputs and a `str` value for `str` Outputs.
10. THE Flow_Runner SHALL return `FlowResult.outputs` with its keys in the order in which the Outputs are declared in the Flow (`Flow.outputs`), not in the order in which the Extract_Steps ran, so that `list(result.outputs)` equals the declared Output names in declaration order (Requirement 15, criterion 8).

### Requirement 4: Step Definitions

**User Story:** As a flow author, I want a closed set of step kinds with fixed fields so that a flow cannot do anything its reviewer did not see.

#### Acceptance Criteria

1. THE Flow_Validator SHALL require an Expect_Step to name 1 to 5 distinct Signature_Names in `signatures`, 0 to 5 distinct Signature_Names in `tolerate` that are not in `signatures`, and optionally a `timeout` of 0.1 to 60 seconds.
2. THE Flow_Validator SHALL require a Type_Step to declare exactly one of `text` (1 to 255 characters of printable ASCII, U+0020 to U+007E) or `input` (the name of a declared Input).
3. THE Flow_Validator SHALL require a Key_Step `key` equal to `enter`, `clear`, `pf` or `pa`, SHALL require `n` as an integer from 1 to 24 when `key` is `pf` or `pa`, and SHALL reject `n` for `enter` and `clear`.
4. THE Flow_Validator SHALL require an Extract_Step to name a declared Output.
5. THE Flow_Validator SHALL require a Handle_Step `signature` as a Signature_Name, `max_count` as an integer from 1 to 20, `settle` as a number from 0 to 10 seconds (default 0) and a non-empty `steps` list of 1 to 50 entries that holds only Type_Steps and Key_Steps.
6. THE Flow_Validator SHALL reject any Step key that the Step kind does not define.
7. THE Flow_Validator SHALL place every Extract_Step in `steps` (not in `finally` and not in a handle body) and SHALL require each declared Output to be named by exactly one Extract_Step.
8. IF a Step violates any of criteria 1 to 7, THEN THE Flow_Validator SHALL reject the Flow, SHALL report an error that identifies the Step position and the offending field, and SHALL leave no partially validated Flow available for execution.
9. IF a Step declares a kind other than Expect_Step, Type_Step, Key_Step, Extract_Step or Handle_Step, THEN THE Flow_Validator SHALL reject the Flow with an error identifying the Step position and the unknown kind.
10. IF a Type_Step declares both `text` and `input`, or neither, THEN THE Flow_Validator SHALL reject the Flow with an error naming the offending field.

### Requirement 5: Validation at Load

**User Story:** As a flow author, I want mistakes found when the flow loads so that a bad flow never touches the host.

#### Acceptance Criteria

1. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every Signature_Name referenced by an Expect_Step, a Handle_Step or an Output exists in the Signature set passed to `load_flow` (default `load_bundled_signatures()`).
2. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every `input` named by a Type_Step is a declared Input.
3. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every Output region lies inside a 24 by 80 screen (Requirement 3, criterion 1).
4. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every Handle_Step has an integer `max_count` from 1 to 20 inclusive.
5. WHEN a Flow is loaded, THE Flow_Validator SHALL check that no Handle_Step contains another Handle_Step at any nesting depth and that the Flow contains no repetition construct other than Handle_Step.
6. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every Key_Step is preceded by an arming Step. An arming Step is an Expect_Step earlier in the same Step list with no Key_Step between them, or the enclosing Handle_Step for the first Steps of its body with no Key_Step between them.
7. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every Type_Step is preceded by an arming Step as defined in criterion 6.
8. WHEN a Flow is loaded, THE Flow_Validator SHALL treat a Handle_Step as leaving no arming Step for the Steps that follow it, so that a Type_Step or Key_Step after a Handle_Step is rejected unless an Expect_Step lies between the Handle_Step and that Step.
9. WHEN a Flow is loaded, THE Flow_Validator SHALL check that the `signature` of each Output is one of the `signatures` of the Expect_Step that arms its Extract_Step.
10. WHEN a Flow is loaded, THE Flow_Validator SHALL check that every reference to a Secret_Input occurs only in the `input` field of a Type_Step.
11. WHEN a Flow is loaded, THE Flow_Validator SHALL check that no Type_Step `text` literal contains the two-character sequence `${`, so that no literal can carry or interpolate a Secret_Value.
12. WHEN a Flow is loaded, THE Flow_Validator SHALL check that `timeouts.step` is from 0.1 to 60 seconds, `timeouts.run` is from 1 to 600 seconds, and `timeouts.finally` is from 1 to 120 seconds, all inclusive.
13. IF any check of this requirement fails, THEN THE Flow_Validator SHALL raise `FlowDefinitionError`, SHALL create no Flow, and SHALL send no data to the host. The error message SHALL name the Step_Index (when a Step applies), the field name and the rule violated.
14. IF several checks of this requirement fail for the same Flow, THEN THE Flow_Validator SHALL raise a single `FlowDefinitionError` that reports the failure of the lowest Step_Index first, and for failures with no Step, the failure of the lowest criterion number of this requirement first.
15. THE `FlowDefinitionError` message SHALL NOT contain the text of any YAML scalar other than the field name, the Step kind, the Flow_Name, a Signature_Name or an Input or Output name.

### Requirement 6: YAML Serialization

**User Story:** As a contributor, I want flows stored as YAML so that humans review them and the recorder can write them.

#### Acceptance Criteria

1. THE Flow_Serializer SHALL provide `Flow.to_yaml() -> str` and `Flow.from_yaml(text: str, signatures=None) -> Flow`, and the Flow_Loader SHALL provide `load_flow(path, signatures=None) -> Flow`.
2. THE Flow_Serializer SHALL parse YAML with `yaml.safe_load` only and SHALL emit YAML with `yaml.safe_dump` only, with `sort_keys=False` and a fixed key order.
3. THE Flow_Serializer SHALL emit a `version` key as the first key with the integer value 1.
4. FOR ALL valid Flows, parsing the output of `to_yaml()` with `from_yaml()` SHALL produce a Flow equal to the original (round-trip property), including strings that contain quotes, backslashes, colons, leading spaces, trailing spaces, and the empty string.
5. FOR ALL equal Flows, two calls of `to_yaml()` SHALL return identical strings.
6. IF a YAML document is malformed, is not a mapping, has an unknown key, lacks a required key, has a value of the wrong type, or declares a `version` other than the integer 1 (including the boolean `true`, the string `"1"`, the float `1.0`, and a missing `version`), THEN THE Flow_Loader SHALL raise `FlowDefinitionError` whose message names the offending key. WHERE the offending value is inside a list, THE message SHALL also include the zero-origin index of the offending item. THE Flow_Loader SHALL return no partial Flow.
7. IF the file given to `load_flow` does not exist, is a directory, cannot be read because of a permission or I/O error, or is not valid UTF-8, THEN THE Flow_Loader SHALL raise `FlowDefinitionError` whose message states that the file could not be read and includes the path given.
8. WHEN a `FlowDefinitionError` is raised for a YAML problem or an unreadable file, THE Flow_Loader SHALL raise it with `from None` so that `__cause__` and `__context__` are `None`.
9. IF `from_yaml` is called with text that is empty or contains only whitespace, THEN THE Flow_Serializer SHALL raise `FlowDefinitionError` whose message states that the document is not a mapping.

### Requirement 7: Session Protocol

**User Story:** As a test author, I want the runtime to need only a small protocol so that I can test flows without a terminal host.

#### Acceptance Criteria

1. THE Flow_Runner SHALL call a Session only through the methods `read_screen`, `string`, `enter`, `clear`, `pf` and `pa`.
2. THE Flow_Runner SHALL NOT call `close` on a Session at any point during `run_flow`, including when `run_flow` raises, because the caller of `run_flow` owns the Session lifecycle.
3. THE Flow_Runner SHALL accept an instance of `greenscreen.connector.Connector` as a Session without an adapter, wrapper or subclass.
4. WHEN executing a Type_Step, THE Flow_Runner SHALL call `string` exactly once with the declared text unchanged, with no added, removed or altered characters.
5. WHEN executing a Key_Step with `key` equal to `pf` or `pa`, THE Flow_Runner SHALL call `pf` or `pa` respectively exactly once with the declared integer `n`.
6. IF a Session method (`read_screen`, `string`, `enter`, `clear`, `pf` or `pa`) raises any exception that is an `Exception` and not already a `FlowError` (including `ConnectorError`, `OSError`, `RuntimeError` and any other class), THEN THE Flow_Runner SHALL stop executing further Steps, release the Run_State, and raise `FlowError` with `reason` equal to `session_error`, with `__cause__` and `__context__` equal to `None` and `__suppress_context__` true (raised `from None` outside any `except` block). Requirement 14, criteria 9 and 10 define the message and the release order.
7. THE Flow_Runner SHALL perform no network, subprocess or file I/O of its own, so that a test double Session is the only channel through which `run_flow` communicates outside the process.
8. IF a Session method raises a `BaseException` that is not an `Exception` (for example `KeyboardInterrupt` or `SystemExit`), THEN THE Flow_Runner SHALL release the Run_State, run no Finally_Step, send no further key, and let that exception propagate unchanged (the same object, not wrapped, not converted to `FlowError`). The release SHALL happen before the exception leaves `run_flow`.
9. IF a Session method raises a `FlowError` (criterion 6 excludes it from conversion), THEN THE Flow_Runner SHALL release the Run_State and let that `FlowError` propagate unchanged.

### Requirement 8: Screen-Gated Execution

**User Story:** As an operator, I want every keystroke guarded by a verified screen so that a flow never sends keys into the wrong place.

#### Acceptance Criteria

1. WHEN an Expect_Step runs, THE Flow_Runner SHALL call `read_screen` and then `recognize` against the Flow_Signatures once per attempt, sleeping Poll_Interval seconds on the Clock between consecutive attempts, until the screen is accepted or the Step timeout (the Step `timeout`, default Timeouts `step`) elapses. The Step timeout is measured on the Clock from the start of the Expect_Step, and the Flow_Runner SHALL make at least one attempt.
2. WHEN `recognize` returns a name in `signatures` of the Expect_Step, THE Flow_Runner SHALL accept the screen, make it the Current_Screen and continue with the next Step.
3. WHEN `recognize` returns a name in `tolerate` of the Expect_Step, THE Flow_Runner SHALL send no key and SHALL continue polling until the Step timeout.
4. WHEN `recognize` raises `UnknownScreenError` during polling, THE Flow_Runner SHALL send no key and SHALL continue polling until the Step timeout.
5. IF the Step timeout elapses and the last `recognize` call raised `UnknownScreenError`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `unknown_screen`, the Step_Index, the expected names sorted in ascending lexicographic order, and the Redacted_Summary of the last screen read, and SHALL send no further key.
6. IF the Step timeout elapses and the last screen read was recognized as a tolerated name, was recognized as the Pre_Key_Name, or was equal to the Pre_Key_Screen, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `timeout`, the Step_Index, the expected names sorted in ascending lexicographic order, and the Redacted_Summary of the last screen read, and SHALL send no further key.
7. IF `recognize` raises `AmbiguousScreenError`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `ambiguous_screen` before any further `read_screen` call or sleep, with the Step_Index, the expected names sorted in ascending lexicographic order, and the Redacted_Summary of the screen read, and SHALL send no further key.
8. IF `recognize` returns a name that is in none of `signatures` of the Expect_Step, `tolerate` of the Expect_Step and the Pre_Key_Name (Pre_Key_Name applies as in criteria 20 and 21), THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `unexpected_screen` before any further `read_screen` call or sleep, with the Step_Index, the expected names sorted in ascending lexicographic order, and the Redacted_Summary of the screen read, and SHALL send no further key.
9. WHEN the Flow_Runner reaches a Key_Step, THE Flow_Runner SHALL call `read_screen` exactly once to obtain the Pre_Key_Screen and SHALL compare the field geometry of the Pre_Key_Screen with the field geometry of the Current_Screen. Two field geometries are equal when both Screens have the same fields with the same start positions, lengths and attributes. The cursor position MAY differ. WHEN the field geometries are equal, THE Flow_Runner SHALL build the Comparison_Screen from the Pre_Key_Screen by restoring the cells of every Typed_Field to their content on the Current_Screen, SHALL call `recognize` on the Comparison_Screen, and SHALL send the key only when the result equals the name of the Current_Screen. WHEN the Typed_Fields are empty, THE Comparison_Screen SHALL have the same cells as the Pre_Key_Screen.
10. IF, at a Key_Step, the field geometry of the Pre_Key_Screen differs from the field geometry of the Current_Screen, or `recognize` on the Comparison_Screen returns a name different from the Current_Screen, THEN THE Flow_Runner SHALL treat the Pre_Key_Screen as a different screen, SHALL raise `FlowError` with `reason` `unexpected_screen`, the Step_Index and the Redacted_Summary of the Pre_Key_Screen as read, and SHALL send no key. WHEN the field geometry differs, THE Flow_Runner SHALL NOT call `recognize` for that Key_Step.
11. IF, at a Key_Step, `recognize` on the Comparison_Screen raises `UnknownScreenError`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `unknown_screen`, the Step_Index and the Redacted_Summary of the Pre_Key_Screen as read, and SHALL send no key. IF it raises `AmbiguousScreenError`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `ambiguous_screen`, the Step_Index and the Redacted_Summary of the Pre_Key_Screen as read, and SHALL send no key.
12. WHEN a key has been sent, THE Flow_Runner SHALL clear the Current_Screen, and WHILE a screen read equals the Pre_Key_Screen exactly as read (not the Comparison_Screen) in both cell content and cursor position, THE Flow_Runner SHALL treat it as "no answer yet", SHALL send no key, SHALL NOT act on its recognition result, and SHALL continue polling every Poll_Interval seconds until the Step timeout.
13. WHEN a screen read after a key differs from the Pre_Key_Screen in cell content or cursor position, THE Flow_Runner SHALL apply criteria 2 to 8 to that screen.
14. THE Flow_Runner SHALL send at most one key per accepted screen, so that two consecutive Key_Steps are separated by an accepted screen that differs from the Pre_Key_Screen of the first.
15. WHILE the Current_Screen is absent, THE Flow_Runner SHALL send no key.
16. IF `recognize` raises `SignatureError` or `TypeError`, THEN THE Flow_Runner SHALL raise `FlowDefinitionError` and SHALL send no further key.
17. WHEN a Type_Step types into the cursor field of the Current_Screen, THE Flow_Runner SHALL add that field to the Typed_Fields, identified by its start position and length on the Current_Screen, so that typing twice into the same field gives one entry.
18. WHEN a new Current_Screen is accepted, and WHEN a key is sent, THE Flow_Runner SHALL empty the Typed_Fields.
19. THE Flow_Runner SHALL take the restored cells of every Typed_Field, hidden or not, from the Current_Screen and SHALL make no other copy of Typed_Field cell content, so that the Flow_Runner keeps only what the Comparison_Screen needs. THE Flow_Runner SHALL build the Comparison_Screen without reading the `text` of a hidden Typed_Field (Requirement 10, criterion 7). For a hidden Typed_Field the restored cells are the cells of the Current_Screen, which the Flow_Runner SHALL hold only inside the runner for the duration of the check and SHALL NOT place in any log record, `FlowError` message, `args` or attribute, Audit_Record, FlowResult or attribute, in line with Requirement 14, criterion 7 and Requirement 16, criterion 3. THE Flow_Runner SHALL release the Comparison_Screen before it raises any FlowError.
20. WHILE a key has been sent and no screen has been accepted since, THE Flow_Runner SHALL tolerate the Pre_Key_Name in the same way as a name in `tolerate`: WHEN `recognize` returns the Pre_Key_Name and that name is not in `signatures` of the Expect_Step, THE Flow_Runner SHALL send no key and SHALL continue polling until the Step timeout, without raising `unexpected_screen`. THE Flow_Runner SHALL NOT add the Pre_Key_Name to the `expected` names of a FlowError. WHEN the Pre_Key_Name is in `signatures` of the Expect_Step, criterion 2 applies.
21. WHILE the Pre_Key_Name is absent, THE Flow_Runner SHALL apply no implicit tolerance, so that the first Expect_Step of a Flow, before any key is sent, raises `unexpected_screen` for a recognized name that is in neither `signatures` nor `tolerate`.

### Requirement 9: Handle Steps

**User Story:** As a flow author, I want to handle optional screens with a hard cap so that a TSO pause screen never turns into an endless loop.

#### Acceptance Criteria

1. WHEN a Handle_Step runs, THE Flow_Runner SHALL obtain a recognized screen by polling as in Requirement 8, criteria 1 and 4. It SHALL treat the Handle_Step `signature` and every other name of the Flow_Signatures as accepted names, so that any name returned by `recognize`, including the Pre_Key_Name, ends polling and raises no `unexpected_screen` error (Requirement 8, criterion 20 adds no tolerance here). It SHALL reuse the Current_Screen without calling `read_screen` when the Current_Screen is present. It SHALL stop polling after the Step timeout, and IF the last `recognize` call at that time raised `UnknownScreenError`, THEN it SHALL raise `FlowError` with `reason` `unknown_screen` as in Requirement 8, criterion 5.
2. WHILE the recognized screen equals the Handle_Step `signature` and fewer than `max_count` body iterations have run, THE Flow_Runner SHALL run the body Steps in order with the recognized screen as the Current_Screen. It SHALL then obtain the next recognized screen as in criterion 1, treating any screen identical to the Pre_Key_Screen as read, in cell content and cursor position, as "no answer yet" (Requirement 8, criteria 12 and 13). The Step timeout SHALL restart for each such wait.
3. WHEN the recognized screen is not the Handle_Step `signature`, THE Flow_Runner SHALL end the Handle_Step, SHALL keep that screen as the Current_Screen for the next Step, and SHALL record the Handle_Step as `ok` with the number of body iterations run (0 to `max_count`).
4. IF the recognized screen still equals the Handle_Step `signature` after `max_count` body iterations have run and the next recognized screen has been obtained, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `loop_limit` naming the Step_Index, SHALL record the Handle_Step as `failed`, and SHALL send no further key.
5. WHERE a Handle_Step has `settle` greater than 0 (0 to 10 seconds), WHEN the first recognized screen equals `signature`, THE Flow_Runner SHALL read and recognize the screen every Poll_Interval seconds, measured on the Clock, for up to `settle` seconds before running the body. IF the recognized screen becomes a different name within that time, THEN THE Flow_Runner SHALL run no body iteration, SHALL keep that screen as the Current_Screen, and SHALL record the Handle_Step as `ok` with iteration count 0. IF an `UnknownScreenError` occurs during the settle period, THEN THE Flow_Runner SHALL continue reading until `settle` elapses. IF the screen still equals `signature` when `settle` elapses, THEN THE Flow_Runner SHALL run the body.
6. WHEN the first recognized screen is not the Handle_Step `signature`, THE Flow_Runner SHALL run no body iteration, SHALL keep that screen as the Current_Screen, and SHALL record the Handle_Step as `ok` with iteration count 0.
7. THE Flow_Runner SHALL run at most `max_count` (1 to 20) body iterations of one Handle_Step in one run, and SHALL send no key from a body iteration beyond that count.
8. THE Flow_Runner SHALL apply Requirement 8, criteria 9 to 11 and 17 to 19 (pre-key check, Typed_Fields and Comparison_Screen) to every Type_Step and Key_Step in a handle body, with the recognized screen of that iteration as the Current_Screen.

### Requirement 10: Typing and Secret Inputs

**User Story:** As a security reviewer, I want secrets typed only into hidden fields so that a password never lands in a visible field or a log.

#### Acceptance Criteria

1. WHEN a Type_Step runs, THE Flow_Runner SHALL locate the cursor field with `ScreenView.containing_field` of `greenscreen.recognizer.view`, applied to the Current_Screen cursor position, and SHALL require that field to exist and to be unprotected. `containing_field` returns only the field geometry and the `protected` and `hidden` flags and never reads `Field.text`, which is consistent with criterion 7.
2. IF the cursor field does not exist or is protected, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `bad_target`, the Step_Index and the Redacted_Summary, SHALL call `Session.string` zero times for that Step, and SHALL leave the Current_Screen unchanged.
3. IF a Type_Step references a Secret_Input and the cursor field is not hidden, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `secret_target`, the Step_Index and the Redacted_Summary, SHALL call `Session.string` zero times for that Step, and SHALL leave the Current_Screen unchanged.
4. WHEN a Type_Step references a Secret_Input and the cursor field is unprotected and hidden, THE Flow_Runner SHALL call `Session.string` exactly once for that Step with the rendered Secret_Value.
5. WHEN a Type_Step references an Input that is not a Secret_Input and the cursor field is unprotected, THE Flow_Runner SHALL call `Session.string` exactly once for that Step with the rendered value, whether the field is hidden or not.
6. WHERE an optional Input (with `required` false) was not supplied, THE Flow_Runner SHALL skip each Type_Step that references it, SHALL record that Step as `skipped`, and SHALL call `Session.string` zero times for that Step.
7. THE Flow_Runner SHALL determine the hidden flag of the cursor field without reading the `text` of a hidden field.
8. THE Flow_Runner SHALL pass a Secret_Value only to `Session.string`, and SHALL hold it in no object that outlives the Type_Step, apart from the caller's own `inputs` mapping.
9. THE Flow_Runner SHALL exclude every Secret_Value from the `FlowError` message, the Redacted_Summary, and all log output.

### Requirement 11: Extraction

**User Story:** As an API consumer, I want outputs read only from the screen the flow just verified.

#### Acceptance Criteria

1. WHEN an Extract_Step runs, THE Flow_Runner SHALL read the Output from the Current_Screen and SHALL NOT call `read_screen` for it.
2. THE Flow_Runner SHALL read an Output only when the Current_Screen name equals the `signature` of the Output.
3. IF the Current_Screen name differs from the Output `signature`, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `unexpected_screen`, `step_index` of the Extract_Step, `expected` holding the Output `signature` as a one-element tuple, and `summary` holding the Redacted_Summary of the Current_Screen built from the screen cells (hidden cells shown as `*`), and SHALL read no cell of the Output region. WHEN no Current_Screen exists, `summary` SHALL be `None`.
4. THE Flow_Runner SHALL never read Output text from a hidden field (Requirement 3, criterion 7).

### Requirement 12: Timeouts and Bounds

**User Story:** As an operator, I want every wait to have a limit so that a stuck host cannot hang a caller.

#### Acceptance Criteria

1. THE Flow_Runner SHALL enforce the Step timeout for each Expect_Step and for each wait inside a Handle_Step, as in Requirement 8.
2. WHILE the main `steps` run, THE Flow_Runner SHALL track elapsed Clock time from the start of the run, and WHEN the elapsed time reaches Timeouts `run`, THE Flow_Runner SHALL stop before the next Session call and raise `FlowError` with `reason` `run_timeout`.
3. WHILE Finally_Steps run, THE Flow_Runner SHALL track elapsed Clock time from the start of the Finally_Steps, and WHEN that time reaches Timeouts `finally`, THE Flow_Runner SHALL stop before the next Session call and record the failure per Requirement 13.
4. THE Flow_Runner SHALL read the time only through the Clock and SHALL sleep only through the Clock.
5. THE Flow_Runner SHALL sleep Poll_Interval seconds between reads in every polling loop and SHALL accept a Poll_Interval from 0.01 to 1.
6. THE Flow_Runner SHALL execute at most `max_count` body iterations per Handle_Step and at most 200 Steps per Flow definition, so that a Flow terminates for every Session behavior.

### Requirement 13: Finally Steps

**User Story:** As an operator, I want cleanup such as logoff to run after a failure, but never into an unknown screen.

#### Acceptance Criteria

1. WHEN the main `steps` finish without error, THE Flow_Runner SHALL run the Finally_Steps in the order declared, starting with the Current_Screen carried over from the last main step.
2. WHEN the main `steps` stop with a FlowError and the Flow_Runner holds a Current_Screen that was recognized as a known name, THE Flow_Runner SHALL run the Finally_Steps in the order declared, starting with that Current_Screen.
3. IF the main `steps` stop with `reason` `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error` or `input_invalid`, or stop because a FlowDefinitionError is raised during the run (Requirement 8, criterion 16, for example when a Signature_Name is missing from the signature set), THEN THE Flow_Runner SHALL skip all Finally_Steps, SHALL send zero keys to the host during the Finally phase, and SHALL record each skipped Finally_Step as `skipped` in the audit trail.
4. THE Flow_Runner SHALL apply every rule of Requirements 8 to 11 to Finally_Steps, so that a key in `finally` is sent only after an accepted screen.
5. IF a Finally_Step fails and the main `steps` had already failed, THEN THE Flow_Runner SHALL record that Finally_Step as `failed` in the audit trail and SHALL raise the FlowError of the main `steps`, leaving the main FlowError's `reason` unchanged.
6. IF a Finally_Step fails and the main `steps` had succeeded, THEN THE Flow_Runner SHALL record that Finally_Step as `failed` in the audit trail and SHALL raise the FlowError of the Finally_Step.
7. WHEN every Finally_Step has been run or skipped and no FlowError is pending, THE Flow_Runner SHALL return the FlowResult. THE Flow_Runner SHALL NOT return or raise before the status of every Finally_Step is recorded in the audit trail.
8. IF a Finally_Step fails, THEN THE Flow_Runner SHALL NOT run any later Finally_Step, SHALL send zero further keys, and SHALL record each later Finally_Step as `skipped` in the audit trail.
9. IF the main `steps` stop with a FlowError and the Flow_Runner holds no Current_Screen, THEN THE Flow_Runner SHALL skip all Finally_Steps, SHALL send zero keys to the host during the Finally phase, and SHALL record each skipped Finally_Step as `skipped` in the audit trail.
10. FOR EACH Unmatched_Handle in `steps` or in `finally`, THE Flow_Runner SHALL append exactly one Audit_Record to the audit trail for every Body_Step of that Handle_Step, with `status` `skipped`, `duration_seconds` 0.0, `iteration` None and `signature` None, immediately after the Audit_Record of the Handle_Step in depth-first order, on every path (a run that returns, a run that raises `FlowError` and a run that raises `FlowDefinitionError`). The Audit_Record of the Unmatched_Handle itself SHALL keep `status` `ok`.
11. THE Flow_Runner SHALL treat a Body_Step that never began because its Handle_Step ran zero iterations as a Step with a recorded status of `skipped`, which refines Requirement 15, criterion 2 ("each Step it begins") and satisfies criterion 7 (the status of every Finally_Step is recorded). A Body_Step inside a skipped Finally_Step (criteria 3, 8 and 9) SHALL likewise receive exactly one `skipped` Audit_Record, so that no Step_Index of `finally` is without a record when `run_flow` returns or raises.
12. WHEN a Handle_Step ran k body iterations with k at least 1, THE Flow_Runner SHALL record each Body_Step that began with its normal Audit_Record per iteration (`iteration` 1 to k) and SHALL append no `skipped` Audit_Record for a Body_Step of that Handle_Step in `steps`.
13. IF a Handle_Step stops with `reason` `loop_limit`, THEN THE Flow_Runner SHALL record the Handle_Step as `failed`, SHALL keep the normal Audit_Records of iterations 1 to `max_count` of every Body_Step (all of which ran), and SHALL append no `skipped` Audit_Record for its Body_Steps.
14. IF a Handle_Step fails inside a body iteration in `finally`, THEN THE Flow_Runner SHALL record each Body_Step that has no Audit_Record at all as `skipped` under criterion 8, with `iteration` None, and SHALL append no `skipped` Audit_Record for a Body_Step that already has one.

### Requirement 14: FlowError

**User Story:** As an operator reading a failed run, I want to know the step, the screens we expected and what we saw, without exposing secrets.

#### Acceptance Criteria

1. IF a Flow_Runner run fails, THEN THE Flow_Runner SHALL raise `FlowError` with the attributes `reason` (a Reason_Code), `step_index`, `expected`, `summary` and `audit`.
2. IF `FlowError` has `reason` `timeout`, `unknown_screen`, `ambiguous_screen` or `unexpected_screen`, THEN THE Flow_Runner SHALL set `step_index` to the zero-based Step_Index of the failing Step, `expected` to a tuple of the accepted Signature_Names sorted in ascending lexicographic order, and `summary` to the Redacted_Summary of the last screen read.
3. IF `FlowError` has a `reason` other than `timeout`, `unknown_screen`, `ambiguous_screen` or `unexpected_screen`, THEN THE Flow_Runner SHALL set `step_index` to the Step_Index of the failing Step, or to `None` when no Step had begun, set `expected` to an empty tuple, and set `summary` to `None` when no screen was read.
4. THE FlowError message SHALL be a single line of at most 500 characters, containing the Reason_Code, the Step_Index, the Step kind, the expected Signature_Names and their count, and no screen text and no input value.
5. THE `str()` and `repr()` of FlowError, FlowDefinitionError and FlowInputError SHALL contain no Secret_Value and no content of any hidden cell.
6. THE Flow_Runner SHALL raise every FlowError with `from None` outside any `except` block.
7. THE Flow_Runner SHALL hold no `Screen`, `cell_grid`, `Field` or input value in the `args` of FlowError, in its attributes, or in the locals of traceback frames inside `greenscreen.flow`.
8. THE `audit` attribute SHALL hold the Audit_Records of all Steps that began before the failure, in execution order, including the failed Step with `status` `failed`, and the `skipped` Audit_Records of Requirement 13, criteria 8 to 11 and 14.
9. IF a Session method raises an exception under Requirement 7, criterion 6, THEN THE Flow_Runner SHALL raise `FlowError` with `reason` `session_error` and a message that contains only the Reason_Code, the exception class name (`type(exc).__name__`) and the Step_Index (criterion 4 format with no exception message, no `args` of the exception and no `repr` of the exception), and SHALL raise it `from None` after the Run_State has been released, so that the Session exception, its message and its `args` are held by no attribute of the FlowError.
10. WHEN a `FlowError` with `reason` `session_error` is raised, THE Flow_Runner SHALL have released the Run_State before the raise, so that no traceback frame inside `greenscreen.flow` holds a Screen, an input value, the inputs mapping, a Typed_Field, the Comparison_Screen or the Pre_Key_Screen in its locals (criterion 7), and `traceback.format_exception` with chain and `__context__` shows no text of the Session exception.
11. IF `FlowError` has `reason` `unexpected_screen` and the failing Step is an Extract_Step, THEN THE Flow_Runner SHALL set `step_index` to the Step_Index of the Extract_Step, `expected` to a one-element tuple holding the Output `signature`, and `summary` to the Redacted_Summary of the Current_Screen, or to `None` when no Current_Screen exists (Requirement 11, criterion 3).

### Requirement 15: FlowResult and Audit Trail

**User Story:** As a compliance reviewer, I want a record of what ran, with no screen text or inputs in it.

#### Acceptance Criteria

1. WHEN a run finishes without error, THE Flow_Runner SHALL return a `FlowResult` with `flow`, `outputs` and `audit`.
2. THE Flow_Runner SHALL append one Audit_Record for each Step it begins, with `step_index`, `kind`, `phase`, `iteration` (the body iteration number starting at 1 for Steps inside a Handle_Step, otherwise None), `signature` (the recognized name or None), `status` and `duration_seconds` measured with the Clock.
3. THE Audit_Record SHALL contain no screen text, no Field tuple, no input value and no output value.
4. THE Flow_Runner SHALL record `skipped` Steps (Requirement 10, criterion 6 and Requirement 13, criteria 3, 8 and 9) with `duration_seconds` 0.0.
5. THE `repr()` of FlowResult and Audit_Record SHALL show no input value, and the FlowResult `repr` MAY show Output names only.
6. FOR ALL runs on the same Flow, the same Inputs and the same sequence of Screens served by the Session, THE Flow_Runner SHALL return equal `outputs`, send the same sequence of Session key and typing calls, and write an audit trail that is equal in every field except `duration_seconds`.
7. THE Flow_Runner SHALL give every Body_Step of an Unmatched_Handle exactly one Audit_Record with `status` `skipped`, `duration_seconds` 0.0, `iteration` None and `signature` None, in `steps` and in `finally`, on every path (Requirement 13, criteria 10 to 14). This extends criteria 2 and 4: a Body_Step that never began is recorded as `skipped` although criterion 2 appends a record for each Step it begins.
8. THE Flow_Runner SHALL build `FlowResult.outputs` with its keys in the order in which the Outputs are declared in the Flow (Requirement 3, criterion 10). For `tk5-system-info` that order is `USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL` (Requirement 17, criterion 20).

### Requirement 16: Secret Handling and Logging

**User Story:** As a security-conscious maintainer, I want a guarantee that a password cannot leak through the runtime.

#### Acceptance Criteria

1. THE Flow_Runner SHALL NOT place a Secret_Value in any FlowResult, Audit_Record, exception message, exception attribute, `repr()` output or log record, including when a flow run ends in success, failure or an unhandled exception.
2. THE Flow_Runner SHALL emit log records only through the standard `logging` module under the logger name `greenscreen.flow`, at DEBUG level, and each record SHALL contain only one or more of the following fields: Flow_Name, Step_Index, Step kind, Signature_Name, a count (non-negative integer), a Reason_Code, or a duration (in milliseconds).
3. THE Flow_Runner SHALL NOT read the `text` of any hidden field, SHALL NOT pass a Screen object to a logger, and SHALL NOT store a Screen object in an Audit_Record, FlowResult or exception.
4. WHEN the Flow_Runner needs a summary of a Screen, THE Flow_Runner SHALL obtain it only from the recognizer's Redacted_Summary, in which every hidden cell is shown as `*`.
5. THE Flow_Loader SHALL NOT read any environment variable.
6. THE shipped YAML files and the Test_Suite fixtures SHALL contain no host credential, and the integration test (Requirement 20) SHALL read `TK5_USERNAME` and `TK5_PASSWORD` from the environment only.
7. WHEN the Flow_Runner recognizes the first Screen after the password prompt, THE Flow_Runner SHALL ignore the residual password in the hidden cells of that Screen and SHALL NOT treat its presence as an error.
8. IF a Flow_Runner operation raises an exception while a Secret_Value is in use, THEN THE Flow_Runner SHALL propagate an exception whose message, attributes and `repr()` output contain no Secret_Value, and SHALL leave no Secret_Value in the FlowResult or Audit_Record.
9. IF a Session method raises an exception that carries a Secret_Value in its message or `args`, THEN THE Flow_Runner SHALL raise the `session_error` FlowError of Requirement 14, criteria 9 and 10, so that the Secret_Value is absent from `str()`, `repr()`, `args` and the attributes of the FlowError, from the output of `traceback.format_exception` (with chain), and from the locals of every `greenscreen.flow` traceback frame.

### Requirement 17: Shipped Flows

**User Story:** As a developer, I want ready-made TK5 flows so that logon, logoff and a first useful transaction work out of the box.

#### Acceptance Criteria

1. THE Flow_Loader SHALL ship exactly three YAML Flows as package data in `greenscreen/flow/flows/`: `tk5-logon.yaml`, `tk5-logoff.yaml` and `tk5-system-info.yaml`.
2. WHEN `load_bundled_flows() -> dict[str, Flow]` is called from any working directory, THE Flow_Loader SHALL return a dict with exactly three entries, keyed by Flow_Name `tk5-logon`, `tk5-logoff` and `tk5-system-info`.
3. IF a bundled Flow file is missing or fails to parse when `load_bundled_flows()` is called, THEN THE Flow_Loader SHALL raise `FlowDefinitionError` that names the affected file and SHALL return no partial dict.
4. THE `tk5-logon` Flow SHALL declare the Input `userid` (`str`, required, `max_length` 8, `regex` `[A-Za-z0-9@#$]{1,8}`) and the Secret_Input `password` (`str`, required, `max_length` 8), SHALL declare no Output, and SHALL end on an Expect_Step for `ispf-primary-menu`.
5. THE `tk5-logon` Flow SHALL contain a Handle_Step on `tk5-logo` with `settle` of at least 3 seconds whose body is one Key_Step `enter`, so that Enter is pressed only if the logo is still showing after the settle period (steering GOTCHA).
6. THE `tk5-logon` Flow SHALL contain a Handle_Step on `tso-input-not-recognized` whose body is one Key_Step `clear` (the verified recovery).
7. THE `tk5-logon` Flow SHALL contain a Handle_Step on `tso-pause` with `max_count` 5 and a body of one Key_Step `enter`.
8. THE `tk5-logon` Flow SHALL, after an Expect_Step for `tk5-logon`, type `userid` and press `enter`, then after an Expect_Step for `tso-password-prompt` type `password` and press `enter`, and SHALL contain no other Type_Step that types an Input.
9. THE `tk5-logoff` Flow SHALL declare no Input and no Output.
10. THE `tk5-logoff` Flow SHALL contain exactly these Steps in order: an Expect_Step for `ispf-primary-menu`, a Type_Step with the literal `X`, a Key_Step `enter`, an Expect_Step for `tso-ready`, a Type_Step with the literal `LOGOFF`, a Key_Step `enter`, and an Expect_Step for `tk5-logon`.
11. THE `tk5-system-info` Flow SHALL declare the same Inputs as `tk5-logon` and SHALL declare the Outputs `USERID`, `SYSTEMID`, `RELEASE` and `TERMINAL`, each `str` and each taken from `ispf-primary-menu`.
12. THE `tk5-system-info` Flow SHALL contain, in order, the Steps of `tk5-logon`, the four Extract_Steps, and the Steps of `tk5-logoff`.
13. THE Output regions of `tk5-system-info` SHALL be: `USERID` at row 2, col 71, length 8; `TERMINAL` at row 4, col 71, length 8; `RELEASE` at row 10, col 71, length 8; and `SYSTEMID` at row 12, col 71, length 8 (rows and columns as numbered in `captures/ispf-primary-menu`).
14. THE Test_Suite SHALL verify that, in `captures/ispf-primary-menu`, each of the four Output regions lies within the screen bounds and that the text at col 60 of the same row is the label for that Output.
15. THE `tk5-system-info` Flow SHALL declare Finally_Steps, in this order: a Handle_Step on `ispf-primary-menu` (Type_Step `X`, Key_Step `enter`) with `max_count` 1, a Handle_Step on `tso-ready` (Type_Step `LOGOFF`, Key_Step `enter`) with `max_count` 1, and an Expect_Step for `tk5-logon`.
16. WHEN the `tk5-system-info` run is scripted against Screens loaded from `captures/`, THE Flow_Runner SHALL return exactly the keys `USERID`, `SYSTEMID`, `RELEASE` and `TERMINAL`, each equal to the capture text at its Output region with leading and trailing whitespace removed.
17. THE Test_Suite SHALL verify that the first Steps of `tk5-system-info` equal the Steps of `tk5-logon`, and that the Steps after the four Extract_Steps equal the Steps of `tk5-logoff`, so that the three Flows cannot drift.
18. THE bundled Flows SHALL pass the Flow_Validator against `load_bundled_signatures()` with zero errors.
19. THE bundled Flow files SHALL contain no literal userid or password value, and SHALL reference credentials only through the Inputs `userid` and `password`.
20. THE `tk5-system-info` Flow SHALL declare its Outputs in the order `USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL` (the order of criterion 11, not the order of criterion 13), so that `list(result.outputs)` equals that list (Requirement 3, criterion 10, and Requirement 15, criterion 8). It refines criterion 16, which fixes the set of keys.

### Requirement 18: Scripted Session and Unit Tests

**User Story:** As a developer, I want deterministic tests without a terminal host.

#### Acceptance Criteria

1. THE Test_Suite SHALL provide a Scripted_Session in `tests/flow_support.py` that implements the Session protocol, serves Screens from an ordered list of states, and records every call in the order it was made.
2. WHEN a key call (`enter`, `clear`, `pf`, or `pa`) is made on the Scripted_Session, THE Scripted_Session SHALL advance to the next state in the list, and SHALL stay on the last state without raising an error if no next state exists.
3. WHERE a state defines a `stale_reads` count N (integer, 0 to 10, default 0), THE Scripted_Session SHALL return the previous state's Screen for the first N reads after a key call and the state's own Screen from read N+1 onward, to model the steering GOTCHA that one read after Enter can still show the old screen.
4. THE Scripted_Session SHALL load every Screen through `load_capture_screen` of `tests/screen_support.py` (the `captures/*.readbuffer.txt` files and `ScreenParser`) or through `make_screen`, and SHALL NOT start a subprocess or a fake s3270.
5. THE Scripted_Session SHALL provide a screen based on a synthetic copy of `tso-password-prompt` in which the hidden field cells contain a sentinel string (non-empty, at most 8 characters, not present in any file under `captures/`), to model the residual password.
6. THE Test_Suite SHALL provide a fake Clock whose time starts at 0.0 seconds, increases by exactly the number of seconds passed to each sleep call, and returns from sleep without waiting, and SHALL use it in every runner test.
7. THE Test_Suite SHALL include unit tests in `tests/unit/`, each of which passes without a terminal host, covering: each Step kind (one test per kind); each rule of Requirements 2 to 5 (one test per rule); each Reason_Code (one test per code); each flow YAML error (one test per error); the `settle` rule; the stale-read rule; the finally rules; and the three bundled Flows run against scripted captures.
8. WHEN the Scripted_Session is driven by the `tk5-logon` Flow with the screens `tk5-logo`, `tk5-logon`, `tso-password-prompt`, two pause screens, and `ispf-primary-menu` in that order, THE Test_Suite SHALL assert that the recorded calls are exactly, in order: `enter`, `string(userid)`, `enter`, `string(password)`, `enter`, `enter`, `enter`, and that the run ends with the `ispf-primary-menu` Screen.
9. WHEN the Scripted_Session is driven by the `tk5-logon` Flow starting at the `tso-input-not-recognized` screen, THE Test_Suite SHALL assert that the first recorded key call is `clear`.
10. THE Test_Suite SHALL NOT create or add a capture of the screen that holds the typed password, as the steering file forbids it.
11. THE Test_Suite SHALL include one unit test for each typed screen of the shipped Flows, each building the Pre_Key_Screen in memory from the accepted capture by writing the typed text into the cursor field cells, and each asserting that the following key is sent and no FlowError is raised: the userid typed at `tk5-logon`, the password typed at `tso-password-prompt` (a hidden field, using a sentinel as the typed text), `X` typed at `ispf-primary-menu`, and `LOGOFF` typed at `tso-ready`.
12. THE Test_Suite SHALL include a unit test in which a typed screen whose field geometry differs from the Current_Screen (a changed field start position, length or attribute) blocks the key, so that `FlowError` with `reason` `unexpected_screen` is raised and zero key calls reach the Scripted_Session (Requirement 8, criterion 10).
13. THE Test_Suite SHALL include a unit test in which, after a key, the Scripted_Session serves a partial repaint recognized as the Pre_Key_Name and then the expected screen, and the run succeeds with no extra key call (Requirement 8, criterion 20).
14. THE Test_Suite SHALL include a unit test in which, after a key, the Scripted_Session serves a screen recognized as the Pre_Key_Name (differing from the Pre_Key_Screen in cell content) until the Step timeout elapses, and the run raises `FlowError` with `reason` `timeout`, the Step_Index, the expected names and a Redacted_Summary (Requirement 8, criterion 6).
15. THE Test_Suite SHALL include a unit test in which the first Expect_Step of a Flow, before any key is sent, meets a screen recognized as a name in neither `signatures` nor `tolerate`, and the run raises `FlowError` with `reason` `unexpected_screen` (Requirement 8, criterion 21).
16. THE Test_Suite SHALL assert, in the unit test of criterion 11 for the hidden field, that the sentinel appears in no FlowError, log record, Audit_Record or FlowResult of the run.
17. THE Test_Suite SHALL include one unit test for each of the six Session calls `read_screen`, `string` (on a Type_Step that types a Secret_Input), `enter`, `clear`, `pf` and `pa`, in which a Scripted_Session raises `RuntimeError` whose message and `args` both carry the sentinel, and SHALL assert that `run_flow` raises `FlowError` with `reason` `session_error` and the Step_Index of the failing Step, and that the sentinel is absent from `str()`, `repr()`, `args` and every attribute of the FlowError (Requirement 7, criterion 6, and Requirement 14, criterion 9).
18. IN each test of criterion 17, THE Test_Suite SHALL assert that `__cause__` and `__context__` are `None`, that the message contains the class name `RuntimeError` and no other exception text, that the sentinel is absent from `"".join(traceback.format_exception(err))` (with chain), and, by walking `tb_frame.f_locals` of every traceback frame whose module is in `greenscreen.flow`, that no local is a `Screen`, an input value, the inputs mapping, or a container holding the sentinel (Requirement 14, criterion 10).
19. THE Test_Suite SHALL include a unit test in which a Session method raises `KeyboardInterrupt`, and SHALL assert that the same exception object propagates out of `run_flow`, that no key is sent afterwards, that no Finally_Step runs, and that no `greenscreen.flow` traceback frame holds a Screen or the inputs mapping (Requirement 7, criterion 8).
20. THE Test_Suite SHALL include a unit test that runs `tk5-system-info` against Screens loaded from `captures/` and asserts `list(result.outputs) == ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]`, and a second unit test with a generated Flow whose Extract_Steps run in an order different from the declaration order and whose `outputs` keys still follow the declaration order (Requirement 3, criterion 10).
21. THE Test_Suite SHALL include unit tests for the `skipped` records of Requirement 13, criteria 10 to 14: an Unmatched_Handle in `steps` and one in `finally`, each on a returning run and on a failing run, asserting exactly one `skipped` record per Body_Step with duration 0.0, iteration None and signature None, the Handle_Step record `ok`, and no duplicate Step_Index and iteration pair. They SHALL include a Handle_Step that ran k of 1 and 3 iterations (records with `iteration` 1 to k and no `skipped` record) and a `loop_limit` failure (Handle_Step `failed`, iterations 1 to `max_count` recorded, no `skipped` record).
22. THE Test_Suite SHALL include a unit test in which a FlowDefinitionError is raised during the run (a Signature_Name that `recognize` reports through `SignatureError`) and asserts that no key is sent in the Finally phase and that every Finally_Step is recorded `skipped` (Requirement 13, criterion 3).
23. THE Test_Suite SHALL include a unit test in which an Extract_Step meets a Current_Screen whose name differs from the Output `signature`, and SHALL assert the `unexpected_screen` FlowError has `step_index`, `expected` equal to the one-element tuple of the Output signature, and a Redacted_Summary, and that no cell of the Output region was read (using a Screen double that counts reads of those cells) (Requirement 11, criterion 3, and Requirement 14, criterion 11).
24. THE Test_Suite SHALL include a unit test that a Type_Step locates its target field through `ScreenView.containing_field` and that `Field.text` of a hidden field is never read (Requirement 10, criteria 1 and 7).

### Requirement 19: Property-Based Tests

**User Story:** As a maintainer, I want properties that hold for every generated flow and screen script, not just for the shipped flows.

#### Acceptance Criteria

1. THE Test_Suite SHALL include a Hypothesis property test asserting `Flow.from_yaml(flow.to_yaml()) == flow` for generated valid Flows covering all Step kinds, Inputs with every option and Outputs, and asserting identical `to_yaml()` strings across 2 repeated calls on the same Flow (Property 1).
2. THE Test_Suite SHALL include a Hypothesis property test asserting that, for the same Flow and the same generated Screen script (including stale reads and transient unknown screens), two runs return equal `outputs` and the same ordered sequence of recorded Session key and typing calls (Property 2).
3. THE Test_Suite SHALL include a Hypothesis property test that uses a sentinel Secret_Value of 1 to 8 characters from an alphabet found in no other generated text, runs generated Flows that succeed and fail, and asserts that the sentinel appears in none of: FlowResult `repr` and fields, Audit_Records, every raised exception `str`, `repr`, `args` and attributes, the Redacted_Summary of any FlowError, and every `greenscreen.flow` log record (message and arguments). The generated Flows SHALL include the residual-password Screen. The generated failure modes SHALL also include "session raises with the sentinel": a Session that raises an `Exception` carrying the sentinel in its message and `args` at a generated call (`read_screen`, `string`, `enter`, `clear`, `pf` or `pa`), and in that mode the test SHALL assert in addition that the sentinel is absent from `"".join(traceback.format_exception(err))` of the raised FlowError (Property 3).
4. THE Test_Suite SHALL include a Hypothesis property test asserting that, for generated Screen scripts in which at least 1 screen is unknown or ambiguous, no key or typing call reaches the Session after the Flow_Runner reads that screen and raises FlowError, and that for every key sent the field geometry of the Pre_Key_Screen equaled that of the Current_Screen and the Comparison_Screen built from the Pre_Key_Screen was recognized as the name of the Current_Screen (Property 4).
5. THE Test_Suite SHALL include a Hypothesis property test asserting that, for generated Handle_Steps with `max_count` from 1 to 20 and generated Sessions that show the handled screen forever, the run ends with `loop_limit` after at most `max_count` body iterations and at most `max_count` key calls. The test SHALL also assert that, for Sessions that show the handled screen exactly k times (k from 0 to 20), the run sends exactly k keys when k is at most `max_count` (Property 5).
6. THE Test_Suite SHALL include a Hypothesis property test asserting that stale reads (the Session serving the pre-key screen 0 to 5 more times after a key) cause zero extra key calls and leave `outputs` equal to the outputs of the same run with 0 stale reads. The generated variations SHALL also include 0 to 3 partial repaints recognized as the Pre_Key_Name (differing from the Pre_Key_Screen in cell content) served after the key and before the expected screen, with the same assertions of zero extra key calls and equal `outputs` (Property 6).
7. THE Test_Suite SHALL include a Hypothesis property test asserting that the Flow_Validator rejects every generated Flow containing a Key_Step or Type_Step that has no arming Step, and accepts the same Flow after an Expect_Step is inserted immediately before that Step (Property 7).
8. THE Test_Suite SHALL treat each of the 8 property tests of criteria 1 to 7 and 11 as a required task, SHALL write each as exactly one `@given` test with `@settings(max_examples=100, deadline=None)` or a higher `max_examples`, and SHALL start each with the comment `# Feature: flow-runtime, Property N: <title>`, where N is the property number from 1 to 8.
9. THE Test_Suite SHALL complete all property tests in `tests/property`, including those of the connector, the recognizer and this feature, in under 90 seconds in total on one run, the limit set in Requirement 11.9 of the screen-recognizer spec. THE Test_Suite SHALL complete the flow-runtime property modules in under 35 seconds of that total, using the fake Clock (zero real sleep calls) and in-memory Screens.
10. THE Test_Suite SHALL place the property tests in `tests/property/` in files named `test_flow_*.py` and SHALL place shared strategies in `tests/property/_flow_strategies.py`. THE Test_Suite SHALL pass with zero network connections and zero subprocesses started.
11. THE Test_Suite SHALL include a Hypothesis property test asserting that, for every unprotected cursor field of the screens in `captures/` that the shipped Flows use (`tk5-logon`, `tso-password-prompt`, `ispf-primary-menu` and `tso-ready`), typing any generated printable-ASCII text (U+0020 to U+007E) of length 1 to the field length (at most 255 characters and at most the cells from the cursor to the end of the field) into the cursor field of that accepted screen never blocks the following key, so that the key is sent and no FlowError is raised. THE test SHALL build each typed Pre_Key_Screen in memory, SHALL draw its inputs from the shared strategies module of criterion 10, and SHALL NOT write the typed screen to `captures/` or to any other file (Property 8).

### Requirement 20: Integration Test Against the Live Host

**User Story:** As a developer, I want one end-to-end test against the real TK5 host so that I know the flow really works.

#### Acceptance Criteria

1. THE Test_Suite SHALL include one integration test in `tests/integration/test_flow_live_system_info.py`, marked `@pytest.mark.integration`, that runs `tk5-system-info` through a `Connector` against the host.
2. IF `TK5_USERNAME` or `TK5_PASSWORD` is unset or is an empty string, THEN THE integration test SHALL skip with a message that names each missing or empty variable and SHALL NOT attempt a connection to the host.
3. IF the session-scoped `host_reachable` fixture of `tests/conftest.py` reports that the host did not accept a connection within 5 seconds, THEN THE integration test SHALL skip with a message stating that the host is unreachable.
4. THE integration test SHALL read the host, port and s3270 binary from the `GS_HOST`, `GS_PORT` and `GS_S3270_BINARY` settings, using the same names and default values as the existing integration tests.
5. WHEN the integration test runs with both credentials set and the host reachable, THE Flow_Runner SHALL return a `SYSTEMID` and a `RELEASE` that each contain at least 1 non-whitespace character.
6. WHEN the integration test runs with both credentials set and the host reachable, THE Flow_Runner SHALL return a `USERID` equal to `TK5_USERNAME` under case-insensitive comparison.
7. WHEN the Flow_Runner finishes the `tk5-system-info` flow in the integration test, THE host SHALL be on the logon screen, as determined by the recognizer matching the `tk5-logon` signature on the final screen.
8. THE integration test SHALL assert that the value of `TK5_PASSWORD` does not occur as a substring of `repr(result)`, of `str()` of any raised or returned error, or of the `message` of any log record captured at all levels during the test.
9. THE integration test SHALL also capture the DEBUG records of the `greenscreen.connector` logger and of all loggers (root logger at level DEBUG) during the full logon of `tk5-system-info`, and SHALL assert that `TK5_PASSWORD` in plain text and as hex (lowercase and uppercase, each with and without a space between bytes, of the ASCII bytes) occurs in no record `msg`, no element of `args` and no `getMessage()` result. This is the flow-side check of tn3270-connector Requirement 12, criteria 29 to 45 (in particular criteria 38 to 45).
10. IF `TK5_PASSWORD` is shorter than 4 characters, THEN THE integration test SHALL skip the hex checks of criterion 9, because a hex form of fewer than 8 digits is ambiguous, and SHALL still run the plain-text checks of criteria 8 and 9.

### Requirement 21: Packaging and Dependencies

**User Story:** As a maintainer, I want the package to ship its flows and add nothing to the dependency list.

#### Acceptance Criteria

1. THE Flow_Loader SHALL be the package `greenscreen.flow` (with `greenscreen/flow/__init__.py`) exporting `Flow`, `load_flow`, `load_bundled_flows`, `run_flow`, `FlowResult`, `AuditRecord`, `FlowError`, `FlowInputError` and `FlowDefinitionError`, so that `from greenscreen.flow import <name>` succeeds for each of the nine names.
2. THE `pyproject.toml` SHALL declare `"greenscreen.flow.flows" = ["*.yaml"]` under `[tool.setuptools.package-data]` and SHALL contain entries under `dependencies` and `optional-dependencies` that are identical, entry for entry, to those in the last commit before this feature.
3. WHEN `load_bundled_flows` is called, THE Flow_Loader SHALL read each bundled file through `importlib.resources.files("greenscreen.flow.flows")` and SHALL return all three bundled Flow objects.
4. IF a bundled Flow YAML file is missing, cannot be parsed by `yaml.safe_load`, or fails Flow validation, THEN THE Flow_Loader SHALL raise `FlowDefinitionError` whose message contains the file name, SHALL return no Flow objects, and SHALL leave no partially loaded Flow registered or cached.
5. WHEN the Test_Suite packaging check runs with network access disabled, THE Test_Suite SHALL build a wheel and SHALL assert that the wheel's file list contains exactly the three bundled Flow YAML files under `greenscreen/flow/flows/`.
6. IF the wheel build fails or the wheel lacks any of the three Flow YAML files, THEN THE Test_Suite packaging check SHALL fail and report the build error or the names of the missing files.
7. THE implementation SHALL use the documented behavior of `yaml.safe_load` and `yaml.safe_dump` (PyYAML 6, where `sort_keys=False` keeps insertion order), the `hypothesis` `@given` and `@settings` API, and `importlib.resources.files`, as described in each library's current documentation.

