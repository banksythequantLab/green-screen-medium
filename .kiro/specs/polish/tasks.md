# Implementation Plan: polish

## Overview

Do the seven polish items of `requirements.md` and `design.md` in this folder: a true README with tests that keep it true, two Kiro hooks with a test, a small command `python -m greenscreen.flow.check <file.yaml>` with its tests, one example question per tool that Ask offers on the console page (from a new optional `example:` member of the Flow YAML, carried as `x-ask-example` in the OpenAPI document only for the Flows in the Ask plan and only when Ask is on, with whole-word hints and at most 12 buttons), a smaller font for multi-line outputs, the console key read on `hashchange`, `MEMBER_COUNT` for `tk5-library-members` (a new optional `counts:` output member), and the stale text corrections.

**Order (small steps, each leaves the suite green).** Task 1 records the starting state. Task 2 does the text corrections and the rename (no code). Tasks 3 and 4 extend the Flow package (`example`, then `counts`) with their tests. Task 5 edits the bundled Flow files and the three flagged existing tests. Task 6 publishes the example in the OpenAPI document for the Flows that Ask offers. Tasks 7 to 9 change the console page (examples and hints, multi-line font, `hashchange`). Task 10 writes the hook files and their tests. Task 11 writes the Flow check command and its tests. Task 12 writes the README and its tests last, because it documents everything before it. Task 13 is the final checkpoint: it runs the whole suite once, writes `.kiro/specs/polish/report.md` and STOPS. Nothing is committed, ever.

Production files touched: `greenscreen/flow/model.py`, `yamlio.py`, `validate.py`, `runner.py`; `greenscreen/flow/check.py` (new); `greenscreen/flow/flows/tk5-system-info.yaml`, `tk5-time.yaml`, `tk5-list-datasets.yaml`, `tk5-dataset-info.yaml`, `tk5-library-members.yaml`, `tk5-job-status.yaml`; `greenscreen/publisher/rest.py`; `greenscreen/publisher/ask/service.py` (one read-only property `offered`); `greenscreen/publisher/console/snippets.js`, `console.js`, `console.css`; `README.md`; `.kiro/hooks/*.json` (new); two files of `.kiro/specs/linux-readiness`, two of `.kiro/specs/console`, two of `.kiro/specs/ask` and one of `.kiro/specs/more-flows`. Not touched: `.kiro/steering`, `sigterm-diagnostic.txt`, `pyproject.toml`, `.env.example`, `greenscreen/flow/__init__.py`, `greenscreen/connector`, `greenscreen/recognizer`, the rest of `greenscreen/publisher/ask`, `calls.py`, `app.py`, `cli.py`, `captures/`, `%TEMP%\more-flows-amend`. Every path is repo-relative. The executor works on Windows with Python 3.11. Every task states: no live host, no real model, no browser; Windows.

## Open points from the design

Rows marked CLOSED are decided; the others keep the default, which the tasks follow. The last column names the tasks that change if the reviewer decides otherwise.

| Point | Default taken in these tasks | Tasks affected if decided otherwise |
|---|---|---|
| Hook action type (A2) | CLOSED: hooks keep the shell-command form, run through the runner `python tests/hook_pytest.py` (design Decision A2b). The `1>&2` suffix was rejected because it is a parse error in PowerShell, and the `agent` alternative is described in the design. | 10.1, 10.2 (two JSON files and one assertion) |
| README lists ten specs, not nine (Open decision 1) | CONFIRMED by the reviewer: ten rows including `polish`. | 12.1, 12.2 |
| File-hook payload (Open decision 3, Finding 14) | CLOSED: the documentation gives no usable carrier for the saved path (design, "Hook payload finding"), so the Flow hook runs the three test files and does not call the check command. Reviewer check 8 reads the real payload. | 10.1, 10.2 (one assertion), a later spec |
| `GS_ASK_FLOWS` and examples (Open decision 4) | CLOSED: handled. `x-ask-example` only for Flows in the Ask plan, only when Ask is on; the page shows a button only where it is present. | 6.1, 6.2, 6.3, 7.1, 7.2, 7.3 |
| Example button cap (A18) | 12, one constant `ASK_EXAMPLE_MAX`; tested at 12 and at 13. | 7.1, 7.2, 7.3 |
| Check command output (A16) | The first violation, as `check_flow` raises it; six exit codes 0 to 5; no option. | 11.1, 11.2, 11.3, 12.1 |
| `MEMBER_COUNT` repeats the region of `MEMBERS` (A13) | Repeat and validate equality. | 4.1, 5.1 |
| Count with no rows (A12) | Present, value 0. | 4.1, 4.3, 5.2 |
| Other stale `publishing 1 of 3` text (Open decision 6) | CLOSED: corrected in the console and ask specs too (four files), and the stale-text test covers them. | 2.1, 2.3 |
| Multi-line font numbers (A8) | `0.9rem` and `1.25`, 21.3 lines in 24rem. | 8.1 |
| `hashchange` while a call runs (A10) | Adopt the key, no listing reload. | 9.1, 9.2 |

### Estimates and order

About 54 hours of work.

| # | Top-level task | Hours |
|---|---|---|
| 1 | Pre-flight and baseline (record only) | 0.75 |
| 2 | Stale text, rename and docstrings | 2.25 |
| 3 | The Flow `example` member | 4.5 |
| 4 | The Count_Output | 8.0 |
| 5 | Bundled Flows and the three flagged contract pins | 5.0 |
| 6 | Publisher: `x-ask-example` for the Flows that Ask offers | 4.5 |
| 7 | Console: example questions and whole-word hints | 8.5 |
| 8 | Console: multi-line outputs | 1.5 |
| 9 | Console: the key on `hashchange` | 4.0 |
| 10 | Kiro hooks and the hook test | 3.0 |
| 11 | The Flow check command | 3.5 |
| 12 | README and its tests | 6.5 |
| 13 | Final checkpoint, report, STOP | 1.5 |
| | **Total** | **53.5** |

If time runs short, cut in this order and report each cut: the README link-resolution test (12.2, criterion 2.8), the Node property of the example buttons (Property 4, keep the unit tests over the six real Flows and the cap tests), the unit tests of `test_polish_stale_text.py`. Never cut a flagged-edit task, the secret scans, the README coverage test, the hook-file test, the three Ask cases or the check command tests.

### Rules for every task

- DO NOT COMMIT and do not stage anything. Leave every change in the working tree. The reviewer commits.
- Never edit `.kiro/steering`. Never edit `.kiro/specs/linux-readiness/sigterm-diagnostic.txt`. Never touch `%TEMP%\more-flows-amend`. Do not delete or modify any file you did not create, except the files a task names.
- No secret is printed or written: no `TK5_USERNAME` or `TK5_PASSWORD` value, no `GS_BIND_*` value, no API key, no model key, no host address, in code, tests, fixtures, logs, assertion messages, notes, the README or the report. The README lists variable NAMES only.
- No new dependency. `pyproject.toml` stays unchanged. No framework, build step, CDN, font, script or image.
- Existing tests keep passing unmodified, with exactly the flagged edits of the table "Every existing-test edit" in the design (made by tasks 2.2, 5.3 and 7.1) and the spec text edits of tasks 2.1 and 2.2. Each flagged edit lists the expected values. No assertion is removed or weakened. If any other existing test fails, stop and report the test and the cause; never edit it.
- Stop and report a production defect found outside the files named above. Do not fix it silently.
- No task needs the live host, a real model, a real network or a browser. Tests use scripted sessions, `FakeClock`, `FakeHost`, recorded captures and raw ASGI scopes. Nothing runs `ws3270`, `s3270` or the Publisher against a host.
- Node tests: prepend `$env:Path = "C:\Program Files\nodejs;" + $env:Path` and record `node --version` once (task 1.1).
- Temp files go in a folder the task creates (`$env:TEMP\polish-<task>`) and removes at the end, never in a shared temp location.
- Library documentation: before a task that writes code with a library API (PyYAML, Hypothesis, pytest node ids, Node `vm`), re-check the API in the installed version (`python -m pip list` or `node --version`) and say so in the task note. For task 10, re-fetch https://kiro.dev/docs/hooks/ and compare it with the design table; a difference is a stop-and-report.
- Every new test file starts with a docstring that names the spec (`polish`) and the requirements it covers. Every property test is a sub-task with exactly one `@given` test per property, `max_examples` at least 100 (200 for Properties 1, 8 and 9), first line `# Feature: polish, Property <n>: <statement>`.
- Static rules for new production code: no log record, exception message or audit field holds row text, a supplied value or an example text; `greenscreen/flow/screens.py` stays the only Flow module that reads cells; `snippets.js` takes no parameter named like a key, has no `import`, no host or URL literal and none of the DOM names that `test_console_assets.py` forbids; `console.js` keeps `history.replaceState` before the first `fetch(`.
- Every task is required except where a sub-task carries `*` (none do).

