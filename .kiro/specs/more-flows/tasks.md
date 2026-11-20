# Implementation Plan: more-flows

## Overview

Build the five read-only Command_Flows (`tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members`, `tk5-job-status`) as described in `requirements.md` and `design.md` in this folder. The work is: promote 36 capture files, add two signatures (`tso-cleared`, `tso-reenter`), extend the Flow runtime (Rows_Output, `collect` step, Flag_Output, the `exec_key` refactor `_press`), add the `dsname` input rule and its tests, extend the shared logon steps by three Handle steps (the Logon_Cleanup), write the five Flow files, and correct the older spec texts named in Requirement 23.

**Order (server and runtime first, then Flows).** Tasks 1 to 6 build and prove the captures, signatures, runtime, name rule and logon extension on scripted screens and test-only Flows; no bundled Flow is added yet and the eight-Flow counts are not touched. Task 7 is CHECKPOINT A and a STOP-POINT: the executor stops there and waits for the reviewer. Tasks 8 to 11 (the five Flows, the count edits, Publisher, Ask and console checks, spec text edits, final run) start only after the reviewer says so. The section "Reviewer-only items" lists what the executor does not run.

Production files touched: `greenscreen/recognizer/bundled.py`, `greenscreen/recognizer/signatures/tso-cleared.yaml` and `tso-reenter.yaml` (new), `greenscreen/flow/model.py`, `validate.py`, `yamlio.py`, `screens.py`, `runner.py`, `bundled.py`, `greenscreen/flow/flows/tk5-logon.yaml`, `tk5-system-info.yaml` and the five new Flow files, and, only if D1 stays at its default, `greenscreen/publisher/console/console.css`. Not touched: `greenscreen/publisher/**` (other than that CSS file), `greenscreen/connector/**`, `greenscreen/publisher/ask/**`, `.env.example`, `README.md`, `pyproject.toml`, `.kiro/steering`. Every path is repo-relative. The executor works on Windows with Python 3.11.9. Every task states: no live host, no real model, no browser; Windows.

**Correction to the brief about the capture count.** The brief speaks of promoting 56 capture files. The design and requirements move 36 files (18 captures) from `.kiro/specs/more-flows/captures`; `/captures` then holds 56 files (28 captures: the 10 existing captures, 20 files, plus the 18 moved). Task 2.1 moves 36 and checks that 56 are there afterwards.

