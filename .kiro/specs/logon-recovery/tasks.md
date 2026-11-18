# Implementation Plan: logon-recovery

## Overview

Make the bundled logon steps recover from `IKJ56425I LOGON REJECTED, USERID <id> IN USE` by reconnecting to the orphaned TSO session, as `requirements.md` and `design.md` in this folder describe. The change is three new Signatures, three promoted captures, a new step list in two Flow YAML files, and tests. The behaviour of `greenscreen/flow/` does not change. The Python production edits are: `_MANIFEST` and one docstring in `greenscreen/recognizer/bundled.py`; one added line in `greenscreen/flow/runner.py` (the public constant `FINALLY_SKIP_REASONS`); and `_session_clean` plus one import and one derived constant in `greenscreen/publisher/calls.py`, so the call log marks every stop after which the `finally` steps did not run (task 6.4). The plan is sized for one working day (about 8 hours). Every path is repo-relative.

### Estimates and order

| # | Top-level task | Hours |
|---|---|---|
| 1 | Golden normal-path call lists, recorded on unchanged code | 0.5 |
| 2 | Promote the captures, update inventory pins, password scans | 0.5 |
| 3 | Signatures, manifest, matrix, facts tests | 0.75 |
| 4 | Test support entries and line-mode examples | 0.75 |
| 5 | Flow change and the hard-coded flow tests | 0.75 |
| 6 | Scripted tests: recovery, stop cases, `secret_target`; flow constant and publisher `session_clean` change | 1.75 |
| 7 | Property additions and full-suite run | 0.75 |
| 8 | Checkpoint | 0.25 |
| 9 | Live test with Cleanup_Helper (written, not run against the host) | 0.75 |
| 10 | Amend the earlier requirements and the `session_clean` passages of the publisher spec | 0.6 |
| 11 | Live run against the host (done by the reviewer, 2026-11-18) | 0 |
| 12 | Doc edits for the recovery limit and the lifted exposure restriction | 0.35 |
| 13 | Test-only fix of the probe/schema-constant collision | 0.5 |
| 14 | Final checkpoint | 0.25 |
| | **Total** | **8.45** |

The total is a little over a working day because task 6.4 grew. Tasks 12 and 13 come after task 10; task 11 was done by the reviewer.

### Rules for every task

- Stop and report a production defect. If the work finds a defect in any production file outside the files this spec names, do not fix it silently. Stop and report it (Requirements, "Conventions").
- No secret is printed. No test, log, assertion message, task note or spec text contains `TK5_PASSWORD`, `TK5_USERNAME` or the host address. Every password verdict is a boolean. `TK5_USERNAME` and `TK5_PASSWORD` are read from the environment only, and only by the live test (task 9.1), the capture scan (task 2.2) and the credential scans (tasks 3.2).
- No new dependency. `pyproject.toml` stays unchanged and `dependencies` stays as it is.
- DO NOT COMMIT anything. Leave every change in the working tree, and run no `git commit`. The reviewer commits. (`git mv` in task 2.1 only moves the files and is allowed.)
- Publisher code changes are limited to `_session_clean`, its import line and one derived constant in `greenscreen/publisher/calls.py` (task 6.4). Every other file under `greenscreen/publisher/` stays byte-identical, `pyproject.toml` stays unchanged, and no task adds recovery, retry or reaper logic to the publisher (publisher Requirement 23.7).
- The behaviour of `greenscreen/flow/` stays unchanged, and the Flow YAML schema `version` stays 1. Besides the YAML files under `greenscreen/flow/flows/`, the only edit there is one added line in `greenscreen/flow/runner.py`: the public constant `FINALLY_SKIP_REASONS` (task 6.4). `greenscreen/flow/__init__.py` and its nine-name `__all__` do not change.
- `.kiro/steering/mainframe-host.md` is never edited. The reviewer owns it. `.kiro` is never git-ignored.
- No capture of the screen that follows the password entry on the normal path is ever written (Requirement 2.4). The `***` pause under the reconnect message is a synthetic screen only.
- Unit and property tests need no live host, socket or subprocess, and none is skipped (Requirement 7.8). Screens come from `captures/` or `make_screen`. Runner tests use `FakeClock`.
- Every property test is exactly one `@given` test with `@settings(max_examples=100, deadline=None)` or more, and its first line is the comment `# Feature: logon-recovery, Property N: <title>`.
- Every task is required. Nothing is marked optional with `*`, matching the sibling plans.
- Do not mark any task complete unless the tests it names pass. Task 11 was run by the reviewer; the executor does not run the live test.
- The live pass on the recovery path exists (task 11.1), so the doc edits in task 12 are executed, not skipped.

## Tasks