### Every existing-test edit (and the task that makes it)

The table in the design, section "Every existing-test edit", is the list. In short: 2.1 corrects the log line in six spec documents; 2.2 renames one test and edits two docstrings and one spec sentence; 5.3 edits `test_flow_command_flows.py`, `test_flow_command_publish.py` and `test_flow_command_timing.py`; 7.1 edits `test_ask_snippets.py`. No other test file is edited.

## Tasks

- [x] 1. Pre-flight and baseline (about 0.75 h; record only; no live host, no real model, no browser; Windows, Node on PATH)
  - [x] 1.1 Record the starting tree and the baseline counts
    - `git status --short` and `git diff --stat`. Expected: nothing staged; only `.kiro/specs/polish/` untracked. Anything else: STOP and report. Record `git log --oneline -1`.
    - Prepend Node, record `node --version`, `python --version` and `python -m pip list` lines for `pytest`, `hypothesis`, `pyyaml`, `mcp`, `fastapi`.
    - Baseline: `python -m pytest -m "not integration" --collect-only -p no:cacheprovider` (record the number of tests collected) and run once `python -m pytest tests/unit/test_flow_bundled.py tests/unit/test_flow_sync.py tests/unit/test_flow_command_sync.py tests/unit/test_flow_captures.py tests/unit/test_command_capture_files.py tests/unit/test_recognizer_capture_inventory.py tests/unit/test_publisher_static.py tests/unit/test_publisher_openapi.py tests/unit/test_console_assets.py tests/unit/test_console_css.py tests/unit/test_ask_snippets.py -p no:cacheprovider`: all pass before any change. Record the numbers for the final report.
    - Full baseline: run `python -m pytest -m "not integration" -p no:cacheprovider` once and record passed, skipped, failed and the time. The reviewer's baseline is **4565 passed, 4 skipped, 0 failed**. If the numbers differ, record the difference in the report and go on only when failed is 0; a failure here is a stop-and-report.
    - Record the line ending of the six Flow files and the README: `git ls-files --eol greenscreen/flow/flows README.md` (task 5.1 keeps it).
    - Make NO change to any file. Run `validate_spec_format` on the three spec documents and report the result.
    - _Requirements: 17.1, 17.7_

- [x] 2. Stale text, rename and docstrings (about 2.25 h; no live host, no real model, no browser; Windows)
  - [x] 2.1 Correct `publishing 1 of 3` in the linux-readiness, console and ask specs (about 0.75 h)
    - First check what the Publisher logs: read `greenscreen/publisher/cli.py` `_report_startup` (`publishing %d of %d flows over %s`) and `tests/unit/test_publisher_cli.py` line 668 (`publishing 1 of 8`). Record both lines in the note.
    - Search first: `grep_search` for `1 of 3` over `.kiro/specs/console` and `.kiro/specs/ask` (every file, including `tasks.meta.json` and `.config.kiro`), and `publishing 1 of 3` over `.kiro/specs/linux-readiness`. The expected hits are exactly these, found on 2026-11-20: `linux-readiness/design.md` lines 67 and 376, `linux-readiness/requirements.md` line 22, `console/design.md` line 298, `console/requirements.md` line 42, `ask/design.md` line 1312, `ask/tasks.md` line 447, plus the untouchable `linux-readiness/sigterm-diagnostic.txt` line 24. Report any other hit; fix it only when it states what the Publisher logs, and report the others unchanged. Other numbers in the same files (for example `of 3` in a different sense at `ask/design.md` lines 120 and 319, `ask/requirements.md` line 466 and `ask/tasks.md` line 211) are not the log line and are left alone.
    - Edit, changing nothing else in these files: `linux-readiness/design.md` line 67 (`publishing 1 of 3 flows over stdio` becomes `publishing 1 of 8 flows over stdio`) and line 376 (`grep -q "publishing 1 of 3"` becomes `grep -q "publishing 1 of 8"`); `linux-readiness/requirements.md` line 22 (`publishing 1 of 3` becomes `publishing 1 of 8`); `console/design.md` line 298 and `console/requirements.md` line 42 (`publishing 1 of 3` becomes `publishing 1 of 8`); `ask/design.md` line 1312 and `ask/tasks.md` line 447 (`publishing 1 of 3 flows over http` becomes `publishing 1 of 8 flows over http`). Do NOT edit `sigterm-diagnostic.txt`; it records a past run.
    - Confirm with `git diff --stat` that exactly these six files changed and with `git diff --exit-code -- .kiro/specs/linux-readiness/sigterm-diagnostic.txt` that the diagnostic file did not. Run `validate_spec_format` on the six edited files and report the result (pre-existing findings are reported, not fixed).
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.9_

  - [x] 2.2 Rename the test, fix the two docstrings and the more-flows sentence (about 0.5 h)
    - Flagged edits (see the design table): in `tests/unit/test_flow_bundled.py` rename `test_exactly_three_entries_with_expected_keys` to `test_exactly_eight_entries_with_expected_keys`, body unchanged; in `tests/unit/test_flow_sync.py` replace the line 1 docstring text with `The Flows tk5-logon, tk5-logoff and tk5-system-info must not drift apart (Requirements 17.11, 17.12, 17.17).`; in `tests/property/test_publisher_bindings.py` change `(after the three bundled Flows, in file order)` to `(after the eight bundled Flows, in file order)` in the docstring (line 4).
    - In `.kiro/specs/more-flows/tasks.md` line 109 replace the sentence about `test_exactly_three_entries_with_expected_keys` so that it says the test was renamed by the polish spec to `test_exactly_eight_entries_with_expected_keys`; keep the rest of the line. Search the repository for any other occurrence of the old name (`grep_search` over all files except `.kiro/steering`); the expected result is none besides that line. Report the search result.
    - Run `tests/unit/test_flow_bundled.py`, `tests/unit/test_flow_sync.py` and `tests/property/test_publisher_bindings.py`: all pass.
    - _Requirements: 16.3, 16.4, 16.5, 16.7_

  - [x] 2.3 Write `tests/unit/test_polish_stale_text.py` (about 0.75 h)
    - Tests: every file under `.kiro/specs/linux-readiness`, `.kiro/specs/console` and `.kiro/specs/ask` (all files, found with `rglob`) except the file named `sigterm-diagnostic.txt` is free of the text `publishing 1 of 3` (build the search text from two parts so that this test file does not match itself); the exclusion is by file name and the test asserts that `sigterm-diagnostic.txt` exists and still contains the old text (the record is kept); the three folders exist; no file under `tests/` contains the text `test_exactly_three_entries` (two-part text again); `tests/unit/test_flow_bundled.py` defines `test_exactly_eight_entries_with_expected_keys` (use `ast`); `test_flow_sync.py` docstring names `tk5-system-info`; `test_publisher_bindings.py` docstring contains `eight bundled`; a self-test with a synthetic folder in `tmp_path` shows that the scan flags a stale file and ignores an excluded file of the same name only inside the linux-readiness case (so the scanner is not vacuous).
    - Messages name the file and the rule only. Run the file: passes.
    - _Requirements: 16.8_

