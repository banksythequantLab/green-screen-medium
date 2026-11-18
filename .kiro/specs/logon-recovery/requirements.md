# Requirements Document

## Introduction

A connection that ends without `LOGOFF` leaves the TSO user id logged on. Every later logon then stops with `unknown_screen`, because the host answers the user id with `IKJ56425I LOGON REJECTED, USERID <id> IN USE` and no bundled Signature matches that screen. The publisher's `call_timeout`, abort and shutdown teardown all end calls this way (publisher design, "Account lock and recovery"). This spec makes the bundled logon steps recover on their own: on the IN USE screen the Flow reconnects to the orphaned session and continues to the ISPF primary option menu, so `tk5-logon` and `tk5-system-info` succeed whether or not the account was left locked.

The sequence below was verified live twice (mainframe-host steering, "Verified 2026-11-17 (evening)"). The three new screens were captured and sit in `captures/incoming/` (each as `.ascii.txt` and `.readbuffer.txt`).

1. User id and Enter at `Logon ===>` give `tso-userid-in-use`.
2. Typing `LOGON <id> RECONNECT` and Enter gives `tso-reconnect-password-prompt`, two rows lower than the normal prompt.
3. Password and Enter give `tso-reconnect-ok` (`IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED`), which needs one Enter.
4. That Enter gives a `***` pause, which `tso-pause` already recognizes. One more Enter gives `ispf-primary-menu`.

The screen in step 4 (the reconnect message with `***` under it) was verified live by the reviewer on 2026-11-17, twice. The bundled signatures recognized it as `tso-pause` and it held no password. No capture of it was kept, so the tests use a synthetic screen (Requirement 4.2).

### Conventions

- IF the work finds a defect in production code (anything outside the files this spec names), THEN the implementer SHALL stop and report it instead of fixing it silently.
- No test, log, message or spec text prints a secret (`TK5_PASSWORD`, `TK5_USERNAME` or the host address).
- No new dependency is added, and the `dependencies` of `pyproject.toml` stay unchanged.
- DO NOT COMMIT anything. The executor leaves every change in the working tree and the reviewer commits. No requirement or task of this spec asks for a commit, a staged file or a branch.
- Production code outside the files this spec names is never changed. The files it names are: the three New_Signatures, `_MANIFEST` and one docstring in `greenscreen/recognizer/bundled.py`, the two bundled Flow YAML files, one public constant added to `greenscreen/flow/runner.py`, and `_session_clean` with its import in `greenscreen/publisher/calls.py` (Requirement 12). `pyproject.toml` stays unchanged.

### Findings from reading the code

**The flow format needs no change.** Checked in `greenscreen/flow/model.py`, `validate.py` and `runner.py`:

- The format has no branching. Two existing steps give optional-screen behaviour: an Expect_Step accepts up to 5 Signatures (`ExpectStep.signatures`), and a Handle_Step runs its body only when the recognized screen is its `signature`. A Handle_Step with zero iterations keeps the screen and sends no key (`exec_handle`), so the normal path costs no extra key.
- Typing a literal and an input into the same field before one key is expressible. A Type_Step takes exactly one of `text` or `input`, and a literal containing `${` is rejected (flow-runtime Requirement 5.11, so interpolation is deliberately absent). But a Type_Step does not change the arming state, replaces no screen and reads none (`validate.py` `_StepWalk._type`, `runner.py` Type_Step ends with `typed_fields.add`). A Handle_Step body may therefore hold `type text "LOGON "`, `type input userid`, `type text " RECONNECT"` and one `key enter`. Each is a separate `string` call at the cursor, and the typed-field set records the field once. `Connector.string` escapes only `\` and `"`, so the leading and trailing spaces survive.
- The price is that `userid` is typed twice on the recovery path. flow-runtime Requirement 17.8 ("no other Type_Step that types an Input") becomes false and is amended here (Requirement 9).
- No change to the behaviour of `greenscreen/flow/*.py` is needed. The only Python edit there is a pure addition: the public frozen constant `FINALLY_SKIP_REASONS` in `runner.py` (Requirement 12). `greenscreen.flow.__all__` stays at its nine names.

**The publisher marks too few stops.** Checked in `greenscreen/publisher/calls.py` and `greenscreen/flow/runner.py`: `_session_clean` returns `False` only for `unknown_screen`, `call_timeout`, cancel and shutdown. The runner skips the `finally` steps for a larger set of reasons (`_FINALLY_SKIP_REASONS`, which is private). A recovery stop that ends as `timeout`, `run_timeout`, `ambiguous_screen` or `session_error` therefore leaves the user id logged on and is not marked. This spec closes that gap with one small publisher change (Requirement 12), because a recovery that stops half-way is exactly such a case.

**Known risk, accepted.** After a Handle_Step body, `exec_handle` polls with `accept_any=True`, so a partial repaint that is recognized as the handled name counts as another iteration. For the in-use handle (`max_count` 1) that ends in `loop_limit`, which fails closed. `tso-pause` has the same exposure today.

### Known limits

