# Requirements Document

## Introduction

The bridge publishes three Flows today (`tk5-logon`, `tk5-logoff`, `tk5-system-info`), and only `tk5-system-info` returns data. This feature adds five read-only Flows that run one TSO command at the `READY` prompt of the demo host and return what the host printed: `TIME`, `LISTCAT`, `LISTDS '<name>'`, `LISTDS '<name>' MEMBERS` and `STATUS`. They are published as MCP tools and REST endpoints like every other Flow, and Ask can offer them to a model.

Two of the five commands return a variable number of rows over several screens (`LISTCAT`, `LISTDS ... MEMBERS`, and `STATUS` for an account with many jobs). The Flow runtime reads one fixed region per output today and cannot press Enter at a `***` pause while collecting rows. The spec therefore adds the smallest runtime extension that expresses this, keeps every existing contract, and proves the extension with Hypothesis property tests. It promotes the 18 captures recorded on 2026-11-19 (36 files) into `/captures` and adds the two signatures that the new Flows need (`tso-cleared`, `tso-reenter`).

The live host forced three further changes, recorded in the steering section "Verified 2026-11-19 (evening)": (1) a data set name must be well formed for the host, not only free of quotes, because a name the host rejects leaves the session at a ` REENTER -` prompt where `LOGOFF` does not work (Requirement 20); (2) a Flow that types a caller value must be able to leave that prompt with PA1 before it logs off, and the run must end with a defined outcome (Requirement 21); (3) the bundled logon recovery must release an orphaned session that sits at `READY`, at the cleared screen or at a ` REENTER -` prompt, not only one that sits at the ISPF menu (Requirement 22). The spec text that says "only the ISPF menu case is handled" is corrected at implementation time (Requirement 23).

The product rules stay as they are: the runtime is deterministic and uses no LLM, a Flow never guesses (an unknown screen stops the run), credentials come from the environment and are bound on the server, and no Flow writes to the host.

### Findings from reading the code and captures

All probes behind these findings were throwaway scripts and a scratch copy of the repository under `%TEMP%`, outside the workspace, deleted afterwards. No file of the repository other than this one was changed.

**Finding 1: the cleared-screen capture now exists, so the former blocker is gone.** The steering rule says a Flow that reads command output at `READY` sends Clear before typing, so that the echo is on row 0 and the output starts on row 1. The validator refuses a `type` or `key` step that no `expect` step has armed (`greenscreen/flow/validate.py`, `_StepWalk._type` and `_key`, rule `unarmed`), and `armed` is reset by every `key` step (`walk`). After `key: clear` the Flow must therefore `expect` the cleared screen, and that screen needs a signature. `tso-ready` (`last_row: ' READY'`) cannot match a blank screen (`matching._last_row` returns False when no row is non-blank). The capture `tso-cleared` was recorded on 2026-11-19. Read with `ScreenParser`: cursor (0,0), one field start at (23,79) that is unprotected and not hidden, no non-blank row, no hidden field, both file forms agree. A candidate signature (one `field_layout` with `(23,79)`, one `cursor_field` `(23,79, hidden false)`, 24 `region_regex` `^ *$`) matches this capture and no other of the 28 captures, and a typed-over copy (text typed at the cursor, restored through `build_comparison`) still matches only it. The design stage is no longer blocked (Requirement 2).

**Finding 2: every READY-ending output screen already matches `tso-ready`, and every paging screen already matches `tso-pause`.** Read with `ScreenParser` through the same code as `tests/screen_support.py`. Both signatures are `last_row` matchers (`tso-pause` adds `before_cursor`), and the last non-blank row of every output screen is the prompt row (` READY` or ` ***`). The repository convention that each capture matches exactly one signature (`tests/unit/test_recognizer_capture_matrix.py`) holds if the new captures map to `tso-ready` and `tso-pause`. Adding a more specific signature (for example "LISTDS not in catalog") would make the same screen match two signatures. `recognize` raises `AmbiguousScreenError` for that, and the runner turns it into `ambiguous_screen`, which is in `_FINALLY_SKIP_REASONS` and leaves the user id logged on. The distinction between "found" and "not in catalog" is therefore made by reading the screen (Decision 3), not by a signature. The matrix of 12 signatures against 28 captures (336 evaluations, run on 2026-11-19 with the candidate signatures of Requirements 2 and 21) gives exactly one match per capture; the two new READY-ending captures `tso-listcat-level-page3` and `tso-listds-reenter-after-pa1` match `tso-ready`, and the two new paging captures `tso-listcat-level` and `-page2` match `tso-pause`.

**Finding 3: the runner can press Enter at a pause and poll, but cannot read rows inside a loop.** `exec_handle` (`runner.py`) runs a body of `type` and `key` steps up to `max_count` times (validator: 1 to 20; body kinds other than `type` and `key` are `not_allowed_in_handle`). `Extract` reads one `OutputSpec` region (`row`, `col`, `length`, 1 to 80 characters on one row) once, from the Current_Screen, and `finish()` demands exactly one `extract` per output (`needs_exactly_one_extract`). A paging read cannot be written as a Handle around an Extract. A new step kind is needed (Decision 2).

**Finding 4: outputs are `str` or `int` end to end.** `OutputSpec.type` is checked against `("str", "int")` (`validate._check_outputs`), `FlowResult.outputs` is typed `Mapping[str, str | int]` (`model.py`), `build_schemas` maps `int` to `integer` and everything else to `string` (`registry.py`), Ask's `project_result` keeps an output only when `_typed(v, (str, int))` and the Ask response schema allows `["string", "integer"]` (`ask/service.py`), and the console prints an object value with `JSON.stringify` and any other value with `String(value)` (`console.js`). A list-valued output would be silently dropped from the Ask trace and would change the OpenAPI, MCP, Ask and console contracts. A `str` output holding the rows separated by one line feed changes none of them (Decision 1).

**Finding 5: the pinned counts and the measured effect on existing tests.** The repository pins ten captures, ten signatures and three Flows. To find exactly which existing tests change, the executor-to-be's design was applied to a scratch copy of the repository outside the workspace (two new signature files and the new logon steps of Requirement 22 in `tk5-logon.yaml` and `tk5-system-info.yaml`, nothing else) and the suites were run on 2026-11-19. Result for `tests/unit`: the only failures are the signature-count tests (`test_recognizer_bundled.py`, `test_recognizer_capture_matrix.py`, `test_recognizer_recognize.py::test_unknown_for_ispf_without_ispf_signature_shows_option_prompt`) and eight tests of `test_flow_spec_consistency.py`, which fail in the copy only because it holds no `.kiro` directory. `test_flow_bundled.py`, `test_flow_sync.py`, `test_flow_logon_script.py`, `test_flow_logon_recovery.py`, `test_flow_system_info_script.py`, `test_flow_runner_fixes_skipped.py`, `test_flow_packaging.py` and the publisher tests pass without edit. Result for `tests/property`: exactly three failures, `test_flow_determinism.py`, `test_flow_stale_reads.py` and `test_flow_unknown_stops.py`, all with `LookupError: no partial repaint cell found for 'tso-cleared'` raised by `tests/flow_support.py` (`_SIGNATURE_CAPTURE` has no entry for the new signatures and a blank screen has no repaintable cell); they pass on an unmodified copy. The integration tests were not run (no host). The table "Existing behaviour and tests that could be affected" is built from this measurement.

**Finding 6: input validation runs before the first Session call, with Python `re`.** `run_flow` calls `prepare_inputs(flow, inputs)` before it builds `_RunState` and before `run_phase` (`runner.py`, `run_flow`). `prepare_inputs` (`inputs.py`) checks, in this order, the type, then `len(value) > max_length`, then printable ASCII (0x20 to 0x7E), then `re.fullmatch(spec.regex, value)`. A `FlowInputError` carries the input name and the rule, never the value. The regex dialect is Python `re` (str pattern, no flags); the match is anchored at both ends by `fullmatch`; the validator accepts a pattern of 1 to 200 characters that `re.compile` accepts (`validate._check_inputs`). There is no backtracking guard anywhere in the code. Safety comes from the order of the checks (the length limit runs before the regex, so the subject has at most `max_length` characters) and from the shape of the pattern (Finding 17). The Publisher checks the same rules earlier, before it takes the Limiter slot (`registry.check_inputs`), and publishes the regex as a JSON Schema `pattern` `^(?:<regex>)$` plus `maxLength` when `_ecma_safe` accepts it (`registry._input_property`). Typing quote characters is done with literal `type` steps around the input, as `tk5-logon` does for `LOGON <id> RECONNECT`. A literal must be 1 to 255 printable ASCII characters and may not contain `${` (`validate._type`), so `LISTDS '`, `'` and `' MEMBERS` are valid literals.

**Finding 7: the captures differ from the steering text in two places.** (a) Member names start at column 3, not column 2. Row 7 of `tso-listds-members` is `SF(c8)` at column 0, two blank cells, then `$$$INDEX` from column 3, then `SF(c0)` at column 11; all 136 member rows of the seven pages start at column 3 and are 4 to 8 characters long. (b) The seven pages hold 16 + 5 x 23 + 5 = 136 members, not "about 140". Every other number in the steering section matches the captures. The steering file is not edited here (Open decision 7). The Flows use the measured column.

**Finding 8: no capture holds the password, and the user id in captures is accepted.** All 36 files were searched for the value of `TK5_PASSWORD` in plain, lower-case and upper-case form and as lower-case and upper-case hex pairs with and without blanks (the forms of `tests/connector_support.forms_of_run`): no hit. The same check for `TK5_USERNAME` hits four of the twelve earlier captures (`tso-listcat-output`, `tso-listds-output`, `tso-listds-not-in-catalog`, `tso-status-output`), because the host prints the user id in data set names and in the job line, and none of the six newer captures. The existing capture `tso-password-prompt` already holds the user id the same way. The reviewer has accepted the user id in captures (Decision 22); the password stays out of everything. No capture has a hidden field or a non-blank hidden cell. For each of the 18 captures both file forms agree: the `Ascii()` rows equal `Screen.text_grid` of the `ReadBuffer(Ascii)` form (checked for the six new ones on 2026-11-19, for the twelve older ones earlier).

**Finding 9: the Ask start rule does not depend on the new Flows' own timeouts, but a call that runs past 30 s is cut and may orphan the session.** The registry deadline is `min(GS_CALL_TIMEOUT, run + finally + 30)` (`registry.build_registry`). With `GS_CALL_TIMEOUT=30`, which Ask requires (ask Requirement 16, criterion 4), the deadline is 30 for any Flow, so C = 30 + 10 = 40 and C + 2M = 90 = T holds for all five new Flows. What matters is that no legitimate run needs more than 30 s: otherwise the call timeout fires, `session_clean=false` is logged and the next logon meets `IN USE`. The recovery that exists handled an orphan at the ISPF menu only; Requirement 22 extends it to `READY`, the cleared screen and a ` REENTER -` prompt. Requirement 16 sets timeouts so that `run + finally + 4 s` for opening the session stays within 30 s.

**Finding 10 (corrected): the finally steps run only when the run holds a Current_Screen, and an `expect` that stops on a known screen holds none.** `run_finally` skips the finally steps for the reasons in `_FINALLY_SKIP_REASONS` (`unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`, `session_error`, `input_invalid`, `definition`) and also when `self.current is None` (flow-runtime Requirement 13, criterion 9). `exec_key` sets `current` to None when it sends a key, and `poll` raises `unexpected_screen` without accepting the screen it read. A probe on 2026-11-19 ran a Command-Flow-shaped Flow against a script whose answer to Enter was a known screen that the `expect` did not list: the run stopped with `unexpected_screen` at the `expect` step, every finally step was recorded `skipped`, and no key was sent after the Enter. `calls._session_clean` marks only the codes in `FINALLY_SKIP_REASONS` as `session_clean=false`, so such a stop reports no claim (`None`) while the user id is still logged on. The finally steps do run for a stop in a step that holds a Current_Screen: `extract`, `collect` (a mismatch of the held screen), `loop_limit`, `hidden_output`, `output_type`, `screen_size`, `bad_target`, `secret_target`. A Handle on a signature does nothing when the Current_Screen has another name (`exec_handle`: count 0 skips the body). The consequence for this spec: a screen that the Flow must be able to clean up after (the ` REENTER -` prompt) is listed among the signatures of the `expect` that follows the command, so that the runner accepts it as the Current_Screen, and the next `extract` or `collect` step stops with `unexpected_screen` while holding it. The probe confirmed this shape: `unexpected_screen` at the `extract` step, then the finally steps send PA1, Clear, `LOGOFF`, Enter and the run ends on the logon screen. Without the listing the finally steps are skipped. A stop after the command text was typed and before Enter leaves text in the input field, so a `LOGOFF` typed afterwards is appended to it and the host answers with an error screen; this stays a known limit (Requirement 10, criterion 6). A stop of an `expect` after Enter on any other known but unexpected screen has the same latent gap, which this spec does not change (Open decision 6).

**Finding 11: tool descriptions are the only text a model sees about a tool's outputs.** Ask passes the tool `description` and `inputSchema` to the model and no `outputSchema` (ask Requirement 4, criterion 8). `OutputSpec` has no description member, and `tests/property/test_publisher_schema.py` pins an output schema to exactly `{"type": "integer" | "string"}`. The Flow `description` (at most 500 characters, `validate._check_flow_fields`) therefore names each output and says what it holds. An input description is limited to 200 characters. Output names are chosen to be self-explanatory.

**Finding 12: Ask limits the size of a tool result.** `GS_ASK_MAX_RESULT_CHARS` defaults to 4000, and a longer result becomes a Rejected_Call `result_too_large` (`ask/agent.py`; `facing()` shows the model only `flow` and `outputs`). A rows output is therefore bounded by `max_rows x (length + 2) + 200 <= 4000` characters for every bundled Flow (Requirement 4, criterion 6). The caps below satisfy it.

**Finding 13: the Ask offer rule admits the new Flows when the password is bound.** A Flow is offered when no caller input is secret (`McpToolPort.list_tools` reads `writeOnly`; ask Requirement 1, criterion 10). The new Flows have the inputs `userid` and `password` (both bound per Flow by `GS_BIND_<FLOW>__USERID` and `GS_BIND_<FLOW>__PASSWORD`) and, for two of them, `dsname`, which is not secret. A hostile `dsname` from the model is refused by `check_inputs` as `request_invalid` before the Limiter slot is taken and before any Session call. Data set names, member names and the job line then reach a third-party model when Ask is on; the reviewer accepted this (Decision 21).

**Finding 14: the logon recovery today, and what the new Flows meet.** The bundled logon handles `IN USE` by typing `LOGON <id> RECONNECT`, giving the password at the lower prompt and pressing Enter at the reconnect message and at the `***` pause (`tk5-logon.yaml`, plan indices 7 to 18), then expects the ISPF menu (index 19). Verified by hand on the live host, the session comes back wherever it was left: at the ISPF menu (2026-11-17 and 2026-11-18, through the Flow), and at a ` REENTER -` prompt (2026-11-19, by hand: `LOGON <id> RECONNECT`, password, Enter, the old prompt shows again, PA1, Clear, `LOGOFF`). Not verified: a reconnect that lands at `READY` or at the cleared screen (the code reads it so, and the steering notes the account stays IN USE after a drop, but no capture or run shows it), a second `***` pause after the reconnect, and an orphan inside an ISPF sub-panel. With the logon steps as they are, a landing at `READY`, the cleared screen or a ` REENTER -` prompt makes the `expect ispf-primary-menu` poll stop with `unexpected_screen` and no Current_Screen, the finally steps are skipped (Finding 10), and the reconnected session is dropped again and stays logged on. The command Flows spend most of their time at `READY`, so a call timeout, an abort or a shutdown during a command orphans exactly such a session, and without Requirement 22 the next caller finds the account locked. Requirement 22 adds three Handle steps before the final `expect` of the logon steps that release such a session and stop the call with `unexpected_screen`.