- [x] 3. The Flow `example` member (about 4.5 h; no live host, no real model, no browser; Windows)
  - [x] 3.1 Add `Flow.example`, its YAML key and its validator rule (about 1.5 h)
    - Before coding, note the installed PyYAML version and that `safe_dump` with `sort_keys=False` keeps insertion order.
    - `greenscreen/flow/model.py`: add `example: str = ""` as the last member of `Flow` (after `timeouts`). `greenscreen/flow/yamlio.py`: add `"example": "str"` to `_TOP` after `description`; in `to_yaml` insert `example` right after `description` only when it is not empty; in `_build_flow` pass `example=obj.get("example", "")`. `greenscreen/flow/validate.py` `_check_flow_fields`: the three rules of the design (`invalid_text` for a non-string or a character outside 0x20 to 0x7E, `too_long` above 200, `interpolation_marker` for `${`).
    - Run the existing Flow tests unedited: `tests/unit/test_flow_model.py`, `test_flow_yaml.py`, `test_flow_validate.py`, `test_flow_bundled.py`, `test_flow_static.py`, `test_flow_public_api.py` and `tests/property/test_flow_yaml_roundtrip.py`: all pass. A Flow without `example` must emit the same text as before (the shipped-YAML equality test proves it).
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7_

  - [x] 3.2 Unit tests for the member (about 1.5 h)
    - `tests/unit/test_flow_example.py` (new): defaults and positional construction (`Flow("n", steps)` still works, `example == ""`); emitted key order (`description` then `example`, absent when empty); reading `example: ''` gives the empty example; wrong type (`example: 5`) names the key; the three rules with boundary strings (200 characters accepted, 201 rejected, 0x1F, 0x7F, `é`, `${`); a message never contains the rejected text; `check_flow` names `example` and the rule; the Runner ignores `example` (the result and the audit of a scripted run are equal with and without it, `repr(result)` does not contain it).
    - The test for the bundled Flows (six have a question, two have none) is added in 5.2 to this file.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.7_

  - [x] 3.3 Property test: example validation agrees with its definition (about 1.5 h)
    - `tests/property/test_flow_example.py` (new): **Property 1: Example validation agrees with its definition**. Strategy: text from the alphabet of printable ASCII, a few controls, `é`, a CJK character and `${` fragments, 0 to 260 characters. Oracle: written in the test from the definition, not from the module. Assert acceptance equals the oracle, the rule name for a rejection, and that the message does not contain the text when it has 4 or more characters.
    - **Validates: Requirements 7.3, 7.4**

- [x] 4. The Count_Output (about 8.0 h; no live host, no real model, no browser; Windows)
  - [x] 4.1 Add `OutputSpec.counts`, its YAML key, its validator rules and the runner line (about 2.5 h)
    - `greenscreen/flow/model.py`: add `counts: str | None = None` as the last member of `OutputSpec` (after `equals`). `yamlio.py`: add `"counts": "str"` to `_OUTPUT_OPTIONAL`. `validate.py`: the loop of design section 9 in `_check_outputs`; in `_StepWalk._extract` and `_StepWalk._collect` the rule `counts_not_readable` (return after adding it); in `_StepWalk.finish` skip outputs whose `counts` is not `None`. `runner.py`: add `_RunState._store_rows(output, rows)` and call it from `exec_extract` (Rows_Output branch) and `exec_collect` in place of the two `self.outputs[output.name] = "\n".join(rows)` lines.
    - Run unedited: `tests/unit/test_flow_rows_output.py`, `test_flow_collect.py`, `test_flow_flag_output.py`, `test_flow_validate.py`, `test_flow_yaml.py`, `test_flow_runner_extract.py`, `test_flow_runner_fixes_outputs_order.py`, `test_flow_static.py`, `test_flow_command_flows.py`, `test_flow_command_finally.py` and `tests/property/test_flow_rows_extraction.py`, `test_flow_collect_model.py`, `test_flow_flag_output.py`, `test_flow_secret_leak.py`, `test_flow_determinism.py`: all pass. A failure is a stop-and-report.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.9, 14.1, 14.3, 14.5, 14.6, 14.7_

  - [x] 4.2 Unit tests (about 2.0 h)
    - `tests/unit/test_flow_counts.py` (new): defaults and positional construction (`OutputSpec("o","str","s",0,0,1)` and the nine-argument form of `test_flow_flag_output.py` still work); YAML key position (after `equals`); each of the six rules with one explicit Flow and the exact rule name and field in the message; `counts_not_readable` for `extract` and for `collect`; a Count_Output needs no read step (a Flow with only the rows read is accepted); `reference_violations` and the referenced signature names are unchanged by a Count_Output.
    - Runtime examples over the existing `tests/property/_collect_support.py` pages: 3 pages of 5 lines give count 15 and 15 lines; an empty listing gives value `""` and count 0 (present, `type is int`); `extract` of a Rows_Output sets the count too; a `loop_limit` stop returns no outputs; `repr` of the result and the log records hold no row text (the style of `test_flow_secret_leak.py`).
    - _Requirements: 13.1 to 13.7, 13.9, 14.1 to 14.4, 14.6, 14.7_

  - [x] 4.3 Property test: Count_Output validation (about 1.25 h)
    - `tests/property/test_flow_counts.py` (new): **Property 8: Count_Output validation agrees with its mutations**. Base: a valid Flow (one `expect`, one `collect` or `extract` of a Rows_Output, one Count_Output). Mutations: type not `int`; `max_rows`, `next_row` or `equals` added; `counts` unknown; `counts` equal to its own name; `counts` naming an output without `max_rows`; one region member changed; an `extract` or `collect` step naming the Count_Output. The expected rule per mutation is a table in the test. Assert the base is accepted, each mutant is rejected with exactly that rule, and the message contains the output name and the rule and none of the generated text.
    - **Validates: Requirements 13.3, 13.4, 13.5, 13.6, 13.7, 13.9**

  - [x] 4.4 Property test: the count equals the number of rows read (about 1.25 h)
    - `tests/property/test_flow_counts.py` (append to the file of 4.3): **Property 9: The count equals the number of rows read**. Strategy: `page_sequence(lines_per_page, ...)` from `tests/property/_collect_support.py` with 0 to 10 pages of 0 to 22 lines (the last page ends with `ready`, earlier pages with `pause`), run through `run_flow` with a `ScriptedSession`. Assert the count is an `int` that is not a `bool`, equals the number of tokens on the pages, equals `len(value.split("\n"))` when the value is not empty and 0 otherwise, the outputs are in declaration order, and the keys sent and the audit of the run equal those of the same Flow without the Count_Output.
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.5, 14.6**

  - [x] 4.5 Property test: YAML round trip with `example` and `counts` (about 1.0 h)
    - `tests/property/test_flow_example.py` (append to the file of 3.3): **Property 2: YAML round trip with `example` and `counts`**. Build small valid Flows with an optional `example` (printable ASCII, 0 to 200) and an optional Count_Output; assert `Flow.from_yaml(flow.to_yaml()) == flow`, no `example:` line when it is empty, no `counts:` line when no output has it. Use the bundled signatures or a test signature as in `test_flow_flag_output.py`.
    - **Validates: Requirements 7.2, 7.5, 7.6, 13.2, 13.8**