- Recovery covers an orphaned session that sits where the verified sequence assumes, at the ISPF primary option menu. After reconnect the flow presses Enter at `tso-reconnect-ok` and at the `***` pause and expects the menu. An orphan left elsewhere (for example at `READY` or inside an ISPF panel) lands on another screen and the flow stops with `unknown_screen`.
- `IKJ56700A ENTER USERID` (an abandoned logon) stays unhandled, as flow-runtime "Known Limits" says.
- The second IN USE state stays unhandled. After one more Enter on the IN USE screen the host adds `IKJ56400A ENTER LOGON OR LOGOFF-`. The flow never presses that Enter (it types the reconnect command on the first IN USE screen), so this state is out of scope and the flow stops with `unknown_screen` if it ever appears.
- RECONNECT takes over whatever session holds the user id. A person or a second process using the same user id is taken over too. Operator commands and cancelling another user's session stay out of scope.
- The host does not always keep the orphan: on 2026-11-15 it purged the user within seconds of a disconnect, on 2026-11-17 it stayed IN USE for minutes (steering, unexplained). The live test therefore cannot assume a lock (Requirement 8).

## Glossary

- **Capture_Set**: The `*.ascii.txt` and `*.readbuffer.txt` files directly under `captures/`.
- **New_Captures**: `tso-userid-in-use`, `tso-reconnect-password-prompt` and `tso-reconnect-ok`, each in both file forms.
- **Signature_Bundle**: The YAML files under `greenscreen/recognizer/signatures/`, listed in `_MANIFEST` of `greenscreen/recognizer/bundled.py`.
- **New_Signatures**: Signature_Bundle entries named like the New_Captures.
- **Recognizer**: `greenscreen.recognizer` (`recognize`, `load_bundled_signatures`).
- **Flow_Bundle**: The YAML files under `greenscreen/flow/flows/`, loaded by `load_bundled_flows`.
- **Logon_Steps**: The steps of `tk5-logon`. `tk5-system-info` starts with exactly these steps (`tests/unit/test_flow_sync.py`).
- **Recovery_Path**: The part of the Logon_Steps that runs when the screen after the user id is `tso-userid-in-use`.
- **Normal_Path**: The Logon_Steps run when the screen after the user id is `tso-password-prompt`.
- **Flow_Runner**: `greenscreen.flow.run_flow`.
- **Scripted_Session**: `ScriptedSession` in `tests/flow_support.py`.
- **Test_Suite**: The pytest and Hypothesis tests under `tests/`.
- **Live_Test**: The integration test of Requirement 8, `tests/integration/test_flow_live_recovery.py`.
- **Cleanup_Helper**: The test-side function of Requirement 8 that logs the account off using raw Connector calls.
- **Hex_Forms**: The five forms of a password: plain, and the ASCII bytes as hex in lower case and upper case, each with and without a space between bytes (`forms_of_run` in `tests/connector_support.py`).

## Requirements

### Requirement 1: Promote the captures and update the inventory tests

**User Story:** As a maintainer, I want the three new captures in `captures/` and every test that pins the capture count updated, so that the pins keep guarding against stray captures.

#### Acceptance Criteria

1. WHEN the work is complete, THE Capture_Set SHALL hold exactly ten captures, each in both file forms (the `*.readbuffer.txt` form and the Ascii form), directly under `captures/`: the seven existing captures (`tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready`, `tso-pause-2`) and the three New_Captures (`tso-userid-in-use`, `tso-reconnect-password-prompt`, `tso-reconnect-ok`).
2. WHEN the six New_Capture files are moved from `captures/incoming/` to `captures/`, THE move SHALL leave the bytes of every moved file unchanged, and `captures/incoming/` SHALL hold zero capture files afterwards.
3. THE Test_Suite SHALL pin the Capture_Set to exactly those ten names in `tests/unit/test_recognizer_capture_inventory.py`, in `tests/unit/test_recognizer_capture_matrix.py` (`test_capture_glob_has_exactly_seven_files`) and in `tests/unit/test_flow_captures.py` (`test_readbuffer_captures_are_exactly_the_seven_names`).
4. THE Test_Suite SHALL rename every test name and docstring in those three files that says "seven" so that it says "ten", leaving no occurrence of "seven" that refers to the capture count.
5. THE Test_Suite SHALL set `CAPTURE_NAMES` in `tests/screen_support.py` to the ten names, so that every test parametrized over it (for example `test_every_capture_loads_as_24_by_80` and `test_containing_field_agrees_with_find_field_at_the_cursor`) runs once for each of the three New_Captures and passes.
6. IF any `*.readbuffer.txt` file other than those ten appears directly under `captures/`, THEN the inventory tests SHALL fail and the failure message SHALL name the unexpected file.
7. IF any of the ten expected captures is missing from `captures/` in either file form, THEN the inventory tests SHALL fail and the failure message SHALL name the missing file.
8. THE Test_Suite SHALL assert in `tests/unit/test_recognizer_capture_facts.py`, for each New_Capture parsed through `ScreenParser`, a size of 24 rows by 80 columns and these facts, which were read from the files while writing this spec:
   - `tso-userid-in-use`: cursor (1, 0); fields (start row, start col, length) (0, 0, 46), (0, 47, 1871) and (23, 79, 0), all unprotected and not hidden; row 0 is the only non-blank row.
   - `tso-reconnect-password-prompt`: cursor (3, 1); a hidden field at (3, 0) of length 1678 under the cursor; non-blank rows are exactly 0, 1 and 2, where row 2 holds `IKJ56714A ENTER CURRENT PASSWORD FOR <id>-`.
   - `tso-reconnect-ok`: cursor (1, 0); fields (0, 0, 58), (0, 59, 1859) and (23, 79, 0), none hidden; row 0 is the only non-blank row.

