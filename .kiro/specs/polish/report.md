# Polish: final report (task 13.1)

Run on Windows, PowerShell, Python 3.11, Node `v24.19.0` (prepended to PATH). HEAD is `d2e9d5d more-flows: five read-only TSO command tools, stuck-session release`. Nothing is committed or staged.

## Suite counts

Command: `$env:PATH = "C:\Program Files\nodejs;" + $env:PATH; python -m pytest -m "not integration" -p no:cacheprovider`, run once.

| | Baseline | After | Delta |
|---|---|---|---|
| passed | 4565 | **4780** | +215 |
| skipped | 4 | 4 | 0 |
| failed | 0 | **0** | 0 |
| deselected | 20 | 20 | 0 |

Summary line: `4780 passed, 4 skipped, 20 deselected, 2 warnings in 1118.00s (0:18:38)`. Wall time 18 min 44 s.

Skips (all four are the same as the baseline):
- `tests/unit/test_fake_s3270_descriptors.py:34`: descriptor counting needs `/proc/self/fd` or `/dev/fd`; this is win32.
- `tests/unit/test_flow_strategy_cost.py:51`: perf test is opt-in (`GS_RUN_PERF=1`).
- `tests/unit/test_publisher_cli.py:652`: POSIX only, SIGTERM is a hard kill on Windows (`test_stdio_sigterm_stops_cleanly`).
- `tests/unit/test_publisher_perf.py:22`: perf test is opt-in (`GS_RUN_PERF=1`).

Warnings: two `DeprecationWarning`s from `websockets`/`uvicorn` (third-party, not ours).

New test files and their `def test_` counts (parametrized cases and Hypothesis examples make the collected number larger; 152 functions give the +215):

| File | Test functions |
|---|---|
| tests/unit/test_flow_example.py | 21 |
| tests/unit/test_flow_counts.py | 19 |
| tests/unit/test_readme.py | 19 |
| tests/unit/test_publisher_example.py | 14 |
| tests/unit/test_console_examples.py | 13 |
| tests/unit/test_flow_check.py | 13 |
| tests/unit/test_kiro_hooks.py | 9 |
| tests/unit/test_console_hashchange.py | 8 |
| tests/unit/test_flow_member_count.py | 8 |
| tests/unit/test_polish_stale_text.py | 8 |
| tests/unit/test_console_multiline.py | 5 |
| tests/property/test_console_examples.py | 6 |
| tests/property/test_flow_counts.py | 2 |
| tests/property/test_flow_example.py | 2 |
| tests/property/test_kiro_hook_matchers.py | 2 |
| tests/property/test_console_fragment.py | 1 |
| tests/property/test_flow_check.py | 1 |
| tests/property/test_publisher_example.py | 1 |

Support files without tests: `tests/console_node_extract.py`, `tests/example_support.py`, `tests/hook_pytest.py`.

## Existing tests edited

Each row was checked against `git diff -U0` of the file. No other test file differs from HEAD.