- [x] 1. Record the golden normal-path call lists FIRST, on the unchanged code (about 0.5 h)
  - [x] 1.1 Record the lists from the unchanged flows as literals before any flow or signature change (uncommitted)
    - Guard: `git diff --stat -- greenscreen/flow greenscreen/recognizer/signatures` prints nothing, and no new file exists under `greenscreen/recognizer/signatures/`. If either check fails, stop and report.
    - Run a throwaway script (not committed) that builds `ScriptedSession([...], echo_typing=True)` with `FakeClock()`, `poll_interval=0.25` and inputs `{"userid": "FAKEUSR", "password": "SNTNL-01"}`, using the bundled flows and the bundled seven Signatures, and prints the calls without `read`. `tk5-logon` states: `capture("tk5-logon")`, `capture("tso-password-prompt")`, `pause_variant(0)`, `pause_variant(1)`, `capture("ispf-primary-menu")`. `tk5-system-info` states: the same five, then `capture("tso-ready")`, `capture("tk5-logon")`. Also record the one-pause variant (`pause_variant(0)` only) for each flow.
    - Write the lists as literals in `tests/unit/test_flow_logon_script.py` (`GOLDEN_LOGON`) and `tests/unit/test_flow_system_info_script.py` (`GOLDEN_SYSTEM_INFO`), each as a parametrized test over the two-pause and one-pause cases. Leave the existing `FULL_KEYS` tests as they are. The design's literals are the expected result: `string(userid), enter, string(password), enter, enter, enter` for logon and the same plus `string("X"), enter, string("LOGOFF"), enter` for system info. If the script output differs, the script output wins, and the difference is reported.
    - Run the two files against the unchanged flow files and require they pass. Do not commit. The tests stay in the working tree and must still pass after the flow change, so the new flows are measured against the old behavior.
    - The password in the literals is the fake `SNTNL-01`, never `TK5_PASSWORD`.
    - _Requirements: 7.1, 11.4, 11.5, 5.4_

- [x] 2. Promote the captures and update the inventory pins (about 0.5 h)
  - [x] 2.1 Move the six capture files and update every pin and name list
    - `git mv` the six files from `captures/incoming/` (`tso-userid-in-use`, `tso-reconnect-password-prompt`, `tso-reconnect-ok`, each `.ascii.txt` and `.readbuffer.txt`) to `captures/`, so bytes stay unchanged. Check `git diff -M --stat` shows pure renames, and `captures/incoming/` holds no capture file afterwards.
    - In `tests/screen_support.py` set `CAPTURE_NAMES` to the ten names.
    - In `tests/unit/test_recognizer_capture_inventory.py`, `tests/unit/test_recognizer_capture_matrix.py` (`test_capture_glob_has_exactly_seven_files`) and `tests/unit/test_flow_captures.py` (`test_readbuffer_captures_are_exactly_the_seven_names`) pin exactly the ten names, and rename every test name and docstring saying "seven" about the capture count to "ten". A missing file in either form and an unexpected `*.readbuffer.txt` file each fail with a message that names the file.
    - Do not touch the signature-count pins or the matrix evaluation here (task 3.2). Tests that still count seven Signatures may fail until task 3.1, which is expected; the pin tests of this task must pass.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 2.2 Add the password-free capture tests
    - In `tests/unit/test_flow_captures.py`, run the `_holds_password` check over all ten captures (every hidden-field cell is a space or null; fail naming the capture otherwise).
    - Add a test that, when `TK5_PASSWORD` is set and non-empty, asserts none of the Hex_Forms (`forms_of_run` in `tests/connector_support.py`) occurs in any file under `captures/`, including `captures/incoming/` while it exists. It computes a boolean, and a failure message names at most the file, never the value or a hex form. When the variable is unset or empty, the test skips with a message naming `TK5_PASSWORD`.
    - Add a test that no file and no capture name contains the first-pause residue (no `captures/` file for the screen after the password), and confirm the existing `test_sentinel_occurs_in_no_file_under_captures` passes over all ten with no skip.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3. Signatures, manifest, matrix and facts tests (about 0.75 h)
  - [x] 3.1 Add the three Signature files and the manifest entries
    - Create `greenscreen/recognizer/signatures/tso-userid-in-use.yaml`, `tso-reconnect-password-prompt.yaml` and `tso-reconnect-ok.yaml` with the exact YAML of the design, section 2.
    - In `greenscreen/recognizer/bundled.py` append the three names to `_MANIFEST` after `tso-pause`, and change the docstring "seven" to "ten". Change nothing else in the file, and leave `pyproject.toml` unchanged.
    - Confirm with `load_bundled_signatures()` that ten Signatures load, and with `git diff --stat greenscreen/recognizer/bundled.py` that only `_MANIFEST` and the docstring changed.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.9_

  - [x] 3.2 Update the matrix, count pins and Signature content tests
    - In `tests/unit/test_recognizer_capture_matrix.py` extend the matrix to ten Signatures by ten captures (100 evaluations). Per capture assert that exactly one Signature is satisfied, that it is the capture's own (`tso-pause-2` maps to `tso-pause`), and that `recognize` returns its name. A failing evaluation names both the Signature and the capture. Include the pairs `tso-reconnect-password-prompt` against the `tso-password-prompt` capture and the reverse.
    - Update the count of seven to ten in `tests/unit/test_recognizer_bundled.py` and `tests/unit/test_recognizer_packaging.py`, and check `test_bundled_matchers_match_capture_cells` now covers each `text_at`, `cursor_field` and `region_regex` of the new files against its capture.
    - Add a scan that none of the three new Signature files contains the values of `TK5_USERNAME` or `TK5_PASSWORD` or the host address when those are set (skip with a message naming the missing variable otherwise, never printing a value), and confirm or extend `test_no_bundled_yaml_contains_user_id` so it checks the three new files case-insensitively against the user id of the captures, naming the file and not the id on failure.
    - _Requirements: 3.5, 3.6, 3.7, 3.8, 4.1, 4.5_

  - [x] 3.3 Add the capture-fact tests
    - In `tests/unit/test_recognizer_capture_facts.py` add one example test per New_Capture, parsing through `ScreenParser`: size 24 by 80 and the facts of Requirement 1.8. `tso-userid-in-use`: cursor (1, 0); fields (0, 0, 46), (0, 47, 1871), (23, 79, 0), all unprotected and not hidden; row 0 only non-blank. `tso-reconnect-password-prompt`: cursor (3, 1); hidden field at (3, 0) of length 1678 under the cursor; non-blank rows exactly 0, 1 and 2 with the `IKJ56714A` text on row 2. `tso-reconnect-ok`: cursor (1, 0); fields (0, 0, 58), (0, 59, 1859), (23, 79, 0), none hidden; row 0 only non-blank.
    - Do not assert the extra fields of the reconnect prompt capture (design, "Data Models").
    - _Requirements: 1.8_

