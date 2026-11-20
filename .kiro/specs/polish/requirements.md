# Requirements Document

## Introduction

Nine specs built the bridge: connector, recognizer, flow runtime, publisher, logon recovery, Linux readiness, console, Ask and five command Flows. Six Flows are published as tools. This feature is the final polish pass before the hackathon deadline. It changes no host behaviour and adds no Flow. It makes seven things true or better:

1. **README.** The README still says that the bridge records transactions in a web terminal, supports AS/400 5250 and ships Kiro hooks. None of that exists. The README is rewritten so that every statement is true today, and tests keep it true (Requirements 1 and 2).
2. **Kiro hooks and a Flow check command.** Two hooks in `.kiro/hooks`: one runs the Flow validation and sync tests when a bundled Flow YAML is saved, one runs the capture password scan and the capture inventory tests when a file under `captures/` is created or saved. A test checks the hook files (Requirements 3, 4 and 5). A small command, `python -m greenscreen.flow.check <file.yaml>`, runs `check_flow` on one file and reports through its exit code (Requirement 6).
3. **Ask examples on the console page.** One example question per tool that Ask actually offers, phrased as a real question, taken from the published tool and not from a list in the page, shown only when Ask is enabled, never cut in the middle of a word, at most 12 buttons (Requirements 7, 8, 9 and 10).
4. **Multi-line outputs.** A value that contains a line feed uses a smaller font so that 20 or more lines fit in the scroll box (Requirement 11).
5. **Key on `hashchange`.** The console reads `#key=` when the address fragment changes, not only on load (Requirement 12).
6. **`MEMBER_COUNT`.** `tk5-library-members` returns the number of member names as an integer, so that a model does not have to count 136 lines (Requirements 13, 14 and 15).
7. **Stale text.** A wrong log line (`publishing 1 of 3`) in the Linux readiness, console and Ask specs, two docstrings that say "three" and a test name that says "three" are corrected (Requirement 16).

The product rules stay as they are: the runtime is deterministic and uses no LLM, a Flow never guesses, credentials come from the environment, no secret or host value appears in a document or a test, and the `.kiro` directory is never git-ignored. This spec adds no dependency and no Flow step kind. Requirement 17 collects the rules for every task.

### Findings from reading the code and the documentation

All probes were read-only. Nothing in the repository was changed except the files of this spec folder.

**Finding 1: the README claims things that do not exist.** `README.md` says "Turn legacy terminal screens (IBM 3270 mainframe, AS/400 5250) into MCP tools", "Walk through a transaction once in a web terminal. Green Screen Medium records it", "See `/.kiro` for the specs, steering and hooks" and "Early build. Setup instructions will land here". The repository has no recorder, no 5250 code, no write Flow and no `.kiro/hooks` directory. The product steering file describes the recorder and 5250 as core pieces, so the README is the only place that needs correcting; the steering file is not edited.

**Finding 2: the hook file format is not the one in the brief.** The brief recalls `*.kiro.hook` JSON files with `when` and `then`. The Kiro documentation (fetched 2026-11-20, page dated 2026-11-12) describes standalone JSON files at `.kiro/hooks/<id>.json` with the members `version` (`"v1"`), `hooks[]` (`name`, `description`, `trigger`, `matcher`, `action`, `timeout`, `enabled`), PascalCase triggers (`PostFileSave`, `PostFileCreate`, `PostFileDelete`) and an action of type `command` or `agent`. The `.kiro.hook` form is the IDE 0.x form that the page says was replaced. This spec uses the current form. Sources are listed in the design.

**Finding 3: command hooks report failure through stderr.** The documentation says that a command action with exit code 0 adds its standard output to the agent's context, and that any other exit code sends standard error to the agent. pytest writes its report to standard output, so a failing run would show the agent nothing. The commands therefore run pytest through the runner `tests/hook_pytest.py`, which writes the report to standard error and exits with pytest's exit code, so the report reaches the agent exactly when the exit code is not 0. (A `1>&2` suffix was rejected: it is a parse error in PowerShell.) A passing run is silent. The documentation does not name the field in which a file hook receives the saved path on standard input, so no hook command depends on it (Finding 13).

**Finding 4: `check_flow` is a function, not a command.** `greenscreen/flow/validate.py` defines `check_flow(flow, signatures)`. No command line wraps it. `tests/unit/test_flow_bundled.py::test_every_bundled_flow_passes_validator` calls it for all eight bundled Flows against the bundled signatures, `test_shipped_yaml_equals_to_yaml` checks that every shipped file equals `Flow.to_yaml()`, and the `flows` fixture of that file names the failing file when a YAML file does not load. `tests/unit/test_flow_sync.py` and `tests/unit/test_flow_command_sync.py` keep the shared logon and exit steps equal across Flows. A hook that runs these three files therefore runs `check_flow` on every bundled file, including the saved one. `yamlio.load_flow` already calls `check_flow` and raises `FlowDefinitionError` for the first violation only, with a message that holds the step index, the step kind, the field name and a fixed rule name, never a YAML scalar; a small command can be built on it (Requirement 6). `tests/unit/test_flow_static.py` applies to every module under `greenscreen/flow`: no `environ` or `getenv`, no `time`, `datetime` or `random`, and only `yaml.safe_load` and `yaml.safe_dump`; a new module there must respect these rules.

**Finding 5: the Ask examples are cut and limited by the page code.** `askExamples` in `greenscreen/publisher/console/snippets.js` skips every Flow that has a required input or a secret input, stops after 3 items (`Math.min(Math.max(limit, 0), 3)`), writes the button text `Run <name> and tell me what it returns.` and builds the hint with `.slice(0, 100)` of the whole description, which cuts in the middle of a word ("TIME_TEXT holds the"). The call in `console.js` is `askExamples(flows, 3)`, so the number 3 stands in two places: the argument and the clamp inside the function. With the demo configuration (user id and password bound) `tk5-system-info`, `tk5-time`, `tk5-list-datasets` and `tk5-job-status` have no required input and `tk5-dataset-info` and `tk5-library-members` require `dsname`, so the page can show four of six at best and only three because of the cap. The existing test `test_ask_examples_limits_and_hostile_values` has four qualifying Flows (`ok-one`, `ok-two`, `ok_3`, `ok-4`) and asserts that a limit of 99 returns 3 items, which shows the clamp; with a cap of 12 the same four Flows give 4 items.