| File::test | Before | After |
|---|---|---|
| tests/unit/test_flow_bundled.py (line 47) | `test_exactly_three_entries_with_expected_keys` | `test_exactly_eight_entries_with_expected_keys`; body unchanged |
| tests/unit/test_flow_sync.py (line 1, docstring) | `The three bundled flows must not drift apart (Requirements 17.11, 17.12, 17.17).` | `The Flows tk5-logon, tk5-logoff and tk5-system-info must not drift apart (Requirements 17.11, 17.12, 17.17).` |
| tests/property/test_publisher_bindings.py (line 4, docstring) | `(after the three bundled Flows, in file order)` | `(after the eight bundled Flows, in file order)` |
| tests/unit/test_flow_command_flows.py::test_library_members_check_flow_and_yaml_round_trip (lines 458, 463, +468-469) | `len(flow.description) == 333`; `(out,) = flow.outputs` | `== 381`; `(out, count) = flow.outputs`; added `(count.name, count.type, count.counts) == ("MEMBER_COUNT", "int", "MEMBERS")` and `(count.signature, count.row, count.col, count.length) == (out.signature, out.row, out.col, out.length)`. The step counts 31 and 6 assertions are untouched. |
| tests/unit/test_flow_command_publish.py (line 38, 146, +149-150) | `OUTPUTS["tk5-library-members"] = {"MEMBERS": {"type": "string"}}`; `... if k != "FOUND"` | `{"MEMBERS": {"type": "string"}, "MEMBER_COUNT": {"type": "integer"}}`; `if k not in ("FOUND", "MEMBER_COUNT")`; added `if name == "tk5-library-members": assert types["MEMBER_COUNT"] == "integer"` |
| tests/unit/test_flow_command_timing.py (line 58) | `MEASURED["tk5-library-members"] = 1335` | `1354` (+19) |
| tests/unit/test_flow_command_timing.py (line 62) | `WORST["tk5-library-members"] = 2053` | `2079` (+26); `max(WORST.values()) == 3285` pin unchanged |
| tests/unit/test_ask_snippets.py::test_ask_examples_limits_and_hostile_values (lines 82-100) | no `example` members; texts `Run ok-one and tell me what it returns.` (and `ok-two`, `ok_3`); `items[1]["hint"] == "b" * 100`; `len(askExamples(flows, 99)) == 3` | `example` on `ok-one`, `ok-two`, `ok_3`, `ok-4` (`What is <name>?`) and a new row `needs-dsname` (required input, example `Which members does SYS2.JCLLIB have?`); texts `What is ok-one?`, `What is ok-two?`, `What is ok_3?`; `items[1]["hint"] == ""`; `len(... 99)) == 5`. `limit 1` still gives 1. |
| tests/unit/test_ask_openapi.py::test_ask_only_adds_the_path_and_the_three_schemas (+187-194) | `assert on == off` after popping `/ask` and the three schemas | before that assert, for each `/flows/*` operation: assert the added members are a subset of `{"x-ask-example"}`, then pop it. The final `assert on == off` stays. |
| tests/property/test_flow_collect_model.py::test_a_bad_screen_in_the_middle_of_a_collect_stops_the_run_at_once (line 196) | `assert clock.now < _T.step` | `assert clock.now < _T.step + 1e-9` with a comment that 1e-9 absorbs float rounding of the summed fake clock. Flagged edit, Decision B. |
| tests/property/test_publisher_parity.py::test_front_ends_agree_and_success_fits_schema (+101-109, 114) | `probes("int", max_size=4)` | `probes("int", max_size=4).filter(lambda n: str(n) not in _SCREEN_TEXT)`; new module constant `_SCREEN_TEXT`, the joined `text_grid` of every state of `mini_states()`. Flagged edit. |

Spec text edits (all single-line, `git diff -U0`):

| File | Line | Before | After |
|---|---|---|---|
| .kiro/specs/linux-readiness/design.md | 67 | `publishing 1 of 3 flows over stdio` | `publishing 1 of 8 flows over stdio` |
| .kiro/specs/linux-readiness/design.md | 376 | `grep -q "publishing 1 of 3"` | `grep -q "publishing 1 of 8"` |
| .kiro/specs/linux-readiness/requirements.md | 22 | `publishing 1 of 3` | `publishing 1 of 8` |
| .kiro/specs/console/design.md | 298 | `publishing 1 of 3` | `publishing 1 of 8` |
| .kiro/specs/console/requirements.md | 42 and 582 | `publishing 1 of 3` | `publishing 1 of 8` (two lines; the design table names only line 42) |
| .kiro/specs/ask/design.md | 1312 | `publishing 1 of 3 flows over http` | `publishing 1 of 8 flows over http` |
| .kiro/specs/ask/tasks.md | 447 | `publishing 1 of 3 flows over http` | `publishing 1 of 8 flows over http` |
| .kiro/specs/more-flows/tasks.md | 108 | `The test name test_exactly_three_entries_with_expected_keys keeps its name (only the numbers change)` | `The test test_exactly_three_entries_with_expected_keys was renamed by the polish spec to test_exactly_eight_entries_with_expected_keys` (the design table says line 109; the diff shows line 108) |

## Files changed

`git diff --cached --name-only` prints nothing. The `git diff --exit-code` over `.kiro/steering pyproject.toml .env.example .gitignore greenscreen/flow/__init__.py greenscreen/connector greenscreen/recognizer greenscreen/publisher/calls.py greenscreen/publisher/app.py greenscreen/publisher/cli.py captures .kiro/specs/linux-readiness/sigterm-diagnostic.txt` exits 0 with no output. `.kiro/steering` is unchanged in this run (checked again after the suite). `git check-ignore .kiro` prints nothing (not ignored). HEAD is unchanged (`d2e9d5d`).