### Requirement 2: Captures hold no password

**User Story:** As a security reviewer, I want proof that no capture contains the password, so that fixtures never leak a credential.

#### Acceptance Criteria

1. THE Test_Suite SHALL assert, for each of the ten captures in the Capture_Set, that every cell of every hidden field is a space or a null, using the `_holds_password` check of `tests/unit/test_flow_captures.py`. The test SHALL fail if any capture has a hidden-field cell holding any other character.
2. WHERE `TK5_PASSWORD` is set and non-empty in the environment, THE Test_Suite SHALL assert that none of the Hex_Forms of its value occurs in any file under `captures/`, including `captures/incoming/` while that directory exists. THE Test_Suite SHALL compute the verdict as a boolean, so that a failure message names at most the offending file and never contains the password value or any Hex_Form of it.
3. IF `TK5_PASSWORD` is unset or empty, THEN THE Test_Suite SHALL skip the test of criterion 2 with a skip message that names the variable `TK5_PASSWORD`, and SHALL NOT report that test as passed.
4. THE Test_Suite SHALL contain no capture of the screen that follows the password entry on the Normal_Path (the first `***` pause, which holds the typed password in its hidden cells), and no test SHALL add one to `captures/` or `captures/incoming/`.
5. WHEN the Capture_Set contains the ten captures, THE Test_Suite SHALL run the existing test `test_sentinel_occurs_in_no_file_under_captures` over all ten and report it as passed with no failures or skips.

### Requirement 3: Bundled signatures for the three new screens

**User Story:** As the runtime, I want a Signature for each recovery screen, so that the Flow_Runner can check the screen before every key.

#### Acceptance Criteria

1. THE Signature_Bundle SHALL contain ten Signatures: the seven existing ones and `tso-userid-in-use`, `tso-reconnect-password-prompt` and `tso-reconnect-ok`, and `_MANIFEST` SHALL list all ten, each exactly once.
2. THE `tso-userid-in-use` Signature SHALL be satisfied by a Screen whose row 0 matches `IKJ56425I LOGON REJECTED, USERID <1 to 8 characters without a space> IN USE` and whose rows 1 and 2 are blank, and SHALL use no Field_Layout_Matcher and no Cursor_Field_Matcher. The unprotected field on this screen starts directly after the message (column 47 for the 6-character id in the capture), so its position changes with the length of the user id.
3. THE `tso-reconnect-password-prompt` Signature SHALL be satisfied by a Screen whose row 2 matches `IKJ56714A ENTER CURRENT PASSWORD FOR <1 to 8 characters without a space>-` and whose cursor lies in a hidden field starting at row 3, col 0 (a Cursor_Field_Matcher with `hidden` true), and SHALL carry no matcher on row 1, which holds the typed reconnect command.
4. THE `tso-reconnect-ok` Signature SHALL be satisfied by a Screen whose last non-blank row, with trailing spaces removed, equals ` IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED` (a Last_Row_Matcher), so that the `***` pause that appears under the same message does not satisfy it.
5. THE New_Signatures SHALL contain no user id, no password and no host address, and a Test_Suite check SHALL verify that no New_Signature file contains the value of `TK5_USERNAME`, the value of `TK5_PASSWORD` or the host address when those are set.
6. THE Recognizer SHALL build the New_Signatures only from text and positions present in the New_Captures or stated in the mainframe-host steering file, and a Test_Suite check in the style of `test_bundled_matchers_match_capture_cells` (`tests/unit/test_recognizer_bundled.py`) SHALL verify this for each `text_at`, `cursor_field` and `region_regex` against its capture.
7. WHEN `load_bundled_signatures()` is called, THE Recognizer SHALL return ten Signatures, and the tests that pin seven (`tests/unit/test_recognizer_bundled.py`, `tests/unit/test_recognizer_capture_matrix.py`, `tests/unit/test_recognizer_packaging.py`) SHALL be updated to ten.
8. WHEN the Recognizer is given each of the three New_Captures and each of the seven existing captures, THE Recognizer SHALL report exactly one matching Signature per capture, namely the Signature named for that capture. In particular, `tso-reconnect-password-prompt` SHALL NOT match the capture for `tso-password-prompt`, and `tso-password-prompt` SHALL NOT match the capture for `tso-reconnect-password-prompt`. The `***` pause screen under the reconnect message SHALL be recognized as `tso-pause` and not as `tso-reconnect-ok`.
9. THE Recognizer SHALL change no Python module except `_MANIFEST` and the docstring of `greenscreen/recognizer/bundled.py`, and `pyproject.toml` SHALL stay unchanged (the existing `greenscreen.recognizer.signatures = ["*.yaml"]` package-data entry already covers the new files).

### Requirement 4: No signature matches a screen it should not

