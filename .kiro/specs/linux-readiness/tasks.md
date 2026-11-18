# Implementation Plan: linux-readiness

## Overview

Fix the four Linux defects described in `requirements.md` and `design.md` in this folder without changing Windows behaviour. Three are implemented here: the `FakeS3270` descriptor leak (Requirement 1), the `Connector` session pipes (Requirement 4) and the missing build backend in the `dev` extra (Requirement 3). The fourth, the stdio SIGTERM hang (Requirement 2), stops at the diagnostic: no change to `cli.py` or `mcp_server.py`. The production files touched are `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py` and `pyproject.toml` (one line). Every path is repo-relative. The executor works on Windows with Python 3.11.9 only.

### Estimates and order

| # | Top-level task | Hours |
|---|---|---|
| 1 | `FakeS3270.close()`, fixtures and the fake tests | 1.75 |
| 2 | `Connector` session pipe release and its tests | 1.5 |
| 3 | `setuptools>=70.1` in `dev` and the guard tests | 0.5 |
| 4 | SIGTERM evidence and reviewer diagnostic (stopped, no code) | 0.25 |
| 5 | Final checkpoint and report | 0.5 |
| | **Total** | **4.5** |

### Rules for every task

- DO NOT COMMIT and do not stage anything. Leave every change in the working tree. The reviewer commits.
- No secret is printed or written: no `TK5_PASSWORD`, `TK5_USERNAME` or host address in code, tests, logs, assertion messages or notes. Diagnostics use `unused.invalid`.
- Stop and report a production defect found outside the four findings (for example in `greenscreen/connector/_io.py`). Do not fix it silently. Otherwise run every task without stopping for review.
- No new dependency except `setuptools>=70.1` in the `dev` extra. No `wheel` package. `dependencies`, `publish` and `[build-system]` stay unchanged.
- Windows behaviour is unchanged and every test that passes on Windows today keeps passing, with no assertion changed apart from the three `dev` lists in task 3.2.
- `.kiro/steering` is never edited. `.kiro` is never git-ignored.
- Production edits are limited to `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py` and one line of `pyproject.toml`. `greenscreen/publisher/cli.py`, `greenscreen/publisher/mcp_server.py`, `greenscreen/connector/_io.py` and `tests/unit/test_publisher_cli.py` stay byte-identical.
- Every new test: no live host, no real socket, no real `s3270`. Tests use `FakeS3270`, `BytesIO` stand-ins or a thread stand-in.
- Python version: the executor runs everything on 3.11.9. 3.12, 3.13 and 3.14 are Reviewer_Check only. The executor installs no interpreter and no package.
- A requirement with a Reviewer_Check is reported as "implemented, awaiting Reviewer_Check". Requirement 2 is reported as "stopped, awaiting diagnostic".
- Every task is required. Nothing is marked optional with `*`. The design has no Correctness Properties section, so there are no property-test tasks.

### Decisions recorded from the user

- The design's read of the private `PipeReader._thread` (through `getattr`) is accepted. No method is added to `_io.py` (design Open item 1).
- When a reader thread does not end within `PIPE_JOIN_SECONDS`, the Connector leaves that one pipe open and logs at DEBUG. Requirement 4.1 is read with that exception, and its text in `requirements.md` carries it (design Open item 2).
- SIGTERM: the investigation was done on Windows (design, "Evidence", Finding 2). The task re-checks that the evidence and reviewer diagnostic are in the design, changes no code, and stops. It does not block the final checkpoint.

## Tasks