- [x] 4. Test support entries and line-mode examples (about 0.75 h)
  - [x] 4.1 Add the synthetic screen builders to `tests/screen_support.py`
    - Add `in_use_screen(userid)`, `reconnect_prompt_screen(userid)`, `reconnect_pause_screen()` and `second_in_use_screen()` with `make_screen`, as in design section 4. The second field of `in_use_screen` starts at `1 + len(msg)`. The pause screen has row 0 ` IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED`, ` ***` as the last non-blank row and the cursor on it at column 5. The second IN USE screen has the `IKJ56425I` text on row 0, `IKJ56400A ENTER LOGON OR LOGOFF-` on row 2 and the cursor at (3, 0).
    - Builders contain no real user id, password or host address.
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 4.2 Add the three identity entries to `_SIGNATURE_CAPTURE` in `tests/flow_support.py`
    - Map `tso-userid-in-use`, `tso-reconnect-password-prompt` and `tso-reconnect-ok` each to the capture of the same name, so `partial_repaint` and `chain_scripts()` do not raise `LookupError` for the new names. Change nothing else, and check the import-time assertions of the module still hold.
    - _Requirements: 9.5_

  - [x] 4.3 Add the line-mode example tests
    - In `tests/unit/test_recognizer_line_mode_signatures.py` add: the `***` pause under the reconnect message (`reconnect_pause_screen()`) is recognized as `tso-pause`, satisfies no other Signature, and does not satisfy `tso-reconnect-ok`; the second IN USE state (`second_in_use_screen()`) makes `recognize` report no match and satisfies none of the ten Signatures (count 0).
    - _Requirements: 4.2, 4.3_

- [x] 5. Flow change and the hard-coded flow tests (about 0.75 h)
  - [x] 5.1 Regenerate `tk5-logon.yaml` and `tk5-system-info.yaml`
    - Use a throwaway script that loads each bundled flow, rebuilds only the logon `steps` as the 12 top-level steps in design section 3, and writes `flow.to_yaml()`. Do not edit the YAML by hand, and do not add the script to the repo. `tk5-system-info` gets the same 12 steps in place of its first 11 logon steps; its four Extract_Steps, seven logoff steps and `finally` list stay.
    - Verify: this task changes only the two files under `greenscreen/flow/flows/` and no Python file; `inputs`, `outputs`, `timeouts`, `finally` and `description` of every bundled flow, and all of `tk5-logoff.yaml`, are identical to HEAD as `to_yaml()` output; `check_flow` reports zero violations for all three against the ten Signatures; `tests/unit/test_flow_sync.py` passes with no edit; `test_shipped_yaml_equals_to_yaml` passes.
    - Re-run the golden tests of task 1.1; they must pass unchanged.
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.7, 5.10, 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.2 Update `tests/unit/test_flow_bundled.py`
    - `test_logon_typing_sequence`: the top-level non-handle steps become `expect tk5-logon`, `type userid`, `key enter`, `expect [tso-password-prompt, tso-reconnect-password-prompt]`, `type password`, `key enter`, `expect ispf-primary-menu`; typed Inputs in depth-first order are `userid`, `userid`, `password`.
    - `test_logon_ends_on_ispf_primary_menu` must still pass.
    - `test_no_literal_credentials_or_placeholders`: the allowed literals become exactly `X`, `LOGOFF`, `LOGON ` (trailing space) and ` RECONNECT` (leading space), with spaces preserved by the quote-stripping logic.
    - _Requirements: 5.5, 5.7, 6.5, 6.6_

  - [x] 5.3 Update `tests/unit/test_flow_runner_fixes_skipped.py`
    - In `test_bundled_tk5_logon_skips_logo_inr_and_pause_bodies` and `test_bundled_tk5_system_info_skips_main_and_finally_bodies` point every positional index at the step the name describes: unmatched handles `main[0]`, `main[1]`, `main[5]` (in-use), `main[9]` (reconnect-ok) and `main[10]` (pause); audit indexes 1 and 3 stay `skipped`. Replace the hard-coded child kind `"key"` with `child.step.kind`, because the in-use body has three `type` steps.
    - _Requirements: 6.7_