**User Story:** As a flow author, I want every screen recognized as exactly one name, so that a flow never acts on a guess.

#### Acceptance Criteria

1. THE Test_Suite SHALL extend the matrix test in `tests/unit/test_recognizer_capture_matrix.py` to ten Signatures by ten captures (100 evaluations). For each capture, the test SHALL assert that exactly one of the ten Signatures is satisfied, that it is the capture's own Signature, and that `recognize` returns that Signature's name (the `tso-pause-2` capture maps to `tso-pause`). A failing evaluation SHALL name both the Signature and the capture.
2. THE Test_Suite SHALL assert with a synthetic Screen, built with `make_screen` from `tests/screen_support.py`, that the `***` pause under the reconnect message is recognized as `tso-pause` and not as `tso-reconnect-ok`. The Screen has row 0 ` IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED`, a ` ***` row as the last non-blank row below it, and the cursor on that row at column 5, right after the `***`. The reviewer verified this screen live on 2026-11-17, twice: the bundled Signatures recognized it as `tso-pause` and it held no password. No capture of it was kept, so the synthetic Screen is used.
3. THE Test_Suite SHALL assert with a synthetic Screen that the second IN USE state matches none of the ten bundled Signatures, so that a flow stops there with `unknown_screen`. The Screen has ` IKJ56425I ...` on row 0, ` IKJ56400A ENTER LOGON OR LOGOFF-` on row 2, and the cursor at (3, 0), per steering "Verified 2026-11-17". The test SHALL assert that `recognize` reports no match and that the count of satisfied Signatures is 0.
4. FOR ALL user ids of 1 to 8 characters drawn from the userid alphabet of the bundled flows (`[A-Za-z0-9@#$]`), at least 100 generated per run, THE Test_Suite SHALL assert both of the following.
   - A synthetic `tso-userid-in-use` Screen built for that id (message on row 0, the unprotected field starting directly after the message, cursor (1, 0)) satisfies the `tso-userid-in-use` Signature only, and `recognize` returns `tso-userid-in-use`.
   - A synthetic reconnect prompt Screen built for that id (prompt text on row 2, hidden field at row 3, col 0, cursor (3, 1)) satisfies the `tso-reconnect-password-prompt` Signature only, and `recognize` returns `tso-reconnect-password-prompt`.
5. THE Test_Suite SHALL assert, in the style of `test_no_bundled_yaml_contains_user_id`, that none of the three New_Signature files contains the user id of the New_Captures, compared case-insensitively. A failing assertion SHALL name the offending file and SHALL NOT print the user id.

### Requirement 5: Bundled logon steps recover from IN USE

**User Story:** As an API consumer, I want the logon to succeed whether or not the account was left locked, so that one dropped call does not break every call after it.

#### Acceptance Criteria

1. WHEN the screen after the user id and Enter is `tso-userid-in-use`, THE Flow_Bundle SHALL type `LOGON `, then the `userid` Input, then ` RECONNECT` into the cursor field and press Enter, using only existing step kinds (three Type_Steps and one Key_Step inside one Handle_Step body).
2. WHEN the screen after the reconnect command is `tso-reconnect-password-prompt`, THE Flow_Bundle SHALL type the `password` Input and press Enter.
3. WHEN the screen after the password on the Recovery_Path is `tso-reconnect-ok`, THE Flow_Bundle SHALL press Enter once, and THE existing `tso-pause` Handle_Step (`max_count` 5, body one Enter) and the final Expect_Step for `ispf-primary-menu` SHALL then finish the logon.
4. WHEN the screen after the user id and Enter is `tso-password-prompt`, THE Flow_Runner SHALL send exactly the Session calls it sent before this change and no others, so that a Normal_Path run sends no extra key and no extra `string` call. From the logon screen those calls, in order, are `string(userid)`, `enter`, `string(password)`, `enter`, `enter`, `enter`.
5. THE Flow_Bundle SHALL type the `password` Input only through a Type_Step with `input: password`.
6. WHILE the Flow_Runner executes a Type_Step with `input: password` on either the normal or the reconnect password prompt, THE Flow_Runner SHALL type into a hidden field only. IF the cursor field at the prompt is not hidden, THEN with the bundled Signatures the Flow_Runner SHALL stop with `unknown_screen` at the Expect_Step, because both prompt Signatures require a hidden cursor field, and SHALL send no `string` call for the password. The `secret_target` stop of the Type_Step is reachable only with a Signature that lacks the hidden-cursor matcher (Requirement 7.5).
7. THE Flow_Bundle SHALL build the reconnect command only from the literals `LOGON ` and ` RECONNECT` and the `userid` Input, so that the command contains the user id and no password.
8. IF the screen is still `tso-userid-in-use` after one reconnect attempt, THEN THE Flow_Runner SHALL stop with `loop_limit` and send no further key (the Handle_Step has `max_count` 1).
9. IF the screen after the user id, after the reconnect command, or after the password matches no bundled Signature or an unexpected one, THEN THE Flow_Runner SHALL stop with `unknown_screen`, `timeout` or `unexpected_screen` as it does today and send no further key.
10. THE Flow_Runner SHALL perform no LLM call, and the behaviour of the Python files under `greenscreen/flow/` SHALL stay unchanged, including the schema `version` 1 of the Flow YAML. The only Python edit there is the added public constant of Requirement 12.2, which changes no behaviour.