- [x] 1. `FakeS3270.close()`, the fixtures and the fake tests (about 1.75 h)
  - [x] 1.1 Add `close()` and the descriptor release to `greenscreen/connector/testing/fake.py`
    - Read the file first. Keep the attribute names `_thread`, `_stdin_read`, `_stdout_write`, `stdin`, `stdout`, `stderr` (`tests/property/test_string_redaction.py` reads them).
    - Add `_close_quietly(f)`, a `_closed` flag with a lock, and `close()` as the design's section 1 describes: set `_terminated`, close `_stdout_write`, close `stdin`, `self._thread.join(timeout=5)`, close `_stdin_read` only if the thread ended, close `stdout` and `stderr`. Idempotent, never raises, safe after `terminate`, `kill`, `wait` and `Connector.close()`. Document the caller rule (close after any reader on `stdout` has ended) in the docstring.
    - `_handle_loop` gets a `finally` that closes `_stdin_read`. `wait()` still returns `0` at once, does not change `poll()`, and now also closes `_stdout_write` (idempotent). `terminate()`, `kill()` and `poll()` are unchanged.
    - Verify: run `tests/unit/test_fake_s3270.py tests/unit/test_connector.py tests/unit/test_connector_redaction.py tests/property/test_pf_pa_boundary.py tests/property/test_string_redaction.py tests/property/test_response_redaction.py tests/property/test_wait_timeout_substitution.py`. All pass with no assertion changed. If one fails because it calls `wait()` and then keeps reading or scripting (design Open item 3), report it before editing any test.
    - _Requirements: 1.1, 1.2, 1.4, 1.8_

  - [x] 1.2 Make every construction site close its fake
    - `tests/conftest.py` `finalize_fakes`: after the terminate loop call `f.close()` for every fake, then `raise_if_failed()` as before.
    - `tests/unit/test_fake_s3270.py`: `make_fake` teardown does `terminate()`, `stdin.close()`, then `close()`. `reader_for` takes `make_fake` as a parameter (so it is torn down first) and at teardown calls `fake.terminate()` and joins each `reader._thread` (2 s) before any pipe is closed.
    - `tests/unit/test_connector.py` `make_connector` teardown: `fake.terminate()` then `fake.close()`. Do not touch the `proc.calls == ["wait", "terminate", "wait", "kill"]` assertion (line about 214).
    - `tests/unit/test_connector_redaction.py`: `make_connector` teardown (about lines 102-103) the same, and `fake.close()` in the `finally` of the direct `RecordingFake` (about lines 575-585).
    - `tests/property/test_pf_pa_boundary.py` (line about 32): in the `finally`, after `conn.close()`, replace `fake.terminate(); fake.stdin.close()` by `fake.terminate(); fake.close()`. Keep the existing comment about write ends.
    - Do not edit `test_string_redaction.py`, `test_response_redaction.py`, `test_wait_timeout_substitution.py` or `tests/connector_support.py`. Re-search `tests/` for `FakeS3270(` and `RecordingFake(` and list in the task notes any construction site not named in the design (section 4); close it the same way.
    - _Requirements: 1.5_

  - [x] 1.3 Add `tests/unit/test_fake_s3270_close.py` (all platforms)
    - For a fake closed through `Connector.close()` and for one closed through `FakeS3270.close()`: each of the five Fake_Descriptors has `closed is True` and `_thread.is_alive()` is false.
    - `close()` twice, after `terminate()`, after `kill()` and after `wait()`: no exception. `close()` returns in under 5 s.
    - The test closes any fake it makes in a `finally`.
    - _Requirements: 1.1, 1.2, 1.3, 1.7_

  - [x] 1.4 Add `tests/unit/test_fake_s3270_descriptors.py` (POSIX count, skipped on Windows)
    - `_fd_count()` is `len(os.listdir("/proc/self/fd"))` with `/dev/fd` as fallback. When neither exists, `pytest.skip` with a message that names the platform (for example `"descriptor counting needs /proc/self/fd or /dev/fd; platform win32"`), so the test never reports as passed on Windows.
    - Procedure: `gc.collect()`, one warm-up cycle, record the count, 200 cycles (even index: `Connector.open()` plus `close()` over a fake; odd index: `FakeS3270.close()` directly), `gc.collect()`, assert the count equals the start value. Use the `Connector` construction of the design's spot check (a `process_factory` returning the fake).
    - Verify on Windows: the file collects and reports one skip with the platform message.
    - _Requirements: 1.6_