- [x] 6. Scripted tests of the recovery paths (about 1.5 h)
  - [x] 6.1 Create `tests/unit/test_flow_logon_recovery.py` with the recovery and stop cases
    - Every run uses `ScriptedSession(..., echo_typing=True)`, `FakeClock()`, `poll_interval=0.25`, the bundled flows and Signatures. Screens come from `captures/` and the builders of task 4.1.
    - `recovery_logon`: `tk5-logon`, `tso-userid-in-use`, `tso-reconnect-password-prompt`, `tso-reconnect-ok`, `reconnect_pause_screen()`, `ispf-primary-menu`. Assert the 10 calls in order (`string(userid)`, `enter`, `string("LOGON ")`, `string(userid)`, `string(" RECONNECT")`, `enter`, `string(password)`, `enter`, `enter`, `enter`), that the run succeeds, that the last screen is recognized as `ispf-primary-menu`, and the audit of steps 7 to 18 from the design.
    - Stop cases, each asserting the reason code, an expected literal call prefix, and zero keys and zero `string` calls after the stop: `loop_limit` (in-use screen shown twice); `unknown_screen` after the reconnect command (`second_in_use_screen()`); `unknown_screen` after the password (`blank_screen()`); `unknown_screen` after the Enter at `tso-reconnect-ok` (`blank_screen()`); `unknown_screen` directly after the user id (`second_in_use_screen()`, calls are `string(userid)`, `enter` only).
    - `no_leak`: for every run above, the password in plain and hex forms (`forms_of_run`) is absent from `repr(result)`, `repr(audit)`, `str(FlowError)` and every log record at DEBUG. Booleans only.
    - _Requirements: 5.1, 5.2, 5.3, 5.8, 5.9, 7.2, 7.4, 7.6, 7.7, 7.8, 11.1, 11.2_

  - [x] 6.2 Add the `secret_target` tests to the same file
    - Bundled variant: a copy of the `tso-reconnect-password-prompt` capture with the hidden field attribute changed to visible. Assert the run stops with `unknown_screen` at the Expect_Step (the bundled Signature requires `hidden`), and that no `string` call carries the password (Requirement 7.5, first bullet; design Open item 2).
    - Test-only Signature variant: run the same screen with a `signatures=` list in which `tso-reconnect-password-prompt` is replaced by a test-only Signature made of the row-2 `region_regex` alone. Assert the run stops with `secret_target` and that no `string` call carries the password. The test-only Signature is built in the test and never written under `greenscreen/`.
    - Both variants assert the `no_leak` checks of task 6.1.
    - _Requirements: 5.6, 7.5, 7.7, 11.2_

  - [x] 6.3 Add the `tk5-system-info` recovery run to `tests/unit/test_flow_system_info_script.py`
    - Script: the recovery prefix of task 6.1, then `tso-ready`, `tk5-logon`. Assert exactly four Outputs in order (`USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`) and that the last screen is recognized as `tk5-logon`. Keep the golden test of task 1.1 as it is.
    - _Requirements: 7.3, 6.1_

  - [x] 6.4 Expose the runtime's finally-skip set and mark every such stop in `_session_clean`, with unit tests
    - This is the one small publisher change of the spec (Requirement 12; design section 8). Read `greenscreen/flow/runner.py` and `greenscreen/publisher/calls.py` first. The runtime set `_FINALLY_SKIP_REASONS` is private (underscore, not in the nine-name `greenscreen.flow.__all__`).
    - `greenscreen/flow/runner.py`: add one line directly after the `_FINALLY_SKIP_REASONS` definition: `FINALLY_SKIP_REASONS: frozenset[str] = _FINALLY_SKIP_REASONS`. Keep the private name (existing tests read it, one by regular expression on the source). Change nothing else in the file, and do not touch `greenscreen/flow/__init__.py` or `__all__`.
    - `greenscreen/publisher/calls.py`: import `FINALLY_SKIP_REASONS` from `greenscreen.flow.runner`, define `_FINALLY_SKIPPED_STOPS = FINALLY_SKIP_REASONS & _FLOW_STOP_CODES` after `_FLOW_STOP_CODES`, and change `_session_clean` to return `False` for `call_timeout`, for a code in `_FINALLY_SKIPPED_STOPS`, or for abort reason `cancel` or `shutdown`, and `None` otherwise. Copy no reason name into the publisher. The result for the current code is exactly `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error`. `loop_limit`, `unexpected_screen`, `bad_target`, `secret_target` and every other code make no claim. Change no other line under `greenscreen/publisher/`, no `pyproject.toml`, and add no recovery, retry or reaper logic.
    - New `tests/unit/test_flow_finally_skip_reasons.py`: `FINALLY_SKIP_REASONS` is a `frozenset`, is the same object as `runner._FINALLY_SKIP_REASONS`, contains the five reasons, and `"FINALLY_SKIP_REASONS" not in greenscreen.flow.__all__`.
    - New `tests/unit/test_logon_recovery_publisher.py`, following `tests/unit/test_publisher_calls.py` (`make`, `call`, `records`, `FakeHost`):
      - The derived `_FINALLY_SKIPPED_STOPS` equals the literal five reasons; a failure message prints the difference (drift check).
      - Table over `ERROR_CODES` plus `call_timeout`: `_session_clean(code, None)` is `False` exactly for the five and `call_timeout`, otherwise `None`; `_session_clean(code, "cancel")` and `"shutdown"` give `False` for every code.
      - Through `CallService` with the bundled `tk5-logon`: a recovery stop with states `tk5-logon`, `tso-userid-in-use`, `second_in_use_screen()` gives `CallOutcome.code == "unknown_screen"`, `session_clean is False` and a record with `outcome="unknown_screen"` and `session_clean=False`; a recovery screen that never arrives (with `FakeClock`) gives `timeout` with `session_clean is False`; the in-use screen twice gives `loop_limit`, `session_clean is None` and no `session_clean` member in the record.
    - Update the pins in `tests/unit/test_publisher_calls.py`: in `test_flow_stops_carry_the_flow_stop_members_and_session_clean` the `timeout` row changes from `None` to `False`; the `unexpected_screen` row stays `None`. Search `tests/` for any other test or property that pins `session_clean` for one of the five codes (`test_publisher_no_leak_logs.py` only checks that the field is `False` when present) and update it the same way. No other publisher test changes.
    - Verify: `git diff --name-only -- greenscreen pyproject.toml` shows no new path from this task other than `greenscreen/flow/runner.py` (one added line) and `greenscreen/publisher/calls.py`; run the publisher unit and property tests and `tests/unit/test_flow_*` and require no failure.
    - _Requirements: 11.3, 12.1, 12.2, 12.3, 12.4, 12.5, 12.7, 10.1_