### Requirement 6: Flow consistency and validation

**User Story:** As a maintainer, I want the three bundled flows to stay in step, so that they cannot drift.

#### Acceptance Criteria

1. THE `tk5-system-info` Flow SHALL consist of, in this order, exactly the steps of `tk5-logon`, then exactly four Extract_Steps, then exactly the steps of `tk5-logoff`, with no other step. `tests/unit/test_flow_sync.py` SHALL pass with no edits to that file.
2. THE `tk5-logoff` Flow, and the Inputs, Outputs, `finally` steps and Timeouts of every bundled Flow, SHALL be identical, when each is compared as `to_yaml()` output, to their definitions before this change.
3. WHEN `check_flow` is run on each bundled Flow against the ten bundled Signatures, THE Flow_Bundle SHALL produce zero violations.
4. THE Flow_Bundle SHALL ship each YAML file with content equal to the `to_yaml()` output of its loaded Flow, as checked by `test_shipped_yaml_equals_to_yaml`.
5. THE Flow_Bundle SHALL contain no literal credential value. Every Type_Step in the Flow_Bundle that is not fed from an Input SHALL have a literal equal to one of exactly four values: `X`, `LOGOFF`, `LOGON ` (with trailing space) or ` RECONNECT` (with leading space).
6. THE Test_Suite SHALL update `test_logon_typing_sequence`, `test_logon_ends_on_ispf_primary_menu` and `test_no_literal_credentials_or_placeholders` in `tests/unit/test_flow_bundled.py`. After the update:
   - The typed Inputs of `tk5-logon` are `userid`, `userid`, `password`, in depth-first step order.
   - The allowed literals are the four values in criterion 5.
7. THE Test_Suite SHALL update `test_bundled_tk5_logon_skips_logo_inr_and_pause_bodies` and `test_bundled_tk5_system_info_skips_main_and_finally_bodies` in `tests/unit/test_flow_runner_fixes_skipped.py`. After the update, every positional index those tests use (for example `main[8]` and audit indexes 1 and 3) SHALL point at the step the test name describes in the new step sequence.
8. IF any test named in criteria 1, 4, 6 or 7 fails, or `check_flow` reports one or more violations, THEN THE Test_Suite SHALL report the run as failed.

### Requirement 7: Scripted tests of the three paths

**User Story:** As a developer, I want deterministic tests of the logon paths without a host.

#### Acceptance Criteria

1. THE Test_Suite SHALL run `tk5-logon` against a Scripted_Session built from captures and assert that the recorded call sequence equals the Normal_Path call sequence of Requirement 5.4, extending `tests/unit/test_flow_logon_script.py` (the existing `FULL_KEYS` assertions stay as they are).
2. THE Test_Suite SHALL run `tk5-logon` from the logon screen through the Recovery_Path (`tk5-logon`, `tso-userid-in-use`, `tso-reconnect-password-prompt`, `tso-reconnect-ok`, a synthetic `***` pause under the reconnect message, `ispf-primary-menu`) and assert that the recorded calls equal exactly these 10 calls in this order: `string(userid)`, `enter`, `string("LOGON ")`, `string(userid)`, `string(" RECONNECT")`, `enter`, `string(password)`, `enter`, `enter`, `enter`. The test SHALL assert that the run ends successfully with the last Screen recognized as `ispf-primary-menu`.
3. THE Test_Suite SHALL run `tk5-system-info` through the Recovery_Path and assert that the result holds exactly four Outputs, in declaration order, and that the last Screen is recognized as `tk5-logon`.
4. WHEN the Scripted_Session shows `tso-userid-in-use` again after the reconnect command was sent, THE Test_Suite SHALL assert that the run stops with the `loop_limit` error and that the Scripted_Session records zero keys after the point of the stop.
5. WHEN the Scripted_Session shows a reconnect password prompt whose cursor field is not hidden (a synthetic copy of the `tso-reconnect-password-prompt` capture with the field attribute changed), THE Test_Suite SHALL assert both of the following, each with zero `string` calls carrying the password:
   - With the bundled Signatures, the run stops with `unknown_screen` at the Expect_Step, before any password is typed, because the bundled `tso-reconnect-password-prompt` Signature requires a hidden cursor field.
   - With a test-only `tso-reconnect-password-prompt` Signature built in the test from the row-2 `region_regex` alone (no hidden-cursor matcher), the run stops with `secret_target`. This Signature is never written under `greenscreen/`.
6. WHEN the Scripted_Session shows the second IN USE state of Requirement 4.3, THE Test_Suite SHALL assert that the run stops with the `unknown_screen` error and that the Scripted_Session records zero keys after that screen.
7. THE Test_Suite SHALL assert, for each run in criteria 2 to 6, that the password value occurs in no audit record, no result `repr` and no log record, in plain or hex form.
8. THE Test_Suite SHALL build every Screen from `captures/` or `make_screen`, and SHALL pass without a live host, a socket or a subprocess and without any test being skipped.

### Requirement 8: Live recovery test