- [x] 2. `Connector` session pipe release and its tests (about 1.5 h)
  - [x] 2.1 Add the end-of-session release to `greenscreen/connector/connector.py`
    - Read the file first. Add `self._drain: threading.Thread | None = None`, `self._pipes_released = False` and the class constant `PIPE_JOIN_SECONDS: float = 2.0`. In `open()` keep the thread returned by `start_stderr_drain(proc.stderr)` in `self._drain`.
    - Add `_release_session()` and the static `_close_pipe(pipe, name)` exactly as the design's section 2 gives them: close `proc.stdin`; join `getattr(self._reader, "_thread", None)` and `self._drain` within one shared `PIPE_JOIN_SECONDS` budget; close `proc.stdout` and `proc.stderr` only when their thread ended; leave a pipe open with a DEBUG record when its thread is still alive; each close independent; catch only `OSError` and `ValueError`; log the stream name and the exception class only.
    - Call `_release_session()` on all three ending paths: in the `finally` of `close()` (it must also run when `send()` already tore the session down and `close()` returned early), after `_terminate_proc()` in the `open()` failure branch, and after `_terminate_proc()` in the pipe-timeout branch of `_send_with_deadline`.
    - The helper calls no method on `proc` other than the three `close()` calls (no `poll()`, no `wait()`), so the `proc.calls` pin in `test_connector.py` holds.
    - Verify: run `tests/unit/test_connector*.py tests/unit/test_fake_s3270*.py`, every `tests/property` module that uses `Connector`, and `tests/unit/test_publisher_*.py`. All pass with no assertion changed. Success-path return values, exceptions, log messages and timing are unchanged.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 1.3_

  - [x] 2.2 Add `tests/unit/test_connector_close_pipes.py` (all platforms)
    - Fake session closed by `close()`: `proc.stdin.closed`, `proc.stdout.closed` and `proc.stderr.closed` are true.
    - The same for the open-failure path (script answers `Connect` with `error`) and the pipe-timeout path (silent fake, `_config.default_timeout = 0.05`).
    - `close()` twice, `close()` on a never-opened Connector and `close()` after an open failure: no exception, still closed.
    - One stream's `close()` raises `OSError` (stand-in process): the other two are closed, `close()` does not raise, and the DEBUG records (captured with `LogCapture` on `greenscreen.connector`) hold only the stream name and the exception class, no data, command or secret.
    - Blocked-reader stand-in: `proc.stdout` iteration blocks on a `threading.Event` and never reaches EOF. With `Connector.PIPE_JOIN_SECONDS` monkeypatched to 0.2, `close()` returns within 2 s, `stdin` and `stderr` are closed, `stdout` is not closed, and a DEBUG record names `stdout`. The event is set in a `finally` so the thread ends.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.9, 4.10_

- [x] 3. `setuptools>=70.1` in the `dev` extra and the guard tests (about 0.5 h)
  - [x] 3.1 Edit `pyproject.toml`
    - Add `"setuptools>=70.1",` as the last line of the `dev` list. Result: `greenscreen-connector[publish]`, `hypothesis>=6.170.15`, `pytest>=8.0`, `pyyaml>=6.0.3`, `setuptools>=70.1`, in that order. Change nothing else: `dependencies`, `publish` and `[build-system]` (`setuptools>=68`, `wheel`) stay as they are.
    - Verify: `git diff --stat pyproject.toml` shows one added line.
    - _Requirements: 3.3, 3.4, 3.5_

  - [x] 3.2 Update the three Dev_Extra_Guard_Tests
    - Set the expected `dev` list to the five entries of task 3.1 in `tests/unit/test_flow_packaging.py` (`EXPECTED_OPTIONAL["dev"]`), `tests/unit/test_flow_model.py` (`EXPECTED_OPTIONAL["dev"]`) and `tests/unit/test_recognizer_packaging.py` (the literal list in `test_dev_extra_unchanged`). Change nothing else in those files. Leave the Wheel_Test and its flags unchanged, and leave `tests/unit/test_publisher_packaging.py` unchanged.
    - Verify: run those three files plus `tests/unit/test_publisher_packaging.py`. All pass, and the Wheel_Test passes on Windows.
    - _Requirements: 3.1, 3.2, 3.6_

  - [x] 3.3 Re-search `tests/` for any other test that pins the `dev` list
    - Search `tests/` and the repo for `hypothesis>=6.170.15` and `pyyaml>=6.0.3` (ignore `.kiro` history). List every file found in the task notes. A pin in a file other than the three above is updated the same way (list only); a production defect found is reported.
    - Record the setuptools version pip resolves in a fresh Windows environment only if a venv can be made without a network install of anything outside the project; otherwise record "not run" for design criterion 3.8. Do not add `wheel`.
    - _Requirements: 3.6, 3.7, 3.8_