- [x] 7. Property additions and full-suite run (about 0.75 h)
  - [x] 7.1 Add Property 1 in `tests/property/test_recognizer_userid_recognition.py` (new)
    - **Property 1: User id length does not change recognition**
    - Exactly one `@given` test with `@settings(max_examples=100, deadline=None)`, first line `# Feature: logon-recovery, Property 1: User id length does not change recognition`. Inline strategy `st.text(alphabet=string.ascii_letters + string.digits + "@#$", min_size=1, max_size=8)`. No new strategy module.
    - For each drawn id assert that `in_use_screen(id)` satisfies `tso-userid-in-use` and no other bundled Signature and `recognize` returns `tso-userid-in-use`, and that `reconnect_prompt_screen(id)` satisfies `tso-reconnect-password-prompt` and no other and `recognize` returns that name. Count satisfied Signatures with `signature_matches` over `load_bundled_signatures()`, as the matrix test does.
    - **Validates: Requirements 4.4, 9.3, 9.4**

  - [x] 7.2 Extend Property 8 to the two new typeable screens
    - In `tests/property/_flow_strategies.py` add `tso-userid-in-use` and `tso-reconnect-password-prompt` to `TYPEABLE`, and give `typed_cases` an optional `names=TYPEABLE` parameter. Keep the `_TYPED_MAX` assertion valid (255 for both).
    - In `tests/property/test_flow_typing_never_blocks.py` move the existing body into a shared `_check(case)` helper (assertion text unchanged), keep the existing test, and add a second test parametrized over the two new names with `data=st.data()`, drawing `data.draw(fs.typed_cases(names=(name,)))` and `max_examples=100` for each. The existing maximum text length stays unchanged.
    - Source text of every other property test stays unchanged, apart from the files named in this task.
    - **Validates: Requirements 9.1, 9.2, 9.4**

  - [x] 7.3 Run the full suite and fix test-only fallout
    - Run `pytest -m "not integration"` and `pytest tests/property --durations=10`. Every property that draws from `SIGNATURE_NAMES` (`chain_scripts()`, `flows()`) must pass with `max_examples` not lowered. Expect other tests that count seven Signatures or ten captures (`test_fixtures.py`, `test_flow_support.py` and `test_flow_strategy_cost.py` are the likely ones); fix them in test code only, and list each file touched in the task notes. A failure that needs a production change is a stop-and-report.
    - Compare the property suite time with the pre-change time and require it within publisher Requirement 20.17 and flow-runtime Requirement 19.9 (publisher property modules under 120 seconds together, `tests/property` under 240 seconds). If a budget is missed, report it and never trim a test or lower `max_examples` below 100. Record the timings.
    - _Requirements: 9.5, 9.6_

- [x] 8. Checkpoint - recovery implemented and tested without the host
  - Run `pytest -m "not integration"`. Require no failure, no skip among the new unit and property tests (the capture scan of task 2.2 and the credential scans of task 3.2 may skip with a message that names the variable), and that the golden tests of task 1.1 pass unchanged.
  - Run `git diff --name-only -- greenscreen pyproject.toml`. Only the three new Signature files, `greenscreen/recognizer/bundled.py`, `greenscreen/flow/flows/tk5-logon.yaml`, `greenscreen/flow/flows/tk5-system-info.yaml`, `greenscreen/flow/runner.py` (one added line) and `greenscreen/publisher/calls.py` may appear, and `pyproject.toml` must not. Nothing is committed.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 3.9, 5.10, 7.8, 10.1, 12.7_