**Finding 15: the ` REENTER -` prompt, from the three new captures.** `tso-listds-reenter` (`LISTDS 'A..B'`): cursor (3,0); five field starts, all unprotected, at (1,0), (1,30), (2,0), (2,10) and (23,79); row 0 `LISTDS 'A..B'` (the echo, 13 characters from column 0), row 1 ` INVALID DATA SET NAME, 'A..B'` (29 characters from column 1), row 2 ` REENTER -` (9 characters from column 1); every other row blank. The last non-blank row is ` REENTER -` and the cursor sits on the row after it at column 0, so `before_cursor` cannot be used (the text is not on the cursor row). No bundled signature matches it today (`UnknownScreenError`). `tso-listds-reenter-after-pa1`: cursor (5,0); nine field starts; rows 0 to 2 as above, row 3 ` |` (1 character from column 1), row 4 ` READY` (5 characters from column 1). The real recognizer reads it as `tso-ready` (its last non-blank row is ` READY`), although row 2 still holds ` REENTER -`. The after-PA1 screen is therefore already recognized, and the new `tso-reenter` signature must not match it (a `last_row` matcher does not, because the last row is ` READY`). The text on row 1 varies (`INVALID DATA SET NAME` or `INVALID KEYWORD`, steering), so the signature may not depend on it. Only the `INVALID DATA SET NAME` form is captured; `INVALID KEYWORD` is steering text only (live check 9).

**Finding 16: `LISTCAT` forms, from the captures.** The plain command `LISTCAT` (capture `tso-listcat-output`, one screen, seven data sets) prints row 0 the echo, row 1 the heading ` IN CATALOG:SYS1.UCAT.TSO`, rows 2 to 8 one data set name per row from column 1, row 9 ` READY`, cursor (10,0). One row holds one name, so a screen boundary can never split an entry of the plain form. The form `LISTCAT LEVEL(SYS2)` (captures `tso-listcat-level`, `-page2`, `-page3`) prints no ` IN CATALOG` heading at all, two rows per entry (` NONVSAM ------- <name>` from column 1, then `      IN-CAT --- <catalog>` from column 6), 22 rows on screen 1 (row 0 the echo, rows 1 to 22 eleven entries, row 23 ` ***` with the cursor at (23,5)), 23 rows on screen 2 (rows 0 to 22, no echo, no heading, row 23 ` ***`), and 5 rows on screen 3 (rows 0 to 4, row 5 ` READY`, cursor (6,0)). Continuation screens therefore start at row 0 with no heading and no echo, and an entry can be split: screen 2 ends with the name row of `SYS2.SUPRTREK.HELP` (row 22) and screen 3 starts with its `IN-CAT` row (row 0). Rows are the unit of `collect`, so the split costs nothing: the joined value keeps the two rows of the entry adjacent and in order (line 45 and line 46 of the 50 lines). What is not known is whether the plain form repeats its heading on a continuation screen, because no account with more than 21 data sets was available and no capture of the plain form has a pause (Open decision 5, live check 5). Flow `tk5-list-datasets` uses the plain form without `LEVEL`, as its caller's prefix is the only intended scope (Decision 20).