**Finding 6: the page learns the tool list from `/openapi.json` only.** `parseListing` in `console.js` reads `paths`, the request schema and the operation `summary`. Console routes are an allow-list of six GET paths pinned by tests, `apiFetch` allows only `/openapi.json`, `/flows/<name>`, `/mcp` and `/ask`, and the Content-Security-Policy is `default-src 'self'; script-src 'self'; style-src 'self'; ...`. A new route or request path would break these pins. The one carrier that needs no new path is the OpenAPI document. `tests/unit/test_publisher_openapi.py` forbids the keys `default`, `example`, `examples`, `const` and `enum` anywhere in the document, so a vendor extension with another name (`x-ask-example`) is allowed and the key `example` is not. MCP `tools/list` is used by the console only for the Run transcript and by Ask for the descriptions, so it does not need the example.

**Finding 7: a multi-line value gets ten lines, not twenty.** `.outputs dd` has `font-size: 2rem`, `line-height: 1.2`, `white-space: pre-line`, `max-height: 24rem` and `overflow-y: auto` (more-flows decision D1, test `test_outputs_keep_line_breaks_and_scroll`). One line is 2.4rem high, so 24rem holds 10 lines. Twenty lines need at most 1.2rem per line. 136 member names with the 2rem font need 326rem of scrolling.

**Finding 8: the key is read once, at module load.** `takeKeyFromFragment` in `console.js` runs at the top of the module, before `refs` exists, and assigns `apiKey` and `keyHeld`. Pasting a new `#key=` link into a tab that is already open changes only the fragment, so the page keeps the old key or none. `history.replaceState` does not fire `hashchange`, so removing the key from the address bar cannot loop. Tests pin that `history.replaceState` comes before the first `fetch(`, that `apiKey` is read only inside `apiFetch`, and that no code assigns `location.hash`.

**Finding 9: rows are never empty and never hold a line feed.** `read_rows` in `greenscreen/flow/screens.py` returns the stripped, non-empty region texts of the rows, and `exec_extract` and `exec_collect` store `"\n".join(rows)`. The number of member lines is therefore `len(rows)`, which equals the number of LF-joined lines when the value is not empty and 0 when it is empty. The host listing of `SYS2.JCLLIB` has 136 members (steering, "Verified 2026-11-20"), and the model answered "over 100" because it had to count.

**Finding 10: an `int` output needs no change outside the Flow package.** `build_schemas` maps `int` to `{"type": "integer"}`; Ask's `project_result` keeps an output when its value is a `str` or an `int` (not a `bool`); the console prints `String(value)`; the REST, MCP and OpenAPI contracts list outputs from `flow.outputs` in declaration order. A new `int` output is a new member of the output object and nothing else. The pins that change are the output list of `tk5-library-members` in `test_flow_command_publish.py`, the description length in `test_flow_command_flows.py` and the measured result size in `test_flow_command_timing.py`.

**Finding 11: the publisher logs a different line than the spec text says.** `greenscreen/publisher/cli.py` (`_report_startup`) logs `publishing %d of %d flows over %s` with the number of published Flows, the number of loaded Flows and the transport. The stdio SIGTERM test sets `GS_PUBLISH_FLOWS` to `tk5-system-info`, eight Flows are loaded, and `tests/unit/test_publisher_cli.py` (line 668) waits for `publishing 1 of 8`. The text `publishing 1 of 3` in `.kiro/specs/linux-readiness/design.md` (lines 67 and 376) and `.kiro/specs/linux-readiness/requirements.md` (line 22) is from the time of three bundled Flows. The recorded output in `sigterm-diagnostic.txt` is a record of a past run and is not edited. The same stale text stands in four more places, all found by `grep` on 2026-11-20: `.kiro/specs/console/design.md` (line 298) and `.kiro/specs/console/requirements.md` (line 42), which say that `test_publisher_cli.py` waits for `publishing 1 of 3`, and `.kiro/specs/ask/design.md` (line 1312) and `.kiro/specs/ask/tasks.md` (line 447), whose live check expects `publishing 1 of 3 flows over http` with `GS_PUBLISH_FLOWS` set to `tk5-system-info`. With eight Flows loaded the line is `publishing 1 of 8 flows over http`. Requirement 16 corrects all of them. The line at `console/requirements.md` 582 quotes the format `publishing %d of %d flows over %s` and is correct.

**Finding 12: the static scan reaches the README and the hook files.** `test_no_file_holds_a_nonempty_api_key_or_binding_value` scans every `.md` and `.json` file of the repository (outside git-ignored and build directories) for a line that starts with `GS_API_KEY` or `GS_BIND_<name>`, optionally after `export `, `set ` or `$env:`, followed by `=` or `:` and a value. A README line such as `$env:GS_API_KEY = "..."` fails that test. The README therefore shows how to set a secret without such a line (a prompt command that starts with another word) and lists names only.

**Finding 13: Ask offers a subset of the published Flows, and `/openapi.json` is built once.** `plan_ask(registry, ask)` in `greenscreen/publisher/ask/service.py` returns an `AskPlan` whose frozen set `eligible` is the list of Flows that Ask offers to the model: the names in `GS_ASK_FLOWS` when it is set (each name must be published and pass the rules, or the start fails), otherwise every published Flow that passes `_rule` (valid name, no secret input, call time within the Ask budget). `prepare()` in `app.py` calls it once and keeps the plan; `build_app` passes it to `AskService` as `_plan`, and the service has no public member that exposes the names. `build_rest` calls `build_openapi(registry, version, ask)` once, stores the dict in a closure variable `document` and serves it from memory on every `/openapi.json` request; the response carries `Cache-Control: no-store`. With Ask off, `ask` is `None` and the document has no `/ask` path. The registry is an immutable mapping and the plan is a frozen dataclass, so the inputs of the document cannot change while the process runs. A Flow that has an example but that Ask does not offer (because `GS_ASK_FLOWS` lists other names) would give a button that Ask refuses; this is why the example must follow the plan and not only the Flow.

**Finding 14: the hook documentation does not give a usable saved-file path.** Read on 2026-11-20 (details in the design, "Hook payload finding"). The page https://kiro.dev/docs/hooks/ (dated 2026-11-12) says that a hook "receives the saved file path and session context via STDIN" and that a command receives "session context as JSON on STDIN". The pages https://kiro.dev/docs/hooks/actions/ (2026-10-10), https://kiro.dev/docs/hooks/types/ and https://kiro.dev/docs/hooks/examples/ (2026-08-21) show no path variable, no placeholder in the command text and no environment variable for a file event; the only documented variable is `USER_PROMPT` for the Prompt Submit trigger. The only JSON payloads shown are for session start (`hook_event_name`, `cwd`, `session_id`), tool events (`tool_name`, `tool_input`) and compaction; no JSON member name is given for `PostFileSave` or `PostFileCreate`. A command could read standard input, but it would have to guess an undocumented member name. The Flow hook therefore does not pass the saved path to the wrapper (Requirement 3, criterion 8).

### Existing behaviour and tests that could be affected