**User Story:** As a maintainer, I want one end-to-end proof against the real host, so that recovery is known to work and the account is never left locked by a test.

#### Acceptance Criteria

1. THE Live_Test SHALL be marked `@pytest.mark.integration`, SHALL live in `tests/integration/test_flow_live_recovery.py` and SHALL follow `tests/integration/test_flow_live_system_info.py` (same `host_reachable` fixture, same `live_connector_config()`, same secret-safe assertions).
2. IF `TK5_USERNAME` or `TK5_PASSWORD` is unset or empty, THEN THE Live_Test SHALL skip with a message that names each missing variable, before any connection to the host.
3. WHEN the Live_Test runs, THE Live_Test SHALL perform these steps in order: (a) run the bundled `tk5-logon` through a `Connector`, (b) leave the `with` block without logging off, which drops the connection, (c) run `tk5-system-info` through a new `Connector`, and (d) run `tk5-system-info` a second time through another new `Connector`.
4. WHEN step (c) returns, THE Live_Test SHALL assert all of the following: the Outputs are in declaration order (`USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`), `USERID` equals `TK5_USERNAME` case-insensitively, `SYSTEMID` and `RELEASE` each contain at least one non-whitespace character, and the final screen is recognized as `tk5-logon`.
5. WHEN step (c) returns, THE Live_Test SHALL read the audit trail and require that the in-use Handle_Step ran at least 1 body iteration.
6. IF the in-use Handle_Step ran 0 body iterations at step (c) because the host had already purged the orphaned session, THEN THE Live_Test SHALL run the Cleanup_Helper of criterion 9 and then skip with a message stating that the lock was not reproduced and the recovery path was not exercised.
7. WHEN step (d) returns, THE Live_Test SHALL assert the same Outputs as in criterion 4 and require that the in-use Handle_Step ran 0 body iterations, which shows that step (c) left the account logged off.
8. THE Live_Test SHALL assert that no Hex_Form of `TK5_PASSWORD` occurs in `repr(result)`, in the text of any raised error, in any audit record, or in any log record captured at DEBUG from the root logger and `greenscreen.connector` (the checks of `test_flow_live_system_info.py`). WHERE `TK5_PASSWORD` has fewer than 4 characters, THE Live_Test SHALL skip the Hex_Form checks. THE Live_Test SHALL compute every verdict as a boolean so that no assertion failure message contains the password.
9. THE Live_Test SHALL run the Cleanup_Helper in a `finally` block on every exit path (pass, fail, error and skip). THE Cleanup_Helper SHALL use only raw `Connector` calls and text waits (`wait_for_text`, `string`, `enter`), and SHALL use no Flow and no Signature. THE Cleanup_Helper SHALL follow the verified manual sequence: at the logon screen type the user id and Enter; on the IN USE screen type `LOGON <id> RECONNECT`, Enter, the password, Enter, then Enter until the ISPF menu shows, then `X`, Enter, `LOGOFF`, Enter; when no IN USE screen appears and the logon proceeds, log off the same way. THE Cleanup_Helper SHALL NOT leave a logon abandoned at a prompt. Each text wait SHALL have a timeout of at most 15 seconds, and the Cleanup_Helper SHALL press Enter at most 5 times while waiting for the ISPF menu.
10. IF the Cleanup_Helper cannot log the account off, THEN THE Live_Test SHALL fail with a message that says the account may still be locked and names the manual recovery (`LOGON <id> RECONNECT` at the IN USE screen), and SHALL include no credential in that message.
11. THE Live_Test SHALL leave no `s3270` or `ws3270` process started by the test running at exit, SHALL read the credentials only from the environment, and SHALL write no capture and no file.
12. WHEN the executor runs the Live_Test and `TK5_USERNAME` or `TK5_PASSWORD` is not visible in the executing shell, THE executor SHALL report that fact, SHALL record the live task as SKIPPED (not failed) and SHALL NOT ask the user for the credentials. The reviewer then runs the Live_Test. The go-ahead to use the demo account is already given, so the executor asks no confirmation before running it when both variables are visible.

### Requirement 9: Property tests, reused strategies, and amended specs

**User Story:** As a maintainer, I want property coverage only where it finds new bugs, and the earlier specs corrected where this change makes them false.

#### Acceptance Criteria