- [x] 9. Live test with the Cleanup_Helper (written here, not run against the host; about 0.75 h)
  - [x] 9.1 Create `tests/integration/test_flow_live_recovery.py`
    - Mark it `@pytest.mark.integration`. Follow `tests/integration/test_flow_live_system_info.py`: the `host_reachable` fixture through `request.getfixturevalue`, `live_connector_config()`, `LogCapture(logging.DEBUG)` on the root and `greenscreen.connector` loggers, and `_password_forms` imported from that module. Add no new fixture or dependency.
    - If `TK5_USERNAME` or `TK5_PASSWORD` is unset or empty, skip with a message naming each missing variable, before any connection and before `host_reachable` is used.
    - Steps in order: (a) `tk5-logon` through a `Connector`; (b) leave the `with` block without logoff; (c) `tk5-system-info` through a new `Connector`; (d) `tk5-system-info` through another new `Connector`. At (c) assert Outputs in order (`USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`), `USERID` equal to `TK5_USERNAME` case-insensitively, `SYSTEMID` and `RELEASE` non-blank, final screen recognized as `tk5-logon`, and that the in-use Handle_Step ran at least one body iteration. If it ran zero iterations, run the Cleanup_Helper and skip with a message that the lock was not reproduced and the recovery path was not exercised. At (d) assert the same Outputs and zero in-use iterations. Count iterations with the `in_use_iterations(flow, result)` helper of design section 9 (audit records with `ok` at the index of the in-use handle's last child, found through `plan(flow)`, no hard-coded index).
    - Assert no Hex_Form of `TK5_PASSWORD` occurs in `repr(result)`, error text, audit records or DEBUG log records, skipping the hex checks when the password has fewer than 4 characters. Every verdict is a boolean and no assertion message contains the password.
    - Cleanup_Helper: raw `Connector` calls and text waits only (`wait_for_text`, `string`, `enter`), no Flow and no Signature, following the state machine of design section 9 (OPEN, USERID, IN_USE, PASSWORD, ADVANCE, MENU, READY, DONE). Each wait is at most 15 seconds, at most 5 Enters while waiting for the ISPF menu, and no logon is left abandoned at a prompt. It runs in a `finally` block on every exit path (pass, fail, error, skip). If it cannot log the account off, the test fails with a fixed message that says the account may still be locked and names the manual recovery (`LOGON <id> RECONNECT` at the IN USE screen), with the literal `<id>` and no credential, and the earlier exception, if any, as `__cause__`.
    - The test leaves no `s3270` or `ws3270` process, reads credentials only from the environment, and writes no capture and no file.
    - Verify only without the host: collect the test with `pytest tests/integration/test_flow_live_recovery.py --collect-only`, and run it once with `TK5_USERNAME` and `TK5_PASSWORD` unset to confirm it skips with a message naming both variables and makes no connection. Do not run it with the variables set in this task (task 11).
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11_

- [x] 10. Amend the earlier requirements documents
  - [x] 10.1 Amend `.kiro/specs/screen-recognizer/requirements.md`
    - Change "seven" to "ten" in Requirement 8 criteria 2, 11 and 21 (about lines 168, 177 and 185) and Requirement 10 criteria 2 to 4 (about lines 216 to 218), and list the three new names where the text lists the seven. Criterion 21 gains "among the ten captures". Leave the lines that say "seven" about Matcher kinds (about lines 7, 20, 49 and 112) as they are. After the edit no amended criterion contains "seven".
    - Edit by exact line match, not by search and replace over the file. Validate with `validate_spec_format` on the file's absolute path.
    - _Requirements: 9.7_

  - [x] 10.2 Amend `.kiro/specs/flow-runtime/requirements.md`
    - Rewrite Requirement 17 criteria 5 to 8 and 12 (about lines 359 to 362 and 366) so the `tk5-logon` step list matches the flow of task 5.1, in the order of the design. Criterion 17.8 states that the flow types `userid`, presses `enter`, handles `tso-userid-in-use` by typing `LOGON `, `userid` and ` RECONNECT` and pressing `enter`, expects `tso-password-prompt` or `tso-reconnect-password-prompt`, types `password`, presses `enter`, handles `tso-reconnect-ok` with `enter`, handles `tso-pause`, and ends on `ispf-primary-menu`. Replace "no other Type_Step that types an Input" in 17.8 and 17.12 with "the only Type_Steps that type an Input are `userid` (twice) and `password`".
    - Validate with `validate_spec_format`. Do not edit any other spec file in this task.
    - _Requirements: 9.8_

  - [x] 10.3 Amend publisher Requirement 23 and the `session_clean` passages of the publisher design (describes shipped code, not conditional on the live result)
    - Depends on task 6.4. In `.kiro/specs/publisher/requirements.md` rewrite Requirement 23 criteria 1 and 5 for the new set: `session_clean` false for `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout` and `session_error` (the reasons for which the runtime skips the `finally` steps and that reach the Publisher as a Flow stop), whether the stop happened in the steps or in the `finally` phase; criteria 2 to 4 (`call_timeout`, cancellation, shutdown) stay; every other outcome, including `unexpected_screen`, `loop_limit`, `bad_target`, `secret_target`, `host_unavailable`, `input_invalid` and every other Error_Code, makes no claim. State that the Publisher derives the set from the flow runtime's public `FINALLY_SKIP_REASONS`. Criteria 6 and 7 stay as they are. Update the glossary entry for `session_clean` and the other places that list the marked outcomes (search `session_clean` and `Requirement 23`), without changing Requirement 23.7.
    - In `.kiro/specs/publisher/design.md` amend the passages that list the marked outcomes to the same set: the "Call_Log_Record and `session_clean`" paragraph, the "Log outcome of a call without a response" paragraph if it lists codes, the `session_clean` sentence of the "Account lock and recovery" section ("no other outcome is marked"), and the `CallService` interface comment if it lists codes. Do not touch the table row about recovery of a locked user id, the "No recovery logic" and "Exposure" bullets, the error-table row about a locked account or open item 2; those belong to task 12.
    - Validate each file with `validate_spec_format`.
    - _Requirements: 9.9, 12.6_

- [x] 11. Live run against the host
  - [x] 11.1 Run the live recovery test once and record the result
    - Satisfied by the reviewer's live run: run by the reviewer 2026-11-18, passed on the recovery path. `tests/integration/test_flow_live_recovery.py` gave 1 passed in 9.7 s, and `pytest -m integration` gave 7 passed in 28.5 s. The executor does not run it again and does not need the credentials.
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 8.7, 8.9, 8.12, 10.2, 10.3_

- [x] 12. Doc edits for the recovery limit and the lifted exposure restriction (the live pass exists, so these edits are now to be executed)
  - [x] 12.1 Edit `.kiro/specs/publisher/design.md`
    - The live pass on the recovery path is recorded in task 11.1. Execute this edit.
    - Find every stale passage by search, because line numbers drift: `follow-up`, `exposed publicly`, `locked`, `IN USE`, `Account lock`. Expect the table row about recovery of a locked user id (about line 20), the "Account lock and recovery" section including its "No recovery logic" and "Exposure" bullets (about lines 464 to 473), the error-table row about a locked account (about line 757) and open item 2 (about line 909). Replace each so it no longer says the Publisher must not be exposed publicly or that recovery is a follow-up spec. Each replacement states in full, without a reference to any section name of this spec: bundled-flow recovery exists; recovery covers an orphan left at the ISPF primary option menu; an orphan left at `READY`, in a sub-panel or mid-logon (for example an abandoned logon showing `IKJ56700A ENTER USERID`, or the second IN USE state with `IKJ56400A` after an extra Enter) is not handled and stops the call with `session_clean` false (`unknown_screen` and the other stops for which the finally steps are skipped); RECONNECT takes over whatever session holds the user id; the host may purge the orphaned session by itself.
    - Keep the `GS_PUBLISH_FLOWS=tk5-system-info` demo guidance byte-identical, and do not touch the `session_clean` passages edited in task 10.3.
    - Validate with `validate_spec_format`.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 12.2 Edit `.kiro/specs/publisher/requirements.md`
    - Replace the Assumptions statements that the Publisher must not be exposed publicly until a follow-up spec is done (line 22) and the follow-up wording of the neighbouring bullets (lines 23 and 24, and the matching sentence about recovery of a locked user id), found by searching `follow-up` and `exposed publicly`, with the same statements of the recovery limit as task 12.1 (recovery covers an orphan left at the ISPF menu; an orphan left at `READY`, in a sub-panel or mid-logon is not handled and stops the call with `session_clean` false; RECONNECT takes over whatever session holds the user id; the host may purge the orphan by itself). Do not change Requirement 23 (task 10.3 owns it), and publisher Requirement 23.7 stays true.
    - Validate with `validate_spec_format`.
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

  - [x] 12.3 Edit the flow-runtime and screen-recognizer designs
    - In `.kiro/specs/screen-recognizer/design.md` update the passages that state seven bundled Signatures, seven captures, a 7 by 7 matrix and the seven-name `_MANIFEST` (search `seven`, `7 by 7`, `_MANIFEST`, and the capture inventory text) to ten, and add the three new Signatures and captures where the design lists them. In `.kiro/specs/flow-runtime/design.md` update the passages that give the old `tk5-logon` step list or say a logon cannot recover from IN USE (search `tk5-logon`, `Known Limits`, `IN USE`, `follow-up`) to the new step list and the same recovery limit (an orphan left at the ISPF menu is recovered; an orphan left at `READY`, in a sub-panel or mid-logon stops the call with `session_clean` false), and mention the public `FINALLY_SKIP_REASONS` where the design names `_FINALLY_SKIP_REASONS` (keep the sentence the consistency test searches for: `_FINALLY_SKIP_REASONS` in the runner holds `definition`). Do not edit `.kiro/steering/mainframe-host.md`.
    - Validate with `validate_spec_format`, and run `tests/unit/test_flow_spec_consistency.py` after the flow-runtime edit.
    - _Requirements: 10.2, 10.3, 10.5_

- [x] 13. Fix the probe/schema-constant collision in `tests/property/test_publisher_no_leak_responses.py` (test-only; about 0.5 h)
  - [x] 13.1 Fix the probe/schema-constant collision in `tests/property/test_publisher_no_leak_responses.py`
    - The failing example is a supplied count of 9999, which equals MINI's `maximum: 9999` in `/openapi.json`. The response then contains the probe value as a legitimate schema constant, and the no-leak check reports a leak.
    - Test-only fix: draw int probes from a range that cannot equal any numeric constant in the MINI schema (or change MINI's bounds so no probe range reaches them). Derive the constants from the schema at test time (walk the generated `/openapi.json` or the MINI definition for every number); do not hard-code them.
    - Add an assertion in the helper tests of this module that no probe the strategy can produce equals a schema constant, computed from the schema. Keep the stored failing example in the `.hypothesis` database: do not delete the database, and confirm the property passes with that example still stored.
    - No production code change, and no lowering of `max_examples` (keep it at 100 or more).
    - _Requirements: 9.3, 9.4, 9.6_

  - [x] 13.2 Check Properties 6, 8 and 9 of the publisher property tests for the same collision
    - Read the publisher property tests for Properties 6, 8 and 9 (search `tests/property/test_publisher_*.py` for the probe or sentinel strategies they use) and check whether a drawn probe can equal a constant in the schema, a flow definition or a fixed response field. If it can, fix it the same way as task 13.1: restrict the probe range or alphabet, derive the constants from the source rather than hard-coding them, and add a helper-test assertion that no probe can equal one. If none can, record which constants were checked in the task notes and change nothing.
    - Test code only. No production change, no deleted `.hypothesis` data, no lowering of `max_examples`.
    - _Requirements: 9.3, 9.4, 9.6_

- [x] 14. Final checkpoint - everything consistent
  - Run `pytest -m "not integration"` and `pytest tests/property --durations=10`; report the full-suite pass, fail and skip counts and timings, and the timings against the budgets (publisher property modules under 120 seconds together, `tests/property` under 240 seconds). If a budget is missed, report it and never trim a test or lower `max_examples` below 100.
  - Run `git status` and `git diff --exit-code -- pyproject.toml .kiro/steering/mainframe-host.md`. Confirm `git diff --name-only -- greenscreen` lists only the three new Signature files, `greenscreen/recognizer/bundled.py`, the two Flow YAML files, `greenscreen/flow/runner.py` (one added line) and `greenscreen/publisher/calls.py`. Confirm the changes of tasks 13.1 and 13.2 are under `tests/` only. Nothing is committed.
  - Confirm `captures/incoming/` holds no capture file, no capture or fixture holds the password in plain or hex form, and no file written by this plan contains a credential or the host address.
  - Confirm tasks 12.1 to 12.3 are done and state the recovery limit as written (an orphan left at the ISPF menu is recovered; one left at `READY`, in a sub-panel or mid-logon is not handled and stops the call with `session_clean` false).
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 1.1, 3.9, 5.10, 9.6, 10.1, 12.7_

## Notes

- Nothing is marked optional, matching the sibling plans; every test sub-task is required, including the single property test of task 7.1.
- Nothing is committed by the executor. The reviewer commits.
- Task 1 runs first on purpose: the golden call lists must come from the unchanged flows before any signature or flow change (Requirement 11.5). The guard is an empty `git diff --stat -- greenscreen/flow greenscreen/recognizer/signatures`, and the lists stay uncommitted.
- Task 6.4 is the one small publisher change (Requirement 12). It exposes `FINALLY_SKIP_REASONS` in `greenscreen/flow/runner.py` and derives the `session_clean` set from it. Design Open item 1 records the check of the approved five-reason list against the runtime's real set: the runtime also holds `input_invalid` and `definition`, which never reach the publisher as a Flow stop, and skips `finally` when no screen was accepted yet. Report any new mismatch there instead of choosing silently.
- Design Open item 2: the bundled Signatures stop a visible reconnect prompt with `unknown_screen`, not `secret_target`. Task 6.2 tests both the bundled outcome and the test-only-Signature outcome (`secret_target`); Requirement 7.5 now says so.
- Task 11 was satisfied by the reviewer's live run on 2026-11-18 (passed on the recovery path), so task 12 (stale exposure and recovery wording in the publisher, flow-runtime and screen-recognizer docs) is now to be executed. Task 13 is a test-only fix for a collision between a generated probe and a schema constant; it changes no production code. Task 10.3 (publisher Requirement 23 and its `session_clean` passages) is not conditional, because it describes shipped code.
- The task dependency graph below keeps tasks that write the same file in different waves (`tests/screen_support.py` in 2.1 and 4.1, `tests/unit/test_flow_captures.py` in 2.1 and 2.2, `tests/unit/test_recognizer_capture_matrix.py` in 2.1 and 3.2, `tests/unit/test_flow_logon_recovery.py` in 6.1 and 6.2, `tests/unit/test_flow_system_info_script.py` in 1.1 and 6.3). Checkpoints and top-level tasks are left out of the graph.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "6.1", "6.3", "6.4"] },
    { "id": 6, "tasks": ["6.2", "7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3"] },
    { "id": 8, "tasks": ["9.1"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3"] },
    { "id": 10, "tasks": ["12.1", "12.2", "12.3", "13.1"] },
    { "id": 11, "tasks": ["13.2"] }
  ]
}
```