Edits to existing tests are listed in full in the design ("Every existing-test edit"). They are limited to: the renamed test and two docstrings (Requirement 16), one test of the `tk5-library-members` file checks, one schema pin and one size pin (Requirement 15), and the fixture and expected values of `test_ask_examples_limits_and_hostile_values` (Requirements 9 and 10). The new code also adds one read-only property to `AskService` (Requirement 8, criterion 4). No assertion is removed or weakened. Every other existing test runs unedited.

## Glossary

- **README**: The file `README.md` at the repository root.
- **README_Test**: The new test file `tests/unit/test_readme.py`.
- **Published_Tools**: The six Flows `tk5-system-info`, `tk5-time`, `tk5-list-datasets`, `tk5-dataset-info`, `tk5-library-members` and `tk5-job-status`: the bundled Flows other than `tk5-logon` and `tk5-logoff`.
- **GS_Variable**: An environment variable whose name starts with `GS_` and that the code under `greenscreen/` reads, excluding the `GS_BIND_` family.
- **Binding_Rule**: The rule that `GS_BIND_<FLOW>__<INPUT>` supplies the input `<INPUT>` of the Flow `<FLOW>` from the environment, with both names in upper case and `-` written as `_`.
- **Bundled_Flow**: One of the eight Flow files in `greenscreen/flow/flows`.
- **Spec_Set**: The directories under `.kiro/specs`.
- **Hook_File**: A JSON file under `.kiro/hooks` in the Kiro `v1` hook format.
- **Flow_Hook**: The Hook_File `.kiro/hooks/flow-yaml-check.json`.
- **Capture_Hook**: The Hook_File `.kiro/hooks/captures-check.json`.
- **Hook_Test**: The new test file `tests/unit/test_kiro_hooks.py`.
- **Flow_Model**: The classes `Flow` and `OutputSpec` in `greenscreen/flow/model.py`.
- **Flow_YAML**: The reader and writer in `greenscreen/flow/yamlio.py`.
- **Flow_Validator**: `structural_violations` and `check_flow` in `greenscreen/flow/validate.py`.
- **Flow_Runner**: `run_flow` and its state in `greenscreen/flow/runner.py`.
- **Flow_Check_CLI**: The new module `greenscreen/flow/check.py` with its function `main(argv)`, run as `python -m greenscreen.flow.check <file.yaml>`.
- **Check_Exit_Codes**: The exit codes of the Flow_Check_CLI: 0 clean, 1 violation, 2 usage error, 3 file missing or unreadable, 4 not a YAML mapping, 5 bundled signatures not loadable.
- **Flow_Example**: The optional member `example` of a Flow: one question, in English, that a person could ask and that the Flow answers.
- **Ask_Plan**: The `AskPlan` that `plan_ask` returns at startup. Its `eligible` set is the Ask_Offered_Set.
- **Ask_Offered_Set**: The names of the published Flows that Ask offers to the model: the names of `GS_ASK_FLOWS` when it is set, otherwise every published Flow that passes the Ask eligibility rules. It is empty in meaning when Ask is off.
- **Ask_Example**: One example button of the Ask panel, made of a question text and a hint.
- **Ask_Example_Max**: The maximum number of Ask_Example buttons: 12.
- **Publisher**: The package `greenscreen/publisher`.
- **Ask_Service**: The class `AskService` in `greenscreen/publisher/ask/service.py`, present only when Ask is enabled.
- **OpenAPI_Document**: The JSON that `build_openapi` returns and the route `/openapi.json` serves.
- **Console_Page**: The files `index.html`, `console.js`, `snippets.js` and `console.css` under `greenscreen/publisher/console`.
- **Snippets_Module**: `snippets.js`, the pure module that Node tests import.
- **Console_Script**: `console.js`.
- **Console_CSS**: `console.css`.
- **Example_Builder**: The exported function `askExamples` of the Snippets_Module.
- **Hint_Builder**: The new exported function `hintText` of the Snippets_Module.
- **Fragment_Reader**: The function `takeKeyFromFragment` of the Console_Script.
- **Multi_Line_Value**: An output value, shown as text, that contains the character LF (U+000A).
- **Rows_Output**: An output with `max_rows` (more-flows).
- **Count_Output**: An output with the new member `counts`: an `int` output whose value is the number of rows of a named Rows_Output.
- **Test_Suite**: The tests under `tests/`.
- **Spec_Text**: A Markdown file under `.kiro/specs`.

## Requirements

### Requirement 1: A README in which every statement is true

**User Story:** As a hackathon judge or a new user, I want a README that describes what the project does today and how to run it, so that I can trust every sentence and reproduce the demo.

#### Acceptance Criteria

1. THE README SHALL begin with what the project is: a bridge that logs on to a TN3270 host through `s3270` or `ws3270`, reads its 24 by 80 screens, replays recorded key sequences (Flows) deterministically with no LLM at run time, and publishes each Flow as an MCP tool and a REST endpoint.
2. THE README SHALL state the live demo URL `https://greenscreen.banksyai.com` and SHALL state that an API key is needed to use it.
3. THE README SHALL list the six Published_Tools, each with one line that says what the tool returns.
4. THE README SHALL explain how to install the Publisher and start it with `greenscreen-publish` on Windows (with `ws3270`) and on Linux (with `s3270`), using prompt commands or placeholders for every secret and for every host value.
5. THE README SHALL list every GS_Variable with one line that says what the variable does, and SHALL list names only, never a value that is a key, a password or a user id.
6. THE README SHALL state the Binding_Rule with one example variable name and SHALL say that the bound inputs are not part of a request.
7. THE README SHALL show one short Flow YAML example that Flow_Validator accepts, SHALL name the step kinds `expect`, `type`, `key`, `extract`, `collect` and `handle`, and SHALL say that a Flow stops with an error on any screen it does not know.
8. THE README SHALL show how to call a Published_Tool over REST, over MCP, and from the Kiro MCP configuration in the style of `.kiro/settings/mcp.json`, with the placeholder `<YOUR_API_KEY>` for the key.
9. THE README SHALL describe how Kiro built the project: one line for each directory of the Spec_Set, the steering files `product.md` and `mainframe-host.md`, the real host captures in `captures/`, the hooks of Requirements 3 and 4, the check command of Requirement 6, and how to run the Test_Suite.
10. THE README SHALL have a section "Not built yet" that lists the Flow recorder, 5250 (AS/400) support and Flows that write to the host.
11. THE README SHALL end with a License section that says MIT and links to the file `LICENSE`.
12. THE README SHALL contain no sentence that claims a recorder, 5250 support, a write Flow or an LLM at run time, except in the section "Not built yet".
13. WHERE Ask is described, THE README SHALL say that Ask is optional, that it sends the question and the tool results to an OpenAI-compatible model that the operator configures, and that the model only chooses which Published_Tool to call.
14. THE README SHALL document the command `python -m greenscreen.flow.check <file.yaml>` with one usage example and the six Check_Exit_Codes, and SHALL say that the command validates a Flow file against the bundled signatures and changes nothing.