- [x] 5. Bundled Flows and the three flagged contract pins (about 5.0 h; no live host, no real model, no browser; Windows)
  - [x] 5.1 Write the six `example` lines and `MEMBER_COUNT` (about 1.5 h)
    - Use a throwaway script in `$env:TEMP\polish-5.1` (created and removed by the task). For each of the six files load the Flow with `load_flow`, `dataclasses.replace(flow, example=<text of the design table>)`, and write `flow.to_yaml()` back with the line ending recorded in 1.1. For `tk5-library-members` also replace `outputs` with the two outputs of design section 9 and the description with the 381-character text of the design. Never edit the YAML by hand; `tk5-logon.yaml` and `tk5-logoff.yaml` are not opened.
    - Check: `git diff --stat` lists exactly the six Flow files; `git diff -- greenscreen/flow/flows/tk5-logon.yaml greenscreen/flow/flows/tk5-logoff.yaml` prints nothing; each of the six diffs shows only the `example:` line, and for `tk5-library-members` also the description line and the new output block; `len(description) == 381`; none of `;`, `#`, `@` is in it; `Flow.to_yaml()` equals the file text.
    - Run `tests/unit/test_flow_bundled.py` (the shipped-equals-`to_yaml()` test), `test_flow_command_sync.py`, `test_flow_readonly.py`, `test_publisher_helpers.py` and `tests/property/test_publisher_no_leak_logs.py`, `test_publisher_no_leak_responses.py`: all pass. `test_flow_command_flows.py`, `test_flow_command_publish.py` and `test_flow_command_timing.py` fail only in the places that 5.3 edits (record which). Any other failure is a stop.
    - _Requirements: 8.1, 8.2, 8.3, 15.1, 15.2_

  - [x] 5.2 Tests for the bundled Flows (about 2.5 h)
    - Append to `tests/unit/test_flow_example.py`: each of the six Published_Tools has an `example` that ends with `?`, is 10 to 120 characters, is printable ASCII, and has none of `;`, `#`, `@` except the `?`; `tk5-logon` and `tk5-logoff` have none; the two examples of `tk5-dataset-info` and `tk5-library-members` contain a name that `prepare_inputs` accepts for the `dsname` input; the exact texts of `tk5-library-members` and `tk5-time` (Requirement 8.2).
    - `tests/unit/test_flow_member_count.py` (new): the shipped `tk5-library-members` loads and passes `check_flow`; its outputs are `MEMBERS` then `MEMBER_COUNT`, the count has `counts == "MEMBERS"` and the same region; replay of the seven real member pages (use `command_session(MEMBER_PAGES)` and `_run_dsn`-style helpers of `tests/command_flow_support.py`) gives `MEMBER_COUNT == 136` and 136 lines; the capture `tso-listds-not-in-catalog` gives count 0 and `MEMBERS == ""`; `build_schemas` of the Flow equals the output and success schemas of design section 10 written as literals in the test; REST (`POST /flows/tk5-library-members` through the helpers of `test_flow_command_publish.py`) returns `MEMBER_COUNT` 136 as a JSON number; the MCP `outputSchema` equals the REST 200 schema; `project_result("ok", body)` of the Ask package keeps `MEMBER_COUNT` as an int and drops a `True`.
    - _Requirements: 8.1, 8.2, 8.3, 15.1 to 15.9_

  - [x] 5.3 Flagged edits of three existing tests (about 1.0 h)
    - Edit exactly the places of the design table: `tests/unit/test_flow_command_flows.py::test_library_members_check_flow_and_yaml_round_trip` (description length 333 becomes 381; `(out,) = flow.outputs` becomes `(out, count) = flow.outputs` with the added asserts; the step counts 31 and 6 stay); `tests/unit/test_flow_command_publish.py` (`OUTPUTS["tk5-library-members"]` gets `MEMBER_COUNT` as `integer`; the string-type assertion exempts `MEMBER_COUNT` and a new assert says it is `integer`); `tests/unit/test_flow_command_timing.py` (`MEASURED["tk5-library-members"]`: run the test once, read the measured size from the failure, expect 1354, write it). No other line changes.
    - Run the three files and `test_flow_command_finally.py`: all pass. Report the old and new numbers.
    - _Requirements: 15.5, 15.8, 17.6_

- [x] 6. Publisher: `x-ask-example` for the Flows that Ask offers (about 4.5 h; no live host, no real model, no browser; Windows)
  - [x] 6.1 Add `AskService.offered` and the vendor key to `build_openapi` (about 1.0 h)
    - `greenscreen/publisher/ask/service.py`: add the read-only property `offered` (returns `self._plan.eligible`, a `frozenset[str]`) next to `max_question_chars`. Change nothing else in that file or in the Ask package. Before coding, read `plan_ask` and `AskPlan` again and say in the note that `eligible` is the result of the `GS_ASK_FLOWS` logic.
    - `greenscreen/publisher/rest.py`: in `build_openapi` compute `offered = ask.offered if ask is not None else frozenset()`, build the operation dict in a local variable, add `x-ask-example` as the last member when `published.flow.example` is not empty and `name in offered`, and change the docstring as in the design. Do not edit `mcp_server.py`, `registry.py`, `calls.py`, `app.py` or the signature of `build_rest`.
    - Run unedited: `tests/unit/test_publisher_openapi.py`, `test_publisher_rest.py`, `test_publisher_mcp.py`, `test_publisher_registry.py`, `test_flow_command_publish.py`, `test_ask_openapi.py`, every other `tests/unit/test_ask_*.py`, `tests/property/test_publisher_schema.py`, `test_publisher_schema_agree.py`, `test_publisher_parity.py`, `test_console_parity.py` and every `tests/property/test_ask_*.py`: all pass. A failure in an Ask test is a stop-and-report (design Risk "One property on AskService").
    - _Requirements: 8.4, 8.5, 8.6, 8.7_

  - [x] 6.2 Unit tests (about 2.0 h)
    - `tests/unit/test_publisher_example.py` (new). Build the real application for the six bundled Published_Tools with the helpers of `tests/ask_support.py` (`build_ask_app`, `fetch`, `ASK_ENV`; import them, do not edit them) and the style of `tests/unit/test_ask_openapi.py::served`: `GS_PUBLISH_FLOWS` is the six names, the `userid` and `password` of each are bound with generated placeholder values (never real ones, never printed). Put the builder in a new support module `tests/example_support.py` (a function `six_tool_document(env)` that returns the served document and the app; if `ASK_ENV` publishes other Flows, the module builds its own environment and the note says so) so that task 7.2 reuses it. Required cases, each on the document that `/openapi.json` serves:
      - (a) Ask off (`GS_ENABLE_ASK` false): no operation and no other part of the document has the member `x-ask-example` (walk the whole JSON), and there is no `/ask` path.
      - (b) Ask on, `GS_ASK_FLOWS` unset, all six eligible: exactly six operations have `x-ask-example`, each equal to the `example` of its Flow, and no other member of any operation differs from the document of case (a).
      - (c) Ask on, `GS_ASK_FLOWS` set to `tk5-time,tk5-job-status`: exactly those two operations have the member (equal to their examples) and the other four have none, although they have examples.
    - The operation of `tk5-library-members` in case (b) equals the literal of design section 10 (request schema with `dsname` only, the 200 schema with `MEMBER_COUNT` as `integer`, `security`, and `x-ask-example` equal to `Which members does SYS2.JCLLIB have?`), written out as a literal in the test; the `responses` entries other than `200` are compared with those of another Flow's operation, not written out. In case (a) the same operation equals that literal without `x-ask-example`.
    - More examples in the same file: `AskService.offered` equals `prepared.ask.eligible` for the unset and the set case and is a `frozenset`; a Flow with an empty `example` (built with `dataclasses.replace`) gets no member even when offered; the document is built once: two bodies served by the same app are equal and equal to `build_openapi(registry, _package_version(), app.ask)` called again, and `build_openapi` with another offered set gives another document (the function is pure in its inputs, Requirement 8.7); no key `default`, `example`, `examples`, `const` or `enum` anywhere; the MCP tool of each Flow has the same description, input schema and output schema as before (compare with `build_schemas`); `caplog` over startup and one call with an example set contains no example text; the error bodies are unchanged.
    - _Requirements: 8.4 to 8.11, 15.10_

  - [x] 6.3 Property test: the operation carries the example if and only if Ask offers the Flow and the Flow has one
    - `tests/property/test_publisher_example.py` (new): **Property 3: The OpenAPI operation carries the example if and only if Ask offers the Flow and the Flow has one**. Strategy: 1 to 4 small valid Flows (the `MINI` style of `tests/publisher_support.py`) with random names and optional examples, `build_registry`, Ask on or off, a random subset as the offered set (a three-member stub with `offered`, `max_question_chars` and `max_answer_chars`, the only members `build_openapi` reads; say so in the note), and `build_openapi`. Assert the member rule, that every other operation member equals the one built from the same Flow without the example, the forbidden-key walk, and that two builds from the same inputs are equal.
    - **Validates: Requirements 8.4, 8.5, 8.6, 8.7, 8.8**