1. THE Test_Suite SHALL add `tso-userid-in-use` and `tso-reconnect-password-prompt` to `TYPEABLE` in `tests/property/_flow_strategies.py`, so that Property 8 (`test_flow_typing_never_blocks.py`) and `chain_scripts()` cover typing into the two new cursor fields.
2. WHEN Property 8 runs against `tso-userid-in-use` and `tso-reconnect-password-prompt`, THE Test_Suite SHALL pass with Property 8's existing maximum text length unchanged. The existing single property test keeps its decorator and now draws from six screens. A second test in `tests/property/test_flow_typing_never_blocks.py`, parametrized over the two new screen names and sharing the existing check helper, SHALL run with `max_examples=100` for each of the two screens, so that each new screen gets 100 examples of its own.
3. THE Test_Suite SHALL implement the property of Requirement 4.4 as exactly one `@given` test with `@settings(max_examples=100, deadline=None)`, whose first line is the comment `# Feature: logon-recovery, Property 1: User id length does not change recognition`.
4. THE Test_Suite SHALL add no new strategy module and SHALL leave every property test other than Property 8 and the test in criterion 3 unchanged in source text.
5. WHEN the properties that draw screens from `SIGNATURE_NAMES` (`chain_scripts()`) run with the three new names `tso-userid-in-use`, `tso-reconnect-password-prompt` and `tso-reconnect-ok`, THE Test_Suite SHALL pass every one of them with `max_examples` at or above its value before this change.
6. WHEN the full property suite runs, THE Test_Suite SHALL finish within the time limits of flow-runtime Requirement 19.9 and publisher Requirement 20.17.
7. THE spec work SHALL amend screen-recognizer Requirements 8.2, 8.11, 8.21 and 10.2 to 10.4 so that each states ten Signatures and ten captures where it stated seven, and no amended text states seven. This amendment describes shipped code and does not depend on the live result.
8. THE spec work SHALL amend flow-runtime Requirements 17.5 to 17.8 and 17.12 so that the `tk5-logon` step list matches the flow after this change, and so that 17.12 no longer says "no other Type_Step that types an Input" where the new steps type an Input. This amendment describes shipped code and does not depend on the live result.
9. THE spec work SHALL amend publisher Requirement 23 as Requirement 12.6 states. This amendment describes shipped code and does not depend on the live result.
10. The amendments that state the recovery limits and remove the "must not be exposed publicly" wording, and the matching design text in the flow-runtime and screen-recognizer designs, depend on the live result and are governed by Requirement 10.

### Requirement 10: Publisher note

**User Story:** As an operator, I want the publisher's design to say what is now safe, so that I know whether a dropped call still blocks the account.

#### Acceptance Criteria

1. THE spec work SHALL change publisher code only in `_session_clean` and its import line in `greenscreen/publisher/calls.py` (Requirement 12), SHALL leave `pyproject.toml` byte-identical, and publisher Requirement 23.7 (no recovery logic in the Publisher) SHALL remain true. THE spec work SHALL NOT edit `.kiro/steering/mainframe-host.md`, which the reviewer owns. Spec files outside `.kiro/specs/logon-recovery/` are edited only as Requirement 9.7 to 9.9 and criteria 2 and 3 of this requirement state.
2. WHEN the Live_Test has passed against the live host with step (c) taking the Recovery_Path, whether run by the executor or by the reviewer, THE spec work SHALL replace every stale statement that the Publisher must not be exposed publicly, or that recovery of a locked user id is a follow-up, in these files: `.kiro/specs/publisher/design.md` (the table row about recovery of a locked user id, the "Account lock and recovery" section including its "No recovery logic" and "Exposure" bullets, the error-table row about a locked account, and open item 2; found by searching for `follow-up`, `exposed publicly`, `locked` and `IN USE`), `.kiro/specs/publisher/requirements.md` (the statements in the Assumptions about the follow-up spec and public exposure, including line 22 and the not-in-scope line), and the matching passages of `.kiro/specs/flow-runtime/design.md` and `.kiro/specs/screen-recognizer/design.md` (the text that states seven bundled Signatures, seven captures and the old `tk5-logon` step list or a logon that cannot recover; found by searching for `seven`, `7 by 7`, `_MANIFEST` and `tk5-logon`). Each replacement about recovery SHALL state the following in full, with no reference to any section name of this document:
   - Bundled-flow recovery exists.
   - Recovery covers an orphaned session left at the ISPF primary option menu only.
   - An orphan left at `READY` or inside an ISPF panel, an abandoned logon showing `IKJ56700A ENTER USERID`, and the second IN USE state (`IKJ56400A` after an extra Enter) are not recovered, and a call that meets one of them stops with `unknown_screen`.
   - RECONNECT takes over whatever session holds the user id.
   - The host may purge the orphaned session by itself.
3. IF the Live_Test did not pass on the recovery path (it was skipped because the credentials are not visible, skipped because the lock was not reproduced, failed, or was not run), THEN THE spec work SHALL make none of the edits of criterion 2, and the files named there SHALL be byte-identical to their state before the spec work. The executor SHALL report the edits as not done and as owned by the reviewer, who makes them after a live pass.
4. THE spec work SHALL keep the `GS_PUBLISH_FLOWS=tk5-system-info` demo guidance in `.kiro/specs/publisher/design.md` byte-identical to its state before the spec work, because `tk5-logon` still leaves the user logged on after a successful call.
5. THE spec work SHALL NOT edit the text of publisher Requirement 23 under criterion 2; Requirement 23 changes only as Requirement 12.6 states.

### Requirement 11: Failed recovery stops cleanly; the normal path is unchanged

**User Story:** As an operator, I want a recovery that cannot finish to stop at once and be visible in the call log, and I want proof that the normal logon sends the same calls as before.

#### Acceptance Criteria