### Requirement 2: Tests keep the README true

**User Story:** As a maintainer, I want tests that fail when the README and the code drift apart, so that the README stays true after the deadline.

#### Acceptance Criteria

1. THE README_Test SHALL collect every GS_Variable from the string constants of the modules under `greenscreen/` and SHALL fail, naming the variable, when the README does not mention it.
2. THE README_Test SHALL fail, naming the word, when the README mentions a `GS_` name that is neither a GS_Variable nor the Binding_Rule family.
3. THE README_Test SHALL assert that the set of Flow names in the README tool list equals the bundled Flow names minus `tk5-logon` and `tk5-logoff`.
4. THE README_Test SHALL assert that the README names every directory of the Spec_Set and no other `.kiro/specs` path.
5. THE README_Test SHALL assert that the README names every Hook_File by file name and that every `.kiro/hooks/` path in the README is a file that exists.
6. THE README_Test SHALL assert that the words `recorder`, `5250`, `AS/400`, `web terminal` and `write` Flows appear only inside the section "Not built yet", and that the phrases `Early build` and `will land here` do not appear.
7. THE README_Test SHALL assert that no line of the README assigns a value to `GS_API_KEY`, `GS_LLM_API_KEY`, a `GS_BIND_` name or a `TK5_` name, that no line holds an IPv4 address other than `127.0.0.1`, and that no token of 24 or more letters, digits, `_` or `-` characters appears outside a URL, a file path or a command name.
8. THE README_Test SHALL assert that the README refers to the console script `greenscreen-publish` and the extra `publish` only when both exist in `pyproject.toml`, and that every Markdown link to a repository path resolves to an existing file or directory.
9. THE README_Test SHALL parse every fenced `yaml` block of the README that starts with `version:` with `Flow.from_yaml` and the bundled signatures, and every fenced `json` block with `json.loads`.
10. WHEN the README is added, THE existing test `test_no_file_holds_a_nonempty_api_key_or_binding_value` SHALL pass without an edit.
11. THE README_Test SHALL assert that the README contains the text `python -m greenscreen.flow.check`, that the file `greenscreen/flow/check.py` exists and defines a function `main`, and that every Check_Exit_Codes value (the digits 0 to 5 with their meaning) appears in the README section that documents the command.

### Requirement 3: A hook that checks a bundled Flow when it is saved

**User Story:** As a Flow author, I want Kiro to validate and sync-check the bundled Flows when I save one, so that a broken Flow YAML is found at once.

#### Acceptance Criteria