**Finding 17: the data set name rule, as a regular expression and as a scanner.** The rule (Requirement 20) is: 1 to 8 characters per qualifier, a qualifier starts with a letter or `$ # @` and continues with letters, digits or `$ # @`, qualifiers are joined by single dots, no leading or trailing dot, at most 44 characters, letters of both cases. A regular expression cannot express the 44-character total together with the per-qualifier limits in a short pattern (the repeats `{0,7}` per qualifier and `{0,21}` for the dotted tail allow up to 22 x 8 + 21 = 197 characters), so the Flow input uses both: `max_length: 44` (checked before the regex) and `regex: '[A-Za-z$#@][A-Za-z0-9$#@]{0,7}(?:\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21}'` (72 characters, below the validator's limit of 200). The qualifier classes never contain the dot, so the pattern is deterministic (no ambiguity between where a qualifier ends and the separator starts) and has no nested unbounded quantifier; 20,000 matches of a 44-character near miss took 0.02 s. `registry._ecma_safe` accepts it, so the published schema has `maxLength: 44` and `pattern: ^(?:...)$`. A probe on 2026-11-19 compared `prepare_inputs` with this input against a hand-written scanner (character loop over explicit code-point sets, no `re`, no `str.isalpha`/`isdigit`/`isalnum`, which accept non-ASCII letters and digits) for 5,000 Hypothesis examples (993 accepted, 4,007 rejected) over valid names, hostile text and mutations of valid names (inserted quote, space, parenthesis, comma, control character, non-ASCII letter, double dot, nine-character qualifier, 45 characters): no disagreement. The 22-qualifier limit follows from the length limit (22 one-character qualifiers and 21 dots are 43 characters; 23 qualifiers need 45).

### Capture inventory (18 command captures, 36 files, all to be promoted)

All 36 files are in `.kiro/specs/more-flows/captures`. Rows and columns are 0-based, row text lengths exclude the field-start cell, and every field on these screens is unprotected (`c8` or `c0`) and not hidden. Row 0 is the echo of the typed command and begins at column 0 inside the field that wraps from `(23,79)`. Every other output line is `SF(c8)` at column 0 followed by text from column 1, except member names, which start at column 3.

| Capture | Screen | Cursor | Non-blank rows (row: first column, length) | Matches today |
|---|---|---|---|---|
| `tso-cleared` | blank screen after Clear at `READY` | (0,0) | none; one field start at (23,79), unprotected | none (new signature `tso-cleared`) |
| `tso-time-output` | `TIME` output | (3,0) | 0: echo; 1: (1, 77) the time line; 2: (1, 5) `READY` | `tso-ready` |
| `tso-listcat-output` | plain `LISTCAT`, 7 data sets | (10,0) | 0: echo; 1: (1, 24) `IN CATALOG:...`; 2 to 8: data set names, (1, 11 to 19); 9: `READY` | `tso-ready` |
| `tso-listcat-level` | `LISTCAT LEVEL(SYS2)`, screen 1 | (23,5) | 0: echo (0, 19); 1 to 22: 11 entries, name rows (1, 19 to 40), `IN-CAT` rows (6, 24); 23: (1, 3) ` ***`; 47 fields | `tso-pause` |
| `tso-listcat-level-page2` | screen 2 | (23,5) | 0 to 22: 11 entries and the name row of a 12th at row 22; 23: ` ***`; 49 fields | `tso-pause` |
| `tso-listcat-level-page3` | screen 3 (last) | (6,0) | 0: (6, 24) the `IN-CAT` row of the split entry; 1 to 4: 2 entries; 5: (1, 5) `READY`; 13 fields | `tso-ready` |
| `tso-listds-output` | `LISTDS` of an existing data set | (7,0) | 0: echo; 1: name; 2: (1, 27) header `--RECFM-LRECL-BLKSIZE-DSORG`; 3: (1, 24) values; 4: `--VOLUMES--`; 5: (3, 6) volume; 6: `READY` | `tso-ready` |
| `tso-listds-not-in-catalog` | `LISTDS` of a missing data set | (4,0) | 0: echo; 1: name; 2: (1, 37) `DATA SET '...' NOT IN CATALOG`; 3: `READY` | `tso-ready` |
| `tso-listds-reenter` | `LISTDS 'A..B'`: rejected name | (3,0) | 0: echo (0, 13); 1: (1, 29) ` INVALID DATA SET NAME, 'A..B'`; 2: (1, 9) ` REENTER -`; 5 fields | none (new signature `tso-reenter`) |
| `tso-listds-reenter-after-pa1` | same screen after PA1 | (5,0) | 0 to 2 as above; 3: (1, 1) ` |`; 4: (1, 5) ` READY`; 9 fields | `tso-ready` |
| `tso-listds-members` | `LISTDS ... MEMBERS`, page 1 | (23,5) | 0 to 6 header rows (row 2 is the same `--RECFM-...` header; row 6 is `--MEMBERS--`); 7 to 22: 16 member names (3, 4 to 8); 23: (1, 3) ` ***` | `tso-pause` |
| `tso-listds-members-page2` to `-page6` | pages 2 to 6 | (23,5) | 0 to 22: 23 member names each (3, 4 to 8), no echo; 23: ` ***` | `tso-pause` |
| `tso-listds-members-page7` | last page | (6,0) | 0 to 4: 5 member names; 5: (1, 5) `READY` | `tso-ready` |
| `tso-status-output` | `STATUS` output | (3,0) | 0: echo; 1: (1, 30) job line; 2: `READY` | `tso-ready` |

SHA-256 of the files as recorded (the promoted files must have exactly these hashes, Requirement 1, criterion 3):

```
1432df6c4713e473f437387f9ac43384f2d3bfb98e39e98ef11c83aa1472bffc  tso-cleared.ascii.txt
cfb52107c1b6ea64ee0142ba74edaa86d4073f487b13420ef2b3af21359d3412  tso-cleared.readbuffer.txt
a43b87b6205b3040b3fbbf5a2285d7e1689a57efb96df94391d3a88f78f647a3  tso-listcat-level-page2.ascii.txt
051bf764fc1d8ea249c0e9775e1fb6a18244693174901be510843b526a4092b3  tso-listcat-level-page2.readbuffer.txt
52751e0efe085b5c976da069b7724b8477689e85dfa2e863e2d87e544c96ceeb  tso-listcat-level-page3.ascii.txt
a3c6b7e84299156d35eaa188b9241baa64b0a43275b238c05cbcb9adf744699d  tso-listcat-level-page3.readbuffer.txt
9f274d737e97cd286d096dcba5682b15c0cd186c370d88167b0b2f1a2533ed42  tso-listcat-level.ascii.txt
826f6b5df8b64a2a55b8f3c6abefc828fdb7c96d7c4e3aa41fad6f2236a01e6a  tso-listcat-level.readbuffer.txt
6668faadbd7f807e3546d794d4789f72a582ee24af652a029e15947a3969b944  tso-listcat-output.ascii.txt
9a17e10d7e14d0a89dd9e3ce47143a45d1a782040c4fa60a1668345810f30b7b  tso-listcat-output.readbuffer.txt
918891c570434137779a5387e93cf071bac75c645e2aeb131f9af1c6427258be  tso-listds-members-page2.ascii.txt
934d691455335653dfd5f6f2157d6df9d3acacbf4b0a145b8e54c322ae04c2c0  tso-listds-members-page2.readbuffer.txt
fb21f523166375280816ec5f0a7144cc81c3add68f4fba0d83c6297b4de12501  tso-listds-members-page3.ascii.txt
c87e9071695abfe8d0a5a529850a3559562427210f22b5e90489e9a07051afeb  tso-listds-members-page3.readbuffer.txt
310dfa9bcbb02ff34f6d64bc1a8d93cd3510a5767998fcc871d6602ed568981f  tso-listds-members-page4.ascii.txt
ca5971ee0f4fbbb68fc53457069885ae7f6fb8111477b6c7974b7152061a63be  tso-listds-members-page4.readbuffer.txt
4f76d58620c78b2db4676828beee40bac5a1cad2b83a1df4e9ad7f21cb0eae00  tso-listds-members-page5.ascii.txt
ee1ce60e93c362779c3139ca4c163211373c3a069e2e52417bd6d790164b19a2  tso-listds-members-page5.readbuffer.txt
3691fca5832ec211e7b945f3e727f246a3e9730d03aaf02929a3e8fa7a6f02d5  tso-listds-members-page6.ascii.txt
cddf94ef67f5e266b5423e87894e4ce9a18d41cd37255090ce185e8bb0daf46a  tso-listds-members-page6.readbuffer.txt
660d6a5777a1d139288c67eccef5cf0040120dbeebb8e88f915c51b94240143a  tso-listds-members-page7.ascii.txt
1d18ad7a7a19687e7942c7d162f9ae4efbca0778901d885028a63001c3120191  tso-listds-members-page7.readbuffer.txt
f3292e57c9229f9b85b04ba7cf4cee457c1a3017f9e20dd2c59d87dc54117baa  tso-listds-members.ascii.txt
ec269c35c2abc07d4b57b564ca73677c431d7259d221e41dc49f567e51fe14b8  tso-listds-members.readbuffer.txt
658856ff06f5881790592c4024d2a1f048fef22b70cedbe0e57c4dd2bfde74d2  tso-listds-not-in-catalog.ascii.txt
22520f3dde77bae04cdc62d2e9956e9f4f14cba3456ca336dbf89059d3e28c32  tso-listds-not-in-catalog.readbuffer.txt
29cd27597a3f9a30f083309d7a435402fa4e265b33e53a034743095e64970207  tso-listds-output.ascii.txt
de56ff7b94591056b87cbf218c35f267b6b31a76fc13fece3317b661d9de228b  tso-listds-output.readbuffer.txt
dc79a5b00183b8824f3826f03bc3955278d4e671864683345ce4b9107793a37f  tso-listds-reenter-after-pa1.ascii.txt
0d88ed4d96bc7c1a50e533bec4326ca7101fdd1470113444fa812cb66a91dc7f  tso-listds-reenter-after-pa1.readbuffer.txt
b4e653ff84882ec2044043e9a781819d8c5dd542bb54d44ec8d48326c84eda31  tso-listds-reenter.ascii.txt
61cddc0eefd13317bd2c5f3cd2b6191e3fac8f29ec09bfe0eef31729845f200e  tso-listds-reenter.readbuffer.txt
70fe29e8d5e04716f975eb795264a2c29d82c1af992ad3f18dc9455964eb86cb  tso-status-output.ascii.txt
68629e1e27226476345a3c1a384050b0e169b2f17325d6615ce7a50c313d0ebe  tso-status-output.readbuffer.txt
6d61df9c056ca1ba17fe27c116c8bf98a38640f02275bef65132412ca5452449  tso-time-output.ascii.txt
60b1d1bcd78894efd52ca9a719e9cf207786c04ec55f7fae15ff68a9ccae32e1  tso-time-output.readbuffer.txt
```

### Candidate Flows and what the runtime can express today

| Candidate | Name | Expressible today? | What is missing |
|---|---|---|---|
| 1. `TIME` | `tk5-time` | Almost. One `extract` of row 1 works (`exec_extract`). A time line wider than 78 characters would wrap to row 2 and shift `READY`; one fixed region cannot follow it. | A rows output makes the wrap harmless (Requirement 11). |
| 2. `LISTCAT` (plain form) | `tk5-list-datasets` | No. Variable number of rows, possible `***` pause. | Rows output, `collect` step. |
| 3. `LISTDS '<name>'` | `tk5-dataset-info` | Partly. Fixed rows work for a found data set, but on a missing data set row 3 is `READY`, so a fixed region would return `READY` as a value. No output can say "found". | Rows output (empty when missing), flag output, the host-faithful name validation (Requirement 20), the REENTER safety net (Requirement 21). |
| 4. `LISTDS '<name>' MEMBERS` | `tk5-library-members` | No. Variable rows over several `***` pages. | Rows output, `collect` step, name validation, REENTER safety net. |
| 5. `STATUS` | `tk5-job-status` | No for the general case: `STATUS` lists every job of the account, so the number of rows varies (the capture shows one). | Rows output, `collect` step. |

### Proposed Flows

All five share the inputs `userid` (non-secret, `[A-Za-z0-9@#$]{1,8}`, bound) and `password` (secret, bound), copied unchanged from `tk5-logon`, so the Publisher binds them with `GS_BIND_<FLOW>__USERID` and `GS_BIND_<FLOW>__PASSWORD`. The Flow timeouts are `step: 10.0`, `run: 20.0`, `finally: 6.0` for every Flow (Requirement 16). Every Flow starts with the Logon_Prefix of Requirement 22 (15 top-level steps, plan indices 0 to 26, ending with `expect ispf-primary-menu`).

| Flow | Command typed | Extra input | Outputs | Pause handling | REENTER listed in the command `expect` |
|---|---|---|---|---|---|
| `tk5-time` | `TIME` | none | `TIME_TEXT` (rows output, `max_rows` 3, region (1, 1, 79)) | none: output is one row; `tso-pause` is listed so that a pause is held and drained by the finally steps | no (no caller value) |
| `tk5-list-datasets` | `LISTCAT` (plain form, no operand) | none | `DATASETS` (rows output, `max_rows` 60, region (2, 1, 44), `next_row` 0) | `collect`, `max_screens` 5 | no (no caller value) |
| `tk5-dataset-info` | `LISTDS '` + `dsname` + `'` | `dsname` (Requirement 8) | `FOUND` (flag output, int, region (2, 1, 27), `equals` `--RECFM-LRECL-BLKSIZE-DSORG`), `DETAILS` (rows output, `max_rows` 20, region (3, 1, 79)) | none: at most about ten rows | yes |
| `tk5-library-members` | `LISTDS '` + `dsname` + `' MEMBERS` | `dsname` | `MEMBERS` (rows output, `max_rows` 200, region (7, 3, 8), `next_row` 0) | `collect`, `max_screens` 10 | yes |
| `tk5-job-status` | `STATUS` | none | `JOBS` (rows output, `max_rows` 40, region (1, 1, 79), `next_row` 0) | `collect`, `max_screens` 3 | no (no caller value) |

Step outlines. Indices continue the depth-first numbering of `model.plan`. The Logon_Prefix is indices 0 to 26: the 12 top-level steps of `tk5-logon` as they are today (plan indices 0 to 18 unchanged, including the `tso-pause` Handle at 17 and 18) followed by the Logon_Cleanup (three Handle steps, indices 19 to 25) and `expect ispf-primary-menu` at 26. Every Flow ends its main steps with the Closing_Tail and has the 13 finally indices after the last main step.

| Step | `tk5-time` | `tk5-list-datasets` | `tk5-dataset-info` | `tk5-library-members` | `tk5-job-status` |
|---|---|---|---|---|---|
| 0 to 26 | Logon_Prefix | Logon_Prefix | Logon_Prefix | Logon_Prefix | Logon_Prefix |
| 27 to 29 | `type X`, `key enter`, `expect tso-ready` | same | same | same | same |
| 30, 31 | `key clear`, `expect tso-cleared` | same | same | same | same |
| command | 32 `type TIME`; 33 `key enter`; 34 `expect tso-ready, tso-pause`; 35 `extract TIME_TEXT` | 32 `type LISTCAT`; 33 `key enter`; 34 `expect tso-ready, tso-pause`; 35 `collect DATASETS` | 32 `type "LISTDS '"`; 33 `type input dsname`; 34 `type "'"`; 35 `key enter`; 36 `expect tso-ready, tso-reenter`; 37 `extract FOUND`; 38 `extract DETAILS` | 32 `type "LISTDS '"`; 33 `type input dsname`; 34 `type "' MEMBERS"`; 35 `key enter`; 36 `expect tso-ready, tso-pause, tso-reenter`; 37 `collect MEMBERS` | 32 `type STATUS`; 33 `key enter`; 34 `expect tso-ready, tso-pause`; 35 `collect JOBS` |
| Closing_Tail | 36 `key clear`; 37 `expect tso-cleared`; 38 `type LOGOFF`; 39 `key enter`; 40 `expect tk5-logon` | 36 to 40 | 39 to 43 | 38 to 42 | 36 to 40 |
| Finally_Block | 41 to 53 | 41 to 53 | 44 to 56 | 43 to 55 | 41 to 53 |

### Proposed signatures and the capture each one is checked against

| Signature | Status | Matchers | Captures that must match exactly this one |
|---|---|---|---|
| `tso-ready` | existing, unchanged | `last_row: ' READY'` | `tso-ready`, `tso-time-output`, `tso-listcat-output`, `tso-listcat-level-page3`, `tso-listds-output`, `tso-listds-not-in-catalog`, `tso-listds-reenter-after-pa1`, `tso-listds-members-page7`, `tso-status-output` |
| `tso-pause` | existing, unchanged | `last_row: ' ***'`, `before_cursor: ' ***'` | `tso-pause-2`, `tso-listcat-level`, `tso-listcat-level-page2`, `tso-listds-members`, `tso-listds-members-page2` to `-page6` |
| `tso-cleared` | new, derived from the capture `tso-cleared` | one `field_layout` with the single unprotected field `(23,79)`, one `cursor_field` `(23,79, hidden false)`, and 24 `region_regex` `^ *$` over the full 80 columns of rows 0 to 23 (26 matchers, limit 50) | `tso-cleared` only |
| `tso-reenter` | new, derived from the captures `tso-listds-reenter` and `-after-pa1` | one `last_row: ' REENTER -'` | `tso-listds-reenter` only (`tso-listds-reenter-after-pa1` ends in ` READY` and stays `tso-ready`) |

Both new signatures were evaluated against all 28 captures with the real recognizer (12 signatures x 28 captures = 336 evaluations): each capture matched exactly one signature, and the typed-over cleared screen matched only `tso-cleared`.

### Library documentation record

Checked 2026-11-19 for this stage; the design stage repeats the checks it needs and records the pages (Conventions).

| Library or tool | Version | Used for | Source of the check |
|---|---|---|---|
| Python | 3.11.9 | everything | `python --version` in this workspace |
| PyYAML | 6.0.3 | `safe_load` and `safe_dump` of the new optional keys (`yamlio.py`) | `importlib.metadata.version`; the new keys use plain strings, integers and one block of nested mappings, no new PyYAML API |
| Hypothesis | 6.170.15 | property tests (Requirements 19 and 20) | `importlib.metadata.version`; strategies `text`, `lists`, `sampled_from`, `builds`, `composite`, `one_of`, `settings(max_examples=...)` are already used in `tests/property/` |
| pytest | 9.1.1 | all tests | `importlib.metadata.version` |
| ws3270 (Windows) | 4.5ga6 (`D:\tools\wc3270\ws3270.exe`, from `--version`) | live checks only; the Connector's `string()`, `clear()` and `pa()` actions | steering `mainframe-host.md`; quoting of an apostrophe inside `String("...")` through the Connector has not been verified live (Not verifiable, item 6) |
| x3270 scripting manual (`String`, `Clear`, `PA` actions) | not fetched | the executor reads the current manual before code that changes how text or a PA key is sent | Conventions |

### Conventions

- IF the work finds a defect in production code outside the files this spec names (Files table), THEN the executor SHALL stop and report it instead of fixing it silently.
- No test, log, message, snippet, fixture or spec text prints or stores a password or another secret (`TK5_PASSWORD`, `GS_API_KEY`, a Bound_Value). The user id may appear in captures, because the host prints it (Decision 22); new tests and spec text do not hard-code the user id literal, they read it from the environment or match it with a pattern, and skip when it is unset.
- DO NOT COMMIT anything. The executor leaves every change in the working tree and the reviewer commits. No requirement or task of this spec asks for a commit, a staged file or a branch.
- No new dependency is added. `dependencies` and the extras of `pyproject.toml` stay unchanged. `package-data` already ships `greenscreen.flow.flows` and `greenscreen.recognizer.signatures` as `*.yaml`.
- The `.kiro/steering` directory is not edited by this spec.
- Before the executor writes code that uses a library API, the executor SHALL check the current documentation of that library and record the page, the version and the date in `design.md` or in the task notes. This applies to PyYAML (`safe_dump` of the new keys), Hypothesis (strategies used), the x3270 scripting manual (`String`, `Clear`, `PA`) and the IBM TSO command reference for `LISTCAT`, `LISTDS`, `STATUS` and `TIME` (operands that the Flows type).
- No test needs the live host. Tests that do are marked as integration tests and skip when the host is unreachable (steering, "Rules for tests"). Unit and property tests use the promoted captures and `ScriptedSession` from `tests/flow_support.py`.
- IF an existing test fails after the change and is not named in "Existing behaviour and tests that could be affected", THEN the executor SHALL stop, report the test and the cause, and SHALL NOT edit the test.
- The final report of the executor gives the test counts before and after, lists every test file added, names every existing test file edited with the assertion changed and why, and lists everything not verified.
- A command that does not exist is answered by the host with ` COMMAND <name> NOT FOUND` and then ` READY` (steering, 2026-11-19 evening), and the session stays at `READY`. No Flow needs special handling for it: every command word is a fixed literal that was run on the host (`TIME`, `LISTCAT`, `LISTDS`, `STATUS`), and a test compares each literal with the echo row of its capture (Requirement 9, criterion 6).

### Not in scope

- Any command other than `TIME`, `LISTCAT`, `LISTDS`, `STATUS`; any command that writes; `LISTCAT LEVEL(...)` and other operands (the `LEVEL` captures are evidence and test fixtures only); a member pattern for `MEMBERS` (the Flow has no member input); running a command from inside ISPF; 5250.
- Changing `tk5-logoff`, any existing signature, the Connector, the Publisher code, Ask, the console or `.env.example`. `tk5-logon` and `tk5-system-info` change only by the three inserted Handle steps of Requirement 22.
- Recovery of an orphan inside an ISPF sub-panel, mid-logon (`IKJ56700A ENTER USERID`) or at the second IN USE state (`IKJ56400A`), which stay unhandled (Open decision 2), and a shared binding for several Flows.
- Continuing the call after a recovery that landed at `READY` (Open decision 8): the recovery releases the account and the call fails.
- Editing `.kiro/steering/mainframe-host.md` (Open decision 7). Editing the other spec documents happens at implementation time, not now (Requirement 23).

### Decisions

1. **Rows are one `str` output with the lines joined by a single line feed (LF).** Accepted. Alternatives: a new list-valued output type; a fixed set of row outputs. The list type would change `validate`, `model`, `registry.build_schemas`, `ask/service.project_result` (which would drop it), the Ask response schema and `test_publisher_schema`, in order to type something a split on LF already gives. A fixed set of row outputs cannot hold 136 members (the validator allows 20 outputs) and bloats every schema. The LF form keeps `string` in OpenAPI and MCP, passes through the Ask projection and `RESULT_SPECS` unchanged, shows readably in the console, and is unambiguous because a screen row can never contain an LF. Size is bounded by `max_rows` and the region length (Finding 12). An empty result is the empty string. A truncated list is not returned: reaching `max_rows` stops the run with `loop_limit` (Decision 4).
2. **A new `collect` step reads rows across pauses.** Accepted. It is the smallest addition that keeps Handle bodies as they are. It reads the rows of the Current_Screen, presses Enter while the screen is a `more` screen, polls with the normal rules, and stops at the final screen. It reuses `loop_limit` for its caps, so `REASON_CODES` stays at 13 and the tests that pin 13 and 22 codes stay as they are.
3. **"Found" is a flag output, read from the screen.** Accepted. A flag output is an `int` output with an `equals` text: its value is 1 when the stripped region text equals `equals`, otherwise 0. Alternatives: two signatures for the two screens (impossible, Finding 2); a Handle that sets a constant (Handle bodies hold only `type` and `key`); two Extract paths with a default output (needs the same signature split). The flag reuses `extract`, the arming rule, the hidden-cell check and the `int` schema. It adds one optional key and one branch in `exec_extract`.
4. **At a cap the run stops with `loop_limit`; it does not return a partial list.** Accepted. "A flow never guesses" and the existing handling of `max_count` point the same way, and no new output (a `truncated` flag) is needed. The finally block drains pauses and logs off.
5. **Terminator detection uses the Prompt_Row.** The rows of a screen are the rows from the start row up to, but not including, the last non-blank row. `tso-ready` and `tso-pause` both anchor on that row with `last_row`, so no terminator text is stored in the output. Blank rows between are skipped.
6. **The data set name input is validated by the Flow input rule before anything is typed** (Decisions 11 to 13 give the rule). The quotes are literal `type` steps.
7. **The new Flows are bundled, and copy the logon steps.** Accepted (no `GS_FLOWS_DIR`). They join `_MANIFEST` in `greenscreen/flow/bundled.py` so the demo works without it. This changes the tests that pin "three Flows" (listed).
8. **Every Flow clears the screen before the command and before `LOGOFF`.** The first Clear follows the steering rule. The second keeps `LOGOFF` away from the bottom of a full output screen and uses the same cleared-screen signature.
9. **The cleared-screen signature is built from the capture `tso-cleared`** (Decision 23).
10. **No output description is added.** The Flow description names the outputs (Finding 11). A new `description` member of `OutputSpec` would change the pinned output schema.

Decisions of 2026-11-19. They win over the earlier open list. The column "Closes" names the earlier open decision (numbers of the previous version of this document) that each one settles.

| # | Decision | Closes | Basis |
|---|---|---|---|
| 11 | Lower case is accepted in a data set name: A-Z and a-z, typed as given. The upper-case-only rule is dropped. | old open 1 | Verified live: the host folds lower case (`LISTDS 'sys2.jcllib'` answered as the upper-case form). |
| 12 | The name must be well formed for the host, not only free of quotes: 1 to 8 characters per qualifier, a qualifier starts with a letter or `$ # @` and continues with letters, digits or `$ # @`, qualifiers joined by single dots, no leading or trailing dot, at most 44 characters. | old open 1 (stricter qualifier rule) | Verified live: a rejected name leaves ` REENTER -` where `LOGOFF` does not work (Finding 15). |
| 13 | The rule is expressed as `max_length: 44` plus the regex of Finding 17, and checked in tests against an independent hand-written scanner. No member pattern: `tk5-library-members` has no member input. | old open 1, old open 5 | Finding 17. |
| 14 | The `tso-reenter` signature is one `last_row: ' REENTER -'` matcher. | none | Finding 15: the cursor is on the next row, the text on row 1 varies, and the after-PA1 screen must stay `tso-ready`. |
| 15 | The REENTER prompt is handled by listing `tso-reenter` in the `expect` after the command in the two Flows that type a caller value, so that the next `extract` or `collect` stops with `unexpected_screen` while holding the screen and the finally steps run. No Handle on `tso-reenter` in the main steps. | none | Finding 10: a Handle there would press PA1 and the Flow would go on to read the post-PA1 screen as an answer; without the listing the finally steps are skipped. |
| 16 | A run that meets the REENTER prompt ends with the existing reason code `unexpected_screen` (HTTP 502). No code is added. `session_clean` is not false for it: the code is not in `FINALLY_SKIP_REASONS`, the finally steps run and the account ends logged off, and the Publisher never reports `session_clean` true, so the log carries no `session_clean` member. | none | `calls._session_clean`, `_FINALLY_SKIPPED_STOPS`. |
| 17 | The Finally_Block leaves a REENTER prompt with `key pa` `n: 1` (Handle on `tso-reenter`, `max_count` 3), then presses Clear at `READY` and types `LOGOFF` at the cleared screen. | none | The hand-verified recovery is PA1, Clear, `LOGOFF`; the same three Handles are used in the Logon_Cleanup. |
| 18 | The logon recovery releases an orphan that lands at `READY`, the cleared screen or a REENTER prompt: it ends the reconnected session and the call stops with `unexpected_screen`. It does not continue the call. | old open 8 | Smallest change that keeps every existing test (Requirement 22); continuing is Open decision 8. |
| 19 | The three Handle steps of the Logon_Cleanup are inserted before the final `expect ispf-primary-menu`, not after it. | none | Keeps plan indices 0 to 18 and the number of reads on the normal path, so the golden call lists and the audit indices of steps 7 to 18 stay as they are (Requirement 22). |
| 20 | `tk5-list-datasets` uses the plain `LISTCAT`. Collected rows are joined in screen order with no reassembly of entries. | old open 4 | Finding 16. |
| 21 | Host data (data set names, member names, the job line) may go to the model provider when Ask is on. | old open 10 | Reviewer's decision, 2026-11-19. |
| 22 | The user id in captures is acceptable (the host prints it, as in `tso-password-prompt` today). The captures are kept byte for byte. The password stays out of every capture, test, log and document. | old open 11 | Reviewer's decision, 2026-11-19. |
| 23 | `tso-cleared` is no longer provisional: the signature is built from the capture of that name, and the former blocker (record a capture before design) is removed. | the blocker of Requirement 2 | The capture exists (Finding 1). |
| 24 | `loop_limit` at a cap with no partial list; the caps are the proposed ones (`TIME_TEXT` 3 rows; `DATASETS` 60 rows and 5 screens; `DETAILS` 20 rows; `MEMBERS` 200 rows and 10 screens; `JOBS` 40 rows and 3 screens); the Flow timeouts are the proposed ones (`step` 10, `run` 20, `finally` 6) and the reviewer measures them live. | old open 2, 3, 7 | Decision 4; Finding 12; Requirement 16. |

### Open decisions

1. **Reason code for the REENTER stop.** Default: `unexpected_screen` (Decision 16). The caller sees the fixed message "The host showed a known screen the flow did not expect.", `expected` (`tso-ready`, or `tso-pause` and `tso-ready`) and the redacted screen summary, which holds the rejected name and the host's message. A dedicated code (for example `host_rejected_input`) would change `REASON_CODES`, `ERROR_CODES`, `MESSAGES`, `HTTP_STATUS` and every test that pins 13 and 22. Not needed while validation keeps the case rare.
2. **Depth of the logon recovery.** The recovery handles a landing at the ISPF menu, at `READY`, at the cleared screen, at a REENTER prompt and at further `***` pauses. It does not handle an orphan inside an ISPF sub-panel, an abandoned logon (`IKJ56700A`), the second IN USE state (`IKJ56400A`), or any landing the signatures do not know. Those stop with `unknown_screen` or `timeout` and `session_clean=false`, as today.
3. **`STATUS` shape for an account with batch jobs or held output.** Only one job line is captured. `JOBS` takes the rows between row 1 and the prompt row (Requirement 15).
4. **PA1 at a `***` pause, and other prompts a command can raise.** Not verified. The Finally_Block drains a pause with Enter, then handles REENTER with PA1.
5. **Plain `LISTCAT` over several screens.** Whether the heading ` IN CATALOG:...` repeats on a continuation screen is not known (Finding 16). `DATASETS` starts at row 2 on the first screen and row 0 on later ones; a repeated heading would appear as a row.
6. **A stop of an `expect` after a key on a known but unexpected screen skips the finally steps** and reports no `session_clean` claim (Finding 10). Fixing it needs a runner change (accept the screen before raising) or a Publisher change; both are outside this spec.
7. **Steering correction.** The steering section says member names start at column 2 and the library has "about 140" members; the captures show column 3 and 136. The reviewer decides whether to edit `.kiro/steering/mainframe-host.md`.
8. **Continue after a recovery that landed at `READY`.** Today the call fails once with `unexpected_screen` and the next call works. Continuing would need Flow-specific steps after the logon and is deferred.
9. **Finally timeout margin.** `finally` 6 s holds a path of four keys (PA1, Clear, `LOGOFF`, Enter) with an estimated 2 to 4 s; nothing is measured. If the live run (Not verifiable, item 8) shows more than 5 s, the fallback is `run` 18 and `finally` 8 (the sum of 26 stays).

## Glossary

- **Flow_Runtime**: The package `greenscreen/flow` (model, validator, YAML reader and writer, runner).
- **Runner**: `run_flow` and `_RunState` in `greenscreen/flow/runner.py`.
- **Validator**: `structural_violations`, `reference_violations` and `check_flow` in `greenscreen/flow/validate.py`.
- **Recognizer**: The package `greenscreen/recognizer`.
- **Publisher**: The package `greenscreen/publisher` (REST, MCP, registry, Ask).
- **Command_Flow**: One of the five Flows of this spec: `tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members`, `tk5-job-status`.
- **Name_Flow**: A Command_Flow that types a caller value: `tk5-dataset-info` and `tk5-library-members`.
- **Logon_Prefix**: The 15 top-level steps (plan indices 0 to 26) at the start of `tk5-logon`, `tk5-system-info` and every Command_Flow: the 12 top-level steps of today's `tk5-logon` with the Logon_Cleanup inserted before the last one.
- **Logon_Cleanup**: Three Handle steps (plan indices 19 to 25): on `tso-reenter` (`max_count` 3) `key pa` `n: 1`; on `tso-ready` (`max_count` 1) `key clear`; on `tso-cleared` (`max_count` 1) `type LOGOFF`, `key enter`.
- **Landing_Screen**: The screen the host shows after a reconnect (after the `tso-reconnect-ok` and `tso-pause` Handles): the ISPF menu, `READY`, the cleared screen or a REENTER prompt.
- **Exit_Fragment**: `type X`, `key enter`, `expect tso-ready`.
- **Closing_Tail**: `key clear`, `expect tso-cleared`, `type LOGOFF`, `key enter`, `expect tk5-logon`.
- **Finally_Block**: The 13 finally indices of Requirement 10, criterion 4: the Handles on `ispf-primary-menu`, `tso-pause`, `tso-reenter`, `tso-ready` and `tso-cleared`, then `expect tk5-logon`.
- **Prompt_Row**: The highest-numbered row of a screen that has a non-blank cell after hidden cells are blanked. On `tso-ready` and `tso-pause` screens it holds ` READY` or ` ***`.
- **Reenter_Prompt**: The screen that ends in ` REENTER -` after the host rejected a command operand; signature `tso-reenter`.
- **Rows_Output**: An `OutputSpec` of type `str` with `max_rows` set. Its value is the text of its rows, each stripped of blanks at both ends, joined by one LF.
- **Flag_Output**: An `OutputSpec` of type `int` with `equals` set. Its value is 1 or 0.
- **Collect_Step**: The new step kind `collect` (Requirements 5 and 6).
- **More_Screen**: A screen whose signature is the `more` member of a Collect_Step.
- **Final_Screen**: A screen whose signature is the `signature` of the Collect_Step's output.
- **Dataset_Name**: The value of the input `dsname`.
- **Dsn_Rule**: The rule of Requirement 20: qualifiers of 1 to 8 characters, each starting with a letter or `$ # @` and continuing with letters, digits or `$ # @`, joined by single dots, no leading or trailing dot, at most 44 characters, both letter cases.
- **Dsn_Pattern**: The regular expression `[A-Za-z$#@][A-Za-z0-9$#@]{0,7}(?:\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21}`, used together with `max_length: 44`.
- **Reference_Scanner**: The hand-written function in the test suite that decides the Dsn_Rule by a character loop over explicit code-point sets, with no regular expression and no Unicode-aware `str` method.
- **Read_Only_Set**: The set of literal texts a Command_Flow may type: `X`, `LOGOFF`, `LOGON `, ` RECONNECT`, `TIME`, `LISTCAT`, `STATUS`, `LISTDS '`, `'` and `' MEMBERS` (Requirement 9).
- **Promoted_Capture**: A capture file moved from `.kiro/specs/more-flows/captures` into `/captures`.
- **Call_Limit**: `GS_CALL_TIMEOUT`, 30 seconds when Ask is on.
- **Open_Allowance**: 4 seconds, the time assumed for opening the session and tearing it down inside the Call_Limit (not verified).
- **Hostile_Name**: A generated string that tries to leave the quoted data set name or to be rejected by the host: quotes, blanks, parentheses, commas, double dots, leading or trailing dots, nine-character qualifiers, 45 or more characters, control characters, non-ASCII text, the empty string.
- **Screen_Script**: A list of screens given to `ScriptedSession` in `tests/flow_support.py`.
- **Fake_Host**: The test double of the Publisher tests (`tests/publisher_support.py`).
- **Ask**, **Ask_Eligible**, **Tool_Worst_Case**, **Call_Log_Record**, **Bound_Value**, **Secret_Input**, **Caller_Input**: as in the ask and publisher specs.

## Requirements

### Requirement 1: Promote the captures into `/captures`

**User Story:** As a maintainer, I want the recorded command screens under `/captures` with their bytes unchanged, so that every fixture and test builds on real host output.

#### Acceptance Criteria

1. THE executor SHALL move the 36 files of `.kiro/specs/more-flows/captures` (18 captures: the 12 earlier command captures, `tso-cleared`, `tso-listds-reenter`, `tso-listds-reenter-after-pa1`, `tso-listcat-level`, `tso-listcat-level-page2`, `tso-listcat-level-page3`) into `/captures` without changing a byte, so that `/captures` holds 28 captures in 56 files, and THE directory `.kiro/specs/more-flows/captures` SHALL hold no capture file afterwards.
2. THE Test_Suite SHALL contain a test that computes the SHA-256 of each of the 36 promoted files and compares it with the hashes listed in this document.
3. THE Test_Suite SHALL contain a test that every promoted `readbuffer` file parses with `ScreenParser` to a 24 by 80 Screen and that the `Ascii()` rows of the matching `ascii` file equal `Screen.text_grid`.
4. THE Test_Suite SHALL contain a test that no promoted file contains the value of `TK5_PASSWORD` in plain, lower-case, upper-case or hex form (the forms of `tests/connector_support.forms_of_run`) and that no promoted Screen has a non-blank hidden cell, and SHALL skip the password part with a reason when `TK5_PASSWORD` is unset. THE test SHALL NOT check for the user id, which the host prints and which is accepted (Decision 22).
5. THE existing capture inventory tests SHALL be updated in place to the 28 names of the table "Capture inventory" plus the 10 existing names, and the counts 28 (readbuffer files) and 56 (all files), and no assertion SHALL be removed or loosened (see "Existing behaviour and tests that could be affected").
6. THE Test_Suite SHALL contain `tests/unit/test_command_capture_facts.py`, which asserts for each of the 18 command captures the cursor, the non-blank rows, the first column and length of each row, the field-start positions of the unprotected fields, and the Prompt_Row, as listed in the table "Capture inventory". It SHALL NOT contain the user id literal.
7. IF the capture directory holds a file whose stem is not in the expected set of 28, THEN the inventory test SHALL fail and name the file.

### Requirement 2: The cleared-screen signature `tso-cleared`

**User Story:** As a Flow author, I want a signature for the blank screen after Clear, so that a Flow can arm its `type` steps after pressing Clear without guessing.

#### Acceptance Criteria

1. THE Recognizer SHALL bundle one new signature `tso-cleared` in `greenscreen/recognizer/signatures/tso-cleared.yaml`, listed in `_MANIFEST` of `greenscreen/recognizer/bundled.py` after `tso-reconnect-ok` and before `tso-reenter`, with exactly these matchers, taken from the capture `tso-cleared`: one `field_layout` with `count: 1` and position (23,79), one `cursor_field` at (23,79) with `hidden: false`, and a `region_regex` `^ *$` of `length: 80` at `col: 0` for each of the rows 0 to 23. THE file SHALL hold no user id, no host and no credential.
2. THE signature SHALL match the capture `tso-cleared` and no other of the 28 captures, and no other bundled signature SHALL match that capture.
3. THE matchers SHALL read only text, geometry and cursor (no hidden cell), so that a screen with text typed into the cleared screen is recognized through the existing `build_comparison` rule. THE Test_Suite SHALL contain a test that a copy of the capture with a command typed at the cursor (`typed_screen`, MDT set), restored through `build_comparison` over the typed field, matches `tso-cleared` only.
4. THE bundled signature count SHALL become 12 (with `tso-reenter`, Requirement 21), and `tests/unit/test_recognizer_bundled.py`, `tests/unit/test_recognizer_capture_matrix.py`, `tests/unit/test_recognizer_capture_inventory.py` and `tests/unit/test_recognizer_recognize.py` SHALL be updated for it.
5. THE matrix test SHALL map every capture to its own signature as in the table "Proposed signatures": `tso-ready` for the nine captures listed, `tso-pause` for the nine listed, `tso-cleared` and `tso-reenter` for one capture each, and the ten existing mappings unchanged, and SHALL evaluate every signature against every capture (28 x 12 = 336 evaluations).
6. THE existing signatures `tso-ready` and `tso-pause` SHALL stay byte for byte as they are.
7. THE test support SHALL be updated so that the signature set can grow: `tests/flow_support.py` `_SIGNATURE_CAPTURE` gains `tso-cleared` mapped to `tso-cleared` and `tso-reenter` mapped to `tso-listds-reenter`, `tests/screen_support.py` `CAPTURE_NAMES` gains the 18 names, and the partial-repaint draw of `tests/property/_flow_strategies.py` and `flow_support.partial_repaint` SHALL treat a signature that has no repaintable cell (`tso-cleared`) as "no partial repaint available" without an error. WHEN these edits are made, THE three property tests `test_flow_determinism.py`, `test_flow_stale_reads.py` and `test_flow_unknown_stops.py` SHALL pass without any edit of their own assertions.

### Requirement 3: Rows_Output in the Flow model, the YAML and the Validator

**User Story:** As a Flow author, I want an output that holds a variable number of rows, so that `LISTCAT` and `MEMBERS` can return all their lines.

#### Acceptance Criteria

1. THE `OutputSpec` SHALL gain three members with defaults, added after the existing six so that every existing positional construction and every existing YAML file keep their meaning: `next_row: int | None = None`, `max_rows: int | None = None`, `equals: str | None = None`.
2. THE YAML writer SHALL emit `next_row`, `max_rows` and `equals` only when they are not `None`, after `length`, in that order, and THE YAML reader SHALL accept them as optional keys (`_OUTPUT` keys remain required for the first six). THE shipped YAML of `tk5-logoff` SHALL stay byte for byte equal to `Flow.to_yaml()`, and so SHALL `tk5-logon` and `tk5-system-info` with the Logon_Cleanup of Requirement 22.
3. WHERE `max_rows` is set, THE Validator SHALL require `type` `str`, `max_rows` an integer from 1 to 500, and `next_row` either absent or an integer from 0 to 23. IF `max_rows` is set with `type` `int`, or `next_row` is set without `max_rows`, THEN THE Validator SHALL report a violation named for the field (`rows_requires_str`, `next_row_requires_rows`, `out_of_range`) in the style of the existing rules.
4. THE Validator SHALL require for a Rows_Output the same `row`, `col` and `length` limits as today (`row` 0 to 23, `col` 0 to 79, `length` 1 to 80, `col + length` at most 80), and SHALL report `region_exceeds_row` as today.
5. THE Validator SHALL accept an `extract` step for a Rows_Output (a single-screen read) and SHALL accept a `collect` step for it (Requirement 5). THE rule `needs_exactly_one_extract` SHALL count a `collect` step of an output as its one read, and SHALL report `needs_exactly_one_read` for a Rows_Output with neither or with both.
6. FOR ALL valid Flows built from the generators of `tests/property/_flow_strategies.py` extended with Rows_Outputs, Flag_Outputs and Collect_Steps, `Flow.from_yaml(flow.to_yaml())` SHALL equal the Flow (Property E, round trip), and THE Test_Suite SHALL contain this test with at least 100 examples.
7. THE Validator SHALL accept every existing bundled Flow unchanged, and THE existing tests of the Validator, the YAML reader and the model SHALL pass without edit.

### Requirement 4: Reading rows from one screen

**User Story:** As a Flow author, I want an extract step to read the rows of the current screen up to the prompt, so that a short command output can be returned in one step.

#### Acceptance Criteria

1. WHEN an `extract` step names a Rows_Output and the Current_Screen has the signature of the output, THE Runner SHALL read the rows from `row` up to, but not including, the Prompt_Row, read each row with `read_region(screen, view, r, col, length)` from `greenscreen/flow/screens.py`, strip blanks at both ends, skip rows that are empty after stripping, and store the texts joined by one LF as the output value.
2. IF a region cell of a row that is read is hidden, THEN THE Runner SHALL stop with `hidden_output` and SHALL store no row of that output, exactly as for a single-row output today. THE Prompt_Row SHALL be found from the hidden-blanked rows of `ScreenView`, never from `Screen.text_grid`.
3. IF the number of non-blank rows read exceeds `max_rows`, THEN THE Runner SHALL stop with `loop_limit` and the detail `output <name>`, and SHALL store no value for the output.
4. IF the screen is smaller than 24 by 80, THEN THE Runner SHALL stop with `screen_size` as today.
5. IF `row` is greater than or equal to the Prompt_Row, THEN THE Runner SHALL store the empty string.
6. THE size of a Rows_Output value SHALL be at most `max_rows x length + (max_rows - 1)` characters. FOR EVERY bundled Flow and every Rows_Output, `max_rows x (length + 2) + 200` SHALL be at most 4000, and THE Test_Suite SHALL assert it (Finding 12).
7. THE new row-reading code SHALL live in `greenscreen/flow/screens.py`, the only module that reads `Screen.cell_grid`, and SHALL NOT read `Screen.text_grid`, `Screen.fields`, `Screen.find_field` or `Field.text` (`tests/unit/test_flow_static.py`).
8. FOR ALL generated screens (random text rows, random Prompt_Row, random hidden fields, random `row`, `col`, `length`, `max_rows`), THE value SHALL satisfy: it has no LF inside a line; `value.split("\n")` equals the list of stripped non-empty region texts of the rows from `row` to the Prompt_Row, in order; no cell of a hidden field occurs in it; no row at or after the Prompt_Row occurs in it; and the run stops with `loop_limit` exactly when that list is longer than `max_rows` (Property A, a model comparison against a reference implementation written in the test).
9. FOR ALL generated screens that put a Probe_Value in a hidden field that overlaps a region, THE Runner SHALL stop with `hidden_output`, and no frame, message, audit field or log record of the run SHALL hold the Probe_Value (the style of `tests/unit/test_flow_runner_fixes_frames.py`) (Property A2).
10. THE existing extraction behaviour of an output without `max_rows` (one row, `strip(" ")`, `int` conversion for type `int`) SHALL be unchanged.

### Requirement 5: The `collect` step in the model, the YAML and the Validator

**User Story:** As a Flow author, I want one step that reads rows, presses Enter at each `***` pause and reads on, so that a long listing is a bounded, auditable loop.

#### Acceptance Criteria

1. THE model SHALL gain `CollectStep(output: str, more: str, max_screens: int)` with `kind` `collect`, and THE `Step` union, `plan`, `Flow.to_yaml` and `Flow.from_yaml` SHALL handle it. THE YAML form SHALL be a mapping with the keys `kind`, `output`, `more`, `max_screens`, all required.
2. THE Validator SHALL require: `output` names a Rows_Output; `more` is a valid Signature_Name different from the output's `signature`; `max_screens` is an integer from 1 to 50; the step is in `steps`, not in `finally` and not in a Handle body; and the preceding Expect step, still armed, lists both the output's `signature` and `more` and MAY list further signatures (`signature_not_in_arming_expect` as for `extract`). THE further signature that the Name_Flow `tk5-library-members` lists is `tso-reenter` (Requirement 21).
3. THE Validator SHALL accept `collect` after an Expect step only, and SHALL treat the Flow as armed after the step, as it does after `extract` (the Current_Screen is the Final_Screen).
4. THE reference check SHALL include `more` among the Signature_Names that must exist (`reference_violations`), and THE Runner SHALL include `more` in the signatures it resolves (`_referenced_names`).
5. THE Validator messages SHALL contain only field names, rule names, step indexes and output names, never a YAML scalar.
6. THE existing tests that enumerate step kinds or reject an unknown kind (`tests/unit/test_flow_yaml.py` `kind: dance`) SHALL pass without edit.

### Requirement 6: Running a `collect` step

**User Story:** As an operator, I want paging to stop at known limits and to leave the session in a state the finally steps can log off from, so that a long listing never leaves the account locked.

#### Acceptance Criteria

1. WHEN a `collect` step runs, THE Runner SHALL require the Current_Screen to have the output's `signature` or `more`. IF it has any other name or there is no Current_Screen, THEN THE Runner SHALL stop with `unexpected_screen`, expected `more` and the output's `signature`, and SHALL leave a held Current_Screen in place so that the finally steps run (Finding 10).
2. THE Runner SHALL read the rows of each screen as in Requirement 4, starting at `row` on the first screen and at `next_row` (or `row` when `next_row` is absent) on every later screen, and SHALL append them in screen order. A continuation screen has no heading and no echo (Finding 16), so `next_row` is 0 for the listings of this spec.
3. WHILE the Current_Screen is a More_Screen, THE Runner SHALL, if the number of screens read so far is less than `max_screens`, press Enter exactly once with the pre-key check of `exec_key`, then poll with the accepted names `more` and the output's `signature`, tolerating nothing else, with the step timeout, and make the screen it accepts the Current_Screen.
4. IF the Current_Screen is a More_Screen and the number of screens read equals `max_screens`, THEN THE Runner SHALL stop with `loop_limit` before it presses Enter, so that no more than `max_screens - 1` Enter keys are sent by one `collect` step.
5. WHEN the Current_Screen is the Final_Screen, THE Runner SHALL read its rows, store the joined value and leave the Final_Screen as the Current_Screen, so that the next `key` step is armed.
6. IF the total number of non-blank rows exceeds `max_rows`, THEN THE Runner SHALL stop with `loop_limit` at the screen where it happens, leaving that screen as the Current_Screen.
7. IF the poll after Enter meets an unknown screen until the step timeout, THEN THE Runner SHALL stop with `unknown_screen`; IF it meets a known screen that is neither accepted name, THEN `unexpected_screen`; IF it meets an ambiguous screen, THEN `ambiguous_screen`; IF a region cell is hidden, THEN `hidden_output`. THE reason codes SHALL be the existing 13, and no code SHALL be added.
8. THE audit SHALL hold one record for the step, `kind` `collect`, `signature` the name of the Final_Screen when the step succeeded, `iteration` `None`, and THE debug log SHALL record the number of screens read as `count`, never a row.
9. THE time budget (`run`) SHALL be checked before every Session call of the step, as for every other step.
10. THE stop reasons `unknown_screen`, `timeout`, `run_timeout`, `ambiguous_screen` and `session_error` SHALL keep skipping the finally steps, and `loop_limit`, `unexpected_screen` (of a held screen), `hidden_output` and `screen_size` SHALL run them, so that `session_clean` is reported exactly as `_session_clean` reports it today.
11. FOR ALL generated page sequences (0 to 12 More_Screens followed by one Final_Screen, random rows per page, random `max_rows`, `max_screens`), WITH a Screen_Script that serves the pages in order after each Enter, THE collected value SHALL equal the join of the per-page rows of a reference model; the number of Enter keys sent SHALL equal the number of More_Screens read; the run SHALL end with `loop_limit` exactly when the sequence needs more than `max_screens` screens or more than `max_rows` rows; and the number of Enter keys SHALL never exceed `max_screens - 1` (Property B, model comparison, at least 100 examples).
12. FOR ALL such sequences with one screen replaced by a screen no signature of the Flow matches, THE run SHALL stop with `unknown_screen` after the timeout, and with a known screen of another name SHALL stop with `unexpected_screen` at once (Property B2).
13. THE Test_Suite SHALL contain a scripted test that replays the seven real member pages of `SYS2.JCLLIB` (`tso-listds-members`, `-page2` to `-page7`) through `tk5-library-members` and asserts 136 member names in screen order, 6 Enter keys at the collect step, and that the first three names are `$$$INDEX`, `$HISTORY`, `ADDALIAS` and the last is `ZAPDSCB`.
14. THE Test_Suite SHALL contain a scripted test that replays the three `LISTCAT LEVEL(SYS2)` captures through a test-only Flow with a `collect` step (first row 1, `next_row` 0, `col` 1, `length` 79, `max_rows` 100, `max_screens` 5, `more` `tso-pause`) and asserts 50 lines, that line 45 is `NONVSAM ------- SYS2.SUPRTREK.HELP` and line 46 is `IN-CAT --- SYS1.MCAT.TK5` (the entry split between screen 2 and screen 3 stays adjacent and in order, so `collect` needs no reassembly rule), and exactly 2 Enter keys at the collect step.

### Requirement 7: Flag_Output

**User Story:** As an API consumer, I want a plain yes or no for "does this data set exist", so that a missing data set is a normal answer and not an error.

#### Acceptance Criteria

1. WHERE `equals` is set, THE Validator SHALL require `type` `int` and an `equals` of 1 to 80 printable ASCII characters that is not longer than `length`, and SHALL reject `equals` on a `str` output (`equals_requires_int`).
2. WHEN an `extract` step names a Flag_Output, THE Runner SHALL read the region with `read_region`, strip blanks at both ends, and store 1 when the text equals `equals` and 0 otherwise, and SHALL NOT apply the digit rule of `int` conversion.
3. IF a region cell is hidden, THEN THE Runner SHALL stop with `hidden_output` as for any output.
4. FOR ALL region texts and all `equals` texts, THE stored value SHALL be 1 exactly when the stripped region text equals `equals`, and SHALL always be 0 or 1 (Property C). THE Test_Suite SHALL contain this test with at least 100 examples.
5. THE output schema of a Flag_Output SHALL be the existing `{"type": "integer"}`, so that OpenAPI, MCP, Ask and the console are unchanged.
6. THE two real screens SHALL give `FOUND` 1 on `tso-listds-output` and 0 on `tso-listds-not-in-catalog` through `tk5-dataset-info`, with `DETAILS` equal to the three lines of the found screen and to the empty string on the missing one.

### Requirement 8: The data set name input

**User Story:** As a security reviewer, I want a caller-supplied data set name to be unable to add TSO operands or end the quoted name, so that the only text a caller can choose is a data set name.

#### Acceptance Criteria

1. THE Flows `tk5-dataset-info` and `tk5-library-members` SHALL declare the input `dsname` as `type: str`, `required: true`, `max_length: 44`, `secret: false`, `regex` equal to the Dsn_Pattern `[A-Za-z$#@][A-Za-z0-9$#@]{0,7}(?:\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21}`, after `userid` and `password`, with a description of at most 200 characters.
2. THE regular expression SHALL be accepted by `registry._ecma_safe`, so that the published JSON Schema carries `pattern` `^(?:<Dsn_Pattern>)$` and `maxLength` 44.
3. THE Runner SHALL validate `dsname` in `prepare_inputs` before the first Session call (Finding 6), and THE Publisher SHALL validate it in `check_inputs` before the Limiter slot is taken. IF the value does not match, THEN THE call SHALL end with `input_invalid` (Flow) or `request_invalid` (Publisher), naming the input and the rule and never the value, and THE Session SHALL receive no call.
4. THE Flows SHALL type the name only as `type text: "LISTDS '"`, `type input: dsname`, `type text: "'"` (or `"' MEMBERS"`), so that the text sent to the host is `LISTDS '<name>'` or `LISTDS '<name>' MEMBERS` and nothing else, at most 61 characters, which fits one row. THE name SHALL be typed as given, in the case the caller used; the host folds lower case (Decision 11).
5. THE Test_Suite SHALL check the Hostile_Name behaviour of this input with the Property D of Requirement 20.
6. FOR ALL values that `prepare_inputs` rejects or accepts, THE published JSON Schema `pattern` and `maxLength` SHALL agree with the runtime verdict on every value that has no LF or CR (the style of `tests/property/test_publisher_schema_agree.py`), because a JSON Schema `$` can match before a trailing LF while the runtime uses `fullmatch` and the printable-ASCII rule.
7. THE `dsname` SHALL NOT be a Secret_Input, SHALL NOT be bound, and SHALL be the only input of a Command_Flow other than the bound `userid` and `password`.
8. THE Flow texts SHALL contain no other caller-controlled text: the command word, the quotes and the `MEMBERS` operand are literals.
9. THE description of the input `dsname` SHALL be, in both Name_Flows: `Data set name, e.g. SYS2.JCLLIB: up to 44 characters, qualifiers of 1-8 characters joined by single dots; each qualifier starts with a letter or $ # @, then letters, digits or $ # @. Any case.` (192 characters).

### Requirement 9: Read-only guarantee

**User Story:** As an owner of the mainframe, I want proof that the new Flows can only read, so that publishing them to a model does not put data at risk.

#### Acceptance Criteria

1. THE Test_Suite SHALL load every bundled Flow and assert that the set of literal `type` texts it contains (in `steps` and `finally`, in Handle bodies too) is a subset of the Read_Only_Set, and that each Command_Flow contains exactly its own command literals: `tk5-time` the text `TIME`, `tk5-list-datasets` the text `LISTCAT`, `tk5-dataset-info` the texts `LISTDS '` and `'`, `tk5-library-members` the texts `LISTDS '` and `' MEMBERS`, `tk5-job-status` the text `STATUS`.
2. THE Test_Suite SHALL assert that every `type` step with an `input` in a Command_Flow names `userid`, `password` or `dsname`, that no `key` step is a PF key, and that the only PA key in any bundled Flow is `key: pa` with `n: 1` inside a Handle on `tso-reenter` (the Logon_Cleanup and the Finally_Block). PA1 sends no data to the host; it ends a pending prompt.
3. THE Test_Suite SHALL assert that the Flow YAML files contain no text outside the Read_Only_Set in a `text:` value, using the existing `tests/unit/test_flow_bundled.py::test_no_literal_credentials_or_placeholders` pattern, in a new test file, and no credential key or value (`tests/unit/test_flow_static.py` already scans every shipped YAML).
4. THE Test_Suite SHALL assert, for each Command_Flow run against a Screen_Script of its real captures, that the sequence of Session calls is exactly: the logon calls, the `X`, the Clear, the command text, Enter, the paging Enters, Clear, `LOGOFF` and Enter, and that the typed strings are exactly the literals and the validated name.
5. THE Flows SHALL start no command other than the listed ones, and a future change that adds a literal outside the Read_Only_Set SHALL fail criterion 1.
6. THE Test_Suite SHALL assert, for each Command_Flow, that its command literals typed in order (`TIME`, `LISTCAT`, `LISTDS '` + name + `'`, `LISTDS '` + name + `' MEMBERS`, `STATUS`) reproduce the echo row (row 0) of the capture that its Screen_Script ends in, for the names of the captures, so that a misspelled command word is caught without the host. A misspelled word would otherwise be answered by the host with ` COMMAND <name> NOT FOUND` and ` READY` and returned as a row.

### Requirement 10: The shared logon, exit, closing and finally steps

**User Story:** As a maintainer, I want the five Flows to share the logon, the exit from ISPF, the logoff and the finally steps exactly, so that a fix to one place cannot leave a Flow behind.

#### Acceptance Criteria

1. THE `steps` of every Command_Flow SHALL begin with the steps of `tk5-logon` (the Logon_Prefix of Requirement 22, copied, as `tk5-system-info` does), followed by the Exit_Fragment, then `key clear`, `expect tso-cleared`, then the command steps of the table "Step outlines", and SHALL end with the Closing_Tail.
2. THE `inputs` of every Command_Flow SHALL begin with the two inputs of `tk5-logon`, equal to them, followed by the Flow's own input.
3. THE Test_Suite SHALL contain a new file `tests/unit/test_flow_command_sync.py` that asserts criteria 1, 2 and 4 for every Command_Flow, and that the first 15 top-level steps of every Command_Flow equal `tk5-logon.steps`, and SHALL leave `tests/unit/test_flow_sync.py` unedited (it keeps asserting the three existing Flows).
4. THE `finally` of every Command_Flow SHALL be, in this order and with `max_count` and `settle` as shown: a Handle on `ispf-primary-menu` (`max_count` 1, `settle` 0.0) with `type X`, `key enter`; a Handle on `tso-pause` (`max_count` 20) with `key enter`; a Handle on `tso-reenter` (`max_count` 3) with `key: pa`, `n: 1`; a Handle on `tso-ready` (`max_count` 1) with `key clear`; a Handle on `tso-cleared` (`max_count` 1) with `type LOGOFF`, `key enter`; `expect tk5-logon`. THE `finally` steps SHALL be equal in all five Flows and take 13 plan indices.
5. THE Test_Suite SHALL run each Command_Flow against Screen_Scripts that stop it, with a held Current_Screen, at each of: the ISPF menu, the `READY` after X, the cleared screen, a `***` pause in the middle of a listing, the output screen after the command, and the cleared screen before `LOGOFF`, with a failure reason of `unexpected_screen` (a held screen that the next step does not accept), `loop_limit` or `hidden_output` injected, and SHALL assert that the finally steps end on `tk5-logon` with the Session calls that log off (from `READY`: Clear, `LOGOFF`, Enter; from the cleared screen: `LOGOFF`, Enter; from a pause: Enter first).
6. THE Test_Suite SHALL document, by a test that expects the failure, that a stop after the command text was typed and before Enter leaves the finally steps unable to reach `tk5-logon` (Finding 10), so that the limit is visible and a later improvement changes the test deliberately.
7. WHEN a Command_Flow succeeds, THE Finally_Block SHALL send no key: its five Handles run zero iterations and only the final `expect tk5-logon` reads the screen.
8. THE Runner's skip reasons (`_FINALLY_SKIP_REASONS`) and the Publisher's `session_clean` rule SHALL stay unchanged.

### Requirement 11: The Flow `tk5-time`

**User Story:** As a caller, I want the host's current time, so that I can show it or compare it with the wall clock.

#### Acceptance Criteria

1. THE Flow `tk5-time` SHALL follow the outline of the column `tk5-time` in "Step outlines", with the output `TIME_TEXT` (type `str`, signature `tso-ready`, `row` 1, `col` 1, `length` 79, `max_rows` 3) read by `extract`, and with `tso-pause` listed after `tso-ready` in the `expect` that follows Enter (step 34), so that a pause stops the run at the `extract` step with the screen held and the finally steps drain it.
2. WHEN the Screen_Script is the real capture sequence (`tso-ready`, cleared screen, `tso-time-output`), THE Flow SHALL return `TIME_TEXT` equal to the stripped text of row 1 of `tso-time-output`, which starts with `TIME-` and ends with the year.
3. THE description SHALL be: `Read the current date and time of the mainframe by running the TSO TIME command. TIME_TEXT holds the host's own line: time of day, CPU time, service units, session time and date. The host clock can differ from real time. Read-only; logs on and off with the bound account.`
4. IF a `***` pause appears after the command, THEN THE Flow SHALL stop with `unexpected_screen` at the `extract` step, and the finally steps SHALL press Enter at the pause and log off.

### Requirement 12: The Flow `tk5-list-datasets`

**User Story:** As a caller, I want the names of the account's catalogued data sets.

#### Acceptance Criteria

1. THE Flow `tk5-list-datasets` SHALL follow the outline of its column, typing `LISTCAT` without operands (the plain form, Decision 20), with the output `DATASETS` (type `str`, signature `tso-ready`, `row` 2, `col` 1, `length` 44, `next_row` 0, `max_rows` 60) read by `collect` with `more: tso-pause` and `max_screens: 5`.
2. WHEN the Screen_Script is `tso-listcat-output` alone, THE Flow SHALL return `DATASETS` with seven names, in screen order, none empty, each at most 44 characters, and no `IN CATALOG` line.
3. THE description SHALL be: `List the data sets in the account's own catalog by running the TSO LISTCAT command. DATASETS holds one data set name per line; an empty string means none were listed. Only entries under the account's own prefix are shown. Read-only; logs on and off with the bound account.`
4. THE first screen of the plain form has the heading ` IN CATALOG:...` on row 1 and the names from row 2; a continuation screen, as far as the `LEVEL` captures show, starts at row 0 with no heading (Finding 16). THE Test_Suite SHALL test the paging with the real member pages (Requirement 6, criterion 13), with the three `LEVEL` captures (criterion 14), and with a synthetic two-screen plain `LISTCAT` built from `make_screen` (screen 1: echo, heading, names from row 2, ` ***` last; screen 2: names from row 0, ` READY` last) that returns the names of both screens in order and no heading. WHERE a continuation screen of the real plain form repeats the heading, THE heading would be returned as a row; THE live check of Not verifiable item 5 SHALL decide (Open decision 5).
5. THE one-row-per-name form means a name cannot be split across two screens; THE Test_Suite SHALL assert that every row of `tso-listcat-output` from row 2 up to the Prompt_Row holds exactly one blank-free token.

### Requirement 13: The Flow `tk5-dataset-info`

**User Story:** As a caller, I want the attributes of one data set, and a clear "not found" when it does not exist.

#### Acceptance Criteria

1. THE Flow `tk5-dataset-info` SHALL follow the outline of its column, with the outputs, in this order, `FOUND` (type `int`, signature `tso-ready`, `row` 2, `col` 1, `length` 27, `equals` `--RECFM-LRECL-BLKSIZE-DSORG`) and `DETAILS` (type `str`, signature `tso-ready`, `row` 3, `col` 1, `length` 79, `max_rows` 20), both read by `extract`, with the `expect` after Enter listing `tso-ready` and `tso-reenter` (Requirement 21).
2. WHEN the Screen_Script ends in `tso-listds-output`, THE Flow SHALL return `FOUND` 1 and `DETAILS` equal to the three lines `FB    80    27920   PO`, `--VOLUMES--`, `TSO001` joined by LF.
3. WHEN the Screen_Script ends in `tso-listds-not-in-catalog`, THE Flow SHALL end with a success result `FOUND` 0 and `DETAILS` equal to the empty string, and SHALL NOT stop with an error.
4. THE description SHALL be: `Look up one data set by name (TSO LISTDS). FOUND is 1 when the data set is catalogued and 0 when the host says it is not in the catalog; 0 is a normal answer, not an error. DETAILS then holds, on separate lines, record format, record length, block size and organisation, the text --VOLUMES--, and the volume serial numbers. Read-only.` (at most 500 characters).
5. THE input description of `dsname` SHALL be the text of Requirement 8, criterion 9.
6. A name that the Dsn_Rule rejects SHALL never reach the host (Requirement 20). A name that the Dsn_Rule accepts and the host still rejects SHALL end the run as Requirement 21 says, and SHALL NOT be reported as `FOUND` 0.

### Requirement 14: The Flow `tk5-library-members`

**User Story:** As a caller, I want the member names of a library.

#### Acceptance Criteria

1. THE Flow `tk5-library-members` SHALL follow the outline of its column, with the output `MEMBERS` (type `str`, signature `tso-ready`, `row` 7, `col` 3, `length` 8, `next_row` 0, `max_rows` 200) read by `collect` with `more: tso-pause` and `max_screens: 10`, with the `expect` after Enter listing `tso-ready`, `tso-pause` and `tso-reenter` (Requirement 21).
2. WHEN the Screen_Script is the seven real member captures, THE Flow SHALL return 136 names (Requirement 6, criterion 13).
3. WHEN the data set has no members (the shape of the steering note: `--MEMBERS--` followed directly by `READY`), THE Flow SHALL return the empty string. WHEN the data set does not exist (the shape of `tso-listds-not-in-catalog`), THE Flow SHALL also return the empty string, because the first screen is a `tso-ready` screen whose Prompt_Row is above row 7. THE description SHALL say so and point to `tk5-dataset-info`.
4. THE description SHALL be: `List the member names of a partitioned data set (library) by name (TSO LISTDS with MEMBERS). MEMBERS holds one member name per line, in the host's order, up to 200; a longer list stops the call with an error. An empty MEMBERS means the library has no members or does not exist; call tk5-dataset-info to tell the two apart. Read-only.`
5. THE input description of `dsname` SHALL be the text of Requirement 8, criterion 9.
6. IF the library has more than 200 members or needs more than 10 screens, THEN THE Flow SHALL stop with `loop_limit` at the `collect` step, and the finally steps SHALL drain the remaining pauses (at most 20) and log off.

### Requirement 15: The Flow `tk5-job-status`

**User Story:** As a caller, I want to know which jobs the account has and their state.

#### Acceptance Criteria

1. THE Flow `tk5-job-status` SHALL follow the outline of its column, with the output `JOBS` (type `str`, signature `tso-ready`, `row` 1, `col` 1, `length` 79, `next_row` 0, `max_rows` 40) read by `collect` with `more: tso-pause` and `max_screens: 3`.
2. WHEN the Screen_Script is `tso-status-output`, THE Flow SHALL return `JOBS` equal to the one stripped line of row 1, which starts with `JOB ` and ends with `EXECUTING`.
3. THE description SHALL be: `List the jobs of the mainframe account by running the TSO STATUS command. JOBS holds one line per job with job name, job id and state; the account's own TSO session appears as EXECUTING. Read-only; logs on and off with the bound account.`
4. THE `STATUS` output beyond one job (batch jobs, held output) and its paging are not captured (Open decision 3); THE Test_Suite SHALL use synthetic screens for them, and Not verifiable item 7 SHALL check the live shape.

### Requirement 16: Timeouts and the Ask limit

**User Story:** As an operator running Ask with `GS_CALL_TIMEOUT=30`, I want every new Flow to finish by itself inside the call limit, so that the call timeout never cuts a session in half.

#### Acceptance Criteria

1. THE Flow `timeouts` of every Command_Flow SHALL be `step` 10.0, `run` 20.0, `finally` 6.0, so that `run + finally` is 26 seconds and, with the Open_Allowance of 4 seconds, 30 seconds. THE values are the proposed ones (Decision 24); the reviewer measures them live (Not verifiable, item 8).
2. THE Test_Suite SHALL assert for every bundled Command_Flow that `run + finally + 4.0 <= 30.0`.
3. THE registry deadline of each Command_Flow SHALL be 30.0 with `GS_CALL_TIMEOUT=30` (`min(30, 20 + 6 + 30)`), the Tool_Worst_Case 40.0, and `C + 2M` 90, equal to `GS_ASK_TIMEOUT_SECONDS` 90 with `GS_ASK_MODEL_TIMEOUT_SECONDS` 25, so that all five are Ask_Eligible. THE Test_Suite SHALL assert this through `build_registry` and the Ask planning function of `ask/service.py` (`plan_ask`), with the existing arithmetic and no change to `calls.py` or `ask/`.
4. THE worst-case durations SHALL be as in the table below. "Legitimate worst" is the longest run that is not a stop: recovery logon at the ISPF menu 9.7 s (measured, steering "Verified 2026-11-18") plus the command and closing steps (estimate 2 s) plus paging (estimate 0.5 s per screen, not measured). "Orphan released" is a call that meets an orphan at `READY`, at the cleared screen or at a REENTER prompt: the reconnect part of the measured recovery (about 7 s of the 9.7 s, estimate) plus the Logon_Cleanup (up to four keys: PA1, Clear, `LOGOFF`, Enter, each about 0.5 s, estimate); the call ends with `unexpected_screen`. "Stop worst" is a stop that runs the finally steps: `run` 20 + `finally` 6.

   | Flow | Normal run (estimate) | Legitimate worst | Orphan released (estimate) | Stop worst | Fits 30 s call limit? |
   |---|---|---|---|---|---|
   | `tk5-time` | 7 s | 12 s | 9 to 11 s | 26 s | yes |
   | `tk5-list-datasets` | 7 s | 12 s | 9 to 11 s | 26 s | yes |
   | `tk5-dataset-info` | 7 s | 12 s | 9 to 11 s | 26 s | yes |
   | `tk5-library-members` (136 members, 7 screens) | 10 s | 17 s (10 screens: 18 s) | 9 to 11 s | 26 s | yes |
   | `tk5-job-status` | 7 s | 12 s | 9 to 11 s | 26 s | yes |

   The Logon_Cleanup adds no Session call and no read on the normal path (Requirement 22, criterion 3), so the normal and legitimate figures do not change. The finally steps of a stop at `READY` now press Clear before `LOGOFF`, and from a REENTER prompt they send PA1 first; the longest finally path is four keys (an estimated 2 to 4 s against the `finally` budget of 6 s, Open decision 9). The normal and paging figures are estimates from the verified logon-to-logoff time of "under 6 seconds" and are listed in Not verifiable (item 8) for a live measurement. A stop with `run_timeout`, `timeout` or `unknown_screen` skips the finally steps and logs `session_clean=false` as today.
5. THE start rule of Ask (a tool call needs Remaining of at least C + M = 65 s) SHALL allow about three tool calls of 10 to 17 s each in one question of 90 s; this is a statement, not a requirement on code.
6. THE Test_Suite SHALL assert that each Command_Flow's `step` timeout does not exceed `run`.

### Requirement 17: Publication, descriptions and Ask

**User Story:** As a language model choosing among tools, I want each tool's name and description to say what it reads and what it returns, so that I pick the right one.

#### Acceptance Criteria

1. THE five Flows SHALL be added to `_MANIFEST` of `greenscreen/flow/bundled.py` after `tk5-system-info`, in the order `tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members`, `tk5-job-status`, and THE five YAML files SHALL be in `greenscreen/flow/flows/`, written by `Flow.to_yaml()` so that the shipped text equals the emitted text.
2. THE Flow description SHALL be the text proposed in Requirements 11 to 15, each of at most 500 characters and each mentioning every output name, and THE Publisher SHALL use it unchanged as the OpenAPI summary and the MCP tool description (`registry.build_registry`: `summary=flow.description`).
3. THE output schema of every Command_Flow SHALL be the existing generated object with string and integer members only (no new schema type) and `additionalProperties: false`.
4. WHEN Ask is on and the password of a Command_Flow is bound, THE Flow SHALL be offered to the model, because its only caller input, `dsname`, is not secret; WHEN the password is not bound, THE Flow SHALL not be offered (ask Requirement 1, criterion 10). THE `GS_ASK_FLOWS` allow-list SHALL accept the five names.
5. THE operator documentation SHALL name the bindings `GS_BIND_<FLOW>__USERID` and `GS_BIND_<FLOW>__PASSWORD` for each Flow (names only), and SHALL tell the demo to extend `GS_PUBLISH_FLOWS`; THE `.env.example` file SHALL NOT be edited by this spec.
6. THE console SHALL show the five Flows and their outputs through its existing code with no change; the page shows an output with an LF as the browser renders it (blanks), and the REST and MCP bodies carry the LF.
7. THE Test_Suite SHALL assert, for each Command_Flow, that its description names every output, is at most 500 characters, and that every input description is at most 200 characters.

### Requirement 18: Existing behaviour does not change

**User Story:** As the owner of the existing Flows and their tests, I want them to behave as before, so that the new Flows add to the product and never move it.

#### Acceptance Criteria

1. THE Flow `tk5-logoff` SHALL stay as it is. THE Flows `tk5-logon` and `tk5-system-info` SHALL change only by the three Handle steps of the Logon_Cleanup (Requirement 22): plan indices 0 to 18 and their audit records, and every normal-path Session call, stay as they are, the later step indices of `tk5-system-info` move up by 7, and `tests/unit/test_flow_sync.py`, `tests/unit/test_flow_logon_recovery.py`, `tests/unit/test_flow_logon_script.py`, `tests/unit/test_flow_system_info_script.py` and `tests/unit/test_flow_bundled.py` SHALL pass without edit (measured on a scratch copy, Finding 5).
2. THE secrecy rules of the steering section "What must never be logged" SHALL hold for the new code: no response data line, Screen, input value or row text in a log record, exception message, audit field or frame local that leaves `run_flow`; `tests/property/test_flow_secret_leak.py` and `tests/property/test_publisher_no_leak_*.py` SHALL pass without edit.
3. THE `REASON_CODES` (13), `ERROR_CODES` (22) and the Publisher and Ask contracts SHALL stay as they are.
4. THE Connector, the Publisher, Ask, the console and `.env.example` SHALL NOT be changed. THE Flow_Runtime, the Recognizer data, the Flow YAML files, the captures, the test support and the tests are the only code changes (Files table), and the spec documents named in Requirement 23 are the only document changes besides this spec.
5. THE steering file SHALL NOT be edited.
6. THE hostile-input and no-leak property tests of the Publisher SHALL pass with the eight bundled Flows, and IF one fails for a reason outside the named tests, THEN THE executor SHALL stop and report it (Conventions).

### Requirement 19: Tests

**User Story:** As a reviewer, I want every rule proven without the live host, and the rules that need the host listed.

#### Acceptance Criteria

1. THE Test_Suite SHALL contain these new files: `tests/unit/test_command_capture_facts.py`, `tests/unit/test_command_capture_files.py` (hashes, forms, secrecy), `tests/unit/test_flow_rows_output.py`, `tests/unit/test_flow_collect.py`, `tests/unit/test_flow_flag_output.py`, `tests/unit/test_flow_command_flows.py` (one scripted run per Command_Flow with the real captures), `tests/unit/test_flow_command_sync.py`, `tests/unit/test_flow_readonly.py`, `tests/unit/test_flow_command_timing.py`, `tests/unit/test_flow_reenter.py` (Requirement 21), `tests/unit/test_flow_logon_cleanup.py` (Requirement 22), `tests/unit/test_flow_dataset_name.py` (boundary examples of Requirement 20), and the property files `tests/property/test_flow_rows_extraction.py` (Properties A, A2, E), `tests/property/test_flow_collect_model.py` (Properties B, B2), `tests/property/test_flow_flag_output.py` (Property C), `tests/property/test_flow_dataset_name.py` (Property D), `tests/property/test_flow_logon_landing.py` (Property F), `tests/property/test_flow_reenter_outcome.py` (Property G), plus `tests/integration/test_flow_live_commands.py`, `tests/integration/test_flow_live_reenter.py` and `tests/integration/test_flow_live_cleanup.py`, each marked as an integration test.
2. EVERY property test SHALL use Hypothesis with at least 100 examples (200 for Properties D and G) and SHALL carry a comment `Feature: more-flows, Property <letter>: <statement>`.
3. THE Test_Suite SHALL contain the capture-to-signature matrix of Requirement 2, criterion 5, in the existing matrix file.
4. THE Test_Suite SHALL contain a scripted run of each Command_Flow with the real captures and the logon captures, asserting the outputs, the audit kinds (including `collect`), that the Finally_Block sends no key on success (Requirement 10, criterion 7), and that the Session received no call after `tk5-logon` on the closing screen.
5. THE live integration tests SHALL run each Command_Flow through the Connector against the host, skip when the host is unreachable or `TK5_USERNAME` or `TK5_PASSWORD` is unset, log the account off on every path (a Cleanup_Helper in the style of `tests/integration/test_flow_live_recovery.py`), and never print a credential.
6. THE test counts before and after SHALL be in the executor's report.

### Requirement 20: A data set name that the host accepts

**User Story:** As an operator, I want a caller-supplied data set name checked against the host's own naming rule before anything is typed, so that a name the host rejects can never leave the session at a prompt where `LOGOFF` does not work.

#### Acceptance Criteria

1. THE Dsn_Rule SHALL be: the name has 1 to 44 characters; it is one or more qualifiers joined by single dots, with no leading dot, no trailing dot and no two dots in a row; each qualifier has 1 to 8 characters; the first character of a qualifier is a letter or one of `$`, `#`, `@`; every other character of a qualifier is a letter, a digit or one of `$`, `#`, `@`; a letter is `A` to `Z` or `a` to `z` and nothing else (no accented, full-width or other Unicode letter or digit).
2. THE Flow input `dsname` of `tk5-dataset-info` and `tk5-library-members` SHALL express the Dsn_Rule as `max_length: 44` and the Dsn_Pattern together, because the pattern alone cannot state the 44-character total (it admits up to 197 characters); the length is checked before the pattern in `prepare_inputs`, so the pattern only ever sees at most 44 characters.
3. THE runtime SHALL use Python `re` with `re.fullmatch` (anchored at both ends) and no flags, and SHALL add no backtracking guard; THE Dsn_Pattern SHALL have bounded quantifiers only, character classes that exclude the separator, and a length of at most 200 characters, so that no input of at most 44 characters can make the match slow.
4. THE rule SHALL be enforced in `prepare_inputs` before any Session call, in `run_flow` and, through `check_inputs`, in the Publisher before the Limiter slot is taken; a value that breaks it SHALL give `input_invalid` or `request_invalid` naming the input and the rule, and the `ScriptedSession` call log SHALL be empty.
5. THE Test_Suite SHALL contain a Reference_Scanner in `tests/property/test_flow_dataset_name.py`: a function that decides the Dsn_Rule by a loop over the characters with explicit code-point sets, and that uses no `re`, no `str.isalpha`, `str.isdigit` or `str.isalnum`, and no copy of the Dsn_Pattern.
6. FOR ALL Hostile_Names and valid names (valid names built from 1 to 23 qualifiers of 1 to 8 allowed characters; mutations of them that insert or replace one character from quote, double quote, blank, tab, parenthesis, comma, asterisk, percent sign, hyphen, underscore, slash, backslash, control character including LF, CR and NUL, DEL, `é`, full-width digit, right-to-left mark; names with `..`, a leading dot, a trailing dot, a nine-character qualifier, 45 characters; the empty string; and lower-case and mixed-case names), the verdict of `prepare_inputs` on the shipped `dsname` input of each of the two Name_Flows SHALL equal the verdict of the Reference_Scanner, and every accepted value SHALL be typed as exactly the literal, the value and the literal (Property D, at least 200 examples; the probe of 2026-11-19 agreed on 5,000).
7. THE Test_Suite SHALL contain, in `tests/unit/test_flow_dataset_name.py`, these boundary examples with the expected verdict: accepted `SYS2.JCLLIB`, `sys2.jcllib`, `$A.#B.@C`, a single 8-character name, 22 one-character qualifiers (43 characters), a 44-character name made of 22 qualifiers; rejected `A..B`, `1ABC`, `.A`, `A.`, `A-B`, `A_B`, a 9-character qualifier, 23 one-character qualifiers (45 characters), a 45-character name with valid qualifiers, `A B`, `A'B`, `A(B)`, `A,B` and the empty string.
8. THE published JSON Schema `pattern` and `maxLength` SHALL agree with the runtime verdict for every value without LF or CR (Requirement 8, criterion 6).
9. THE Flow `tk5-library-members` takes no member name, so no member pattern is needed; THE Test_Suite SHALL assert that the typed text of `tk5-library-members` is exactly `LISTDS '`, the validated name and `' MEMBERS`.

### Requirement 21: Leaving a REENTER prompt, and a defined outcome

**User Story:** As an operator, I want a name that passed validation but that the host still rejects to end the call cleanly with the account logged off, so that no caller value can lock the account.

#### Acceptance Criteria

1. THE Recognizer SHALL bundle one new signature `tso-reenter` in `greenscreen/recognizer/signatures/tso-reenter.yaml`, listed in `_MANIFEST` after `tso-cleared`, with exactly one matcher, `last_row` with `text: ' REENTER -'`. THE signature SHALL match the capture `tso-listds-reenter` and no other of the 28 captures, and SHALL NOT match `tso-listds-reenter-after-pa1`, which stays `tso-ready`, and no other signature SHALL match `tso-listds-reenter`.
2. THE `expect` that follows Enter after the command in `tk5-dataset-info` and in `tk5-library-members` SHALL list `tso-reenter` among its signatures (outlines: step 36 of each), so that the Runner accepts the REENTER screen as the Current_Screen and the next `extract` or `collect` step stops with `unexpected_screen` while holding it. THE Flows SHALL NOT contain a Handle on `tso-reenter` in their main steps.
3. WHEN the host answers the command with the REENTER prompt, THE Runner SHALL stop at the first `extract` step (`tk5-dataset-info`, step 37) or at the `collect` step (`tk5-library-members`, step 37) with `unexpected_screen`, `kind` `extract` or `collect`, and `expected` `tso-ready` or `tso-pause` and `tso-ready`, and THE finally steps SHALL run in this order: PA1 (Handle on `tso-reenter`), Clear (Handle on `tso-ready`), `LOGOFF` and Enter (Handle on `tso-cleared`), and `expect tk5-logon`.
4. THE Session calls after the Enter that sent the command SHALL be exactly `pa 1`, `clear`, `string LOGOFF`, `enter`, and THE final screen SHALL be recognized as `tk5-logon`.
5. THE outcome to the caller SHALL be the existing reason code `unexpected_screen`: HTTP 502, the fixed message "The host showed a known screen the flow did not expect.", and the members `step_index`, `kind`, `expected`, `summary` and `audit`. THE Call_Log_Record SHALL NOT carry `session_clean`, because `unexpected_screen` is not in `FINALLY_SKIP_REASONS`, and the account is logged off, so no claim is wrong. THE code table SHALL NOT change (Decision 16, Open decision 1). THE `summary` holds the rejected name and the host message, which the caller supplied or the host printed; it holds no hidden cell.
6. THE Test_Suite SHALL contain tests in `tests/unit/test_flow_reenter.py` that run both Name_Flows with a scripted Fake session that accepts a name the validation accepts (for example `SYS2.NOSUCH`) and answers the command with the capture `tso-listds-reenter`, then `tso-listds-reenter-after-pa1` after PA1, the capture `tso-cleared` after Clear, and the logon capture after `LOGOFF` and Enter, and SHALL assert the reason, `step_index`, `kind`, `expected`, the call list of criterion 4, that every finally audit record is `ok`, that the account ends logged off (final screen `tk5-logon`), and that no call after the command sends text other than `LOGOFF`.
7. THE Test_Suite SHALL contain a test through the Publisher call path (`CallService` with the Fake_Host of `tests/publisher_support.py`) that the same script yields code `unexpected_screen`, HTTP 502 and a log record without `session_clean`.
8. THE Test_Suite SHALL contain a test that a name the validation rejects never reaches the host: `ScriptedSession.calls` is empty and the error is `input_invalid` (Requirement 20, criterion 4).
9. FOR ALL names that the Dsn_Rule accepts (drawn from valid-name strategies) and for each Name_Flow, WITH a script that answers the command with the REENTER capture, THE run SHALL end with `unexpected_screen`, the call list after the command Enter SHALL be exactly `pa 1`, `clear`, `string LOGOFF`, `enter`, the final screen SHALL be `tk5-logon`, and no frame, message or audit field SHALL hold the name beyond the inputs mapping that the Runner already drops (Property G, at least 200 examples).
10. THE Test_Suite SHALL contain a test that repeats the REENTER screen after every PA1 and asserts that at most three PA1 keys are sent, that the main failure stays `unexpected_screen`, and that the audit marks the failed finally step (the main failure wins, `session_clean` makes no claim).
11. THE Test_Suite SHALL contain a test that pins Finding 10: a test-only Flow whose `expect` after Enter does not list `tso-reenter` stops at that `expect` with `unexpected_screen`, every finally step is `skipped` and no key follows the Enter. THE test explains why the listing of criterion 2 exists, and a later runner change makes it fail on purpose.
12. THE Finally_Block of all five Command_Flows SHALL be the same (Requirement 10, criterion 4); THE Flows that type no caller value (`tk5-time`, `tk5-list-datasets`, `tk5-job-status`) SHALL NOT list `tso-reenter` in their `expect`, because they type fixed literals.
13. THE live check SHALL provoke the prompt on the host through the Connector with a test-only Flow whose `dsname` pattern is relaxed (Not verifiable, item 9), and SHALL confirm the host log shows `LOGGED OFF` afterwards.

### Requirement 22: Recovery of an orphaned session beyond the ISPF menu

**User Story:** As an operator, I want a session that was orphaned at `READY`, at the cleared screen or at a REENTER prompt to be released by the next call, so that a call timeout or a shutdown during a command cannot lock the account.

#### Acceptance Criteria

1. THE Logon_Prefix SHALL be the 12 top-level steps of today's `tk5-logon` with three Handle steps inserted between the `tso-pause` Handle (plan indices 17 and 18) and the final `expect ispf-primary-menu`, which moves from index 19 to index 26. THE inserted steps SHALL be, as YAML, in this order:
   ```
   - kind: handle
     signature: tso-reenter
     max_count: 3
     settle: 0.0
     steps:
     - kind: key
       key: pa
       n: 1
   - kind: handle
     signature: tso-ready
     max_count: 1
     settle: 0.0
     steps:
     - kind: key
       key: clear
   - kind: handle
     signature: tso-cleared
     max_count: 1
     settle: 0.0
     steps:
     - kind: type
       text: LOGOFF
     - kind: key
       key: enter
   ```
   THEIR plan indices SHALL be 19 and 20 (REENTER), 21 and 22 (READY), 23 to 25 (cleared).
2. THE shipped `tk5-logon.yaml` and `tk5-system-info.yaml` SHALL be written by `Flow.to_yaml()` with the Logon_Prefix; the `steps` of `tk5-logon` SHALL equal the Logon_Prefix; the `steps` of `tk5-system-info` SHALL begin with it, and its own steps SHALL follow at indices 27 to 37 (the four extracts at 27 to 30, `expect` at 31, `type X` 32, `key enter` 33, `expect tso-ready` 34, `type LOGOFF` 35, `key enter` 36, `expect tk5-logon` 37) and its `finally` at indices 38 to 44. THE `tk5-system-info` `finally` SHALL stay as it is.
3. WHEN the screen after the `tso-pause` Handle is the ISPF menu, THE three Handle steps SHALL run zero iterations, SHALL make no Session call and no read (the Runner polls only when it holds no Current_Screen, and it holds the menu), and THE Session calls, the number of reads and the audit records of indices 0 to 18 SHALL equal those of the flow before the change. THE golden call lists of `test_flow_logon_script.py` and `test_flow_system_info_script.py` SHALL pass without edit.
4. WHEN the screen after the reconnect is `READY` (not cleared), THE Flow SHALL press Clear, type `LOGOFF` and press Enter, SHALL reach the logon screen, and SHALL then stop at `expect ispf-primary-menu` (index 26) with `unexpected_screen`, `expected` `ispf-primary-menu`. WHEN it is the cleared screen, THE Flow SHALL type `LOGOFF` and press Enter and stop the same way. WHEN it is a REENTER prompt, THE Flow SHALL press PA1, then Clear, then type `LOGOFF` and press Enter and stop the same way. A scripted run of `tk5-logon` and `tk5-system-info` against these paths gave exactly these calls on 2026-11-19.
5. WHEN the host shows a `***` pause after the reconnect message, THE existing Handle on `tso-pause` (`max_count` 5) SHALL press Enter until a screen other than a pause shows, and THE screen it ends on SHALL be handled as in criteria 3 and 4. THE Flows SHALL stop with `loop_limit` after five pauses, as today.
6. THE screens that can follow the reconnect and what each does SHALL be as in this table. The column "Evidence" says what has been seen on the host.

   | Landing screen after the `tso-pause` Handle | Evidence | What the Flow does | Call ends |
   |---|---|---|---|
   | ISPF primary menu | through the Flow, 2026-11-17 and 2026-11-18 | continues (normal path), no cleanup key | normal result |
   | `READY` | not seen | Clear, `LOGOFF`, Enter | `unexpected_screen` at index 26 |
   | cleared screen | not seen | `LOGOFF`, Enter | `unexpected_screen` at index 26 |
   | REENTER prompt | by hand, 2026-11-19 (the old prompt showed again; PA1, Clear, `LOGOFF` ended it) | PA1, Clear, `LOGOFF`, Enter | `unexpected_screen` at index 26 |
   | another `***` pause | the first pause under the reconnect message seen 2026-11-17 and 2026-11-18; a second one not seen | Enter (up to five pauses), then as above | as above, or `loop_limit` |
   | an ISPF sub-panel, `IKJ56700A`, `IKJ56400A` or any unknown screen | not handled | no key; the poll stops | `unknown_screen` or `timeout`, `session_clean=false` |

7. THE Flows that need the ISPF menu (`tk5-logon`, `tk5-system-info`, and the five Command_Flows through the Exit_Fragment) SHALL all end at the menu on success, so that a landing anywhere else releases the account and fails the call once. The next call SHALL take the normal path. Continuing the call after a landing at `READY` is not part of this spec (Open decision 8).
8. THE Test_Suite SHALL contain `tests/unit/test_flow_logon_cleanup.py` with scripted runs of `tk5-logon` and `tk5-system-info` for each row of the table (the reconnect screens of `tests/unit/test_flow_logon_recovery.py`, then the landing from `tso-ready`, `tso-cleared`, `tso-listds-reenter` and its after-PA1 and cleared successors), asserting the call lists of criterion 4, the reason, the `expected` names, the final screen `tk5-logon`, and that no password occurs in any output form (`forms_of_run`, the style of `test_flow_logon_recovery.py`). THE pause cases SHALL use `pause_variant(i)` so that consecutive pauses differ.
9. FOR ALL landing sequences (0 to 3 further pauses from `pause_variant`, then one landing from the ISPF menu, `READY`, the cleared screen and the REENTER prompt, with 0 to 2 stale reads per screen), THE run SHALL end at the menu exactly for the menu landing, SHALL end with `unexpected_screen` and the final screen `tk5-logon` for the other three, and the keys after the password SHALL be the Enter keys for the pauses followed by the keys of the table (Property F, at least 100 examples).
10. THE existing tests SHALL need no edit for this change (measured, Finding 5). THE tests named in "Existing behaviour and tests that could be affected" change only for the signature count, the capture names and the test support. THE live test `tests/integration/test_flow_live_recovery.py` SHALL pass unchanged.
11. THE live check SHALL leave an orphan at `READY`, at the cleared screen and at a REENTER prompt on purpose (Not verifiable, item 10), and SHALL confirm that the call after each orphan fails once with `unexpected_screen`, that the host log shows `LOGGED OFF` for the released session, and that the call after that takes the normal path. THE rows "not seen" of the table stay unverified until then.

### Requirement 23: Spec text corrected at implementation time

**User Story:** As a reader of the older specs, I want them to describe the recovery that exists, so that nobody relies on the statement "only the ISPF-menu case is handled".

#### Acceptance Criteria

1. WHEN Requirement 22 is implemented, THE executor SHALL replace these statements, and no other sentence of the same files, and SHALL run `tests/unit/test_flow_spec_consistency.py` afterwards:
   - `.kiro/specs/publisher/requirements.md` line 22 (Assumptions bullet): the sentences from "Recovery covers only an orphan session left at the ISPF primary option menu." up to "...is not handled:" become "Recovery covers an orphan session left at the ISPF primary option menu, at `READY`, at the cleared screen and at a ` REENTER -` prompt. At the menu the call succeeds; at the other three the Flow ends the reconnected session and the call stops with `unexpected_screen`, so that the next call succeeds. An orphan left in a sub-panel or mid-logon (for example an abandoned logon showing `IKJ56700A ENTER USERID`, or the second IN USE state with `IKJ56400A` after an extra Enter) is not handled:"; the rest of the bullet stays.
   - `.kiro/specs/publisher/requirements.md` line 23 (not in scope): the parenthesis becomes "(the bundled Flows recover an orphan left at the ISPF primary option menu, at `READY`, at the cleared screen or at a ` REENTER -` prompt; an orphan left in a sub-panel or mid-logon is not recovered)".
   - `.kiro/specs/publisher/requirements.md` line 491 (Requirement 23.7): "left logged on at the ISPF primary option menu is done by the bundled `tk5-logon` and `tk5-system-info` Flows" becomes "left logged on at the ISPF primary option menu, at `READY`, at the cleared screen or at a ` REENTER -` prompt is done by the bundled Flows (the logon steps shared by all of them)".
   - `.kiro/specs/publisher/design.md` line 20 (table row), line 471 ("The limit of recovery" bullet of "Account lock and recovery"), line 758 (error-table row about a locked account) and line 910 (open item 2): the same two changes: the covered set grows to the menu, `READY`, the cleared screen and a REENTER prompt, the three new cases end with `unexpected_screen` and no `session_clean` claim because the Flow released the account, and only a sub-panel, mid-logon and the second IN USE state stay unhandled with `session_clean=false`.
   - `.kiro/specs/publisher/tasks.md` lines 31 and 294: the words "left at the ISPF primary option menu" in the sentence about recovery get the same set.
   - `.kiro/specs/flow-runtime/design.md` line 1051 (decision 13): "`tk5-logon` recovers only an orphan left at the ISPF primary option menu" becomes "`tk5-logon` recovers an orphan left at the ISPF primary option menu and releases one left at `READY`, at the cleared screen or at a ` REENTER -` prompt (three Handle steps before the final expect: PA1, Clear, `LOGOFF`)"; the sentence "An orphan left at `READY`, in a sub-panel or mid-logon is not handled." becomes "An orphan left in a sub-panel or mid-logon is not handled."; the rest and the reasons column stay, with "the live pass of 2026-11-18 exercised the menu only" kept and the live status of the new cases added.
   - `.kiro/specs/logon-recovery/requirements.md` line 39 ("Known limits" first bullet) and lines 221 to 222 (the statements that criterion 2 lists): the same set; `.kiro/specs/logon-recovery/design.md` line 253 ("The recovery relies on one assumption: the orphan sits at the ISPF primary option menu ... The flow has no other branch.") becomes a description of the three added branches.
2. EACH replacement SHALL say which landings are verified (the menu through the Flow, a REENTER landing by hand on 2026-11-19) and which are not yet seen on the host (`READY`, the cleared screen), until the live check of Requirement 22, criterion 11 has passed; THE reviewer removes that remark afterwards.
3. THE statements about `IKJ56700A`, the second IN USE state, the 3-minute lock and RECONNECT taking over any session SHALL stay as they are.
4. THE console and Ask documents SHALL NOT be edited: searched on 2026-11-19, no sentence of `.kiro/specs/console` or `.kiro/specs/ask` repeats the limit (`console/design.md` line 462 only shows a display example), and `.kiro/specs/linux-readiness/design.md` line 506 is a dated historic note.
5. THE flow-runtime Known Limits paragraph about `IKJ56700A` (`flow-runtime/requirements.md` line 74) SHALL stay as it is.

## Files

| File | Change |
|---|---|
| `captures/*.txt` (36 files) | added (moved, bytes unchanged) |
| `greenscreen/recognizer/signatures/tso-cleared.yaml`, `tso-reenter.yaml` | new |
| `greenscreen/recognizer/bundled.py` | `_MANIFEST` gains `tso-cleared`, `tso-reenter` |
| `greenscreen/flow/model.py` | `OutputSpec` gains `next_row`, `max_rows`, `equals`; new `CollectStep`; `Step` union and `plan` |
| `greenscreen/flow/validate.py` | rules of Requirements 3, 5, 7; `reference_violations` for `more` |
| `greenscreen/flow/yamlio.py` | optional output keys; `collect` step schema, reader and writer |
| `greenscreen/flow/screens.py` | `read_rows` (reads rows above the Prompt_Row, hidden-aware) |
| `greenscreen/flow/runner.py` | rows and flag extraction in `exec_extract`; `exec_collect`; `_EXECUTORS`; `_referenced_names` |
| `greenscreen/flow/bundled.py` | `_MANIFEST` gains five names |
| `greenscreen/flow/flows/tk5-logon.yaml`, `tk5-system-info.yaml` | edited: the three Handle steps of the Logon_Cleanup (Requirement 22) |
| `greenscreen/flow/flows/tk5-time.yaml`, `tk5-list-datasets.yaml`, `tk5-dataset-info.yaml`, `tk5-library-members.yaml`, `tk5-job-status.yaml` | new |
| `tests/screen_support.py`, `tests/flow_support.py`, `tests/property/_flow_strategies.py` | test support (Requirement 2, criterion 7) |
| new test files | listed in Requirement 19 |
| spec documents of Requirement 23 | edited at implementation time only |

## Existing behaviour and tests that could be affected

Tests that must change in this spec. The edit is the smallest one; no assertion is removed or weakened, a count or a set grows. The column "Measured" says whether the need was shown on a scratch copy outside the workspace (Finding 5) or follows from adding the five Flows, which the scratch copy did not include.

| Test | What pins it | New expected value | Measured |
|---|---|---|---|
| `tests/screen_support.py` | `CAPTURE_NAMES`, 10 names | the 10 names plus the 18 names of the table "Capture inventory" (28 names) | follows from Requirement 1 |
| `tests/flow_support.py` | `_SIGNATURE_CAPTURE`, 10 entries; `partial_repaint` raises `LookupError` for a signature with no repaintable cell | 12 entries (`tso-cleared`, `tso-reenter` added); a signature with no repaint cell is skipped by the strategies | yes: three property tests fail without it |
| `tests/property/_flow_strategies.py` | draws a partial repaint for any bundled signature name | skip signatures with no repaint cell (`tso-cleared`) | yes |
| `tests/unit/test_recognizer_capture_inventory.py` | `EXPECTED_NAMES`; `len(paths) == 10`; `len(CAPTURE_NAMES) == 10`; docstring "ten screens" | the 28 names; 28 readbuffer files; 28 names | follows from Requirement 1 |
| `tests/unit/test_recognizer_capture_matrix.py` | `len(paths) == 10`, `len(CAPTURE_NAMES) == 10`, `test_ten_bundled_signatures` (`len(sigs) == 10`), `performed == 10`, `count == 10 * 10`, `EXPECTED` map | 28, 28, 12 signatures, 12 per capture, 28 x 12, the new mapping of Requirement 2, criterion 5 | yes (13 tests fail on the count) |
| `tests/unit/test_recognizer_bundled.py` | `len(loaded) == 10`, the glob count 10, `len(...) == 10` in `test_loader_keeps_no_state_after_failure`, `OWN_CAPTURES` | 12, 12, 12, plus `"tso-cleared": "tso-cleared"` and `"tso-reenter": "tso-listds-reenter"` | yes (2 tests) |
| `tests/unit/test_recognizer_recognize.py` | `test_unknown_for_ispf_without_ispf_signature_shows_option_prompt`: `len(reduced) == 9` | 11 | yes |
| `tests/unit/test_flow_captures.py` | `_EXPECTED_NAMES` in `test_readbuffer_captures_are_exactly_the_ten_names` and in `test_no_capture_exists_for_the_screen_after_the_password_entry` | the 28 names | follows from Requirement 1 |
| `tests/unit/test_flow_bundled.py` | `NAMES`; `len(flows) == 3`; `test_exactly_three_yaml_files_shipped` | the eight names; 8; eight files | follows from Requirement 17 |
| `tests/unit/test_flow_packaging.py` | `EXPECTED_YAML` (equality with the wheel contents) | the eight files | follows from Requirement 17 |
| `tests/unit/test_publisher_registry.py` | `BUNDLED` tuple (load order, used in two tests) | the eight names in manifest order | follows from Requirement 17 |
| `tests/unit/test_publisher_openapi.py` | `len(registry) == 3` | 8 | follows from Requirement 17 |
| `tests/unit/test_publisher_stack.py` | `test_unset_publish_list_publishes_all_three_flows` (`health["flows"] == 3`, 3 paths, 3 tools) | 8 (rename the test) | follows from Requirement 17 |

Tests that pin the logon steps and were checked on the scratch copy with the Logon_Cleanup in place: `test_flow_bundled.py` (including `test_logon_typing_sequence`, which filters out Handle steps, `test_logon_ends_on_ispf_primary_menu` and `test_logon_pause_handle_step`), `test_flow_sync.py`, `test_flow_logon_script.py` (golden call lists), `test_flow_logon_recovery.py` (audit of indices 7 to 18, `audit[-1]` is the final `expect`), `test_flow_system_info_script.py` (including `test_failure_after_extracts_runs_finally_steps_that_log_off`, which counts reads, and the golden call lists), `test_flow_runner_fixes_skipped.py`, `test_flow_packaging.py` and the publisher tests that run `tk5-system-info`. They pass **without edit**, because the three Handle steps sit before the final `expect`, run zero iterations on the normal path and add no read. Had the Handle steps been put after the final `expect`, `test_flow_system_info_script.py` and the `audit[-1]` assertions would have changed. `tests/integration/test_flow_live_recovery.py` was not run (no host) and is on the live list.

Tests that exercise the same code and must pass unchanged (the executor runs them first and stops on a failure that is not in the table above): the tests of the previous paragraph, `test_flow_runner_*.py`, `test_flow_validate.py`, `test_flow_yaml.py`, `test_flow_static.py` (the new row reader must stay in `screens.py` and read no `text_grid`, `fields`, `find_field` or `text`), `test_flow_public_api.py` (`__all__` stays nine names, so `CollectStep` is not exported), `test_flow_spec_consistency.py` (it reads flow-runtime and connector spec documents; Requirement 23 edits one of them, so the executor runs it after the edit), `test_publisher_error_table.py` (13 reason codes), `test_publisher_helpers.py` and the property tests `test_flow_*`, `test_publisher_schema*.py`, `test_publisher_no_leak_*.py`, `test_publisher_audit_summary.py`, `test_render_left_inverse.py` (which parses every `captures/*.readbuffer.txt`, so it also checks the 18 new files), the Ask and console tests (they publish `tk5-system-info` only).

## Not verifiable without the live host

The reviewer runs these. The `curl` form assumes the Publisher on `127.0.0.1:8080` with the key in `GS_API_KEY` and the bindings set in the shell; the commands print no secret. The integration tests are run with `python -m pytest <file> -m integration -q` from the repository root with `TK5_USERNAME` and `TK5_PASSWORD` set. Only one session per user id may run at a time, so a running Publisher and these tests must not overlap (steering, "one TSO session per user id").

1. **Each Flow end to end through the Publisher**: `curl -s -X POST http://127.0.0.1:8080/flows/tk5-time -H "X-API-Key: $env:GS_API_KEY" -H "Content-Type: application/json" -d "{}"`. Repeat for `tk5-list-datasets`, `tk5-job-status`, and with `-d '{"dsname":"SYS2.JCLLIB"}'` for `tk5-dataset-info` and `tk5-library-members`. Expect `TIME_TEXT` starting `TIME-`, seven names from `DATASETS`, one `JOB ... EXECUTING` line, `FOUND` 1 with three `DETAILS` lines, 136 names from `MEMBERS`. After each call the host log shows the user id `LOGGED OFF`. The same by the integration test: `python -m pytest tests/integration/test_flow_live_commands.py -m integration -q`.
2. **Missing data set**: `-d '{"dsname":"NO.SUCH.DSN"}'` to `tk5-dataset-info` returns HTTP 200 with `FOUND` 0 and `DETAILS` empty; the same for `tk5-library-members` returns `MEMBERS` empty.
3. **Names over REST and MCP**: `-d '{"dsname":"A..B"}'`, `"1ABC"`, `"A B"`, `"X'"`, `"A(B)"`, a 45-character name and a 9-character qualifier each return HTTP 400 `request_invalid` and the host log shows no logon; `"sys2.jcllib"` returns HTTP 200 with `FOUND` 1 and the same `DETAILS` as `SYS2.JCLLIB`.
4. **Names at the edge of the rule, by hand** with `ws3270 -model 3279-2` at `READY` after Clear: `LISTDS '$A.#B.@C'`, a name with an 8-character qualifier, and a 43-character name of 22 one-character qualifiers. Expect an answer ending in `READY` (found or not in catalog), never ` REENTER -`. A ` REENTER -` here means the Dsn_Rule is looser than the host and must be tightened.
5. **Plain `LISTCAT` over several screens**: by hand, `LISTCAT` for a user id with more than 21 catalogued data sets, if one exists (this spec cannot create one, because creating a data set writes). Expect continuation screens that start at row 0 with no ` IN CATALOG` heading; a repeated heading changes `next_row` of `DATASETS` or needs a filter (Open decision 5). Also check the shape for a user with no entries.
6. **The apostrophe through the Connector**: run `tk5-dataset-info` and confirm the host echo is `LISTDS 'SYS2.JCLLIB'` (the typed quote is not doubled or dropped).
7. **STATUS shape with batch jobs**: submit nothing; read `STATUS` with an account that has held output, if one exists, to see the line shapes beyond `JOB <id>(TSU...) EXECUTING`.
8. **Timing**: run each Flow ten times and record the Publisher's `duration_ms`; confirm the seven-page member list finishes under 17 s, the others under 12 s, and the Open_Allowance of 4 s (time from `POST` to the first Session call). Run each once with the account locked by a dropped connection at the ISPF menu and confirm the recovery path finishes inside `run` 20 s. Measure the finally path from `READY` (Clear, `LOGOFF`, Enter) and from a REENTER prompt (PA1, Clear, `LOGOFF`, Enter) against the `finally` budget of 6 s (Open decision 9).
9. **A REENTER prompt through the Flow**: `python -m pytest tests/integration/test_flow_live_reenter.py -m integration -q`. The test builds a test-only copy of `tk5-dataset-info` whose `dsname` pattern is relaxed to `.{1,44}`, runs it with `A..B` (`INVALID DATA SET NAME`) and with `1ABC` (`INVALID KEYWORD`, the form that no capture holds), and asserts `unexpected_screen` at the `extract` step, the calls `pa 1`, `clear`, `LOGOFF`, Enter after the command, a final screen `tk5-logon`, and (by a second session) that the user id is not IN USE afterwards. By hand: after the prompt, PA1, Clear, `LOGOFF`, Enter returns the logon screen. Also by hand: whether PA1 at a ` ***` pause is accepted (Open decision 4).
10. **Orphan release at `READY`, the cleared screen and a REENTER prompt**: `python -m pytest tests/integration/test_flow_live_cleanup.py -m integration -q`. The test, for each of the three states, logs on, leaves the state (`READY` after `X`; Clear at `READY`; the REENTER prompt of item 9), closes the connection without `LOGOFF`, then runs `tk5-system-info` on a new connection and expects `unexpected_screen` at index 26 and a logon screen, then runs it again and expects the normal result and zero iterations of the in-use Handle. It records which screen the reconnect landed on, so that the rows "not seen" of Requirement 22, criterion 6 can be confirmed or corrected (including a second `***` pause). A Cleanup_Helper logs the account off on every path; the manual recipe is `LOGON <id> RECONNECT` at `Logon ===>`. An orphan inside an ISPF sub-panel stays unhandled; record what the call does (expected `unknown_screen`, `session_clean=false`).
11. **Existing live recovery**: `python -m pytest tests/integration/test_flow_live_recovery.py -m integration -q` passes unchanged with the new logon steps (menu path).
12. **Ask**: with Ask on, `GS_CALL_TIMEOUT=30`, the five names in `GS_ASK_FLOWS` and the bindings set, ask "What is the host time?", "Which members does SYS2.JCLLIB have?" and "Does data set FOO.BAR exist?"; expect the matching tool, a correct answer, `transport=ask` in the Call_Log_Record, and an account that is logged off afterwards.