**Pre-existing tree state.** On 2026-11-19 `git status` showed ` M .kiro/steering/mainframe-host.md` (the reviewer's own edit) besides the untracked spec folder. The executor records it, never touches, stages or reverts it, and does not treat it as a stop.

## Open points from the design (NOT resolved here)

The reviewer decides these. The tasks follow the default column. If the reviewer decides otherwise, only the tasks in the last column change.

| Point | Default taken in these tasks | Tasks affected if the reviewer decides otherwise |
|---|---|---|
| D1. Console shows a multi-line string output on one line (X4) | Apply: CSS-only change to `.outputs dd` (`white-space: pre-line`, `max-height: 24rem`, `overflow-y: auto`) and one new test `test_outputs_keep_line_breaks_and_scroll` in `tests/unit/test_console_css.py`. This overrides the design's "not applied" default and Requirements 17.6 and 18.4. | 9.3 (dropped), 11.1 (expected file list loses `console.css` and `test_console_css.py`) |
| D2. Tool descriptions and the probe-alphabet test (X1) | Descriptions reworded without `;`, `#` and `@` (texts in design section 6); `test_probe_alphabet_is_absent_from_every_fixed_text` stays unedited. | 8.2 to 8.6 (description and input description texts go back to the requirements wording), 8.7 (an extra flagged edit of `tests/unit/test_publisher_helpers.py`, removing `;`, `#`, `@` from the alphabet or the scan; the alphabet test in the new description test is dropped) |
| X3 / D5. Bad `dsname` gives HTTP 422 `input_invalid`, not 400 `request_invalid` | Accept 422 `input_invalid`; all tests assert 422 and the Flow-level `input_invalid`; the report says this differs from the brief. | 5.2, 8.4, 8.5, 8.10, 9.1 (assertions), 11.1 (report wording). A change to 400 would need production code in `greenscreen/publisher/` (out of scope, stop and report) |
| X5 / D3. Validator rule `equals_blank_edge` (an `equals` with a leading or trailing blank) | Add the rule. | 4.2 (rule removed), 4.5 (its test removed) |
| X8. `test_no_literal_credentials_or_placeholders` over eight Flows | Narrow the parametrization to `NAMES[:3]`; the five new files get their own literal sets in `test_flow_readonly.py`. | 8.7 (edit changes), 8.8 (literal sets stay) |
| `.kiro/specs/publisher/tasks.md` line 31 (D8) | No edit; only line 294 is edited. | 10.1 |
| REENTER reason code (open item 1) | Existing code `unexpected_screen` (HTTP 502, no new code). A new code would change `REASON_CODES`, `ERROR_CODES`, `MESSAGES`, `HTTP_STATUS` and every pin of 13 and 22, which is outside this spec: stop and report. | 8.4, 8.5, 8.10, 9.1 |
| Depth of the logon recovery (open item 2) | Three landings (`READY`, cleared screen, REENTER prompt); a sub-panel, mid-logon and the second IN USE state stay unhandled. | 6.1, 6.2, 6.3, 10.1 to 10.3, 8.10 |
| `STATUS` shape for an account with batch jobs (open item 3) | Only the one captured line; `max_screens` 3, `max_rows` 40; synthetic screens for more jobs and paging. | 8.6 |
| PA1 at a `***` pause and other prompts (open item 4) | Not used: a pause is drained with Enter only; PA1 only in the Handle on `tso-reenter`. | 6.1, 8.2 to 8.6 (Finally_Block), 8.9 |
| Plain `LISTCAT` over several screens (open item 5, R1) | `next_row` 0 for continuation screens; a synthetic two-screen test covers it. If the live host repeats the heading, `next_row` becomes 2 (one YAML key). | 8.3 (YAML key and one test value) |
| `finally` budget (open item 9, R3) | `timeouts` `step` 10.0, `run` 20.0, `finally` 6.0 in all five Flows. The fallback after live measurement is `run` 18.0 and `finally` 8.0 (still `run + finally + 4 = 30`). | 8.2 to 8.6 (the three numbers), 9.2 (the asserted numbers; the test asserts the sum, so only the literals change) |
| Steering column correction (open item 7: member names start at col 3, not col 2) | Owned by the reviewer. No task edits `.kiro/steering`; 2.3 asserts col 3 from the real captures. | none (11.1 only confirms the steering file is untouched by the executor) |
| Continue the call after a landing at `READY` (open item 8) | Deferred: the call ends once with `unexpected_screen` at index 26 and the next call is normal. | 6.1, 6.2, 6.3, 10.1 to 10.3 |
| D4. Operator notes (no repository file carries them) | The notes are in the final report only; `.env.example` and `README.md` stay unchanged. | 11.1 |
| D6. Property 11 (one audit record per `collect`) | Added as a property test. | 4.10 |
| D7. Helper name `has_partial_repaint` | As written. | 3.3 |

### Estimates and order

About 64 hours of work. Task 7 is the STOP-POINT.

| # | Top-level task | Hours |
|---|---|---|
| 1 | Library documentation checks and pre-flight (record only) | 0.75 |
| 2 | Promote the captures; capture tests | 3.5 |
| 3 | Signatures `tso-cleared` and `tso-reenter`; matrix and count pins; test support | 3.5 |
| 4 | Runtime extensions with unit tests and properties 1, 2, 3, 4, 5, 7, 11 | 20.75 |
| 5 | The `dsname` rule: support, unit tests, properties 6 and 10 | 4.5 |
| 6 | Logon recovery extension; new tests; property 8; logon family unedited | 5.5 |
| 7 | CHECKPOINT A: interim report, STOP and wait for the reviewer | 0.5 |
| 8 | The five Flows, count edits, sync, read-only and REENTER tests, property 9 | 15.0 |
| 9 | Publisher, Ask and console impact; D1 CSS; integration test files | 6.0 |
| 10 | Spec text edits (Requirement 23) | 3.25 |
| 11 | Final checkpoint and report | 1.0 |
| | **Total** | **64.25** |

Properties 6 and 10 (they need the `dsname` rule), 8 (needs the logon change) and 9 (needs the two Name_Flows) sit in the tasks after the code they test, not all in task 4. The properties of task 4 run against test-only Flows built in the test files.

If time runs short, cut in this order and report each cut: the extra adapter-style examples of 9.1, the `LEVEL`-capture variants of 4.6 (keep the seven-page replay), the Node-free CSS examples of 9.3. Never cut a property test, the secrecy checks, the matrix, or the Handle-landing table of 6.2.

### Rules for every task

- DO NOT COMMIT and do not stage anything. Leave every change in the working tree. The reviewer commits. Moving captures uses `Move-Item`, never `git mv`.
- No secret is printed or written: no `TK5_PASSWORD`, no `TK5_USERNAME` value, no host address, no API key, in code, tests, fixtures, logs, assertion messages, notes or spec text. No capture, fixture or log may contain the password (checked in plain, lower, upper and hex form). The user id that the host prints inside the real captures is accepted (Decision 22); new tests and documents do not repeat it.
- No new dependency. `pyproject.toml` stays unchanged. No framework, build step, CDN, font, script or image.
- Stop and report a production defect found outside the files named in the Overview. Do not fix it silently.
- Existing tests keep passing unmodified, with exactly the flagged edits listed in the table "Every existing-test edit" below and in the task that makes each one. Each such edit lists the expected values. No assertion is removed or weakened. If any other existing test fails, stop and report the test and the cause; never edit it.
- No task needs the live host, a real model, a real network or a browser. Tests use `ScriptedSession`, `FakeClock`, `FakeHost`, recorded captures and raw ASGI scopes. Three integration files are only written (task 9.4); they skip when the host is unreachable.
- Node is needed for page tests (console CSS and asset tests). Prepend it for the shell: `$env:Path = "C:\Program Files\nodejs;" + $env:Path`, then record `node --version`.
- Library documentation: before any task that writes code using a library API (`re`, PyYAML, Hypothesis, pytest, s3270 scripting, Node), re-check that library's row in the design's "Library documentation checks" table (page, version, date). If the installed version differs from the recorded one, or the row is missing, read the page again and append a dated line (`Checked <date>: <page URL>, <version>, <conclusion>`) to that section of `design.md`. Tasks that do this say so. Task 1.1 appends the first dated lines; `design.md` is edited for those lines only and nowhere else.
- Python in `design.md` is pseudocode; the YAML in it is the exact text the code must emit. Every shipped Flow and signature file equals `to_yaml()` output (the `test_flow_sync` rule).
- Every property test is a sub-task with exactly one `@given` test per property, `max_examples` at least 100 (200 for Properties 6 and 9), first line `# Feature: more-flows, Property <n>: <statement>`, the design's property numbers (the requirements use letters; the design numbers are the ones used here).
- Static rules for new production code: `greenscreen/flow/screens.py` is the only Flow module that reads `Screen.cell_grid` and never reads `text_grid`, `fields`, `find_field` or `Field.text` (`test_flow_static.py`). No log record, exception message, audit field or frame local that leaves `run_flow` holds row text, a screen, an input value or a supplied name.
- Python version: the executor runs everything on 3.11.9. Python 3.12 to 3.14 are reviewer items.
- `.kiro/steering` is never edited. `.kiro` is never git-ignored.
- Every task is required except where a sub-task carries `*` (none do).

### Every existing-test edit (and the task that makes it)

No other existing test file is edited. "Before" and "after" are the values the executor must see.

| Task | File | Edit | Before | After |
|---|---|---|---|---|
| 2.2 | `tests/screen_support.py` (support) | `CAPTURE_NAMES` gains the 18 stems | 10 names | 28 names |
| 2.2 | `tests/unit/test_recognizer_capture_inventory.py` | `EXPECTED_NAMES` plus the 18 stems; `len(paths) == 10`; `len(CAPTURE_NAMES) == 10`; docstring "ten screens" | 10, 10 | 28, 28 |
| 2.2 | `tests/unit/test_flow_captures.py` | `_EXPECTED_NAMES` in the two tests that carry it plus the 18 stems | 10 names | 28 names |
| 3.2 | `tests/unit/test_recognizer_capture_matrix.py` | `EXPECTED` gets 17 overrides; counts `len(paths)`, `len(CAPTURE_NAMES)`, `len(sigs)`, `performed`, `count` | 10, 10, 10, 10, `10 * 10 == 100` | 28, 28, 12, 12, `28 * 12 == 336` |
| 3.2 | `tests/unit/test_recognizer_bundled.py` | three counts; `OWN_CAPTURES` plus two entries | 10, 10, 10 | 12, 12, 12; plus `tso-cleared` and `tso-reenter` (capture `tso-listds-reenter`) |
| 3.2 | `tests/unit/test_recognizer_recognize.py` | line 117 `len(reduced) == 9` | 9 | 11 |
| 3.3 | `tests/flow_support.py` (support) | `_SIGNATURE_CAPTURE` plus two entries; new `has_partial_repaint(name)` | 10 entries | 12 entries |
| 3.3 | `tests/property/_flow_strategies.py` (support) | import `has_partial_repaint`; `ChainScript.states` fallback | draws a repaint for every name | blank repaint when the name has none |
| 8.7 | `tests/unit/test_flow_bundled.py` | `NAMES` (line 22); `len(flows) == 3` (line 40); line 319 `parametrize("name", NAMES)` becomes `NAMES[:3]` | 3 names, 3 | 8 names, 8, first three |
| 8.7 | `tests/unit/test_flow_packaging.py` | `EXPECTED_YAML` plus the five file names | 3 files | 8 files |
| 8.7 | `tests/unit/test_publisher_registry.py` | `BUNDLED` (line 24) | 3 names | 8 names in manifest order |
| 8.7 | `tests/unit/test_publisher_openapi.py` | line 55 `len(registry) == 3` | 3 | 8 |
| 8.7 | `tests/unit/test_publisher_stack.py` | lines 394 to 396 three counts; rename the test at line 381 | 3, 3, 3 | 8, 8, 8; `test_unset_publish_list_publishes_all_eight_flows` |
| 8.7 | `tests/unit/test_publisher_slice.py` | line 102 `loaded_count == 3`; line 136 `== prepared.loaded_count == 3` | 3, 3 | 8, 8 |
| 9.3 | `tests/unit/test_console_css.py` | one test function added (D1); nothing else in the file changes | n/a | `test_outputs_keep_line_breaks_and_scroll` |

`tests/unit/test_recognizer_packaging.py` is NOT edited: its `BUNDLED` list holds ten names and the test only checks that those files exist, so it passes with twelve files (an observation to confirm in 3.2). The two test names `test_exactly_three_entries_with_expected_keys` and `test_exactly_three_yaml_files_shipped` keep their names (only the numbers change); `test_ten_bundled_signatures` keeps its name.

## Tasks

- [ ] 1. Library documentation checks and pre-flight (about 0.75 h; record only; no live host, no real model, no browser; Windows)
  - [ ] 1.1 Record the documentation checks and verify the starting tree
    - Edit `.kiro/specs/more-flows/design.md` only, in the section "Library documentation checks": append dated lines (`Checked <date>: <page URL>, <version>, <conclusion>`) re-confirming the rows that later tasks rely on: Python `re.fullmatch` (3.11.9), Hypothesis strategies (installed version from `python -m pip list`), PyYAML `safe_dump` (installed version), the s3270 and ws3270 scripting page for `PA` and `String` (as far as it can be fetched; say what could not be), and the Node line (`node --version` with Node on PATH). If an installed version differs from the table, say so in the line.
    - Pre-flight: `git status --short` and `git diff --stat`. Expected: nothing staged; only `.kiro/specs/more-flows/` pending (untracked) plus the pre-existing ` M .kiro/steering/mainframe-host.md`. Anything else: STOP and report. `git diff --stat -- pyproject.toml greenscreen/ tests/` prints nothing.
    - Baseline counts: `python -m pytest -m "not integration" --collect-only -q -p no:cacheprovider` (record the number of tests collected; the design measured 3,548 on the scratch copy and the last Windows run was 3524 passed, 4 skipped, 0 failed, 434.01 s) and run `python -m pytest tests/unit/test_flow_static.py tests/unit/test_flow_sync.py tests/unit/test_recognizer_bundled.py tests/unit/test_recognizer_capture_matrix.py -p no:cacheprovider` once: all pass before any change. Record both numbers for the final report.
    - Make NO change to any other file. Run `validate_spec_format` on `design.md` and report the result.
    - _Requirements: 18.4, 18.5, 19.6_

- [ ] 2. Promote the captures (about 3.5 h; no live host, no real model, no browser; Windows)
  - [ ] 2.1 Move the 36 capture files into `/captures` (about 0.75 h)
    - Before moving, compute SHA-256 of each of the 36 files in `.kiro/specs/more-flows/captures` and compare with the 36 hashes in the "Capture inventory" of `requirements.md`. Any mismatch: STOP and report.
    - `Move-Item` the 36 files (the 18 stems of design section 1, each with `.ascii.txt` and `.readbuffer.txt`) into `captures/`. Not `git mv`, not staged. Confirm no existing file in `/captures` is overwritten (the destination names must not exist before the move) and that the 36 destination hashes equal the source hashes.
    - Remove the now empty folder `.kiro/specs/more-flows/captures`. The spec folder then holds `.config.kiro`, `requirements.md`, `design.md`, `tasks.md`.
    - Confirm `captures/` holds exactly 56 files (28 stems x 2) and `captures/incoming` does not exist. Run the password-free scan on the 36 files only if `TK5_PASSWORD` is set in the shell: search each file for the password in plain, lower, upper and hex form (via `tests/connector_support.forms_of_run`), report counts only, never the value. When it is unset, say "skipped, TK5_PASSWORD unset".
    - Do not edit any file under `/captures`. Do not add a capture of the screen after the password entry (steering rule).
    - _Requirements: 1.1, 1.2, 1.4, 1.7_

  - [ ] 2.2 Update the capture test support and the inventory tests (about 0.75 h)
    - Flagged edits (see the table): `tests/screen_support.py` `CAPTURE_NAMES` gains the 18 stems in alphabetical order (28 names); `tests/unit/test_recognizer_capture_inventory.py` `EXPECTED_NAMES` gains the 18 stems, `len(paths) == 10` becomes 28, `len(CAPTURE_NAMES) == 10` becomes 28, and the docstring says 28 screens; `tests/unit/test_flow_captures.py` `_EXPECTED_NAMES` (in `test_readbuffer_captures_are_exactly_the_ten_names` and in `test_no_capture_exists_for_the_screen_after_the_password_entry`) gains the 18 stems. No assertion is removed or loosened; test function names stay.
    - Expected after 3.2 is done: these three files pass. Between 2.2 and 3.2 the matrix test fails on its counts and `test_recognizer_bundled` stays green; this red window is expected and short, and the executor does not stop on it.
    - Run `tests/unit/test_recognizer_capture_inventory.py`, `tests/unit/test_flow_captures.py` and `tests/unit/test_render_left_inverse.py` (the property one under `tests/property/`; it parses every readbuffer capture): they pass.
    - _Requirements: 1.5, 1.7, 2.7_

  - [ ] 2.3 Write `test_command_capture_files.py` and `test_command_capture_facts.py` (about 2.0 h)
    - Re-check the Hypothesis and `re` rows only if the file uses them (it should not); read the design sections "Data Models, Capture facts" and Requirement 1 first.
    - `tests/unit/test_command_capture_files.py` (new): the 36 SHA-256 values (copied from the requirements' list; names only, no secret) for the promoted files; every readbuffer file parses with `ScreenParser` to 24 by 80 and the `Ascii()` rows of the matching ascii file equal `Screen.text_grid`; no promoted file contains the password in plain, lower-case, upper-case or hex form (`forms_of_run`), no promoted Screen has a non-blank hidden cell; the password part is skipped with a reason when `TK5_PASSWORD` is unset. It does NOT check the user id.
    - `tests/unit/test_command_capture_facts.py` (new): for each of the 18 command captures, the cursor, the non-blank rows, the first column and length of each row, the unprotected field-start positions and the Prompt_Row of the design's table "Capture facts"; member names start at column 3 in all 136 rows of the seven member captures (field start at column 0, two blank cells, then the name); member counts 16, 23, 23, 23, 23, 23, 5 (total 136) with the first three names `$$$INDEX`, `$HISTORY`, `ADDALIAS` and the last `ZAPDSCB`; every row of `tso-listcat-output` from row 2 to the Prompt_Row holds exactly one blank-free token. No user id literal anywhere.
    - A failure message names the file and the fact, never a screen row that could hold a secret.
    - _Requirements: 1.2, 1.3, 1.4, 1.6, 12.5_

- [ ] 3. Signatures `tso-cleared` and `tso-reenter` (about 3.5 h; no live host, no real model, no browser; Windows)
  - [ ] 3.1 Add the two signature files and the manifest names (about 0.75 h)
    - Create `greenscreen/recognizer/signatures/tso-reenter.yaml` and `tso-cleared.yaml` with exactly the text of design section 2 (the `tso-cleared` file has 26 matchers: one `field_layout` with count 1 at (23,79), one `cursor_field` at (23,79) with `hidden: false`, and a `region_regex` `^ *$` of length 80 at column 0 for each of the rows 0 to 23). Write them from the draft objects with `ScreenSignature.to_yaml()` so the shipped text equals the emitted text; no colon in a description. No user id, host or credential in either file.
    - `greenscreen/recognizer/bundled.py`: `_MANIFEST` gains `"tso-cleared"` and `"tso-reenter"` after `"tso-reconnect-ok"`, in this order; the docstring says twelve instead of ten. Nothing else changes; `tso-ready.yaml` and `tso-pause.yaml` stay byte for byte.
    - Run `tests/unit/test_recognizer_line_mode_signatures.py` and `tests/unit/test_recognizer_packaging.py`: they pass unedited. Report whether `test_recognizer_packaging.py` passes (it checks only that its ten names exist).
    - _Requirements: 2.1, 2.6, 21.1_

  - [ ] 3.2 Update the matrix and the count pins (about 1.25 h)
    - Flagged edits (before and after values in the table above). `tests/unit/test_recognizer_capture_matrix.py`: `EXPECTED` gets 17 overrides: `tso-listds-reenter` maps to `tso-reenter`; the 8 new pause captures (`tso-listcat-level`, `tso-listcat-level-page2`, `tso-listds-members`, `tso-listds-members-page2` to `-page6`) map to `tso-pause`; the 8 other new output captures (`tso-time-output`, `tso-listcat-output`, `tso-listcat-level-page3`, `tso-listds-output`, `tso-listds-not-in-catalog`, `tso-listds-reenter-after-pa1`, `tso-listds-members-page7`, `tso-status-output`) map to `tso-ready`. `tso-cleared` maps to itself by the default, and the existing `tso-pause-2` mapping stays. Read the existing `EXPECTED` first and make the mapping equal the design's matrix table: 12 signatures, 28 captures, 336 evaluations, exactly one match per capture, `tso-ready` matched by 9 captures and `tso-pause` by 9. Counts: 28, 28, 12, 12 per capture, `28 * 12 == 336`.
    - `tests/unit/test_recognizer_bundled.py`: the three counts 10 become 12 (`len(loaded)`, the glob count, `len(load_bundled_signatures())`); `OWN_CAPTURES` gains `"tso-cleared": "tso-cleared"` and `"tso-reenter": "tso-listds-reenter"`.
    - `tests/unit/test_recognizer_recognize.py` line 117: `len(reduced) == 9` becomes 11.
    - Run those three files plus `tests/unit/test_recognizer_packaging.py`, `test_recognizer_public_api.py`: pass. The matrix result is part of the CHECKPOINT A report (336 evaluations, 0 mismatches).
    - _Requirements: 2.2, 2.4, 2.5, 21.1_

  - [ ] 3.3 Update the Flow test support for the new signatures (about 0.75 h)
    - Flagged edits to support files. These sit here, not in task 4, because adding the two signatures to the manifest makes three property tests fail until the support knows them (measured on the scratch copy). `tests/flow_support.py`: `_SIGNATURE_CAPTURE` gains `"tso-cleared": "tso-cleared"` and `"tso-reenter": "tso-listds-reenter"`; new `has_partial_repaint(name) -> bool` (False when the capture has no repaintable cell, which is `tso-cleared`); `partial_repaint` still raises `LookupError` for such a name, so no assertion of `tests/unit/test_flow_support.py` changes. `tests/property/_flow_strategies.py`: import `has_partial_repaint`; `ChainScript.states` uses `blank_screen() if code == 0 or not has_partial_repaint(prev) else partial_repaint(prev, code - 1)`.
    - Do not edit any assertion of `test_flow_determinism.py`, `test_flow_stale_reads.py`, `test_flow_unknown_stops.py`, `tests/unit/test_flow_support.py`. Run them: they pass unedited with 12 signatures.
    - _Requirements: 2.7_

  - [ ] 3.4 Add the typed-over cleared-screen test and the `tso-reenter` negative cases (about 0.75 h)
    - Append to `tests/unit/test_command_capture_facts.py` (file created in 2.3): a copy of the capture `tso-cleared` with a command typed at the cursor (`typed_screen`, MDT set) is unknown by itself and matches `tso-cleared` only after `build_comparison(pre=typed, accepted=cleared)`; `tso-reenter` matches `tso-listds-reenter` only and not `tso-listds-reenter-after-pa1` (that capture stays `tso-ready`); no other bundled signature matches `tso-listds-reenter`; `tso-cleared` matches no other of the 28 captures and no other signature matches the `tso-cleared` capture.
    - _Requirements: 2.2, 2.3, 21.1_

- [ ] 4. Runtime extensions (about 20.75 h; no live host, no real model, no browser; Windows)
  - [ ] 4.1 Model and YAML: `model.py` and `yamlio.py` (about 1.5 h)
    - Re-check the PyYAML `safe_dump` row and its dated line. Read design sections 3.1 and 3.2 first.
    - `greenscreen/flow/model.py`: `OutputSpec` gains `next_row`, `max_rows`, `equals`, each `... | None = None`, after the existing six members; new frozen slotted dataclass `CollectStep(output, more, max_screens)` with `kind: ClassVar[str] = "collect"`; the `Step` union gains it. `plan()` needs no change. `greenscreen/flow/__init__.py` keeps its nine names (`CollectStep` is not exported).
    - `greenscreen/flow/yamlio.py`: the emitted order of an output is `name, type, signature, row, col, length`, then `next_row`, `max_rows`, `equals`, each only when not `None`; the reader requires the first six and accepts the three as optional keys; `_STEP["collect"]` and `_STEP_REQUIRED["collect"]` with all four keys (`kind`, `output`, `more`, `max_screens`) required; `_step_to_mapping` and `_step_from_mapping` handle `collect`. A `collect` step inside a Handle body is rejected by the reader with the existing message `unsupported step kind 'collect'`. An output without the three keys is emitted byte for byte as today.
    - Run `tests/unit/test_flow_yaml.py`, `test_flow_model.py` (if present), `test_flow_bundled.py` (with the three old Flows), `test_flow_public_api.py`: pass unedited.
    - _Requirements: 3.1, 3.2, 5.1, 5.6_

  - [ ] 4.2 Validator rules: `validate.py` (about 2.0 h)
    - Read design section 3.3 first (the rule table). Messages hold rule names and field names only, never a scalar.
    - Add every rule of the table: `rows_requires_str`, `out_of_range` (`max_rows` 1 to 500, `next_row` 0 to 23, `max_screens` 1 to 50), `next_row_requires_rows`, `equals_requires_int`, `invalid_text` (empty, not printable ASCII, over 80), `longer_than_region`, `equals_excludes_rows`, `equals_blank_edge` (X5, default: add), `needs_exactly_one_read` for a Rows_Output (a plain output keeps `needs_exactly_one_extract`, X7), and the `collect` rules `output: not_a_rows_output`, `more: invalid_name`, `more: same_as_output_signature`, `max_screens: out_of_range`, `output: signature_not_in_arming_expect`, `output: unarmed`, `collect: not_in_steps`, `kind: not_allowed_in_handle`, `output: undeclared_output`. `_StepWalk.walk` gets a `CollectStep` branch that, like `extract`, leaves `armed` and `arming` as they are; `extract_counts` counts a `collect` as the one read of its output; `reference_violations` checks `more` against the signature names.
    - Run `tests/unit/test_flow_validate.py` and `test_flow_static.py`: pass unedited (`needs_exactly_one_extract` for plain outputs is unchanged).
    - _Requirements: 3.3, 3.4, 3.5, 3.7, 5.2, 5.3, 5.4, 5.5, 7.1_

  - [ ] 4.3 Row reader and the `_press` refactor: `screens.py` and `runner.py` (about 1.5 h)
    - Read design sections 4.1 and 4.3 first. This task changes no behaviour of a run.
    - `greenscreen/flow/screens.py`: `prompt_row(view)` (highest row whose hidden-blanked `base_rows` entry is non-empty after `strip(" ")`, `-1` if none) and `read_rows(screen, view, start, col, length)` (rows from `start` up to, not including, the prompt row, each read with the existing `read_region`, stripped, empty rows skipped, `None` on any hidden cell). The module still reads only `cell_grid`.
    - `greenscreen/flow/runner.py`: extract the body of `exec_key` into `_press(idx, kind, key, n) -> str` (no current screen is `unexpected_screen`; the pre-key read; `_key_check` which now takes the step `kind`; send the key; set `pre_key_screen` and `pre_key_name`; clear `current` and `typed_fields`); `exec_key` becomes one call with `kind` `"key"`. No other runner change in this task.
    - Run the whole `tests/unit/test_flow_runner_*.py` family, `test_flow_static.py`, `test_flow_logon_script.py`, `test_flow_system_info_script.py` and the `tests/property/test_flow_*.py` files: they pass unedited.
    - _Requirements: 4.1, 4.2, 4.7, 4.10, 6.3, 18.1_

  - [ ] 4.4 Rows, flag and `collect` execution: `runner.py` (about 2.5 h)
    - Read design sections 4.2, 4.4 and 4.6 first. The `screen_size` check and the signature check stay in front of the new branches.
    - `exec_extract`: a Rows_Output (`max_rows` set) reads with `read_rows`, stops with `hidden_output` on `None`, stops with `loop_limit` (detail `output <name>`) when the row count exceeds `max_rows` and stores nothing, else stores the rows joined by one LF (empty string for none). A Flag_Output (`equals` set) reads with `read_region`, strips blanks, and stores 1 when the text equals `equals` and 0 otherwise, with no digit rule; a hidden cell is `hidden_output`. The existing single-row and `int` branches are unchanged.
    - New `exec_collect` exactly as the pseudocode: accepted names are the output signature and `more`; a current screen of another name, or none, stops with `unexpected_screen` (a held screen stays held); read each screen (first screen from `row`, later ones from `next_row` or `row`); `loop_limit` when total rows exceed `max_rows` (no value stored) or, on a More_Screen, when screens read equal `max_screens` (before any Enter); otherwise `_press(idx, "collect", "enter", None)` then `poll(..., accepted=(signature, more), expected=...)` with no tolerate list. The value is the join of all rows; the audit holds one record with `kind` `collect`, `signature` the Final_Screen name, `iteration` `None`; the debug log holds the screens read as `count`, never a row. `_EXECUTORS["collect"]` registers it; `_referenced_names` adds `more`. `REASON_CODES` (13) and `ERROR_CODES` (22) are unchanged; `poll`, `exec_handle`, `run_finally` and `_FINALLY_SKIP_REASONS` are untouched.
    - Run the existing runner, validate, yaml, static and logon test families unedited: all pass.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.9, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 7.2, 7.3, 18.2, 18.3_

  - [ ] 4.5 Write `test_flow_rows_output.py` (about 2.5 h)
    - Re-check the Hypothesis row only if used (unit file: examples only). Read Requirements 3, 4 and 7 first.
    - `tests/unit/test_flow_rows_output.py` (new): `to_yaml` key order and byte equality for a Flow with a Rows_Output and a Flag_Output; an output without the three keys is emitted as before; every validator rule name of design section 3.3 for outputs (`rows_requires_str`, both `out_of_range` cases, `next_row_requires_rows`, `equals_requires_int`, `invalid_text` for empty, non-ASCII and over-80, `longer_than_region`, `equals_excludes_rows`, `equals_blank_edge` for a leading and a trailing blank, `needs_exactly_one_read` for zero and two reads of a Rows_Output, and `needs_exactly_one_extract` still reported for a plain output, `region_exceeds_row`); the shipped `tk5-logoff.yaml` equals `Flow.to_yaml()` byte for byte; runner examples with `ScriptedSession` and test-only Flows: rows on `tso-time-output` (the one line of row 1), rows on `tso-listcat-output` (seven names), a row at or after the Prompt_Row gives the empty string, `loop_limit` with no value when rows exceed `max_rows`, `hidden_output` with a hidden cell in a read row, `screen_size` for a smaller screen, a plain output unchanged.
    - Messages and failures never print a row or a screen.
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.10, 7.1_

  - [ ] 4.6 Write `test_flow_collect.py` (about 2.5 h)
    - Read Requirements 5 and 6 first.
    - `tests/unit/test_flow_collect.py` (new): YAML round trip of a `collect` step and the key order; a `collect` in a Handle body is rejected by the reader; every `collect` validator rule of the table; `reference_violations` and `_referenced_names` include `more`; replay of the seven real member pages through a test-only Flow whose parameters equal the planned `tk5-library-members` (`row` 7, `col` 3, `length` 8, `next_row` 0, `max_rows` 200, `max_screens` 10, `more` `tso-pause`): 136 names in screen order, 6 Enter keys at the `collect` step, first three `$$$INDEX`, `$HISTORY`, `ADDALIAS`, last `ZAPDSCB`; replay of the three `LISTCAT LEVEL(SYS2)` captures through a test-only Flow (row 1, `next_row` 0, `col` 1, `length` 79, `max_rows` 100, `max_screens` 5): 50 lines, line 45 `NONVSAM ------- SYS2.SUPRTREK.HELP`, line 46 `IN-CAT --- SYS1.MCAT.TK5`, exactly 2 Enter keys; `max_screens` lowered to 3 gives `loop_limit`, finally steps run, Enter count at the `collect` is `max_screens - 1`; `max_rows` lowered to 30 gives `loop_limit` on page 2; a blank screen as page 3 gives `unknown_screen` after the step timeout with 3 Enters and the finally steps skipped; the ISPF menu as page 3 gives `unexpected_screen` at once with the finally steps skipped (the Finding 10 limit); an ambiguous screen and a session error mid-listing (scripted, using the existing `poll` code) stop with `ambiguous_screen` and `session_error`; same result with 0, 1 and 2 stale reads per screen; one audit record `collect` at the step index.
    - A failure never prints a row. The shipped-Flow replay (`tk5-library-members`) is repeated in 8.5.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.13, 6.14_

  - [ ] 4.7 Write `test_flow_flag_output.py` (about 1.0 h)
    - `tests/unit/test_flow_flag_output.py` (new): `FOUND` 1 on `tso-listds-output` and 0 on `tso-listds-not-in-catalog` through a test-only Flow with `equals` `--RECFM-LRECL-BLKSIZE-DSORG` (`row` 2, `col` 1, `length` 27), `DETAILS` equal to the three lines `FB    80    27920   PO`, `--VOLUMES--`, `TSO001` joined by LF on the found screen and the empty string on the missing one; a hidden cell in the flag region stops with `hidden_output`; the output schema of a Flag_Output through the Publisher registry is `{"type": "integer"}`; the stored value is 0 when the region text only differs by an inner blank.
    - _Requirements: 7.2, 7.3, 7.5, 7.6_

  - [ ] 4.8 Extend the property strategies for Rows_Outputs and `collect` (about 1.0 h)
    - Flagged edit to a support file, additive only: `tests/property/_flow_strategies.py` gains the `rows_outputs()` composite and a `COMMAND_FLOWS` strategy that append Rows_Outputs, Flag_Outputs and `collect` steps to a `flows()` result. `flows()` itself is not changed, so the existing property tests keep their draws. Also add a page-sequence builder (`line_screen`, pages with `pause`/`ready` last rows and a unique token per page) in a new `tests/property/_collect_support.py`, built on `tests/screen_support.make_screen`.
    - Run the existing `tests/property/test_flow_*.py`: they pass unedited and with the same examples.
    - _Requirements: 3.6, 4.8, 6.11_

  - [ ] 4.9 Property tests for rows extraction, hidden cells and the YAML round trip (about 2.5 h)
    - Re-check the Hypothesis strategies row and its dated line. File `tests/property/test_flow_rows_extraction.py`, three tests.
    - **Property 1: Rows extraction matches the reference model.** `# Feature: more-flows, Property 1: Rows extraction matches the reference model`. Reference implementation written in the test; asserts value, `loop_limit` boundary, no LF inside a line, nothing at or after the prompt row, no Session call.
    - **Property 2: Hidden cells never reach a value or any output.** Hidden field (`0xCC` closed by `0xE0`) above, below or overlapping; probe text in no value, message, summary, audit field; the style of `tests/unit/test_flow_runner_fixes_frames.py`.
    - **Property 7: Flow YAML round trip.** `Flow.from_yaml(flow.to_yaml()) == flow` over `COMMAND_FLOWS`; at least 100 examples each.
    - _Requirements: 3.6, 4.1, 4.2, 4.3, 4.5, 4.8, 4.9, 5.1_

  - [ ] 4.10 Property tests for `collect` (about 3.0 h)
    - File `tests/property/test_flow_collect_model.py`, three tests, `ScriptedSession` with the pages as states, no live host.
    - **Property 3: `collect` matches the page model.** 0 to 12 More_Screens then a Final_Screen; value, `loop_limit` boundary at `max_rows` or `max_screens`, Enter count equal to More_Screens read and never above `max_screens - 1`, no value stored on `loop_limit`.
    - **Property 4: A bad screen in the middle of a `collect` stops the run at once.** `unknown_screen` after the step timeout with k Enters, or `unexpected_screen` before any further key (probe Flow whose finally steps reference the other signature, X6).
    - **Property 11: A `collect` leaves one allow-listed audit record.** Exactly one record of `kind` `collect`, `iteration` `None`, `signature` the Final_Screen name, status `ok` on success and `failed` on `loop_limit`, with exactly the seven `AuditRecord` members (D6).
    - At least 100 examples each; the comment line on each test.
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.11, 6.12_

  - [ ] 4.11 Property test for the flag value (about 0.75 h)
    - File `tests/property/test_flow_flag_output.py`, one test. **Property 5: The flag value is 1 exactly when the stripped region text equals `equals`.** `st.text` for the region text and for `equals` (printable ASCII, no blank edge); value always 0 or 1; a region text equal to `equals` stores 1. At least 100 examples; the comment line.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 7.2, 7.4_

- [ ] 5. The `dsname` input rule (about 4.5 h; no production code; no live host, no real model, no browser; Windows)
  - [ ] 5.1 Write the shared dataset-name test support (about 1.0 h)
    - Re-check the `re.fullmatch` and Hypothesis rows and their dated lines.
    - New file `tests/dsname_support.py` (test support, no production change): the exact `dsname` input spec of design section 5 as a constant (`name: dsname`, `type: str`, `required: true`, `max_length: 44`, `secret: false`, the Dsn_Pattern `[A-Za-z$#@][A-Za-z0-9$#@]{0,7}(?:\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21}`, the 199-character description of the design) built into an `InputSpec`; the Reference_Scanner of the design (explicit code-point sets, no `re`, no `str.isalpha`, `isdigit` or `isalnum`, no copy of the pattern); the name strategies (valid names of 1 to 22 qualifiers within 44 characters, up to 23 qualifiers, arbitrary text, one-character mutations from the hostile set listed in Property 6); a helper that builds a test-only Flow typing `LISTDS '` + name + `'` over `ScriptedSession`.
    - _Requirements: 8.1, 8.2, 20.1, 20.2, 20.5_

  - [ ] 5.2 Write `test_flow_dataset_name.py` (unit) (about 1.5 h)
    - `tests/unit/test_flow_dataset_name.py` (new): the boundary examples of Requirement 20.7 (accepted `SYS2.JCLLIB`, `sys2.jcllib`, `$A.#B.@C`, a single 8-character name, 22 one-character qualifiers (43 characters), a 44-character name of 22 qualifiers; rejected `A..B`, `1ABC`, `.A`, `A.`, `A-B`, `A_B`, a 9-character qualifier, 23 one-character qualifiers (45 characters), a 45-character name with valid qualifiers, `A B`, `A'B`, `A(B)`, `A,B`, the empty string) through `prepare_inputs`; for an accepted name the typed strings of the test-only Flow are exactly the literal, the name, the literal, and for the `MEMBERS` form `' MEMBERS`; for a rejected name `run_flow` raises `FlowInputError` naming the input and the rule, never the value, and `ScriptedSession.calls` is empty; length is checked before the pattern; the pattern has bounded quantifiers only, is at most 200 characters, is accepted by `registry._ecma_safe`, and a 49-character near miss is matched in negligible time; the description is at most 200 characters and holds no character of the probe alphabet of `test_probe_alphabet_is_absent_from_every_fixed_text` (D2 default).
    - The Publisher answer for a bad name (HTTP 422 `input_invalid`, X3) is asserted in 8.10 and 9.1 once the Flows exist.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 20.1, 20.2, 20.3, 20.4, 20.7_

  - [ ] 5.3 Property tests for the name rule and the published schema (about 2.0 h)
    - File `tests/property/test_flow_dataset_name.py`, two tests, using `tests/dsname_support.py`.
    - **Property 6: The input verdict equals the independent scanner, and accepted names are typed exactly.** At least 200 examples; `prepare_inputs` on the spec agrees with the Reference_Scanner for every drawn string; for an accepted name the typed strings are the literal, the name and the literal. A drift test in 8.4 and 8.5 asserts the shipped `dsname` of each Name_Flow equals the constant.
    - **Property 10: The published schema agrees with the runtime.** For any name without LF or CR, the JSON Schema (`maxLength` 44 and `pattern`, read from the registry built over a test-only Flow carrying the spec) accepts it exactly when `prepare_inputs` accepts it and exactly when the scanner accepts it (the style of `tests/property/test_publisher_schema_agree.py`). At least 100 examples.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6, 20.1, 20.6, 20.8, 20.9_

- [ ] 6. Logon recovery extension (about 5.5 h; no live host, no real model, no browser; Windows)
  - [ ] 6.1 Insert the three Handle steps into `tk5-logon.yaml` and `tk5-system-info.yaml` (about 1.0 h)
    - Read design section 7 first. Production files: `greenscreen/flow/flows/tk5-logon.yaml` and `greenscreen/flow/flows/tk5-system-info.yaml` only.
    - Insert, between the `tso-pause` Handle (plan indices 17 and 18) and the final `expect ispf-primary-menu`, the three Handles of Requirement 22.1: `tso-reenter` (`max_count` 3, `settle` 0.0, `key pa` `n` 1), `tso-ready` (`max_count` 1, `key clear`), `tso-cleared` (`max_count` 1, `type LOGOFF`, `key enter`). The shared Logon_Prefix becomes 27 plan indices (0 to 26); the `expect ispf-primary-menu` moves from 19 to 26; for `tk5-system-info` the later records move up by 7 (its own steps are 27 to 37, its `finally` stays at 38 to 44).
    - Write both files with a one-off builder in `%TEMP%` (outside the workspace, deleted afterwards) from `Flow.from_yaml(...)` plus the three steps and `Flow.to_yaml()`, so the shipped text equals the emitted text. Check `check_flow` with the 12 bundled signatures and `Flow.from_yaml(flow.to_yaml()) == flow`.
    - Run unedited, all passing: `test_flow_sync.py`, `test_flow_logon_script.py` (golden call lists), `test_flow_logon_recovery.py` (the `audit[-1]` assertions), `test_flow_system_info_script.py`, `test_flow_bundled.py` (with its three Flows still), `test_flow_runner_fixes_skipped.py`, `test_flow_packaging.py`. If one of them fails, STOP and report (the design measured that none does).
    - _Requirements: 22.1, 22.2, 22.3, 22.10, 18.1_

  - [ ] 6.2 Write `test_flow_logon_cleanup.py` (about 2.5 h)
    - Read design section 7 (the table "What each landing does") and `tests/unit/test_flow_logon_recovery.py` first.
    - `tests/unit/test_flow_logon_cleanup.py` (new): one parametrized scripted run per row of the landing table for each of `tk5-logon` and `tk5-system-info`, using the reconnect screens of `test_flow_logon_recovery.py` and then the landing screen from the captures (`tso-ready`, `tso-cleared`, `tso-listds-reenter` with its after-PA1 and cleared successors): ISPF menu (no cleanup key, normal result), `READY` (Clear, `LOGOFF`, Enter), cleared screen (`LOGOFF`, Enter), REENTER prompt (PA1, Clear, `LOGOFF`, Enter), one more `***` pause then `READY` (four Enters then Clear, `LOGOFF`, Enter, using `pause_variant(i)` so consecutive pauses differ), five more pauses (`loop_limit` at index 17 as today), an unrecognized screen (`unknown_screen` at 17, no key). Assert the keys after the password Enter, the reason `unexpected_screen`, `step_index` 26, `expected` `["ispf-primary-menu"]`, the final screen `tk5-logon`, that no key follows on the menu path, and that the password occurs in no output form (`forms_of_run`).
    - Also pin: the plan indices 19 to 26 of both Flows; the shipped YAML equals `to_yaml()`; the normal path of both Flows (0, 1 and 2 stale reads) has Session call lists, including reads, equal to the golden lists, and audit indices 0 to 18 equal, indices 19 to 25 new (three `handle` records `ok` and four body records `skipped`) and later records shifted by 7; `tk5-system-info`'s finally Handles run zero iterations (3 `ok`, 4 `skipped`, no key).
    - _Requirements: 22.3, 22.4, 22.5, 22.6, 22.7, 22.8, 18.1_

  - [ ] 6.3 Property test for the logon landing (about 1.5 h)
    - Re-check the Hypothesis row. File `tests/property/test_flow_logon_landing.py`, one test. **Property 8: A logon landing after a reconnect is released or continued, and nothing else is sent.** 0 to 3 further pauses (`pause_variant`) then one landing from the ISPF menu, `READY`, the cleared screen or the REENTER prompt, 0 to 2 stale reads per screen; `tk5-logon` ends at the menu exactly for the menu landing, ends with `unexpected_screen` at step 26 with `expected` `ispf-primary-menu` and the logon screen last for the other three; keys after the password are `3 + p` Enters followed by exactly the cleanup keys of that landing. At least 100 examples; the comment line.
    - _Requirements: 22.3, 22.4, 22.5, 22.9_

  - [ ] 6.4 Confirm the logon family passes unedited (about 0.5 h)
    - Verification only; no file is edited. Run `tests/unit/test_flow_sync.py`, `test_flow_logon_script.py`, `test_flow_logon_recovery.py`, `test_flow_system_info_script.py`, `test_flow_runner_fixes_skipped.py`, `test_flow_bundled.py`, `test_flow_packaging.py`, the Publisher tests that run `tk5-system-info` (`test_publisher_stack.py`, `test_publisher_calls*.py`) and `tests/property/test_flow_*.py`: all pass with no edit beyond the flagged ones made so far. Record whether `test_flow_runner_fixes_skipped.py` needed an index edit (expected: none; if one is needed, STOP and report, do not edit). Run `git diff --stat -- tests/` and confirm only the files listed in the table for tasks 2.2, 3.2 and 3.3 are modified.
    - Run the whole of `tests/unit` and `tests/property` once (`python -m pytest -m "not integration" -p no:cacheprovider`) and record passed, skipped, failed and time. Expected: 0 failed. If the Node tests skip, set Node on PATH first.
    - _Requirements: 22.10, 18.1, 18.2_

- [ ] 7. CHECKPOINT A and STOP-POINT: runtime, signatures and logon work finished (about 0.5 h; report only; no live host, no real model, no browser; Windows)
  - [ ] 7.1 Write the interim report and STOP
    - Do not add any Flow file, do not edit `greenscreen/flow/bundled.py`, and do not start task 8. The interim report (in the final message of the run, not in a file) lists: test counts now against the baseline of 1.1 (collected, passed, skipped, failed, time); new and changed files by task; every existing-test edit made so far with before and after values (tasks 2.2, 3.2, 3.3) and the statement that no other existing test was edited; the signature matrix result (12 signatures, 28 captures, 336 evaluations, 0 mismatches, per-signature capture counts); the `test_recognizer_packaging.py` result; the scripted logon landing table result; the properties written (1, 2, 3, 4, 5, 6, 7, 10, 11 and 8) with example counts; the library documentation lines appended; the open-point table with any default that turned out to need a decision; and what is unverified (live host, `PA(1)` at a REENTER prompt, the apostrophe echo, the `READY` and cleared-screen landings after a reconnect, timings, a browser).
    - After the report, STOP and wait for the reviewer. The reviewer checks the runtime, the two signatures and the logon change before any Flow is added.
    - _Requirements: 19.6_

- [ ] 8. The five Flows (about 15.0 h; starts only after the reviewer releases the STOP-POINT; no live host, no real model, no browser; Windows)
  - [ ] 8.1 Write the shared Command_Flow test support (about 0.75 h)
    - New test support file `tests/command_flow_support.py`: load a shipped Flow by path (`greenscreen/flow/flows/<name>.yaml`, so the manifest is not needed yet), the normal-logon `ScriptedSession` states (logo, logon, password prompt, two pauses, menu) with the fake credentials of the existing logon tests, the `X` to `READY`, Clear to `tso-cleared` steps, the closing `tso-cleared` to `tk5-logon` steps, a builder that concatenates a command's screens, and a helper listing the Session calls after the menu. Also decide the one-off Flow builder location `%TEMP%\gs-build\build_flows.py` (outside the workspace, deleted in 8.7): it builds a `Flow` from the Logon_Prefix (`tk5-logon.steps`), the Exit_Fragment, the command block, the Closing_Tail and the Finally_Block of design section 6 and writes `Flow.to_yaml()`. No password literal anywhere.
    - _Requirements: 10.1, 10.2, 19.4_

  - [ ] 8.2 Flow `tk5-time` and its scripted test (about 1.25 h)
    - Re-check the PyYAML row. Build `greenscreen/flow/flows/tk5-time.yaml` as in design section 6.1 (inputs `userid`, `password` equal to `tk5-logon`'s; output `TIME_TEXT` `str` `tso-ready` row 1 col 1 length 79 `max_rows` 3; steps: Logon_Prefix indices 0 to 26, Exit and clear 27 to 31, `type TIME`, `key enter`, `expect [tso-ready, tso-pause]`, `extract TIME_TEXT`, Closing_Tail 36 to 40; Finally_Block 41 to 53; `timeouts` step 10.0, run 20.0, finally 6.0; the 271-character description of the design, no `;`, `#` or `@`). Written with `Flow.to_yaml()`; do not touch `bundled.py` yet.
    - Create `tests/unit/test_flow_command_flows.py` (new) with the scripted run: the real captures give `TIME_TEXT` equal to the stripped row 1 of `tso-time-output`, starting `TIME-`; keys after the menu `X`, Enter, Clear, `TIME`, Enter, Clear, `LOGOFF`, Enter; final screen `tk5-logon`; audit `extract` at step 35; the 13 finally records are 6 `ok` and 7 `skipped` and no key is sent; a `***` pause after the command stops with `unexpected_screen` at step 35 (`expected` `tso-ready`), the finally steps send Enter, Clear, `LOGOFF`, Enter (10 `ok`, 3 `skipped`) and end on `tk5-logon`; `check_flow` with the 12 bundled signatures passes and `from_yaml(to_yaml(flow)) == flow`.
    - _Requirements: 10.1, 10.2, 10.4, 10.7, 11.1, 11.2, 11.3, 11.4, 16.1_

  - [ ] 8.3 Flow `tk5-list-datasets` and its scripted test (about 1.5 h)
    - Build `tk5-list-datasets.yaml` as in design section 6.2 (output `DATASETS` `str` `tso-ready` row 2 col 1 length 44 `next_row` 0 `max_rows` 60; command block `type LISTCAT`, `key enter`, `expect [tso-ready, tso-pause]`, `collect DATASETS` with `more` `tso-pause`, `max_screens` 5; Closing_Tail 36 to 40; Finally_Block 41 to 53; 272-character description).
    - Append to `tests/unit/test_flow_command_flows.py`: the real `tso-listcat-output` gives seven names in screen order, none empty, each at most 44 characters, no `IN CATALOG` line; a synthetic two-screen plain `LISTCAT` from `make_screen` (screen 1: echo, heading, names from row 2, ` ***` last; screen 2: names from row 0, ` READY` last) returns the names of both screens in order and no heading (R1, open point); one `collect` audit record at step 35; `check_flow` and the YAML round trip.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 8.4 Flow `tk5-dataset-info` and its scripted test (about 1.5 h)
    - Build `tk5-dataset-info.yaml` as in design section 6.3 (inputs `userid`, `password`, `dsname` with the exact spec of `tests/dsname_support.py`; outputs `FOUND` (`int`, row 2 col 1 length 27, `equals` `--RECFM-LRECL-BLKSIZE-DSORG`) and `DETAILS` (`str`, row 3 col 1 length 79 `max_rows` 20); the command block of indices 32 to 38 with `LISTDS '`, input `dsname`, `'`, `expect [tso-ready, tso-reenter]`, `extract FOUND`, `extract DETAILS`; Closing_Tail 39 to 43; Finally_Block 44 to 56; 336-character description).
    - Append to `test_flow_command_flows.py`: `tso-listds-output` gives `FOUND` 1 and `DETAILS` equal to `FB    80    27920   PO`, `--VOLUMES--`, `TSO001` joined by LF, typed strings `X`, `LISTDS '`, the name, `'`, `LOGOFF`; `tso-listds-not-in-catalog` ends in success with `FOUND` 0 and empty `DETAILS`; the REENTER answer stops with `unexpected_screen` at step 37 (`kind` `extract`, `expected` `tso-ready`); `A..B` gives `input_invalid` naming `dsname` and the rule with an empty Session call list; the shipped `dsname` input equals the constant of `tests/dsname_support.py` (drift test, Property 6 target); `check_flow` and the round trip.
    - _Requirements: 8.1, 8.3, 8.4, 8.9, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 21.2, 21.3_

  - [ ] 8.5 Flow `tk5-library-members` and its scripted test (about 1.5 h)
    - Build `tk5-library-members.yaml` as in design section 6.4 (output `MEMBERS` `str` `tso-ready` row 7 col 3 length 8 `next_row` 0 `max_rows` 200; command block indices 32 to 37 with `LISTDS '`, input `dsname`, `' MEMBERS`, `key enter`, `expect [tso-ready, tso-pause, tso-reenter]`, `collect MEMBERS` `more` `tso-pause` `max_screens` 10; Closing_Tail 38 to 42; Finally_Block 43 to 55; 333-character description).
    - Append to `test_flow_command_flows.py`: the seven real pages give 136 names in screen order, first three `$$$INDEX`, `$HISTORY`, `ADDALIAS`, last `ZAPDSCB`, 1,145 characters, 6 Enters at the `collect` (8 Enters after the command text: command, 6 pages, `LOGOFF`), one audit record `collect` at 37, the same result with 0, 1 and 2 stale reads per screen; the typed text is exactly `LISTDS '`, the name, `' MEMBERS`; `tso-listds-not-in-catalog` gives the empty string; the REENTER answer stops with `unexpected_screen` at 37 (`kind` `collect`, `expected` `tso-pause` and `tso-ready`); `max_screens` lowered to 3 gives `loop_limit` at 37 with the finally steps pressing Enter 4 times, Clear, `LOGOFF`, Enter (13 `ok`); a blank page 3 gives `unknown_screen` with all 13 finally records skipped; the shipped `dsname` equals the constant; `check_flow` and the round trip.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 6.13, 20.9, 21.2, 21.3_

  - [ ] 8.6 Flow `tk5-job-status` and its scripted test (about 1.0 h)
    - Build `tk5-job-status.yaml` as in design section 6.5 (output `JOBS` `str` `tso-ready` row 1 col 1 length 79 `next_row` 0 `max_rows` 40; command block `type STATUS`, `key enter`, `expect [tso-ready, tso-pause]`, `collect JOBS` `max_screens` 3 (`more` `tso-pause`); Closing_Tail 36 to 40; Finally_Block 41 to 53; 237-character description).
    - Append to `test_flow_command_flows.py`: `tso-status-output` gives `JOBS` equal to the one stripped row 1 line starting `JOB ` and ending `EXECUTING`; a synthetic screen with several job lines and a synthetic two-screen listing return all lines in order (open item 3: shapes beyond one job are not captured); `check_flow` and the round trip.
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [ ] 8.7 Manifest, count edits and description tests (about 2.0 h)
    - Re-check the PyYAML row. Delete the one-off builder directory in `%TEMP%`.
    - `greenscreen/flow/bundled.py`: `_MANIFEST` gains the five names after `tk5-system-info` in the order `tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members`, `tk5-job-status`; docstring "three" becomes "eight".
    - Flagged edits (table above, before and after values): `tests/unit/test_flow_bundled.py` (`NAMES` the eight names; `len(flows) == 8`; line 319 `parametrize("name", NAMES[:3])`, X8: the allowed literal set `X`, `LOGOFF`, `LOGON `, ` RECONNECT` is not widened); `tests/unit/test_flow_packaging.py` (`EXPECTED_YAML` plus the five file names); `tests/unit/test_publisher_registry.py` (`BUNDLED` the eight names); `tests/unit/test_publisher_openapi.py` (line 55, 3 becomes 8); `tests/unit/test_publisher_stack.py` (lines 394 to 396, 3 becomes 8 three times; test renamed `test_unset_publish_list_publishes_all_eight_flows`); `tests/unit/test_publisher_slice.py` (line 102 and line 136, 3 becomes 8). Each edit is a count or a set growing; no assertion is removed. Any other failing test: STOP and report (design measured none).
    - Append to `test_flow_command_flows.py`: manifest order and that each shipped file text equals `Flow.to_yaml()`; every description is at most 500 characters and names every output of its Flow; every input description is at most 200 characters; no character of the probe alphabet in any fixed text (D2 default; `test_publisher_helpers.py` passes unedited); the registry deadline; `check_flow` over all eight with the 12 signatures; `Flow.from_yaml(flow.to_yaml()) == flow` for all eight.
    - Wheel packaging: `test_flow_packaging.py` builds the wheel (several minutes); record the duration.
    - _Requirements: 17.1, 17.2, 17.7, 18.1, 18.6, 2.7_

  - [ ] 8.8 Write `test_flow_command_sync.py` and `test_flow_readonly.py` (about 1.5 h)
    - `tests/unit/test_flow_command_sync.py` (new): for each of the five Flows: `steps` begin with the first 15 top-level steps of `tk5-logon.steps` (equal), then the Exit_Fragment, `key clear`, `expect tso-cleared`, the command steps of its design outline, the Closing_Tail; `inputs` begin with the two inputs of `tk5-logon`, equal; `finally` equals the Finally_Block in all five, with `max_count` and `settle` as in the design and 13 plan indices; plan indices of the last main step (40, 40, 43, 42, 40) and the finally ranges (41 to 53, 41 to 53, 44 to 56, 43 to 55, 41 to 53); `timeouts` 10.0, 20.0, 6.0. `test_flow_sync.py` stays unedited.
    - `tests/unit/test_flow_readonly.py` (new): the set of literal `type` texts of every bundled Flow (steps, finally, Handle bodies) is a subset of the Read_Only_Set; each Command_Flow contains exactly its own command literals (`TIME`; `LISTCAT`; `LISTDS '` and `'`; `LISTDS '` and `' MEMBERS`; `STATUS`); every `type` step with an `input` names `userid`, `password` or `dsname`; no PF key; the only `key: pa` in any bundled Flow is `n: 1` inside a Handle on `tso-reenter`; the Session call sequence of each Flow (logon, `X`, Clear, command, Enter, paging Enters, Clear, `LOGOFF`, Enter); each command literal typed in order reproduces row 0 (the echo) of the capture that its script ends in (a misspelled command word would otherwise be returned as a row); the three Flows that type fixed literals do not list `tso-reenter` in their `expect`. The literals test (X8) for the five new files lives here with its own sets.
    - _Requirements: 8.4, 8.7, 8.8, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 21.12_

  - [ ] 8.9 Finally steps at each stop (about 1.5 h)
    - Append to `tests/unit/test_flow_command_flows.py`: each Command_Flow with a held screen at each of the ISPF menu, the `READY` after `X`, the cleared screen, a `***` pause in the middle of a listing, the output screen after the command and the cleared screen before `LOGOFF`, with `unexpected_screen`, `loop_limit` or `hidden_output` injected, asserts the finally steps end on `tk5-logon` with the calls that log off (from `READY`: Clear, `LOGOFF`, Enter; from the cleared screen: `LOGOFF`, Enter; from a pause: Enter first); success sends no finally key (the five Handles run zero iterations, only the last `expect` reads); the test that EXPECTS the failure for Finding 10 (a stop after the command text was typed and before Enter leaves the finally steps unable to reach `tk5-logon`; a test-only Flow whose `expect` after Enter omits `tso-reenter` stops there with every finally step `skipped` and no key after the Enter), with a docstring saying a later runner change makes it fail on purpose; the skip reasons `_FINALLY_SKIP_REASONS` are unchanged.
    - _Requirements: 10.5, 10.6, 10.7, 10.8, 21.11_

  - [ ] 8.10 Write `test_flow_reenter.py` and the REENTER outcome property (about 2.5 h)
    - Re-check the Hypothesis row. `tests/unit/test_flow_reenter.py` (new): both Name_Flows with a scripted session that accepts a name the validation accepts (for example `SYS2.NOSUCH`) and answers the command with `tso-listds-reenter`, then `tso-listds-reenter-after-pa1` after PA1, `tso-cleared` after Clear, the logon capture after `LOGOFF` and Enter: reason `unexpected_screen`, `step_index` 37, `kind` `extract` or `collect`, `expected`, the call list after the command Enter exactly `pa 1`, `clear`, `string LOGOFF`, `enter`, every finally audit record `ok`, final screen `tk5-logon`, no call after the command sends text other than `LOGOFF`; through the Publisher path (`CallService` with the Fake_Host of `tests/publisher_support.py`) the code is `unexpected_screen`, HTTP 502, and the Call_Log_Record has no `session_clean` member; a rejected name (`A..B`) never reaches the host: `ScriptedSession.calls` empty, Flow error `input_invalid`, and through the Publisher HTTP 422 `input_invalid` with the host factory not called (X3); a test that repeats the REENTER screen after every PA1 sends at most three PA1 keys, the main failure stays `unexpected_screen` and the audit marks the failed finally step; the three fixed-literal Flows do not list `tso-reenter`.
    - File `tests/property/test_flow_reenter_outcome.py`, one test. **Property 9: A name the host rejects always ends logged off.** At least 200 examples; names from the valid-name strategy of `tests/dsname_support.py`, each Name_Flow, a script answering with the REENTER capture; ends with `unexpected_screen`, keys after the command Enter exactly `pa 1`, `clear`, `string LOGOFF`, `enter`, last screen `tk5-logon`, the name occurs in no message or audit field. The comment line.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 8.3, 13.6, 20.4, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 21.10_

- [ ] 9. Publisher, Ask and console impact (about 6.0 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [ ] 9.1 Schema and Publisher shape tests for the new outputs (about 1.5 h)
    - New file `tests/unit/test_flow_command_publish.py`: with the eight bundled Flows published through the real registry and `build_app` with a Fake_Host: the OpenAPI request-body schema and the MCP `inputSchema` of each Flow as in the design table of section 8 (`dsname` with `type string`, `maxLength` 44, `pattern` `^(?:...)$`, `description`, `required ["dsname"]` for the two Name_Flows; empty `properties` and `additionalProperties: false` for the others); the `outputs` schemas (`TIME_TEXT`, `DATASETS`, `MEMBERS`, `JOBS` string; `FOUND` integer, `DETAILS` string); the audit item schema unchanged (seven members, `kind` a string); one REST call to `tk5-library-members` over the seven real pages returns HTTP 200, `MEMBERS` of 136 lines and 1,145 characters, one `collect` audit record; a bad `dsname` (`A..B`) gives HTTP 422 `input_invalid` with the host factory not called; the Publisher uses each Flow description unchanged as the OpenAPI summary and the MCP tool description; the no-leak property tests still pass with eight Flows (run `tests/property/test_publisher_no_leak_*.py` and `test_publisher_schema*.py` unedited).
    - _Requirements: 8.2, 8.3, 17.2, 17.3, 18.2, 18.6, 20.8_

  - [ ] 9.2 Write `test_flow_command_timing.py`: timing, Ask sizing and Ask eligibility (about 1.5 h)
    - New file `tests/unit/test_flow_command_timing.py`: for every Command_Flow `run + finally + 4.0 <= 30.0` and `step <= run`; `build_registry` with `GS_CALL_TIMEOUT` 30 gives the deadline 30.0 for each; `plan_ask` with the password bound, `GS_CALL_TIMEOUT` 30, `GS_ASK_TIMEOUT_SECONDS` 90 and model timeout 25 offers all five (and `tk5-system-info`): Tool_Worst_Case 40.0 each, `need = 30 + 10 + 2 x 25 = 90 <= 90`, `worst_case_seconds` 92.5 and `largest_tool_seconds` 40.0 through the existing `ask/service.py` code (no change to `calls.py` or `ask/`); with the password not bound a Flow is not offered; `GS_ASK_FLOWS` accepts each of the five names. Ask sizing (Requirement 4.6 and Finding 12): for every Rows_Output of a bundled Flow, `max_rows x (length + 2) + 200 <= 4000`; the measured result size on the real captures is under 4,000 (the five measured sizes of the design: 123, 171, 105, 1,335, 77) and the worst case computed from the caps is under 4,000 (287, 2,812, 1,681, 2,053, 3,285 characters, LF counted as two characters; the largest is 3,285 for `tk5-job-status`); a row full of quotes or backslashes exceeds the limit and gives a `result_too_large` Rejected_Call without any other effect.
    - Eligibility is asserted at `GS_CALL_TIMEOUT` 30 only; the fallback `run` 18.0 and `finally` 8.0 (open point) would pass the same sum assertions.
    - _Requirements: 4.6, 16.1, 16.2, 16.3, 16.6, 17.4_

  - [ ] 9.3 Console CSS for multi-line outputs (D1) (about 1.0 h)
    - Default applies (D1): this is the one production file outside the Flow and recognizer packages. Edit `greenscreen/publisher/console/console.css` only: in the existing `.outputs dd` rule add `white-space: pre-line`, `max-height: 24rem`, `overflow-y: auto`, keeping every existing declaration. No colour literal, no new token, no `url(`, no font, no animation.
    - Flagged edit (addition only): `tests/unit/test_console_css.py` gains `test_outputs_keep_line_breaks_and_scroll` in the style of `_rule(css, ".outputs dd")` helpers of the file, asserting `white-space` is `pre-line`, `max-height` is set and `overflow-y` is `auto`. Run `tests/unit/test_console_css.py`, `test_console_seance.py`, `test_console_audit_layout.py`, `test_console_assets.py` and `test_console_packaging.py` (Node on PATH): all pass. No existing console test reads `.outputs dd`; if one fails, STOP and report. Snippets and the Run transcript copy `outputs` unchanged (`RESULT_SPECS` keeps `outputs: true`).
    - Record that the CSS is verified only by static tests; the browser rendering is a reviewer item.
    - _Requirements: 17.6, 18.4_

  - [ ] 9.4 Write the three integration test files (about 2.0 h)
    - New files, marked integration, written but not run: `tests/integration/test_flow_live_commands.py` (each Command_Flow through the Connector), `test_flow_live_reenter.py` (a test-only Flow with a relaxed `dsname` pattern provokes the REENTER prompt and checks the account ends logged off), `test_flow_live_cleanup.py` (leaves an orphan at `READY`, at the cleared screen and at a REENTER prompt, then runs `tk5-time` twice: the first call ends with `unexpected_screen` at index 26, the second succeeds). All skip when the host is unreachable or `TK5_USERNAME` or `TK5_PASSWORD` is unset; each has a Cleanup_Helper in the style of `tests/integration/test_flow_live_recovery.py` that logs the account off on every path; none prints a credential or a screen. The executor only collects them (`python -m pytest tests/integration/test_flow_live_commands.py tests/integration/test_flow_live_reenter.py tests/integration/test_flow_live_cleanup.py --collect-only -q`) and confirms they skip with the host unreachable; it never runs them against the host. `tests/integration/test_flow_live_recovery.py` is not edited.
    - _Requirements: 19.1, 19.5, 22.11, 21.13_

- [ ] 10. Spec text edits from Requirement 23 (about 3.25 h; documents only; no live host, no real model, no browser; Windows)
  - [ ] 10.1 Edit the publisher requirements and tasks documents (about 0.75 h)
    - Edit `.kiro/specs/publisher/requirements.md` lines 22, 23 and 491 and `.kiro/specs/publisher/tasks.md` line 294 ONLY, with the replacement wording of design section 7 ("Spec text edits", Edits 1, 2, 3 and 5). Before each replacement read the line and check that the old words of the design are there verbatim; if the line numbers or words have drifted, STOP and report. Replace only the words listed; the rest of each line stays. Line 31 of `publisher/tasks.md` is NOT edited (D8). Each new text states which landings are verified (the menu through the Flow on 2026-11-17 and 2026-11-18, the REENTER landing by hand on 2026-11-19) and which are not yet seen (`READY`, the cleared screen).
    - Run `validate_spec_format` on `publisher/requirements.md` and `publisher/tasks.md`; report issues that were already there separately from any this edit introduced.
    - _Requirements: 23.1, 23.2, 23.3_

  - [ ] 10.2 Edit the publisher design document (about 1.0 h)
    - Edit `.kiro/specs/publisher/design.md` lines 20 (table row), 471 ("The limit of recovery"), 758 (error-table row) and 910 (open item 2) ONLY, with the replacement wording of Edit 4 in design section 7, after checking the old words as in 10.1. The statements about `IKJ56700A`, the second IN USE state, the 3-minute lock and RECONNECT taking over any session stay. Run `validate_spec_format` on the file.
    - _Requirements: 23.1, 23.2, 23.3_

  - [ ] 10.3 Edit the flow-runtime and logon-recovery documents (about 1.0 h)
    - Edit `.kiro/specs/flow-runtime/design.md` line 1051 (three replacements inside the row, Edit 6), `.kiro/specs/logon-recovery/requirements.md` line 39 and lines 221 to 222 (Edit 7, the third change on line 222 replaces only the words "An orphan left at `READY` or inside an ISPF panel, an abandoned logon showing" with "An orphan left inside an ISPF panel, an abandoned logon showing") and `.kiro/specs/logon-recovery/design.md` line 253 (Edit 8), with the wording of design section 7, after checking the old words. `flow-runtime/requirements.md` line 74 and the console and Ask documents are NOT edited. Run `validate_spec_format` on the three files.
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5_

  - [ ] 10.4 Run the consistency test and check the document diff (about 0.5 h)
    - Run `tests/unit/test_flow_spec_consistency.py` (it reads flow-runtime and connector documents): it passes unedited. Run `git diff --stat -- .kiro/specs` and confirm that only the six files named in 10.1 to 10.3 changed, plus `more-flows/design.md` (1.1) and `more-flows/tasks.md` if the executor was asked to tick boxes; `git diff --exit-code -- .kiro/steering` shows only the pre-existing reviewer edit and nothing the executor made. Report the changed line numbers per file.
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 23.1, 23.4, 18.5_

- [ ] 11. Final checkpoint and report (about 1.0 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [ ] 11.1 Run the whole suite, check the tree and write the final report
    - Prepend Node: `$env:Path = "C:\Program Files\nodejs;" + $env:Path`, record `node --version`, run `python -m pytest -m "not integration" -p no:cacheprovider`. Record passed, skipped, failed, deselected, pytest time and wall time against the last Windows baseline (3524 passed, 4 skipped, 0 failed, 434.01 s) and against the count taken in 1.1. Expected: passed rises by the new tests, skipped unchanged unless Node is absent, failed 0. A timing difference is reported, never a failure. Record the duration of the wheel test and of the longest property tests.
    - Git checks: `git diff --name-only` lists only these modified tracked files: the recognizer and Flow production files of the Overview, `tk5-logon.yaml`, `tk5-system-info.yaml`, `console.css` (if D1 stays), the support files `tests/screen_support.py`, `tests/flow_support.py`, `tests/property/_flow_strategies.py`, the existing test files of the table "Every existing-test edit" (and no other), the spec documents of 10.1 to 10.3, and `more-flows/design.md`. New untracked files: the 36 moved captures, two signature files, five Flow files, the new test and support files, the integration files. The 24 tracked captures show as deletions under `.kiro/specs/more-flows/captures` (the move). `git diff --exit-code -- pyproject.toml greenscreen/publisher/app.py greenscreen/publisher/calls.py greenscreen/connector` prints nothing; `.kiro/steering` shows only the pre-existing reviewer edit; `git diff --cached --name-only` prints nothing; `git log` has no new commit; `.kiro` is not in `.gitignore`.
    - Wheel contents check (`test_flow_packaging.py` and `test_recognizer_packaging.py`): the eight Flow YAML files and the twelve signature YAML files are in the wheel; no capture file and no `tests/` file is in it.
    - Final report: test counts before and after; every test file added; every existing-test edit with before and after values (the table); the statement that no other existing test file was edited; the library documentation lines appended; the status of each requirement ("implemented, awaiting live check" for Requirements 11 to 15, 21 and 22 where the host is needed); the open-point table with the defaults used; the exact viewer strings for each new Flow's outputs from the scripted runs (`TIME_TEXT` (77 characters), `DATASETS` (7 lines), `FOUND` 1 and `DETAILS` (three lines) and `FOUND` 0 with empty `DETAILS`, `MEMBERS` (136 lines, 1,145 characters, first three and last), `JOBS` (one line), each with its LF escapes as the Run transcript shows them, never any password or user id); the operator notes (D4: `GS_BIND_<FLOW>__USERID` and `__PASSWORD` for `TK5_TIME`, `TK5_LIST_DATASETS`, `TK5_DATASET_INFO`, `TK5_LIBRARY_MEMBERS`, `TK5_JOB_STATUS`, and `GS_PUBLISH_FLOWS` extended with the five names; names only); and everything not verified (below).
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 17.5, 18.1, 18.4, 19.6_

## Reviewer-only items (the executor does NOT run these; no checkbox)

These need the live host, a real model, a browser or other Python versions. The executor lists them in the final report as "not run by the executor". One session per user id: stop the Publisher before an integration test and never run two checks at once. Placeholders: `<API_KEY>` (16 characters or more), `<LLM_BASE_URL>`, `<LLM_MODEL>`, `<LLM_API_KEY>`. The demo account comes from `TK5_USERNAME` and `TK5_PASSWORD` in the shell; no command below prints them. The host is `192.168.68.72`, tn3270 port 3270. PowerShell, repository root. Copied from the design's "Live-host checks".

**Start the Publisher** (terminal A; Ctrl+C stops it):

```powershell
$env:GS_S3270_BINARY = "D:\tools\wc3270\ws3270.exe"
$env:GS_HOST = "192.168.68.72"; $env:GS_PORT = "3270"
$env:GS_API_KEY = "<API_KEY>"
$env:GS_CALL_TIMEOUT = "30"; $env:GS_MAX_CONCURRENCY = "1"
$env:GS_PUBLISH_FLOWS = "tk5-time,tk5-list-datasets,tk5-dataset-info,tk5-library-members,tk5-job-status,tk5-system-info"
foreach ($f in "TK5_TIME","TK5_LIST_DATASETS","TK5_DATASET_INFO","TK5_LIBRARY_MEMBERS","TK5_JOB_STATUS","TK5_SYSTEM_INFO") {
  Set-Item "Env:GS_BIND_${f}__USERID" $env:TK5_USERNAME
  Set-Item "Env:GS_BIND_${f}__PASSWORD" $env:TK5_PASSWORD
}
greenscreen-publish
```

Expected on stderr: `publishing 6 of 8 flows over http`.

**Call helper** (terminal B; the body goes through a file so that PowerShell does not mangle the quotes):

```powershell
function Call($flow, $json = "{}") {
  Set-Content -Path "$env:TEMP\gs-body.json" -Value $json -NoNewline
  curl.exe -sS -X POST "http://127.0.0.1:8080/flows/$flow" -H "Content-Type: application/json" -H "X-API-Key: $env:GS_API_KEY" --data-binary "@$env:TEMP\gs-body.json" -w "`nHTTP %{http_code} in %{time_total}s`n"
  Remove-Item "$env:TEMP\gs-body.json"
}
```

| # | What | Command | Expected |
|---|---|---|---|
| 1 | Each Flow | `Call tk5-time`; `Call tk5-list-datasets`; `Call tk5-job-status`; `Call tk5-dataset-info '{"dsname":"SYS2.JCLLIB"}'`; `Call tk5-library-members '{"dsname":"SYS2.JCLLIB"}'` | HTTP 200 each. `TIME_TEXT` starts `TIME-`; `DATASETS` has 7 names; `JOBS` has one `JOB ... EXECUTING` line; `FOUND` 1 and 3 lines in `DETAILS`; `MEMBERS` has 136 names, the first three `$$$INDEX`, `$HISTORY`, `ADDALIAS`. After each call the host log shows the user id `LOGGED OFF` (Hercules console, port 8038, `http://192.168.68.72:8038`, the system log page; the path is not verified) |
| 2 | Missing data set | `Call tk5-dataset-info '{"dsname":"NO.SUCH.DSN"}'`; `Call tk5-library-members '{"dsname":"NO.SUCH.DSN"}'` | HTTP 200; `FOUND` 0 and empty `DETAILS`; empty `MEMBERS` |
| 3 | Hostile names | `Call tk5-dataset-info '{"dsname":"A..B"}'` and the same for `1ABC`, `A B`, `X'`, `A(B)`, a 45-character name, a 9-character qualifier | HTTP **422** `input_invalid` (X3), no logon in the host log. `Call tk5-dataset-info '{"dsname":"sys2.jcllib"}'` returns 200 with `FOUND` 1 and the same `DETAILS` as the upper-case name (the lower-case name check) |
| 4 | Name edge by hand | `ws3270 -model 3279-2`, Clear at `READY`, then `LISTDS '$A.#B.@C'`, a name with one 8-character qualifier, a 43-character name of 22 one-character qualifiers | an answer ending in ` READY`, never ` REENTER -` (otherwise the rule is looser than the host and must be tightened) |
| 5 | Plain `LISTCAT` over several screens | by hand, `LISTCAT` for a user id with more than 21 catalogued data sets, if one exists (creating one writes, so this spec cannot) | continuation screens start at row 0 with no ` IN CATALOG` heading; a repeated heading needs `next_row` 2 or a filter (R1) |
| 6 | STATUS with batch jobs | by hand, `STATUS` for an account with held output, if one exists | the line shapes beyond `JOB <id>(TSU...) EXECUTING` |
| 7 | The apostrophe | run the REENTER probe of row 9 and read row 0 of the redacted `summary` in the error body (the echoed command) | the echo is `LISTDS 'A..B'`: one apostrophe each side, none doubled or dropped |
| 8 | Timing and paging time | `1..10 \| % { Call tk5-library-members '{"dsname":"SYS2.JCLLIB"}' }`, and the same for the other four | each `HTTP 200 in` under 17 s for the members list and under 12 s for the others; the time from the POST to the first Session call within the 4 s allowance; the per-screen time: `duration_seconds` of the `collect` audit record divided by 7 (`($r.audit \| ? kind -eq collect).duration_seconds`) |
| 9 | REENTER and the 6 s `finally` budget | create a test-only Flow file: `python -c "from greenscreen.flow import load_bundled_flows; from dataclasses import replace; f=load_bundled_flows()['tk5-dataset-info']; i=tuple(replace(s, regex='.{1,44}') if s.name=='dsname' else s for s in f.inputs); open(r'%TEMP%\gs-flows\probe.yaml','w').write(replace(f, name='tk5-probe-reenter', inputs=i).to_yaml())"` (create `%TEMP%\gs-flows` first, set `GS_FLOWS_DIR` and `GS_BIND_TK5_PROBE_REENTER__USERID` and `__PASSWORD`, add the name to `GS_PUBLISH_FLOWS`, restart); then `Call tk5-probe-reenter '{"dsname":"A..B"}'` and `'{"dsname":"1ABC"}'` | HTTP 502 `unexpected_screen`, `step_index` 37, `kind` `extract`; the sum of `duration_seconds` of the `finally` audit records (`($r.error.audit \| ? phase -eq finally \| measure duration_seconds -Sum).Sum`) is the finally time, to compare with 6 s (R3); `1ABC` shows `INVALID KEYWORD`; the host log shows `LOGGED OFF`; a second call by `Call tk5-time` takes the normal path |
| 10 | Orphans (landing scenarios) | for each state in `ready`, `cleared`, `reenter`, `pause`: stop the Publisher, run `python %TEMP%\orphan.py <state>` (script below), start the Publisher, `Call tk5-time`, then `Call tk5-time` again | the first call ends HTTP 502 `unexpected_screen`, `step_index` 26, `expected` `["ispf-primary-menu"]`, no `session_clean` member, and the host log shows `LOGGED OFF` for the released session; the second call returns 200. Record the screen each reconnect landed on (the rows "not seen" of design section 7). For `pause`, record what the call does (the expectation, not verified: a reconnect to a paused session shows a pause, the logon Handle presses Enter, then READY or the prompt is handled). After this check passes, the reviewer deletes the last clause of the "not yet seen" remark in each document edited in task 10 |
| 11 | Existing live recovery | `python -m pytest tests/integration/test_flow_live_recovery.py -m integration -q` | passes unchanged (menu landing) |
| 12 | Integration files | `python -m pytest tests/integration/test_flow_live_commands.py tests/integration/test_flow_live_reenter.py tests/integration/test_flow_live_cleanup.py -m integration -q` (Publisher stopped) | pass; each logs the account off on every path |
| 13 | Fit in `GS_CALL_TIMEOUT` 30 | rows 8 and 10 | no `call_timeout` (504) in any call; worst observed durations against 30 s; if the finally budget is too short, apply the fallback `run` 18.0 and `finally` 8.0 (see the open-point table) |
| 14 | Ask | restart with `GS_ENABLE_ASK=true`, `GS_LLM_BASE_URL=<LLM_BASE_URL>`, `GS_LLM_MODEL=<LLM_MODEL>`, `GS_LLM_API_KEY=<LLM_API_KEY>`; then for each question below `curl.exe -sS -X POST http://127.0.0.1:8080/ask -H "Content-Type: application/json" -H "X-API-Key: $env:GS_API_KEY" --data-binary "@ask-body.json"` with the body `{"question": "<question>"}` written to `ask-body.json` | stderr shows `ask enabled` and `ask worst case` with `worst_case_seconds` 92.5 and `largest_tool_seconds` 40.0; each answer uses the matching tool and is correct; `transport=ask` in the Call_Log_Record; the account is logged off afterwards |

Ask questions (one per Flow): "What is the host time?" (`tk5-time`), "Which data sets does my account have?" (`tk5-list-datasets`), "Does data set SYS2.JCLLIB exist, and what are its attributes?" (`tk5-dataset-info`), "Which members does SYS2.JCLLIB have?" (`tk5-library-members`), "Which jobs are running for my account?" (`tk5-job-status`). A sixth, "Does data set FOO.BAR exist?", expects `FOUND` 0 read as "no".

The orphan helper (a throwaway file outside the repository, reviewer-run from the repository root so that `tests` imports; it uses the Connector, the credentials come from the environment and nothing is printed):

```python
# %TEMP%\orphan.py  <ready|cleared|reenter|pause>   (same opening sequence as cleanup_logoff in
# tests/integration/test_flow_live_recovery.py; written here from that file, not run on the host)
import os, sys, time
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError
from tests.flow_support import live_connector_config

state = sys.argv[1]
user, pw = os.environ["TK5_USERNAME"], os.environ["TK5_PASSWORD"]

def wait_any(conn, texts, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for t in texts:
            try:
                conn.wait_for_text(t, timeout=0.3, poll_interval=0.1)
                return t
            except ConnectorTimeoutError:
                pass
    raise SystemExit("no expected screen text appeared")

with Connector(live_connector_config()) as conn:
    try:
        conn.wait_for_text("Logon ===>", timeout=4)
    except ConnectorTimeoutError:
        conn.enter()
        conn.wait_for_text("Logon ===>", timeout=15)
    conn.string(user); conn.enter()
    if wait_any(conn, ["ENTER CURRENT PASSWORD FOR", "IN USE"]) == "IN USE":
        raise SystemExit("the account is already IN USE; release it first")
    conn.string(pw); conn.enter()
    for _ in range(5):
        if wait_any(conn, ["ISPF primary option menu", "***"]) == "ISPF primary option menu":
            break
        conn.enter()
    conn.string("X"); conn.enter(); conn.wait_for_text("READY", timeout=15)
    if state in ("cleared", "reenter", "pause"):
        conn.clear()
    if state == "reenter":
        conn.string("LISTDS 'A..B'"); conn.enter(); conn.wait_for_text("REENTER -", timeout=15)
    if state == "pause":
        conn.string("LISTDS 'SYS2.JCLLIB' MEMBERS"); conn.enter(); conn.wait_for_text("***", timeout=15)
# leaving the with-block closes the connection without LOGOFF: the account stays IN USE
```

The integration file `test_flow_live_cleanup.py` carries the same sequence as a tested function, and the reviewer may run that file instead of this helper. If a call leaves the account IN USE and the Flows do not release it, recover by hand: `LOGON <id> RECONNECT` at `Logon ===>`, the password, Enter until the screen settles, then PA1 (at a REENTER prompt), Clear, `LOGOFF`, Enter.

### Other reviewer items

- Decide the open-point table above, in particular D1 (console CSS), D2 (descriptions), the REENTER reason code and the `finally` budget after check 9.
- Apply the steering correction (member names start at column 3 counted from 0: field start at column 0, two blank cells, then the name; the steering file says col 2). After the live checks the reviewer may add the verified landings and timings to the steering file.
- A browser look at the console with a multi-line output (`MEMBERS`, 136 lines): `.outputs dd` with `pre-line`, the 24rem box scrolls, contrast unchanged.
- Python 3.12, 3.13 and 3.14: run the new unit and property tests on each (only 3.11.9 was run).
- Real model behaviour with the five tools and the Ask answer quality (live check 14), and whether the tool descriptions let the model choose between `tk5-dataset-info` and `tk5-library-members`.
- The Hercules log page path in check 1; the `PA` and `String` scripting text of s3270 4.x (only the old man page was read); `PA(1)` at a REENTER prompt does not block (inferred from the unlocked keyboard in the captures).

### Unverified items the final report must list

- Anything on the live host: the five Flows end to end through the Connector, the apostrophe echo, names at the edge of the rule, the `INVALID KEYWORD` form, PA1 at a pause, the plain `LISTCAT` over several screens, `STATUS` with several jobs.
- A reconnect that lands at `READY`, at the cleared screen, at a second pause, or at a `***` pause orphan; the Logon_Cleanup is proven only on scripted screens, with the REENTER landing (by hand on 2026-11-19) and the ISPF menu (through the Flow, 2026-11-17 and 2026-11-18) the only host evidence.
- All timings: the normal run (7 s), the 7-page listing (10 s), the finally path (2 to 4 s), the recovery (9.7 s measured for the menu only).
- Real model behaviour and the browser rendering of a multi-line output.
- Python 3.12 to 3.14.
- `ambiguous_screen` and `session_error` during a `collect` are scripted in 4.6 over the existing `poll` code only.

## Notes

- Tasks in the same wave write different files. The shared files are written in order: `tests/unit/test_flow_command_flows.py` by 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.9 in separate waves; `tests/unit/test_command_capture_facts.py` by 2.3 then 3.4; `tests/property/_flow_strategies.py` by 3.3 then 4.8.
- Edits to existing test and support files are counted in the table "Every existing-test edit". Between 2.2 and 3.2 the matrix test is expected to be red on its counts; every wave after 3.3 starts green.
- Properties are numbered as in the design (1 to 11). Property 1, 2, 7 are in 4.9; 3, 4, 11 in 4.10; 5 in 4.11; 6 and 10 in 5.3; 8 in 6.3; 9 in 8.10.
- `design.md` is edited by 1.1 (documentation lines) only. `requirements.md` and `.kiro/steering` are never edited by the executor.
- Checkpoints and top-level tasks are left out of the dependency graph. Task 7 (CHECKPOINT A) sits between wave 9 and wave 10: waves 0 to 9 are tasks 1 to 6, waves 10 and later are tasks 8 to 11. The STOP-POINT is the end of wave 9.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["2.3", "3.2", "3.3"] },
    { "id": 4, "tasks": ["3.4", "4.1", "5.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "5.2"] },
    { "id": 6, "tasks": ["4.4", "4.8", "5.3"] },
    { "id": 7, "tasks": ["4.5", "4.6", "4.7", "4.9", "4.10", "4.11", "6.1"] },
    { "id": 8, "tasks": ["6.2", "6.3"] },
    { "id": 9, "tasks": ["6.4"] },
    { "id": 10, "tasks": ["8.1"] },
    { "id": 11, "tasks": ["8.2"] },
    { "id": 12, "tasks": ["8.3"] },
    { "id": 13, "tasks": ["8.4"] },
    { "id": 14, "tasks": ["8.5"] },
    { "id": 15, "tasks": ["8.6"] },
    { "id": 16, "tasks": ["8.7"] },
    { "id": 17, "tasks": ["8.8", "8.9", "8.10"] },
    { "id": 18, "tasks": ["9.1", "9.2", "9.3", "9.4", "10.1", "10.2", "10.3"] },
    { "id": 19, "tasks": ["10.4"] },
    { "id": 20, "tasks": ["11.1"] }
  ]
}
```