1. THE Flow_Hook SHALL be the file `.kiro/hooks/flow-yaml-check.json` in the Kiro hook format `v1`, with one hook whose trigger is `PostFileSave`.
2. THE Flow_Hook SHALL have a `matcher` regular expression that matches the path of each file `greenscreen/flow/flows/<name>.yaml`, written with either `/` or `\` as separator and either relative or absolute, and that matches no other path.
3. THE Flow_Hook SHALL have the action type `command` with the command `python tests/hook_pytest.py tests/unit/test_flow_bundled.py tests/unit/test_flow_sync.py tests/unit/test_flow_command_sync.py -p no:cacheprovider`.
4. THE Flow_Hook SHALL set `timeout` to 120 and `enabled` to `true`.
5. WHEN a bundled Flow YAML file is saved, THE command of the Flow_Hook SHALL run `check_flow` for every bundled Flow against the bundled signatures, SHALL compare each shipped file with `Flow.to_yaml()` and SHALL run the Flow sync tests.
6. IF one of these tests fails, THEN THE command of the Flow_Hook SHALL exit with a code other than 0 and SHALL write the pytest report to standard error.
7. THE Flow_Hook SHALL contain no secret, no host value and no environment variable name.
8. THE Flow_Hook SHALL not run the Flow_Check_CLI, because the Kiro documentation read on 2026-11-20 gives no path variable, no placeholder and no environment variable for the saved file, and names no member of the standard-input JSON that carries it (Finding 14).

### Requirement 4: A hook that checks the captures when one is created or saved

**User Story:** As a maintainer of real host captures, I want Kiro to run the password scan and the inventory checks whenever a capture file changes, so that a capture that holds a password or an unlisted file is found at once.

#### Acceptance Criteria

1. THE Capture_Hook SHALL be the file `.kiro/hooks/captures-check.json` in the Kiro hook format `v1`, with two hooks: one with the trigger `PostFileCreate` and one with the trigger `PostFileSave`.
2. THE Capture_Hook SHALL give both hooks the same `matcher`, a regular expression that matches the path of every file directly inside a directory named `captures`, with either separator and either relative or absolute, and that matches no file outside such a directory.
3. THE Capture_Hook SHALL give both hooks the same command: `python tests/hook_pytest.py` followed by the pytest node ids of the password and hidden-field checks of `tests/unit/test_flow_captures.py`, the file `tests/unit/test_command_capture_files.py` and the file `tests/unit/test_recognizer_capture_inventory.py`, then `-p no:cacheprovider`.
4. THE Capture_Hook SHALL set `timeout` to 120 and `enabled` to `true` on both hooks.
5. WHEN a file in `captures/` is created or saved, THE command of the Capture_Hook SHALL run the checks that no capture holds the password in plain, lower-case, upper-case or hex form, that no capture has a non-blank hidden cell, that the capture set is exactly the expected names and that the hashes of the promoted files are unchanged.
6. WHILE the environment variable `TK5_PASSWORD` is not set, THE tests that scan for the password SHALL skip with a reason and the remaining checks SHALL still run.
7. THE Capture_Hook SHALL contain no secret, no host value and no environment variable value.

### Requirement 5: A test that checks the hook files

**User Story:** As a maintainer, I want a test that parses the hook files, so that a typo in a pattern or a renamed test does not turn a hook into a silent no-op.

#### Acceptance Criteria

1. THE Hook_Test SHALL parse every `*.json` file under `.kiro/hooks` and SHALL assert `version` equal to `"v1"`, a non-empty `hooks` list, and for each hook a non-empty `name` and `description`, a `trigger` that is `PostFileSave` or `PostFileCreate`, a `matcher` that `re.compile` accepts, an `action` of type `command` and a `timeout` between 1 and 300.
2. THE Hook_Test SHALL assert that each `matcher` matches the eight bundled Flow files (Flow_Hook) or a sample of capture file names (Capture_Hook) in all four path forms (relative or absolute, `/` or `\`), and does not match the paths `greenscreen/recognizer/signatures/tso-ready.yaml`, `greenscreen/flow/flows/__init__.py`, `captures-notes.txt` and `tests/unit/test_flow_bundled.py`.
3. THE Hook_Test SHALL assert that every path in a command exists, and that every node id `file::name` names a function defined in that file.
4. THE Hook_Test SHALL assert that every command starts with `python tests/hook_pytest.py`, ends with `-p no:cacheprovider`, contains no `1>&2` and no `-m pytest`, and contains no `-q` and no `-x`, and that no command contains `greenscreen.flow.check`.
5. THE Hook_Test SHALL assert that no hook file contains a `GS_` or `TK5_` name, a URL or an IPv4 address.
6. THE Hook_Test SHALL assert that every Hook_File is named in the README (Requirement 2, criterion 5) and that `.gitignore` does not hide `.kiro/hooks`.
7. IF a Hook_File does not parse, THEN THE Hook_Test SHALL fail and name the file.

### Requirement 6: A command that checks one Flow file

**User Story:** As a Flow author, I want to check one Flow YAML file from the command line, so that I find a broken file before the Publisher refuses to start and so that a script or a hook can use the result.

#### Acceptance Criteria

1. THE Flow_Check_CLI SHALL accept exactly one argument, the path of a YAML file, SHALL define no option, and SHALL print only the lines that criteria 2 to 8 define, never a traceback.
2. WHEN the argument names a readable UTF-8 YAML mapping that holds a valid Flow, THE Flow_Check_CLI SHALL run `check_flow` against the bundled signatures, print `ok: <file name>` to standard output and exit with code 0.
3. IF the file is a YAML mapping and the Flow reader or `check_flow` reports a violation, THEN THE Flow_Check_CLI SHALL print `violation: ` followed by the message of the `FlowDefinitionError` (step index, step kind, field name and rule name) to standard error and exit with code 1.
4. IF the command line has no argument, more than one argument, an argument that starts with `-` or an empty argument, THEN THE Flow_Check_CLI SHALL print one `usage:` line to standard error and exit with code 2.
5. IF the file does not exist, is not a regular file or cannot be read, THEN THE Flow_Check_CLI SHALL print `error: file not found or not readable` to standard error and exit with code 3.
6. IF the file is not valid UTF-8, is not parsable as YAML or is not a YAML mapping, THEN THE Flow_Check_CLI SHALL print `error: not a YAML mapping` to standard error, followed by ` (line L, column C)` when the parser gives a position, and exit with code 4.
7. IF the bundled signatures cannot be loaded, THEN THE Flow_Check_CLI SHALL print `error: bundled signatures could not be loaded` to standard error and exit with code 5.
8. THE Flow_Check_CLI SHALL print only the last component of the path, the fixed texts above and the `FlowDefinitionError` message, SHALL replace every character outside 0x20 to 0x7E with `?` and SHALL cut every line at 200 characters, so that no free-text value of the file (a description, an example or a text to type), no screen cell, no environment variable and no directory name is printed; the message names fields, rules and at most a signature name or key name of the file.
9. THE Flow_Check_CLI SHALL read no environment variable, write no file, open no network connection and no host session, and import no code of `greenscreen/connector`.
10. THE Flow_Check_CLI SHALL use exactly the six Check_Exit_Codes, each for exactly one situation above.
11. FOR ALL file contents, THE Flow_Check_CLI SHALL exit with 0 when `Flow.from_yaml` accepts the text with the bundled signatures and with a non-zero code when it does not (agreement property).
12. THE Test_Suite SHALL contain unit tests for a good file, a bad file with a violation, a missing file and a non-YAML file, each with the exit code and the printed text, plus a usage error, a directory given as the file, a call of the module as `python -m greenscreen.flow.check` in a subprocess, and a test that the six exit codes are distinct.

### Requirement 7: An optional example question in the Flow definition

**User Story:** As a Flow author, I want to write one example question into a Flow, so that the console can offer it without the page knowing the Flow.

#### Acceptance Criteria

1. THE Flow_Model SHALL give `Flow` an optional member `example`, a string with the default `""`, placed after `timeouts` so that existing positional construction is unchanged.
2. THE Flow_YAML SHALL read the optional top-level key `example` as a string and SHALL write it directly after `description` only when the value is not empty, with the schema version still 1.
3. THE Flow_Validator SHALL accept an `example` of 1 to 200 characters, all printable ASCII (0x20 to 0x7E), that does not contain the two characters `${`.
4. IF `example` is longer than 200 characters, contains a character outside 0x20 to 0x7E, or contains `${`, THEN THE Flow_Validator SHALL raise `FlowDefinitionError` with the field name `example` and one of the rule names `too_long`, `invalid_text` or `interpolation_marker`, and the message SHALL hold no YAML scalar.
5. THE Flow_YAML SHALL write a Flow without an `example` to the same text as before this spec, byte for byte.
6. FOR ALL valid Flows, THE Flow_YAML SHALL satisfy `Flow.from_yaml(flow.to_yaml()) == flow` with and without an `example` (round-trip property).
7. THE Flow_Runner SHALL not read `example`, and a run result and an audit record SHALL not contain it.

### Requirement 8: Six example questions, published with the tool when Ask offers it

**User Story:** As a console user, I want each tool that Ask offers to carry an example question, so that I can try it with one click, and I want no example for a tool that Ask would refuse.

#### Acceptance Criteria

1. THE Bundled_Flow files `tk5-system-info.yaml`, `tk5-time.yaml`, `tk5-list-datasets.yaml`, `tk5-dataset-info.yaml`, `tk5-library-members.yaml` and `tk5-job-status.yaml` SHALL each carry an `example` that is a question ending with `?`, between 10 and 120 characters long, and the files `tk5-logon.yaml` and `tk5-logoff.yaml` SHALL carry none.
2. THE `example` of `tk5-library-members` SHALL be `Which members does SYS2.JCLLIB have?` and the `example` of `tk5-time` SHALL be `What time is it on the mainframe?`.
3. THE `example` of each of `tk5-dataset-info` and `tk5-library-members` SHALL contain a data set name that matches the `dsname` input rule of the Flow.
4. WHERE Ask is enabled, WHEN the OpenAPI_Document is built, THE Publisher SHALL add the member `x-ask-example` to the operation of each Flow that is in the Ask_Offered_Set and whose `example` is not empty, with the example text as its value, and SHALL add no other member. The Ask_Offered_Set SHALL be read from the Ask_Plan through a read-only property of the Ask_Service, so that the result of `plan_ask`, which honours `GS_ASK_FLOWS`, is the only source.
5. WHERE Ask is not enabled, THE Publisher SHALL add no `x-ask-example` member to any operation, whatever the `example` of the Flows.
6. WHEN a Flow is not in the Ask_Offered_Set or its `example` is empty, THE Publisher SHALL add no `x-ask-example` member to its operation.
7. THE Publisher SHALL build the OpenAPI_Document from the registry, the version and the Ask_Plan only, all of which are immutable after startup, so that the document built once at startup and served from memory is equal to the document that a rebuild at any later time would give; no request, no setting and no environment variable read after startup SHALL change it.
8. THE OpenAPI_Document SHALL contain none of the keys `default`, `example`, `examples`, `const` and `enum`, as before this spec.
9. THE Publisher SHALL leave the MCP `tools/list` result, every request schema, every response schema and every error body unchanged by this requirement.
10. THE Publisher SHALL not write an `example` text to a log record.
11. THE Test_Suite SHALL contain server-side tests over the OpenAPI_Document of the six Published_Tools with these cases: (a) Ask off: no `x-ask-example` anywhere; (b) Ask on with all six tools offered: exactly six `x-ask-example` members, one per tool, equal to the six examples; (c) Ask on with `GS_ASK_FLOWS` limited to two Flows: exactly those two Flows have the member and the other four have none.

### Requirement 9: The Ask panel shows one example per tool that Ask offers

**User Story:** As a console user, I want one example question for each tool that Ask offers, phrased as a real question, so that I can see what the mainframe can answer, and I want no example button when Ask is off.

#### Acceptance Criteria

1. THE Console_Script SHALL read the member `x-ask-example` of each operation of the OpenAPI_Document into the listing item of the Flow, as a string, and SHALL treat any other type as absent.
2. THE Example_Builder SHALL return one Ask_Example for each Flow of the listing that has a valid name, no secret input and a valid example, in listing order, up to the limit it is given. A valid example is a non-empty string of printable ASCII (0x20 to 0x7E).
3. WHEN a Flow has a valid example, THE Example_Builder SHALL use the example as the Ask_Example text, whether or not the Flow has a required input.
4. IF a Flow has no valid example, THEN THE Example_Builder SHALL skip the Flow and SHALL build no generic text for it.
5. WHILE the listing holds no `x-ask-example` member, THE Console_Script SHALL show no Ask_Example button.
6. WHERE a maximum question length is passed to the Example_Builder, THE Example_Builder SHALL skip every Ask_Example whose text is longer than that length.
7. THE Example_Builder SHALL define the constant Ask_Example_Max with the value 12, SHALL treat every limit above 12 as 12, and SHALL never return more than 12 items whatever the limit and the listing.
8. THE Console_Script SHALL pass Ask_Example_Max and the question limit from the Ask schema, so that the demo with six Published_Tools offered by Ask shows six Ask_Example buttons.
9. WHEN a visitor clicks an Ask_Example button, THE Console_Script SHALL put the example text into the question field, update the counter and focus the field, as before.
10. THE Console_Page SHALL contain no list of Flow names, no list of example questions and no new request path, and every Content-Security-Policy and route pin of the console SHALL stay as it is.
11. THE Ask panel SHALL show the example text as the button text and the hint as the line below it.
12. THE Test_Suite SHALL contain page tests, run under Node over the real OpenAPI_Document of the six Published_Tools, with these cases: (a) Ask off: zero Ask_Example buttons and no `x-ask-example` member; (b) Ask on with all six tools: six items and six buttons; (c) Ask on with `GS_ASK_FLOWS` limited to two Flows: exactly those two items and two buttons; and cap tests at exactly 12 listed Flows (12 items) and at 13 listed Flows (12 items), each also with the limit 13 passed.

### Requirement 10: A hint is never cut in the middle of a word

**User Story:** As a console user, I want the hint under each example to read as a whole sentence or to end at a word with an ellipsis, so that no hint ends with a broken word.

#### Acceptance Criteria

1. THE Hint_Builder SHALL replace every character outside 0x20 to 0x7E with a blank, collapse runs of blanks to one blank and trim the text before it does anything else.
2. WHEN the text has a sentence end (`.`, `!` or `?` followed by a blank or by the end of the text), THE Hint_Builder SHALL start from the first sentence, including its end mark.
3. WHEN the starting text is 100 characters or shorter, THE Hint_Builder SHALL return it unchanged.
4. WHEN the starting text is longer than 100 characters, THE Hint_Builder SHALL cut it before the last blank that leaves 97 characters or fewer, remove trailing blanks and sentence marks, and append `...`.
5. IF the starting text has no blank within its first 97 characters, THEN THE Hint_Builder SHALL return the empty string.
6. FOR ALL strings, THE Hint_Builder SHALL return a string of at most 100 printable ASCII characters in which every word before an appended `...` is a whole word of the input.
7. THE Example_Builder SHALL use the Hint_Builder on the description of the listing item, or on its summary text when it has no description.

### Requirement 11: Multi-line outputs use a smaller font

**User Story:** As a console user, I want a long list in a result to fit in its scroll box in a readable size, so that 20 or more lines are visible without scrolling.

#### Acceptance Criteria

1. THE Snippets_Module SHALL export a function `outputClass` that returns the string `multiline` for a text that contains LF and `null` for every other text.
2. WHEN the Console_Script shows an output value, THE Console_Script SHALL set the class returned by `outputClass` on the `dd` element of that value.
3. THE Console_CSS SHALL keep the rule `.outputs dd` as it is, including `font-size: 2rem`, so that a single value keeps its size.
4. THE Console_CSS SHALL have a rule `.outputs dd.multiline` that sets `font-size` to a `rem` value of at least 0.8 and at most 1, and `line-height` to a number, such that `24 / (font-size * line-height)` is at least 20.
5. THE Console_CSS SHALL add no colour literal, no new custom property, no `url(`, no font file and no animation.
6. WHEN the Multi_Line_Value of `MEMBERS` has 136 lines, THE Console_Page SHALL show the first 20 lines without scrolling and the rest by scrolling inside the box.

### Requirement 12: The key is read when the address fragment changes

**User Story:** As a user who opens the console with a key link, I want a second `#key=` link in the same tab to take effect, so that I do not have to reload the page.

#### Acceptance Criteria

1. THE Console_Script SHALL register a `hashchange` listener on `window` after the error table has loaded.
2. WHEN the address fragment starts with `#key=` and the percent-decoded text after it is not empty, THE Fragment_Reader SHALL adopt that text as the API key, mark the key as held and report that it took a key.
3. WHEN the address fragment starts with `#key=`, THE Fragment_Reader SHALL call `history.replaceState(null, "", pathname + search)` exactly once, whether or not the key text is empty.
4. WHEN the address fragment does not start with `#key=`, THE Fragment_Reader SHALL change nothing and call nothing.
5. IF the percent-decoding of the key text fails, THEN THE Fragment_Reader SHALL adopt the raw text, as on load.
6. WHEN the Fragment_Reader reports that it took a key and no call is running, THE Console_Script SHALL hide the key panel and load the flow listing with the new key.
7. WHILE a call is running, THE Console_Script SHALL adopt a new key and SHALL not load the listing until the visitor acts again.
8. THE Console_Script SHALL still call `history.replaceState` before its first `fetch(`, SHALL still read `apiKey` only inside `apiFetch`, SHALL never assign `location.hash`, and SHALL use no storage and no cookie.
9. WHEN the page loads with a `#key=` fragment, THE Fragment_Reader SHALL behave as before this requirement.

### Requirement 13: A Count_Output in the Flow definition

**User Story:** As a Flow author, I want an output that holds the number of rows of another output, so that a caller does not have to count lines.

#### Acceptance Criteria

1. THE Flow_Model SHALL give `OutputSpec` an optional member `counts`, a string with the default `None`, placed after `equals` so that existing positional construction is unchanged.
2. THE Flow_YAML SHALL read the optional output key `counts` as a string and SHALL write it after `equals` only when it is not `None`, with the schema version still 1.
3. THE Flow_Validator SHALL accept a Count_Output only when its `type` is `int`, its `counts` names another declared output that has `max_rows`, and its `signature`, `row`, `col` and `length` equal those of the named output.
4. IF an output with `counts` has `max_rows`, `next_row` or `equals`, THEN THE Flow_Validator SHALL reject it with the rule `counts_excludes_extras`.
5. IF `counts` names no declared output, names the output itself or names an output without `max_rows`, THEN THE Flow_Validator SHALL reject it with the rule `counts_unknown_output` or `counts_target_not_rows`.
6. IF the type of a Count_Output is not `int` or its region differs from that of the named output, THEN THE Flow_Validator SHALL reject it with the rule `counts_requires_int` or `counts_region_mismatch`.
7. IF an `extract` or `collect` step names a Count_Output, THEN THE Flow_Validator SHALL reject the Flow with the rule `counts_not_readable`, and THE Flow_Validator SHALL not require a read step for a Count_Output.
8. FOR ALL valid Flows with a Count_Output, THE Flow_YAML SHALL satisfy `Flow.from_yaml(flow.to_yaml()) == flow` (round-trip property).
9. THE Flow_Validator messages for these rules SHALL hold only the rule name, the field name and the output name, never a YAML scalar.

### Requirement 14: The Flow_Runner sets the count

**User Story:** As a caller, I want the count to equal the number of lines that I receive, so that I can rely on it.

#### Acceptance Criteria

1. WHEN a `collect` or `extract` step stores the value of a Rows_Output, THE Flow_Runner SHALL store, for every Count_Output that names it, the number of rows read, as an `int`.
2. FOR ALL runs that succeed, THE Flow_Runner SHALL give a Count_Output the value 0 when the Rows_Output value is the empty string, and otherwise the number of LF-separated lines of the Rows_Output value.
3. THE Flow_Runner SHALL always include a Count_Output in the result of a successful run, in declaration order, with the value 0 when no row was read.
4. IF a run stops with an error, THEN THE Flow_Runner SHALL return no outputs, as before.
5. THE Flow_Runner SHALL add no step, no key, no screen read and no audit record for a Count_Output, and a run SHALL send the same keys with and without a Count_Output.
6. THE Flow_Runner SHALL store a Count_Output as a Python `int` that is not a `bool`.
7. THE Flow_Runner SHALL not log, raise or store row text while it sets a Count_Output.

### Requirement 15: `tk5-library-members` returns `MEMBER_COUNT`

**User Story:** As a model or an app that calls `tk5-library-members`, I want the number of members as an integer, so that "how many members" is a lookup and not a count.

#### Acceptance Criteria

1. THE Bundled_Flow `tk5-library-members` SHALL declare a second output `MEMBER_COUNT` of type `int` with `counts: MEMBERS` after `MEMBERS`, and SHALL otherwise keep its steps, inputs and timeouts.
2. THE description of `tk5-library-members` SHALL say, in at most 500 characters and without the characters `;`, `#` and `@`, that `MEMBER_COUNT` is the number of names in `MEMBERS`.
3. WHEN `tk5-library-members` runs over the seven real member pages, THE Flow_Runner SHALL return `MEMBER_COUNT` 136 and a `MEMBERS` value of 136 lines.
4. WHEN `tk5-library-members` runs for a data set that is not in the catalog or has no members, THE Flow_Runner SHALL return `MEMBER_COUNT` 0 and `MEMBERS` equal to the empty string.
5. THE Publisher SHALL list `MEMBER_COUNT` in the REST response schema, the MCP `outputSchema` and the OpenAPI_Document of `tk5-library-members` as `{"type": "integer"}`, and SHALL list both outputs in `required`, in declaration order.
6. THE Ask result projection SHALL keep `MEMBER_COUNT` as an integer and SHALL change no code.
7. THE Console_Page SHALL show `MEMBER_COUNT` as a single value in the large font and SHALL change no code for it.
8. THE result text that Ask shows the model for the seven real member pages SHALL stay below the limit of 4000 characters.
9. THE output schema of `tk5-library-members` SHALL be written out in full in the design, and THE Test_Suite SHALL contain a test that the generated schema equals it.
10. THE design SHALL write out the `/openapi.json` operation of `tk5-library-members` for the demo configuration with Ask on and the Flow offered (request schema, 200 response schema, `x-ask-example`), and THE Test_Suite SHALL contain a test that the generated operation equals it.

### Requirement 16: Stale text is corrected

**User Story:** As a reader of the specs and tests, I want names and numbers that match the code, so that nothing misleads me.

#### Acceptance Criteria

1. THE Spec_Text `.kiro/specs/linux-readiness/design.md` (lines 67 and 376) and `.kiro/specs/linux-readiness/requirements.md` (line 22) SHALL say `publishing 1 of 8 flows over stdio` or `publishing 1 of 8` where they now say `publishing 1 of 3`, which is what the Publisher logs with eight loaded Flows and one published Flow.
2. THE Spec_Text `.kiro/specs/console/design.md` (line 298), `.kiro/specs/console/requirements.md` (line 42), `.kiro/specs/ask/design.md` (line 1312) and `.kiro/specs/ask/tasks.md` (line 447) SHALL say `publishing 1 of 8` (and `publishing 1 of 8 flows over http` where the line says `flows over http`) where they now say `publishing 1 of 3`.
3. BEFORE it edits, THE executor SHALL search every file under `.kiro/specs/console` and `.kiro/specs/ask` for the text `1 of 3` and SHALL fix every occurrence that states what the Publisher logs; an occurrence that is not that log line SHALL be reported and left.
4. THE file `.kiro/specs/linux-readiness/sigterm-diagnostic.txt` SHALL stay byte for byte unchanged, because it records a past run.
5. THE docstring of `tests/property/test_publisher_bindings.py` (line 4) SHALL say "eight bundled Flows" where it says "three bundled Flows", and the docstring of `tests/unit/test_flow_sync.py` (line 1) SHALL name the three Flows `tk5-logon`, `tk5-logoff` and `tk5-system-info` instead of "The three bundled flows".
6. THE test `test_exactly_three_entries_with_expected_keys` in `tests/unit/test_flow_bundled.py` SHALL be renamed `test_exactly_eight_entries_with_expected_keys` with its body unchanged.
7. THE only other place that names the old test is `.kiro/specs/more-flows/tasks.md` (line 109); THE sentence there SHALL name the new test name.
8. THE Test_Suite SHALL contain a stale-text test that scans every file under `.kiro/specs/linux-readiness`, `.kiro/specs/console` and `.kiro/specs/ask`, except the file `sigterm-diagnostic.txt` (which the test SHALL exclude by name and SHALL assert still holds the old text), and fails when a file contains the text `publishing 1 of 3`; and that no file under `tests/` contains the text `test_exactly_three_entries`.
9. THE edits SHALL not touch `.kiro/steering`.

### Requirement 17: Rules for every task

**User Story:** As the reviewer, I want fixed rules that every task of this spec follows, so that the pass changes only what it says.

#### Acceptance Criteria

1. THE executor SHALL not commit, stage or push anything, and SHALL not edit `.kiro/steering`.
2. THE executor SHALL not delete or edit a file that this spec does not name, and SHALL not touch `%TEMP%\more-flows-amend`.
3. THE executor SHALL add no dependency, no framework, no build step and no new file type to `pyproject.toml`.
4. THE executor SHALL print no secret and SHALL write none into a file: the `TK5_*` values, the `GS_BIND_*` values, API keys and model keys never appear in a document, a test or a log.
5. THE executor SHALL keep every temporary file in a folder that it creates and removes, never in a shared location.
6. THE executor SHALL change no existing test except in the way the design table "Every existing-test edit" lists, and SHALL stop and report when another existing test fails.
7. THE executor SHALL run no test that needs the live host, a real model or a browser, and SHALL run the Node tests with `C:\Program Files\nodejs` on `PATH`.
8. THE final task SHALL run the full suite once, write a report file, and stop.
9. THE report file SHALL state the suite counts (passed, skipped, failed) next to the baseline of 4565 passed, 4 skipped and 0 failed, list every existing test that was edited with its value before and after, list the files changed, hold the generated `/openapi.json` fragment of `tk5-library-members` (request schema, 200 response schema and `x-ask-example`), and list the live checks with their exact commands as items that the executor did not run.

## Files

| File | Change |
|---|---|
| `README.md` | rewritten (Requirements 1, 6) |
| `.kiro/hooks/flow-yaml-check.json`, `.kiro/hooks/captures-check.json` | new (Requirements 3, 4) |
| `greenscreen/flow/check.py` | new: the Flow_Check_CLI (Requirement 6) |
| `greenscreen/flow/model.py`, `yamlio.py`, `validate.py`, `runner.py` | `Flow.example`, `OutputSpec.counts` (Requirements 7, 13, 14) |
| `greenscreen/flow/flows/*.yaml` (six of eight) | `example`; `tk5-library-members.yaml` also `MEMBER_COUNT` and description |
| `greenscreen/publisher/rest.py` | `x-ask-example` for offered Flows in `build_openapi` (Requirement 8) |
| `greenscreen/publisher/ask/service.py` | one read-only property `offered` on `AskService` (Requirement 8, criterion 4) |
| `greenscreen/publisher/console/snippets.js`, `console.js`, `console.css` | examples, hint, multi-line class and style, `hashchange` (Requirements 9 to 12) |
| `.kiro/specs/linux-readiness/design.md`, `requirements.md`; `.kiro/specs/console/design.md`, `requirements.md`; `.kiro/specs/ask/design.md`, `tasks.md`; `.kiro/specs/more-flows/tasks.md` | text corrections (Requirement 16) |
| existing tests | the edits of the design table only |
| new tests and test support | listed in the design and the tasks |

## Not verifiable without the live host, a browser or Kiro

The reviewer checks these. The tasks list them in the final report as "not run by the executor".

1. The demo URL answers and the page shows six example buttons, each with a question as text and a whole-word hint, and shows none when Ask is off.
2. A click on each example runs through Ask against the real model and gets a sensible answer.
3. A second `#key=` link in an open tab takes effect and leaves no key in the address bar.
4. With the real 136 members the multi-line font shows at least 20 lines in the box and scrolls the rest.
5. `MEMBER_COUNT` is 136 from the real host, and Ask answers "how many members" from it.
6. Both hooks fire in Kiro on save and create, and a failing run reaches the agent through standard error.
7. The README commands work on Linux with `s3270`.
8. The standard-input JSON that Kiro gives a `PostFileSave` command carries the saved path, under which member name (Finding 14).

## Open decisions

All six decisions below were settled by the reviewer; the text records the outcome.

1. **README lists ten specs, not nine. CONFIRMED.** This spec is the tenth directory of the Spec_Set. A README that said nine would be false the moment this folder exists, and Requirement 2, criterion 4 ties the list to the directories. The README lists all ten and describes `polish` in one line.
2. **Hook action type.** `command`, for a deterministic result without a model call. The alternative `agent` is described in the design and costs a model turn on every save. Hooks keep the shell-command form (reviewer decision).
3. **File-hook payload. DECIDED: the path is not passed.** The documentation says that a file hook receives the saved path on standard input, but names no member, no variable and no placeholder (Finding 14). The Flow hook therefore runs the three test files as designed, and the Flow_Check_CLI is a separate command that a person or a script runs. Reviewer check 8 reads the real payload; if it names a member, a later spec can pass the file.
4. **Examples and `GS_ASK_FLOWS`. DECIDED: handled.** The OpenAPI_Document carries `x-ask-example` only for Flows in the Ask_Offered_Set and only when Ask is enabled; the page shows a button only where the member is present (Requirements 8 and 9).
5. **`MEMBER_COUNT` region fields.** A Count_Output must repeat the region of its Rows_Output (Requirement 13, criterion 3) because `OutputSpec` has four required region members. The spec repeats and validates equality.
6. **Other stale `publishing 1 of 3` text. DECIDED: corrected.** The console and ask spec documents are edited too (Requirement 16, criteria 2 and 3), and the stale-text test covers `linux-readiness`, `console` and `ask`, excluding `sigterm-diagnostic.txt`.