1. IF recovery cannot finish because the screen after the reconnect command, after the reconnect password, or after the Enter at `tso-reconnect-ok` is not the expected screen, THEN THE Flow_Runner SHALL stop with the reason code it already uses for that case (`unknown_screen`, `timeout`, `unexpected_screen`, `loop_limit` or `secret_target`), send no retry and send no further key. The Flow_Bundle SHALL contain no retry loop.
2. THE Test_Suite SHALL assert criterion 1 with a Scripted_Session for each of the three points, and SHALL assert that the Scripted_Session records zero keys and zero `string` calls after the point of the stop. For a visible reconnect prompt, criterion 1 is met by `unknown_screen` with the bundled Signatures and by `secret_target` with the test-only Signature of Requirement 7.5.
3. WHEN a call through the Publisher stops during recovery with a reason for which the runtime skips the `finally` steps (`unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout` or `session_error`), THE Publisher SHALL write a Call_Log_Record with `session_clean` false. A recovery stop with any other reason (`loop_limit`, `unexpected_screen`, `secret_target` and the rest) makes no claim. Requirement 12 defines the rule and the Test_Suite asserts it through the Publisher's call path with Scripted_Sessions that stop during recovery.
4. THE Test_Suite SHALL record the full Session call list that `tk5-logon` and `tk5-system-info` send on the Normal_Path from the logon screen, using the same scripted captures as Requirement 7.1, and SHALL compare each list with a golden call list written as a literal in the test.
5. THE implementer SHALL take the golden call lists of criterion 4 from the code as it stands BEFORE this change (run the unchanged flows against the Scripted_Session first, then write the lists as literals into the tests, uncommitted), so that the test proves the Normal_Path sends exactly the same calls before and after. The guard that the lists come from unchanged flows is that `git diff --stat -- greenscreen/flow greenscreen/recognizer/signatures` prints nothing when the lists are recorded, and that the golden tests pass against those unchanged files.

### Requirement 12: `session_clean` for every stop that skips the finally steps

**User Story:** As an operator, I want the call log to mark every call after which the flow's `finally` steps did not run, so that a recovery that stops half-way, or any other skipped logoff, shows why the next call may fail.

#### Acceptance Criteria

1. THE Publisher's `_session_clean(code, abort_reason)` in `greenscreen/publisher/calls.py` SHALL return `False` when `code` is `call_timeout`, or when `abort_reason` is `cancel` or `shutdown` (as today), and SHALL return `False` when `code` is one of the reasons for which the Flow_Runner skips the `finally` steps and that reach the Publisher as a Flow stop. For the code as it stands that set is exactly `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout` and `session_error`. For every other code `_session_clean` SHALL return `None` (no claim), including `loop_limit`, `unexpected_screen`, `bad_target`, `secret_target`, `hidden_output`, `output_type`, `screen_size`, `input_invalid`, `host_unavailable`, `internal_error`, `busy`, `ok` and every other Error_Code.
2. THE Flow_Runner module `greenscreen/flow/runner.py` SHALL expose the set of reasons for which it skips the `finally` steps as a public frozen constant `FINALLY_SKIP_REASONS: frozenset[str]`, bound to the same object as the private `_FINALLY_SKIP_REASONS`. This SHALL be a pure addition: the private name stays (existing tests pin it), no runner behaviour changes and `greenscreen.flow.__all__` keeps its nine names.
3. THE Publisher SHALL derive the reason set of criterion 1 from `FINALLY_SKIP_REASONS` and not copy it, as the intersection of `FINALLY_SKIP_REASONS` with the Reason_Codes that reach the Publisher as a Flow stop (`_FLOW_STOP_CODES`). A reason added to the runtime set later then reaches the Publisher without an edit there.
4. THE Test_Suite SHALL assert: (a) `FINALLY_SKIP_REASONS` is a `frozenset` equal to `_FINALLY_SKIP_REASONS` and contains the five reasons of criterion 1; (b) the Publisher's derived set equals the literal five reasons, so a drift in either direction fails the test and names the difference; (c) for each code in `ERROR_CODES`, `_session_clean` returns `False` exactly for the five reasons and `call_timeout`, and `None` otherwise, and returns `False` for abort reasons `cancel` and `shutdown` with any code; (d) through `CallService`, a Flow stop at each of `unknown_screen`, `timeout` and `loop_limit` gives `session_clean` `False`, `False` and no claim, and the Call_Log_Record carries the field only when it is `False`; (e) recovery stops of Requirement 11.1 give the records of Requirement 11.3.
5. THE Test_Suite SHALL update the publisher tests that pin `session_clean`: the `timeout` row of `test_flow_stops_carry_the_flow_stop_members_and_session_clean` in `tests/unit/test_publisher_calls.py` changes from no claim to `False`, and any other pin of a code in the five reasons changes the same way. No other publisher test changes.
6. THE spec work SHALL amend publisher Requirement 23 so that criteria 1 and 5 state the new set (`unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error`, whether the stop happened in the steps or in the `finally` phase, plus the cases of criteria 2 to 4) and that every other outcome, including `unexpected_screen`, `loop_limit`, `bad_target`, `secret_target` and `host_unavailable`, makes no claim. It SHALL describe the derivation from the runtime constant, and the text of the publisher design that lists the marked outcomes SHALL be amended the same way. Requirement 23.7 stays as it is.
7. THE change SHALL touch no other line of `greenscreen/publisher/` and no line of `pyproject.toml`, SHALL add no recovery, retry or reaper logic, and SHALL add no dependency.