- [x] 4. SIGTERM: confirm the evidence and the reviewer diagnostic, change no code (about 0.25 h)
  - [x] 4.1 Re-check `design.md` and stop
    - Confirm by reading `.kiro/specs/linux-readiness/design.md` that it records: the `py -0` output and the Local_Pythons note; the Windows experiment and its two runs (Finding 2); the H1, H2 and H3 table with the Windows status of each; the reviewer-only versions (3.12 with dependencies, 3.13, 3.14.4); the D1 to D4 diagnostic commands with the table that separates H1, H2 and H3, and the file `.kiro/specs/linux-readiness/sigterm-diagnostic.txt` where the reviewer pastes the output; and the conditional candidate fix with the portable regression test idea. If a part is missing, add it to `design.md` only.
    - Make NO change to `greenscreen/publisher/cli.py`, `greenscreen/publisher/mcp_server.py` or `tests/unit/test_publisher_cli.py`. Do not create `sigterm-diagnostic.txt` (the reviewer creates it). Verify with `git diff --name-only -- greenscreen/publisher tests/unit/test_publisher_cli.py` printing nothing.
    - Status for the report: **Requirement 2: stopped, awaiting diagnostic.** The Stdio_SIGTERM_Test stays failing on Linux and open. This task does not block task 5.
    - _Requirements: 2.1, 2.9, 2.10, 2.11_

- [x] 5. Final checkpoint and report
  - Run `python -m pytest -m "not integration" -p no:cacheprovider` on Windows and record passed, skipped, failed, deselected, pytest time and wall time. Compare with the baseline in the design: 2096 passed, 7 skipped, 0 failed, 7 deselected, 329.87 s pytest time, 334.9 s wall time. Expected: passed rises by the new Windows-running tests, skipped rises by one (the descriptor-count test), failed stays 0. A timing difference is reported, never a failure.
  - Confirm the connector, fake and publisher suites pass with no assertion changed except the three `dev` lists (`git diff` of `tests/` shows only the edits named in tasks 1 to 3).
  - `git status --short` and `git diff --name-only`: only these paths may appear: `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py`, `pyproject.toml`, the edited test files named in tasks 1.2 and 3.2, the three new test files of tasks 1.3, 1.4 and 2.2, and `.kiro/specs/linux-readiness/`. `git diff -- pyproject.toml` is the one `dev` line. `git diff --exit-code -- .kiro/steering` is clean. `git diff --cached --name-only` prints nothing and `git log` has no new commit.
  - Write the final report: Windows counts and timings before and after; the Python versions run (3.11.9) and the reviewer-only versions; the files listed by task 1.2 and 3.3; and, for every requirement, its status and the exact Reviewer_Check commands from the design's "Reviewer_Check" section: Requirement 1 (descriptor test, `ulimit -n 1024` run, spot check), Requirement 3 (fresh venv, guard tests, `git diff --stat`), Requirement 4 (fdloop script, integration run, pipe tests), Requirement 5 (full run with `ulimit -n 1024`, `/proc/$$/fd` counts, `git status`). Status: Requirements 1, 3, 4 and 5 "implemented, awaiting Reviewer_Check"; Requirement 2 "stopped, awaiting diagnostic", with the Stdio_SIGTERM_Test named as failing on Linux and the D1 to D4 commands listed.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

## Notes

- Tasks marked complete need the tests they name to pass. Task 4.1 is complete when the design is confirmed and nothing outside `design.md` changed; Requirement 2 itself stays open.
- The reviewer decisions above (private `PipeReader._thread`, one pipe left open when its reader does not end) are reflected in `requirements.md` criterion 4.1 and design Open items 1 and 2.
- Windows cannot show the 1024-descriptor failure, the POSIX descriptor count, the behaviour of a real `Popen` pipe under a blocked read, the fresh-venv setuptools resolution (network), or SIGTERM delivery by the kernel. Those stay Reviewer_Checks.
- The dependency graph keeps tasks that write the same file in different waves: `connector.py` only in 2.1; `fake.py` only in 1.1; the new test files are separate; the three guard files are only in 3.2. Checkpoints and top-level tasks are left out of the graph.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "4.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.2", "3.3"] }
  ]
}
```