`git diff --stat`: 33 files changed, 479 insertions(+), 74 deletions(-). Git prints LF-to-CRLF warnings for the modified files; no content effect.

Modified (`M`):
- Production: `greenscreen/flow/model.py` (`Flow.example`, `OutputSpec.counts`); `greenscreen/flow/yamlio.py` (new keys, `to_yaml`, `_build_flow`); `greenscreen/flow/validate.py` (example and Count_Output rules); `greenscreen/flow/runner.py` (`_store_rows`, two call sites); `greenscreen/publisher/rest.py` (`x-ask-example`); `greenscreen/publisher/ask/service.py` (only the property `offered`, 5 added lines); `greenscreen/publisher/console/snippets.js` (`hintText`, `askExamples`, `outputClass`, `ASK_EXAMPLE_MAX`); `console.js` (listing, Ask panel, multi-line class, key on `hashchange`); `console.css` (rule `.outputs dd.multiline`).
- Flows: `greenscreen/flow/flows/tk5-{dataset-info,job-status,library-members,list-datasets,system-info,time}.yaml` (an `example` line each; `tk5-library-members` also `MEMBER_COUNT` and a new description).
- Docs: `README.md` (rewritten, 262 lines changed; modified, not new).
- Tests (11): `tests/property/{test_flow_collect_model,test_publisher_bindings,test_publisher_parity}.py`; `tests/unit/{test_ask_openapi,test_ask_snippets,test_flow_bundled,test_flow_command_flows,test_flow_command_publish,test_flow_command_timing,test_flow_sync}.py`.
- Specs (7): `.kiro/specs/ask/{design,tasks}.md`, `console/{design,requirements}.md`, `linux-readiness/{design,requirements}.md`, `more-flows/tasks.md`.

New (`??`):
- Hooks: `.kiro/hooks/flow-yaml-check.json`, `.kiro/hooks/captures-check.json`.
- Spec: `.kiro/specs/polish/` (requirements, design, tasks, meta, config, this report).
- Production: `greenscreen/flow/check.py` (the check command, six exit codes).
- Test support: `tests/console_node_extract.py`, `tests/example_support.py`, `tests/hook_pytest.py`.
- New tests: the 18 files of the table above.