- [x] 7. Console: example questions and whole-word hints (about 8.5 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [x] 7.1 Change `snippets.js` and `console.js` (about 2.0 h)
    - `snippets.js`: add `ASK_EXAMPLE_MAX` (the value 12), `hintText` and the new `askExamples` of design section 6 (the third parameter is the question limit; no fallback text; a Flow without a valid example is skipped; the clamp uses `ASK_EXAMPLE_MAX`). `console.js`: import `ASK_EXAMPLE_MAX`; `parseListing` reads `operation["x-ask-example"]` (string or empty) into `example`; `renderAsk` calls `askExamples(flows, ASK_EXAMPLE_MAX, askMax.maxQuestion)`, replacing the literal `3`. Add no list of names or questions, no new fetch path. Search `console.js` and `snippets.js` for any other literal `3` that limits examples and report the result.
    - Flagged edit (see the design table): `tests/unit/test_ask_snippets.py::test_ask_examples_limits_and_hostile_values`. Add `example` to `ok-one` (`What is ok-one?`), `ok-two` (`What is ok-two?`), `ok_3` (`What is ok_3?`) and `ok-4` (`What is ok-4?`), add the row `needs-dsname` (example `Which members does SYS2.JCLLIB have?`, one required input) after `ok-4`; the expected texts for the limit 3 are the three examples, the hint of `ok-two` becomes `""`, `len(askExamples(flows, 99))` becomes 5 (was 3), `len(askExamples(flows, 1)) == 1`, the `limit 0` and `"junk"` lines stay, `needs-input` is still skipped. Record each value before and after in the note. Nothing else in the file changes.
    - Run (Node on PATH): `tests/unit/test_ask_snippets.py`, `test_ask_trace_parity.py`, `test_ask_assets.py`, `test_console_assets.py`, `test_console_mcp_assets.py`, `test_console_snippets.py`, `test_console_packaging.py`, `test_console_routes.py`, `tests/property/test_console_snippets.py`, `test_console_mcp_snippets.py`, `test_ask_trace.py`: all pass.
    - _Requirements: 9.1 to 9.8, 9.10, 10.1 to 10.7_

  - [x] 7.2 The extraction harness and the example unit tests (about 3.0 h)
    - `tests/console_node_extract.py` (new support module, same style as `tests/console_node_ask.py`: one `node` process per batch, input on standard input, no stream echoed on failure): `function_source(text, name)` by brace matching (`function` and `async function`), `run_listing(documents)` that runs the extracted `parseListing` over OpenAPI-like documents under `vm.runInNewContext`, and `run_fragment(cases)` that is used by task 9.2. The helper reads `console.js` from the package with `importlib.resources`.
    - `tests/unit/test_console_examples.py` (new, `needs_node`). The three page cases run over the three real documents of task 6.2 (built with `six_tool_document` of `tests/example_support.py`, imported, not edited), each passed through `parseListing` and `askExamples(items, ASK_EXAMPLE_MAX, 500)` under Node, then through the real `renderAsk` text for the button count if the harness can run it, otherwise through the item count and a static check that `renderAsk` creates one `button` per item:
      - (a) Ask off: zero items and zero buttons.
      - (b) Ask on, six offered: six items in listing order (`tk5-system-info`, `tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members`, `tk5-job-status`), texts equal to the six `example` values, hints non-empty, at most 100 characters and printable ASCII; six buttons.
      - (c) Ask on, `GS_ASK_FLOWS` of two names: exactly two items (`tk5-time`, `tk5-job-status`) and two buttons.
    - Cap tests, at the number and one above: a listing of exactly 12 Flows that carry examples gives 12 items for the limit 12 and for the limit 13; a listing of 13 gives 12 items for the limit 12, 13 and 99; the constant `ASK_EXAMPLE_MAX` equals 12 (read from the module, Node) and the literal `3` no longer limits examples in either file.
    - Other examples: with `askMax` 30 the long examples are skipped; the `hintText` examples of Requirement 10 (the description of each of the six Flows: whole first sentence or word-boundary cut; a 300-character single word gives `""`; a text with no sentence end and 120 characters ends with `...`); static: `console.js` and `snippets.js` contain none of the six Flow names, none of the six example texts and no `Run <name> and tell me` text; the click handler text of `renderAsk` sets the field, calls `updateAskCount()` and focuses it.
    - _Requirements: 9.1 to 9.12, 10.1 to 10.7_

  - [x] 7.3 Property test: the example buttons follow the listing (about 1.5 h)
    - `tests/property/test_console_examples.py` (new, `needs_node`, one Node batch per example, style of `tests/property/test_console_mcp_snippets.py`). **Property 4: The example buttons follow the listing**. Strategy: OpenAPI-like documents with 0 to 30 operations (names valid and invalid, `summary` text, `x-ask-example` of string, printable and non-printable text, number, null, list or absent, request schemas with required, optional and `writeOnly` properties), limit -1 to 20, question length absent or 1 to 600. Oracle: a Python model of Requirement 9 (no fallback text, cap 12).
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**

  - [x] 7.4 Property test: a hint ends at a whole word (about 1.0 h)
    - `tests/property/test_console_examples.py` (append to the file of 7.3): **Property 5: A hint ends at a whole word**. Strategy: texts of words and blanks, sentence marks, non-ASCII characters, tabs and newlines, 0 to 400 characters. Assert length, charset, equality with the Python model of Requirement 10, and the whole-word rule for the part before `...`.
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**

  - [x] 7.5 Property test: `outputClass` marks exactly the multi-line values (about 0.75 h)
    - Requires 8.1 (`outputClass`). `tests/property/test_console_examples.py` (append to the file of 7.3): **Property 6: `outputClass` marks exactly the multi-line values**. Strategy: text with and without LF, CR LF, other whitespace, and non-string values (numbers, `null`, lists).
    - **Validates: Requirements 11.1**

- [x] 8. Console: multi-line outputs (about 1.5 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [x] 8.1 Class, style and tests
    - `snippets.js`: add `outputClass` (design section 6). `console.js` `showSuccess`: import `outputClass`; the `dd` gets `{ class: outputClass(text) }`. `console.css`: add the rule `.outputs dd.multiline` of the design directly after `.outputs dd`; do not edit `.outputs dd`.
    - `tests/unit/test_console_multiline.py` (new): the CSS text test of design section 7 (both rules found by exact selector with the `_rule_declarations` style of `test_console_css.py`; `.outputs dd` keeps `font-size: 2rem` and `max-height: 24rem`; the multi-line rule gives at least 20 lines; no colour literal, no `url(`, no `@font-face`, no animation); static: `showSuccess` passes `outputClass(text)` to the `dd` and no other element gets the class; Node (`needs_node`): `outputClass` gives `multiline` for `"a\nb"` and `null` for `"a"`, `""`, `"a b"` and `136`.
    - Run `tests/unit/test_console_css.py`, `test_console_seance.py`, `test_console_audit_layout.py`, `test_ask_assets.py`, `test_console_assets.py` unedited: all pass.
    - _Requirements: 11.1 to 11.6_

- [x] 9. Console: the key on `hashchange` (about 4.0 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [x] 9.1 Change `console.js` (about 1.0 h)
    - `takeKeyFromFragment` returns `false` when the fragment does not start with `#key=` and `text !== ""` otherwise; add `onHashChange` after `connect()`; in `start()` register `window.addEventListener("hashchange", onHashChange)` and call `onHashChange()` once, both directly after `codes = await loadCodes();`. Do not add a second `history.replaceState` text, do not read `apiKey` outside `apiFetch`, do not assign `location.hash`.
    - Run unedited: `tests/unit/test_console_assets.py` (the replaceState-before-fetch test, the `apiKey` read test, the scroll and forbidden-name tests), `test_console_mcp_assets.py`, `test_ask_assets.py`, `tests/property/test_console_auth.py`: all pass.
    - _Requirements: 12.1 to 12.9_

  - [x] 9.2 Tests (about 3.0 h)
    - `tests/unit/test_console_hashchange.py` (new): static: `start()` registers `hashchange` after `loadCodes()`; `onHashChange` calls `takeKeyFromFragment`, `showKeyPanel(false)` and `loadListing()` only when `running` is false; the first `history.replaceState` still precedes the first `fetch(`; Node (`needs_node`) examples through `run_fragment`: `#key=abc` (taken, key `abc`, one `replaceState` call with `(null, "", "/p?x=1")` for pathname `/p` and search `?x=1`), `#key=` (not taken, one call), `#other` (nothing), `#key=%41%42` (key `AB`), `#key=%E0%A4%A` (raw text), `#key=%` (raw text), a second call with a new fragment replaces the key.
    - `tests/property/test_console_fragment.py` (new, `needs_node`): **Property 7: The fragment reader matches its model**. Strategy: fragments built from the prefixes `""`, `#`, `#key=`, `#KEY=`, `#key`, `#key=#key=`, `#other=` and a tail of text (letters, digits, percent escapes that are valid, percent escapes that are invalid UTF-8, a lone `%`, non-ASCII, no lone surrogates), pathname and search strings. Oracle in Python: valid percent escapes decode as UTF-8, otherwise raw. Assert `taken`, the key state, the `replaceState` calls (exactly one with `(null, "", pathname + search)` when the prefix is `#key=`, none otherwise), and that no `replaceState` argument contains the key text. Failure messages name the case index and the rule only.
    - **Validates: Requirements 12.2, 12.3, 12.4, 12.5, 12.9**

- [x] 10. Kiro hooks and the hook test (about 3.0 h; no live host, no real model, no browser; Windows)
  - [x] 10.1 Write the two hook files (about 1.0 h)
    - Re-fetch https://kiro.dev/docs/hooks/ and the related pages https://kiro.dev/docs/hooks/actions/, https://kiro.dev/docs/hooks/types/ and https://kiro.dev/docs/hooks/examples/. Compare the `v1` format with the design table, and compare what the pages say about the saved file's path with the design section "Hook payload finding" (no path variable, no placeholder, no environment variable for a file event, no named member in the standard-input JSON). Record the page dates. A difference in the format: STOP and report. A newly documented carrier for the path: STOP and report, because it would change Decision A3 (the Flow hook could then call the check command of task 11 first); do not change the hook yourself.
    - Create `tests/hook_pytest.py` (design section 1: `pytest.main(args)` with standard output redirected to standard error, exit with pytest's exit code) and `.kiro/hooks/flow-yaml-check.json` and `.kiro/hooks/captures-check.json` with exactly the JSON text of design section 1. The Flow hook runs the three test files and does not call `greenscreen.flow.check`. Do not edit `.gitignore` (it must not hide `.kiro`). Confirm both files parse (`python -c "import json,sys; json.load(open(sys.argv[1]))" <file>` for each) and that `git status --short .kiro/hooks` shows them untracked.
    - Dry-run each command once from the repository root: run the `command` text of the Flow hook and of the Capture hook as written from PowerShell (pwsh) and through `cmd` (`subprocess` with `shell=True`); each exits 0 and prints nothing on standard output. Also run the runner on a deliberately failing test in a temp folder of the task (removed at the end): exit code other than 0, standard output empty, the report on standard error. Record exit codes and the number of tests passed and skipped. With `TK5_PASSWORD` unset the password scans skip with a reason: that is expected, not a failure.
    - Write the finding into the report of task 13 under the heading "Hook path": which case applies (the path cannot be passed in a documented form, so the three tests run), why, and the four URLs with their dates.
    - _Requirements: 3.1 to 3.8, 4.1 to 4.7_

  - [x] 10.2 The hook-file test (about 1.25 h)
    - `tests/unit/test_kiro_hooks.py` (new): the functions of design section 2, including the assertions that every command starts with `python tests/hook_pytest.py ` and ends with ` -p no:cacheprovider`, contains no `1>&2` and no `-m pytest`, and that no hook command contains `greenscreen.flow.check`. The test that each hook file name occurs in `README.md` is part of this file and fails until task 12.1 writes the README: this red window is expected and short, and the executor does not stop on it. A synthetic broken JSON file in `tmp_path` proves that a parse failure names the file.
    - _Requirements: 5.1 to 5.7_

  - [x] 10.3 Property test: hook matchers accept exactly their paths (about 0.75 h)
    - `tests/property/test_kiro_hook_matchers.py` (new): **Property 10: Hook matchers accept exactly their paths**. Strategy: a prefix (empty, relative directories, a Windows drive prefix, an absolute POSIX prefix) joined with `/` or `\`, the fixed directory part, and a file name made of letters, digits, `-`, `_`, `.`; the matchers are read from the real JSON files. Assert the Flow matcher matches exactly when the name ends with `.yaml` and the directory part is `greenscreen/flow/flows`, the capture matchers match every file name directly inside `captures`, neither matches another parent directory, and `re.search` equals `re.fullmatch` on every case.
    - **Validates: Requirements 3.2, 4.2, 5.2**

- [x] 11. The Flow check command (about 3.5 h; no live host, no real model, no browser; Windows)
  - [x] 11.1 Write `greenscreen/flow/check.py` (about 1.25 h)
    - Before coding, note the installed PyYAML version and how `yaml.YAMLError` and `problem_mark` behave (the same facts that `yamlio._safe_load` uses), and read `tests/unit/test_flow_static.py` so that the new module respects its rules.
    - New module `greenscreen/flow/check.py` as in design section 3: the six constants `EXIT_OK = 0`, `EXIT_VIOLATION = 1`, `EXIT_USAGE = 2`, `EXIT_NO_FILE = 3`, `EXIT_NOT_YAML = 4`, `EXIT_NO_SIGNATURES = 5`; `main(argv=None) -> int` with the order usage, read, decode and parse, signatures, validate; the fixed lines of the design table; `_clean` (printable ASCII, 200 characters); `ok: <file name>` on standard output, every other line on standard error; `if __name__ == "__main__": raise SystemExit(main())`. No option, no environment access, no `time`, `datetime` or `random`, only `yaml.safe_load`, no import from `greenscreen.connector`, no write to any file. Do not edit `greenscreen/flow/__init__.py` or `pyproject.toml`.
    - Smoke: `python -m greenscreen.flow.check greenscreen\flow\flows\tk5-time.yaml` prints `ok: tk5-time.yaml` and `$LASTEXITCODE` is 0. Run unedited: `tests/unit/test_flow_static.py`, `test_flow_public_api.py`, `test_flow_packaging.py`, `test_flow_bundled.py`: all pass.
    - _Requirements: 6.1 to 6.10_

  - [x] 11.2 Unit tests (about 1.25 h)
    - `tests/unit/test_flow_check.py` (new), calling `main([...])` with `capsys` and `tmp_path` files: a good file (copy of a bundled Flow file: exit 0, `ok: <name>` on standard output, nothing on standard error); a bad file with a violation (the same Flow with one signature name changed to an unknown name: exit 1, one `violation:` line that holds the rule `unknown_signature` and no description text); a missing file (3, `error: file not found or not readable`); a directory given as the file (3); a non-YAML file (`key: [unclosed` gives exit 4 with `(line L, column C)`, the bytes `\xff\xfe` give exit 4 without a position, a YAML list gives exit 4); usage errors (no argument, two arguments, `-x`, `--help`, the empty string: exit 2, one `usage:` line); a monkeypatched `load_bundled_signatures` that raises (exit 5, fixed line, no cause text); the six exit codes are six distinct integers; the file is not modified (hash before and after); a description of 300 characters with a non-ASCII letter in a violating file never appears in the output; one `subprocess.run([sys.executable, "-m", "greenscreen.flow.check", <file>], env=<environment without any TK5_ or GS_ variable>)` call for a bundled file (0) and for a missing file (3). Messages name the case and never print a file's content.
    - _Requirements: 6.1 to 6.10, 6.12_

  - [x] 11.3 Property test: the check command agrees with the Flow reader (about 1.0 h)
    - `tests/property/test_flow_check.py` (new): **Property 11: The check command agrees with the Flow reader**. Strategy: file contents chosen from `to_yaml()` of small valid Flows (a `description` and an `example` drawn from printable text of 4 to 60 characters), the same text with one field changed (unknown signature, number out of range, a removed required key), arbitrary YAML mappings and lists, malformed YAML, and arbitrary bytes including invalid UTF-8. Write the content into a `tempfile.TemporaryDirectory` made inside the test, call `main([path])` with `capsys`-free capture (`contextlib.redirect_stdout` and `redirect_stderr`), and compare with an oracle written in the test from `Flow.from_yaml` and `yaml.safe_load`: exit 0 exactly when the reader accepts; 4 when the bytes are not UTF-8, the YAML does not parse or the top level is not a mapping; 1 otherwise; every printed line is printable ASCII of at most 200 characters; no line contains the generated free text.
    - **Validates: Requirements 6.2, 6.3, 6.6, 6.8, 6.10, 6.11**

- [x] 12. README and its tests (about 6.5 h; no live host, no real model, no browser; Windows)
  - [x] 12.1 Write `README.md` (about 3.25 h)
    - Use the outline of the design and write only what the code does today. Facts to read before writing, with the file that proves each: `.env.example` and `greenscreen/publisher/config.py` (variable names, ranges, defaults), `greenscreen/publisher/cli.py` (`greenscreen-publish`, the startup log line), `pyproject.toml` (extra `publish`, console script), `greenscreen/publisher/rest.py` (routes, security schemes), `greenscreen/publisher/console/snippets.js` (the Kiro MCP config shape and the curl shape), `greenscreen/flow/check.py` (usage and exit codes), the nine spec `design.md` titles and `.kiro/specs/polish`, `.kiro/steering/product.md` and `mainframe-host.md` (read only), `.kiro/hooks/*.json`.
    - Content: sections of the design outline; the six tool lines; Windows (PowerShell) and Linux blocks with `<path to ws3270.exe>`, `<path to s3270>`, `<mainframe host>` placeholders, `pip install -e ".[publish]"`, `greenscreen-publish`, the secret set by a prompt command that starts with another word (`Set-Item -Path Env:GS_API_KEY -Value (Read-Host "API key")`, `read -rs GS_API_KEY && export GS_API_KEY`), and a statement that `GS_PUBLISH_FLOWS` should be set to the six names because the default publishes all eight, including `tk5-logon`, which leaves the user id logged on; the 30-row variable table written from the code (names only); the Binding_Rule with the example name `GS_BIND_TK5_TIME__USERID` (a name, no value); the validated YAML example of the design; the section "Check a Flow file" with the command `python -m greenscreen.flow.check <file.yaml>`, one usage example, the table of the six exit codes 0 to 5 and the sentence that it validates against the bundled signatures and changes nothing; REST (`curl` with `-H 'X-API-Key: <YOUR_API_KEY>'`), MCP over HTTP and over stdio, and the Kiro `.kiro/settings/mcp.json` block with `<YOUR_API_KEY>`; how Kiro built it (ten spec rows, two steering files, captures from the real host, the two hooks with their file names and what they run (commands of the form `python tests/hook_pytest.py <paths> -p no:cacheprovider`, the runner that puts the pytest report on standard error), the test suite commands `python -m pytest -m "not integration" -p no:cacheprovider` and the Node note); the section "Not built yet" with exactly three bullets (Flow recorder, 5250 (AS/400) support, Flows that write to the host); the License section with the link to `LICENSE`. Ask is described as optional, with the egress sentence of Requirement 1.13, and the example buttons appear only when Ask is on. No IPv4 address except `127.0.0.1`, no key, no `TK5_*` value, no `recorded`/`records` claim about a recorder.
    - Before saving, validate the YAML block with `Flow.from_yaml` and the bundled signatures, and run `tests/unit/test_publisher_static.py::test_no_file_holds_a_nonempty_api_key_or_binding_value`: it passes.
    - _Requirements: 1.1 to 1.14_

  - [x] 12.2 Write `tests/unit/test_readme.py` (about 3.25 h)
    - Tests of Requirement 2 in this order: `test_every_gs_variable_of_the_code_is_in_the_readme` (AST scan of `greenscreen/**/*.py` string constants that fully match `GS_[A-Z0-9]+(_[A-Z0-9]+)*`, so `GS_BIND_` is excluded by its trailing underscore; also every name of `.env.example` is in the README); `test_the_readme_names_no_unknown_gs_variable`; `test_tool_list_is_the_bundled_flows_minus_logon_and_logoff`; `test_spec_list_is_the_spec_directories`; `test_every_hook_file_is_documented_and_exists`; `test_the_check_command_is_documented` (the text `python -m greenscreen.flow.check`, the file `greenscreen/flow/check.py` with a function `main` found with `ast`, and each digit 0 to 5 with its meaning inside the section "Check a Flow file"; Requirement 2, criterion 11); `test_forbidden_claims_only_in_not_built_yet` (split by `## ` headings; words `recorder`, `5250`, `AS/400`, `web terminal`, `write flow`; the phrases `Early build` and `will land here`); `test_no_secret_looking_values` (no assignment line for `GS_API_KEY`, `GS_LLM_API_KEY`, a `GS_BIND_` name or a `TK5_` name; no IPv4 except `127.0.0.1`; no 24-character token outside URLs, paths and command names; the only placeholders are `<YOUR_API_KEY>` and angle-bracket words); `test_script_and_extra_exist_and_links_resolve` (`tomllib` on `pyproject.toml`); `test_yaml_and_json_blocks_parse`; `test_static_secret_scan_is_green_with_the_readme` (calls the same regex as `test_publisher_static.py` on the README text).
    - Scanner self-tests: three synthetic README texts (one with a recorder claim outside the section, one with an assignment line, one with an IPv4 address) must be flagged, and one synthetic README without the check command text must fail the documentation test, so that the scanners are not vacuous. Messages name the rule and the line number, never the matched value.
    - Run `tests/unit/test_readme.py`, `tests/unit/test_kiro_hooks.py` and `tests/unit/test_publisher_static.py`: all pass.
    - _Requirements: 2.1 to 2.11, 5.6_

- [x] 13. Final checkpoint, report, STOP (about 1.5 h; no live host, no real model, no browser; Windows, Node on PATH)
  - [x] 13.1 Run the whole suite, check the tree, write the report and stop
    - Prepend Node, record `node --version`, run `python -m pytest -m "not integration" -p no:cacheprovider` (no `-q`: `pyproject.toml` sets it). Record passed, skipped, failed, deselected, pytest time and wall time.
    - Git checks: `git diff --name-only` lists only the production files of the Overview (`greenscreen/publisher/ask` shows exactly `greenscreen/publisher/ask/service.py`, and `git diff -- greenscreen/publisher/ask/service.py` shows only the property `offered`), the six Flow YAML files, `README.md` (modified, not new), the existing tests of the design table (and no other), the three spec folders' text edits (`linux-readiness`: `design.md`, `requirements.md`; `console`: `design.md`, `requirements.md`; `ask`: `design.md`, `tasks.md`) and `.kiro/specs/more-flows/tasks.md`; `git status --short` lists as untracked only `.kiro/hooks/`, `.kiro/specs/polish/`, `greenscreen/flow/check.py` and the new test and support files. `git diff --exit-code -- .kiro/steering pyproject.toml .env.example .gitignore greenscreen/flow/__init__.py greenscreen/connector greenscreen/recognizer greenscreen/publisher/calls.py greenscreen/publisher/app.py greenscreen/publisher/cli.py captures .kiro/specs/linux-readiness/sigterm-diagnostic.txt` prints nothing; `git diff --cached --name-only` prints nothing; `git log --oneline -1` equals the line recorded in 1.1; `.kiro` is not in `.gitignore`.
    - Secret scan of the new and changed files (not printed): no `TK5_PASSWORD` or `TK5_USERNAME` value, no key, no IPv4 other than `127.0.0.1`; report only counts.
    - Print the generated operation for the report with a throwaway script in `$env:TEMP\polish-13.1` (created and removed): build the six-tool application with `six_tool_document` of `tests/example_support.py` once with Ask on and `GS_ASK_FLOWS` unset, take `document["paths"]["/flows/tk5-library-members"]["post"]`, and print it with `json.dumps(..., indent=2)`; then build it once with Ask off and print only whether the member `x-ask-example` is present. The bound values in that run are generated placeholders and are never printed.
    - Write `.kiro/specs/polish/report.md` with these parts, each with its own heading:
      - **Suite counts**: passed, skipped, failed, deselected before (task 1.1; the reviewer's baseline is 4565 passed, 4 skipped, 0 failed) and after, with the difference, and the number of new tests per new file.
      - **Existing tests edited**: every edit of the design table "Every existing-test edit" with the file, the test, and the value before and after as seen (for example the description length 333 to 381, the measured size 1335 to the measured value, `len(askExamples(flows, 99))` 3 to 5, the renamed test, the clock assertion of `test_a_bad_screen_in_the_middle_of_a_collect_stops_the_run_at_once` from `clock.now < _T.step` to `clock.now < _T.step + 1e-9`, the probe strategy of `test_publisher_parity.py::test_front_ends_agree_and_success_fits_schema` from `probes("int", max_size=4)` to the same with `.filter(lambda n: str(n) not in _SCREEN_TEXT)`), plus the spec text edits with the line numbers.
      - **Files changed**: the output of `git diff --name-only` and `git status --short` grouped as production, tests, specs, docs, hooks.
      - **`/openapi.json` fragment**: the operation of `tk5-library-members` as printed (request schema, the 200 response schema with `MEMBER_COUNT` as `integer`, and `x-ask-example`), and the one-line result for Ask off.
      - **Hook path**: the case and the four URLs with their dates (task 10.1).
      - **Cap**: the value 12, where it is defined, and the two cap tests (12 and 13).
      - **Check command**: the six exit codes as implemented.
      - **Not run by the executor**: the nine reviewer items below with their exact commands, copied from the design section "Live-host checks (reviewer)".
      - The open decisions as settled and anything not verified. Then STOP. Do not commit, stage or start another task.
    - Run `validate_spec_format` on the three spec documents and report the result.
    - _Requirements: 17.1 to 17.9_

## Reviewer-only items (the executor does NOT run these; no checkbox)

These need the live host, a real model, a browser, Kiro itself or Linux. The executor lists them in the report as "not run by the executor", with the exact commands that the design section "Live-host checks (reviewer)" gives for each. One session per user id: stop the Publisher before an integration test and never run two checks at once. Placeholders: `<YOUR_API_KEY>` (16 characters or more), `<LLM_BASE_URL>`, `<LLM_MODEL>`, `<MAINFRAME_HOST>`. The demo account comes from the shell; no check prints it.

1. The check command: exit 0 for a bundled file, 3 for a missing file, 2 for no argument, 1 for a file with a changed signature name, 4 for `README.md`.
2. Ask off: `/openapi.json` has no `x-ask-example`, the Ask panel and the example buttons are not shown.
3. Ask on, six offered: `/openapi.json` names six operations with `x-ask-example`, the page shows six buttons with whole-word hints, and each click and Ask gives a sensible answer from the matching tool.
4. Ask on with `GS_ASK_FLOWS` of two names: exactly those two operations have the member and the page shows two buttons.
5. A second `#key=` link in the same tab takes effect and leaves no fragment; a wrong key brings back the key panel.
6. `tk5-library-members` for `SYS2.JCLLIB` shows at least 20 lines at the smaller size and scrolls the rest; `MEMBER_COUNT` shows 136 in the large size; REST returns 136; Ask answers "How many members does SYS2.JCLLIB have?" with 136.
7. Both hooks fire in Kiro (on save and on create), a broken Flow reaches the agent as a pytest report, and a save by the user (not only by the agent) fires `PostFileSave`.
8. The throwaway payload hook shows which member of the standard-input JSON carries the saved path (settles Decision A3).
9. The README commands work on Linux with `s3270`, from a clean virtual environment to a `/health` answer.

## Notes

- Tasks in the same wave write different files. Shared files are written in order: `snippets.js` by 7.1 then 8.1; `console.js` by 7.1, 8.1, 9.1; `model.py`, `yamlio.py`, `validate.py` by 3.1 then 4.1; `rest.py` and `ask/service.py` only by 6.1; `tests/example_support.py` only by 6.2 (task 7.2 imports it); `tests/unit/test_flow_example.py` by 3.2 then 5.2; `tests/property/test_flow_example.py` by 3.3 then 4.5; `tests/property/test_flow_counts.py` by 4.3 then 4.4; `tests/property/test_console_examples.py` by 7.3, 7.4 and 7.5 in three waves (7.3 needs the harness of 7.2, 7.5 needs `outputClass` from 8.1); `tests/unit/test_kiro_hooks.py` only by 10.2 (its README assertion is green after 12.1); `greenscreen/flow/check.py` only by 11.1.
- Checkpoints and top-level tasks are left out of the dependency graph. Task 13 is the final checkpoint and the only STOP-POINT; its leaf 13.1 is in the last wave.
- Tasks marked with `*` would be optional; none are.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1", "7.1", "10.1", "11.1"] },
    { "id": 2, "tasks": ["2.3", "3.2", "3.3", "4.1", "8.1", "10.2", "10.3", "11.2", "11.3"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.1", "6.1", "9.1"] },
    { "id": 4, "tasks": ["4.4", "5.2", "5.3", "6.2", "6.3", "9.2"] },
    { "id": 5, "tasks": ["4.5", "7.2", "12.1"] },
    { "id": 6, "tasks": ["7.3", "12.2"] },
    { "id": 7, "tasks": ["7.4"] },
    { "id": 8, "tasks": ["7.5"] },
    { "id": 9, "tasks": ["13.1"] }
  ]
}
```