Secret scan over the 62 new and changed files (counts only): `TK5_PASSWORD` value 0 files. The user id string occurs in 2 files, `.kiro/specs/ask/design.md` and `tasks.md`, as the stock demo account in existing spec text that this task did not change (only the one `1 of 3` line in each). IPv4 other than `127.0.0.1`: 6 matches in 3 files, none from this work: `192.168.68.72` x3 in `.kiro/specs/more-flows/tasks.md` (existing text), `127.0.0.2` and `0.0.0.0` in `.kiro/specs/ask/design.md` (existing text), and `10.1.2.3` in `tests/unit/test_readme.py` (a test of the README's IP rule, not a host).

`validate_spec_format`: `requirements.md`, `design.md`, `tasks.md` of the polish spec: no format issues.

## `/openapi.json` fragment

Generated with `six_tool_document` of `tests/example_support.py`, Ask on, `GS_ASK_FLOWS` unset, test-only generated bindings and keys (none printed). Offered operations with `x-ask-example`: all six (`tk5-dataset-info`, `tk5-job-status`, `tk5-library-members`, `tk5-list-datasets`, `tk5-system-info`, `tk5-time`). Operation `paths["/flows/tk5-library-members"]["post"]`; the error responses 400, 401, 404, 413, 422, 429, 500, 502, 503 and 504 are the same `$ref ErrorBody` shape as for every Flow and are abbreviated here with `...` (the full object was printed by the run):

```json
{
  "operationId": "tk5-library-members",
  "summary": "List the member names of a partitioned data set (library) by name (TSO LISTDS with MEMBERS). MEMBERS holds one member name per line, in the host's order, up to 200. MEMBER_COUNT is the number of names in MEMBERS. A longer list stops the call with an error. An empty MEMBERS means the library has no members or does not exist. Call tk5-dataset-info to tell the two apart. Read-only.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "dsname": {
              "type": "string",
              "maxLength": 44,
              "pattern": "^(?:[A-Za-z$#@][A-Za-z0-9$#@]{0,7}(?:\\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21})$",
              "description": "Data set name, e.g. SYS2.JCLLIB, any case. Up to 44 characters. Dot-separated qualifiers of 1-8 characters, each starting with a letter, dollar, number sign or at sign, then letters, digits or those."
            }
          },
          "additionalProperties": false,
          "required": ["dsname"]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "The flow finished.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "flow": {"type": "string"},
              "outputs": {
                "type": "object",
                "properties": {
                  "MEMBERS": {"type": "string"},
                  "MEMBER_COUNT": {"type": "integer"}
                },
                "additionalProperties": false,
                "required": ["MEMBERS", "MEMBER_COUNT"]
              },
              "audit": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "step_index": {"type": "integer"},
                    "kind": {"type": "string"},
                    "phase": {"type": "string"},
                    "iteration": {"type": ["integer", "null"]},
                    "signature": {"type": ["string", "null"]},
                    "status": {"type": "string"},
                    "duration_seconds": {"type": "number"}
                  },
                  "additionalProperties": false,
                  "required": ["step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds"]
                }
              }
            },
            "additionalProperties": false,
            "required": ["flow", "outputs", "audit"]
          }
        }
      }
    },
    "400": {"description": "Error. Error codes with this status: request_invalid.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}}},
    "401": "... same shape (unauthorized)",
    "404": "... same shape (unknown_flow)",
    "413": "... same shape (request_too_large)",
    "422": "... same shape (input_invalid)",
    "429": "... same shape (busy)",
    "500": "... same shape (internal_error)",
    "502": "... same shape (ambiguous_screen, bad_target, hidden_output, host_unavailable, loop_limit, output_type, screen_size, secret_target, session_error, unexpected_screen, unknown_screen)",
    "503": "... same shape (shutting_down)",
    "504": "... same shape (call_timeout, run_timeout, timeout)"
  },
  "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
  "x-ask-example": "Which members does SYS2.JCLLIB have?"
}
```

(The `"401"` to `"504"` lines above are shorthand for the real response objects; they are not valid OpenAPI as written.)

Ask off: `x-ask-example` present on the `tk5-library-members` operation is `False`.

The throwaway folder `%TEMP%\polish-13.1` was created and removed.

## Hook path

Not documented. The Kiro hook pages do not show how the saved file's path reaches a `command` action (path variable, environment variable or a member of the standard-input JSON), so the Flow hook does not call `python -m greenscreen.flow.check`. It runs the three test files `tests/unit/test_flow_bundled.py`, `test_flow_sync.py`, `test_flow_command_sync.py`, which cover every bundled Flow. The check command stays for hand use. The captures hook (`PostFileCreate` and `PostFileSave`, matcher on `captures/<file>`) runs five named capture tests plus `test_command_capture_files.py` and `test_recognizer_capture_inventory.py`. The case and the four documentation URLs with dates are in the design, section "Hook payload finding" (task 10.1).

## Cap

`ASK_EXAMPLE_MAX = 12`, defined at `greenscreen/publisher/console/snippets.js:662`; `askExamples(flows, limit)` returns at most `min(limit, 12)` items. Cap tests: `tests/property/test_console_examples.py::test_cap_is_twelve` (12 Flows with examples give 12 for limits 12 and 13; 13 Flows give 12 for both) and the unit tests of `tests/unit/test_console_examples.py`.

## Check command

`python -m greenscreen.flow.check <file.yaml>` (`greenscreen/flow/check.py`): 0 valid (`ok: <name>`), 1 violation (`violation: <message>`), 2 usage (also for a flag or an empty argument), 3 file missing or unreadable, 4 not a YAML mapping (with line and column for a parse error), 5 bundled signatures could not be loaded. Output goes to stderr except the `ok` line, is printable ASCII only and at most 200 characters, and carries no YAML value.

## Not run by the executor

Placeholders: `<YOUR_API_KEY>` (16+ characters), `<LLM_BASE_URL>`, `<LLM_MODEL>`, `<MAINFRAME_HOST>`. One session per user id: stop the Publisher before an integration test; never run two checks at once. The demo account comes from the shell and no command prints it.

Common setup for checks 2 to 6 (fresh PowerShell per Publisher run):

```powershell
$env:GS_HOST = "<MAINFRAME_HOST>"; $env:GS_PORT = "3270"
$env:GS_S3270_BINARY = "<path to ws3270.exe>"
$env:GS_PUBLISH_HOST = "127.0.0.1"; $env:GS_PUBLISH_PORT = "8080"
$env:GS_ENABLE_CONSOLE = "true"
$env:GS_PUBLISH_FLOWS = "tk5-system-info,tk5-time,tk5-list-datasets,tk5-dataset-info,tk5-library-members,tk5-job-status"
Set-Item -Path Env:GS_API_KEY -Value (Read-Host "API key (16 characters or more)")
foreach ($f in "TK5_SYSTEM_INFO","TK5_TIME","TK5_LIST_DATASETS","TK5_DATASET_INFO","TK5_LIBRARY_MEMBERS","TK5_JOB_STATUS") {
  Set-Item -Path "Env:GS_BIND_${f}__USERID" -Value $env:TK5_USERNAME
  Set-Item -Path "Env:GS_BIND_${f}__PASSWORD" -Value $env:TK5_PASSWORD
}
```

1. **Check command (no host).**
   - `python -m greenscreen.flow.check greenscreen\flow\flows\tk5-time.yaml; $LASTEXITCODE` prints `ok: tk5-time.yaml` and `0`.
   - `python -m greenscreen.flow.check no-such.yaml; $LASTEXITCODE` prints the not-found line and `3`.
   - `python -m greenscreen.flow.check; $LASTEXITCODE` prints a `usage:` line and `2`.
   - Copy a Flow file to `$env:TEMP`, change one signature name, run the command on it: exit `1`, the line names the rule. Run it on `README.md`: exit `4`.
2. **Demo URL and `#key=` clearing, Ask off.** Start `greenscreen-publish` with the common setup (no `GS_ENABLE_ASK`). In a second shell: `curl.exe -s -H "X-API-Key: <YOUR_API_KEY>" http://127.0.0.1:8080/openapi.json | python -c "import json,sys; d=json.load(sys.stdin); print([k for k,v in d['paths'].items() if 'x-ask-example' in v.get('post',{})])"` expects `[]`. Open `http://127.0.0.1:8080/#key=<YOUR_API_KEY>` (and the demo URL in the README with its own key): the key panel hides, the list loads, the fragment is cleared; the Ask panel is hidden and there is no example button.
3. **Ask on, six offered, six buttons and hints.** Add `$env:GS_ENABLE_ASK = "true"; $env:GS_LLM_BASE_URL = "<LLM_BASE_URL>"; $env:GS_LLM_MODEL = "<LLM_MODEL>"; Set-Item -Path Env:GS_LLM_API_KEY -Value (Read-Host "model key")` and restart. The same `curl.exe` command prints six names. `curl.exe -s -H "X-API-Key: <YOUR_API_KEY>" http://127.0.0.1:8080/openapi.json | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['paths']['/flows/tk5-library-members']['post'], indent=2))"` prints the operation above. The page shows six buttons in listing order, each hint a whole sentence or ending in `...` after a whole word; a click fills the question field and Ask answers from the matching tool.
4. **Ask on, two offered.** Add `$env:GS_ASK_FLOWS = "tk5-time,tk5-job-status"`, restart. The `curl.exe` command prints exactly `['/flows/tk5-time', '/flows/tk5-job-status']` and the page shows two buttons.
5. **Second `#key=` link in the same tab.** With the page open, paste a second `#key=<YOUR_API_KEY>` link into the same tab: the key panel hides, the list reloads, the fragment is gone. Repeat with a wrong key: the key panel returns with the 401 text.
6. **Multi-line font, 136 members, `MEMBER_COUNT`.**
   - In the page, run `tk5-library-members` for `SYS2.JCLLIB`: the `MEMBERS` box shows at least 20 lines at the smaller size and scrolls; `MEMBER_COUNT` shows `136` at the large size.
   - REST (PowerShell): `curl.exe -s -X POST -H "X-API-Key: <YOUR_API_KEY>" -H "Content-Type: application/json" -d "{\"dsname\":\"SYS2.JCLLIB\"}" http://127.0.0.1:8080/flows/tk5-library-members | python -c "import json,sys; print(json.load(sys.stdin)['outputs']['MEMBER_COUNT'])"` prints `136`.
   - REST (bash): `curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"dsname":"SYS2.JCLLIB"}' http://127.0.0.1:8080/flows/tk5-library-members | python3 -c "import json,sys; print(json.load(sys.stdin)['outputs']['MEMBER_COUNT'])"` prints `136`.
   - With Ask on, ask "How many members does SYS2.JCLLIB have?": the answer says 136.
7. **Hooks (in Kiro).** Save a bundled Flow YAML: the hook card shows the Flow hook ran. Break a Flow on purpose (unknown signature name) and save: the agent receives the pytest report. Create and save a file under `captures/`: the capture hook runs on create and on save and the inventory test reports the new file. Also save once from the editor by hand (not by the agent) and check that `PostFileSave` fires.
8. **Hook payload probe (settles Decision A3).** Add the throwaway file `.kiro/hooks/zz-payload.json`, delete it afterwards, do not commit it:
   `{"version":"v1","hooks":[{"name":"payload probe","trigger":"PostFileSave","matcher":"\\.yaml$","action":{"type":"command","command":"python -c \"import sys; sys.stderr.write(sys.stdin.read()); sys.exit(1)\""},"timeout":10}]}`
   Save any `.yaml`: the agent receives the JSON on standard error. Record the member that holds the path. If it exists, the Flow hook can call `python -m greenscreen.flow.check <saved path>` before the three tests (open item 3 of the design).
9. **README on Linux with `s3270`.** On a Linux box with `s3270` installed, follow the README commands from a clean virtual environment up to a `/health` answer.
10. **SIGTERM on Linux.** `python -m pytest tests/unit/test_publisher_cli.py -k test_stdio_sigterm_stops_cleanly -p no:cacheprovider` (skipped on Windows). It waits for `publishing 1 of 8` on stderr (the log line now counts eight bundled Flows), sleeps 1 s, sends SIGTERM and expects exit code 0 within 30 s.

## Notes and deviations

- **`1>&2` replaced by `tests/hook_pytest.py`.** The design first allowed a `1>&2` suffix; Decision A2b rejected it because it is shell dependent. The hooks run `python tests/hook_pytest.py <pytest args>`, which redirects stdout to stderr inside the process and returns pytest's exit code. A passing hook is silent; a failure reaches the agent on stderr.
- **Hook path finding.** The documentation gives no usable carrier for the saved path, so the Flow hook runs the three bundled-Flow test files and does not call the check command. Live check 8 settles it.
- **`getattr` reads.** `validate.py` and `runner.py` read `getattr(flow, "example", "")` and `getattr(spec, "counts", None)` because some existing tests build `Flow` or `OutputSpec` objects with `object.__new__`, which lack the new slots.
- **Check command output.** `check.py` prints only the first violation (the `FlowDefinitionError` message). An unknown signature name is echoed in that message (it is a name from the file, not a secret), cleaned to printable ASCII and cut at 200 characters.
- **`ASK_EXAMPLE_MAX = 12`.** A deployment with more than 12 offered Flows with examples shows the first 12 in listing order.
- **README heading.** `README.md` now starts with `## What it is` (inserted at line 3, after the title), followed by the description, the demo URL and the tool list.
- **7.4 test fix.** The Property 5 test (hint ends at a whole word) in `tests/property/test_console_examples.py` was corrected during task 7.4; it passes in this run. I did not re-derive the details from the task log.
- **Two pre-existing Hypothesis flakes fixed by flagged edits.** `test_flow_collect_model.py` (the summed fake clock gave `2.0000000000000004 < 2.0`; tolerance `+ 1e-9`, Decision B) and `test_publisher_parity.py` (probe `count=3277` equals the text `TERMINAL : 3277` of the ISPF menu capture and `find_leaks` reported a false leak; the int probe filter `_SCREEN_TEXT`). Runtime code and `find_leaks` are unchanged. Both pass in this run.
- **Small differences from the design table.** `.kiro/specs/console/requirements.md` has two `1 of 3` lines changed (42 and 582), and the `more-flows/tasks.md` edit is on line 108, not 109.
- **Not verified here:** Kiro hook behaviour, the page in a browser, the real model's answers, the host value 136, Linux. The 136 members and 1,145 characters come from the steering file and `test_flow_command_publish.py` over the captures.

STOP: nothing committed or staged.
