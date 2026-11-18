# Implementation Plan: linux-readiness

## Overview

Fix the four Linux defects described in `requirements.md` and `design.md` in this folder without changing Windows behaviour. Tasks 1 to 5 are done and verified by the reviewer: the `FakeS3270` descriptor leak (Requirement 1), the `Connector` session pipes (Requirement 4) and the missing build backend in the `dev` extra (Requirement 3). The fourth, the stdio SIGTERM hang (Requirement 2), had its root cause confirmed by the reviewer (H1, Python 3.14.4), and tasks 6 and 7 implement the chosen fix in `greenscreen/publisher/cli.py` only. The production files touched are `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py`, `pyproject.toml` (one line) and, in this step, `greenscreen/publisher/cli.py`. Every path is repo-relative. The executor works on Windows with Python 3.11.9 only.

### Estimates and order

| # | Top-level task | Hours |
|---|---|---|
| 1 | `FakeS3270.close()`, fixtures and the fake tests | 1.75 |
| 2 | `Connector` session pipe release and its tests | 1.5 |
| 3 | `setuptools>=70.1` in `dev` and the guard tests | 0.5 |
| 4 | SIGTERM evidence and reviewer diagnostic (stopped, no code) | 0.25 |
| 5 | Interim checkpoint and report (done) | 0.5 |
| 6 | SIGTERM fix: stdin copier, portable test, publisher suites | 1.5 |
| 7 | Final checkpoint and re-check | 0.5 |
| 8 | Reviewer findings: portable SIGTERM test delivery, wheel temp directory, Requirement 23.7 wording, final re-run | 1.5 |
| | **Total** | **8.0** |

### Rules for every task

- DO NOT COMMIT and do not stage anything. Leave every change in the working tree. The reviewer commits.
- No secret is printed or written: no `TK5_PASSWORD`, `TK5_USERNAME` or host address in code, tests, logs, assertion messages or notes. Diagnostics use `unused.invalid`.
- Stop and report a production defect found outside the four findings (for example in `greenscreen/connector/_io.py`). Do not fix it silently. Otherwise run every task without stopping for review.
- No new dependency except `setuptools>=70.1` in the `dev` extra. No `wheel` package. `dependencies`, `publish` and `[build-system]` stay unchanged.
- Windows behaviour is unchanged and every test that passes on Windows today keeps passing, with no assertion changed apart from the three `dev` lists in task 3.2.
- `.kiro/steering` is never edited. `.kiro` is never git-ignored.
- Production edits are limited to `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py`, one line of `pyproject.toml` and, for task 6 only, `greenscreen/publisher/cli.py`. `greenscreen/publisher/mcp_server.py`, the HTTP path in `cli.py`, `greenscreen/connector/_io.py` and `tests/unit/test_publisher_cli.py` stay byte-identical.
- Every new test: no live host, no real socket, no real `s3270`. Tests use `FakeS3270`, `BytesIO` stand-ins or a thread stand-in.
- Python version: the executor runs everything on 3.11.9. 3.12, 3.13 and 3.14 are Reviewer_Check only. The executor installs no interpreter and no package.
- A requirement with a Reviewer_Check is reported as "implemented, awaiting Reviewer_Check". Requirements 1, 3, 4 and 5 are already verified by the reviewer. Requirement 2 is reported as "implemented, awaiting Reviewer_Check" after task 6.
- Every task is required. Nothing is marked optional with `*`. The design has no Correctness Properties section, so there are no property-test tasks.

### Decisions recorded from the user

- The design's read of the private `PipeReader._thread` (through `getattr`) is accepted. No method is added to `_io.py` (design Open item 1).
- When a reader thread does not end within `PIPE_JOIN_SECONDS`, the Connector leaves that one pipe open and logs at DEBUG. Requirement 4.1 is read with that exception, and its text in `requirements.md` carries it (design Open item 2).
- SIGTERM: the reviewer's diagnostic confirmed H1 on Python 3.14.4 (D1 and D2; D3 and D4 not run). The chosen fix is the daemon-thread stdin copier in `cli.py` (tasks 6 and 7). It must hold on Python 3.11 to 3.14: the executor can run 3.11.9 only, 3.12 to 3.14 are Reviewer_Checks.

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
    - Status note: "stopped, awaiting diagnostic" is now **resolved**. The reviewer ran D1 and D2 on Python 3.14.4 and H1 is confirmed (`sigterm-diagnostic.txt`). The fix is task 6. This task was completed as written and is not reopened.
    - _Requirements: 2.1, 2.9, 2.10, 2.11_

- [x] 5. Interim checkpoint and report (done before the SIGTERM fix; the final re-check is task 7)
  - Run `python -m pytest -m "not integration" -p no:cacheprovider` on Windows and record passed, skipped, failed, deselected, pytest time and wall time. Compare with the baseline in the design: 2096 passed, 7 skipped, 0 failed, 7 deselected, 329.87 s pytest time, 334.9 s wall time. Expected: passed rises by the new Windows-running tests, skipped rises by one (the descriptor-count test), failed stays 0. A timing difference is reported, never a failure.
  - Confirm the connector, fake and publisher suites pass with no assertion changed except the three `dev` lists (`git diff` of `tests/` shows only the edits named in tasks 1 to 3).
  - `git status --short` and `git diff --name-only`: only these paths may appear: `greenscreen/connector/testing/fake.py`, `greenscreen/connector/connector.py`, `pyproject.toml`, the edited test files named in tasks 1.2 and 3.2, the three new test files of tasks 1.3, 1.4 and 2.2, and `.kiro/specs/linux-readiness/`. `git diff -- pyproject.toml` is the one `dev` line. `git diff --exit-code -- .kiro/steering` is clean. `git diff --cached --name-only` prints nothing and `git log` has no new commit.
  - Write the final report: Windows counts and timings before and after; the Python versions run (3.11.9) and the reviewer-only versions; the files listed by task 1.2 and 3.3; and, for every requirement, its status and the exact Reviewer_Check commands from the design's "Reviewer_Check" section: Requirement 1 (descriptor test, `ulimit -n 1024` run, spot check), Requirement 3 (fresh venv, guard tests, `git diff --stat`), Requirement 4 (fdloop script, integration run, pipe tests), Requirement 5 (full run with `ulimit -n 1024`, `/proc/$$/fd` counts, `git status`). Status: Requirements 1, 3, 4 and 5 "implemented, awaiting Reviewer_Check"; Requirement 2 "stopped, awaiting diagnostic", with the Stdio_SIGTERM_Test named as failing on Linux and the D1 to D4 commands listed.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 6. SIGTERM fix: daemon-thread stdin copier (about 1.5 h)
  - [x] 6.1 Implement the stdin copier in `greenscreen/publisher/cli.py` only
    - Read `cli.py` and the design section "Requirement 2: SIGTERM root cause confirmed, fix chosen" first. Search `tests/` for `_stdio_streams` and keep every caller working (the function keeps its two-value return).
    - In `_stdio_streams()`, after the `dup`/`dup2` and `sys.stdout = sys.stderr` lines, create `os.pipe()`, start the daemon thread `gs-stdin-copier` running `_copy_stdin(in_fd, feed_w)`, and give the SDK a `TextIOWrapper` (same encoding, `errors="replace"`, `newline="\n"`) over the read end, wrapped by `anyio.wrap_file`.
    - Add `_copy_stdin`, a quiet idempotent close of the write end with a one-shot flag, and the module-level holder. In `_run_stdio` add a `finally` after the existing `try/except KeyboardInterrupt` that closes the write end. The copier closes the write end on EOF or `OSError`. It writes to no stream and logs nothing.
    - No change to `mcp_server.py`, `_run_http`, `_Server.handle_exit`, `_on_sigterm`, the exit code logic of `main()` or any other file. No new dependency.
    - _Requirements: 2.2, 2.4, 2.5, 2.6, 2.7_

  - [x] 6.2 Add the portable regression test in a new file
    - Create `tests/unit/test_publisher_stdio_sigterm_portable.py` (and a sibling child entry file in `tests/` only if `tests/publisher_cli_entry.py` cannot be reused unchanged). Do not edit any existing test in `tests/unit/test_publisher_cli.py`.
    - The child runs the real stdio server on the fake host and, once `cli._on_sigterm` is installed and 1 s has passed, calls `signal.raise_signal(signal.SIGTERM)` from a timer thread. The parent keeps the child's stdin open and idle, never closes it before the assertion, and asserts exit code 0 within 30 s and a report with `rc: 0`. Kill the child in a `finally`.
    - Add small unit tests for the copier helpers: bytes copied unchanged and in order, EOF on the real stdin closes the feed, a double close is safe, a write to a closed feed ends the copier without raising.
    - The test runs on Windows. Note in its docstring what it cannot prove (kernel SIGTERM, selector loop, Python 3.12 to 3.14). Superseded in part by task 8.1: the signal-delivery call is platform dependent (`os.kill` on POSIX, `signal.raise_signal` elsewhere).
    - _Requirements: 2.2, 2.5, 2.8, 2.9_

  - [x] 6.3 Run the publisher suites
    - Run `tests/unit/test_publisher_cli.py` (the stdio stdout-purity and stdio run tests pass unchanged; the Stdio_SIGTERM_Test is POSIX-only and skipped on Windows; the HTTP_Stop_Test passes), the new file from 6.2, every other `tests/unit/test_publisher_*.py` and every `tests/property` module for the publisher. No assertion changed.
    - Report the Python version used (3.11.9). 3.12 to 3.14 are Reviewer_Checks and the Stdio_SIGTERM_Test on Linux stays a Reviewer_Check.
    - _Requirements: 2.3, 2.5, 2.6, 2.7, 2.9_

- [x] 7. Final checkpoint and re-check (about 0.5 h)
  - Run `python -m pytest -m "not integration" -p no:cacheprovider` on Windows. Record passed, skipped, failed, deselected, pytest time and wall time. Compare with the last Windows run: 2115 passed, 4 skipped, 0 failed, 294.94 s. Expected: passed rises by the new Windows-running tests of 6.2, skipped unchanged, failed 0. A timing difference is reported, never a failure.
  - Git checks: `git diff --name-only -- greenscreen` lists `cli.py` as the only production file changed in this step, in addition to the earlier files (`fake.py`, `connector.py`); `git diff --exit-code -- greenscreen/publisher/mcp_server.py` is clean and the HTTP path in `cli.py` is unchanged (`_run_http`, `_Server`); `git diff --exit-code -- tests/unit/test_publisher_cli.py` is clean; `git diff --exit-code -- .kiro/steering` is clean; `git diff --cached --name-only` prints nothing and `git log` has no new commit.
  - Final report: updated counts and timings, the files changed, and for Requirement 2 the status "implemented, awaiting Reviewer_Check" with the Reviewer_Check commands from the design (Stdio_SIGTERM_Test 20 repeats, `pgrep`, the 3.11 to 3.14 loop, the D1 re-run). Requirements 1, 3, 4 and 5 are already verified by the reviewer.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 2.3, 2.7, 2.9, 5.1, 5.2, 5.3, 5.4_

- [x] 8. Reviewer findings on the Linux run: portable SIGTERM test, wheel temp directory, Requirement 23.7 wording (about 1.5 h)
  - Context: the reviewer's Linux run (Python 3.14.4, uncommitted tree) passed `test_stdio_sigterm_stops_cleanly` 20 of 20, so the `cli.py` fix works and Requirement 2 is verified for 3.14.4 (3.11 to 3.13 reviewer-only). The full suite gave 2116 passed, 1 failed, 6 skipped. The failure is `tests/unit/test_publisher_stdio_sigterm_portable.py::test_stdio_sigterm_with_idle_open_stdin_exits_0` (child did not exit in 30 s). Confirmed cause, test-only: `tests/publisher_sigterm_entry.py` sends the signal with `signal.raise_signal(SIGTERM)`, which on Linux leaves the child alive with no report, while `os.kill(os.getpid(), SIGTERM)` from the same thread and a real external `kill -TERM` both exit 0 with a clean report and stdin open. See design "Reviewer run 2".
  - Same rules as above: no commit, no staging, no secret, no new dependency. A production defect found is reported, not fixed. `greenscreen/publisher/cli.py` is not touched in this task.

  - [x] 8.1 Fix the signal delivery in the portable test entry (test-only)
    - Change only `tests/publisher_sigterm_entry.py`: in the timer thread, when `os.name == "posix"` call `os.kill(os.getpid(), signal.SIGTERM)`; otherwise call `signal.raise_signal(signal.SIGTERM)` (`os.kill` with SIGTERM terminates the process on Windows without running the Python handler). Keep the 1 s wait after `cli._on_sigterm` is installed.
    - Correct the module docstring of that file to say why the call differs by platform.
    - In `tests/unit/test_publisher_stdio_sigterm_portable.py` change only the module/test docstring and the "What this cannot prove" note: the test is portable in structure, not in the delivery call; on Windows the signal is in-process, on POSIX it goes through the kernel to the child's own pid but is not sent by another process; Python 3.12 to 3.14 and external `kill -TERM` stay Reviewer_Checks. No assertion, timeout or fixture changes.
    - No change to `greenscreen/` (check `git diff --name-only -- greenscreen` still lists only files already pending) and none to `tests/unit/test_publisher_cli.py`.
    - Verify on Windows: `tests/unit/test_publisher_stdio_sigterm_portable.py` passes as before.
    - _Requirements: 2.8, 2.9_

  - [x] 8.2 Make the wheel test clean up its temp directory on every path (test-only)
    - Read the wheel test in `tests/unit/test_flow_packaging.py` and find where it creates its build directory (the `/tmp/gs-wheel-*` directories left on Linux). Check every exit path: success, build failure, timeout, any exception, and `pytest.skip`.
    - Fix with `tempfile.TemporaryDirectory`, pytest `tmp_path`, or `try`/`finally` with `shutil.rmtree`. Do not change what the test asserts, its flags, its skip conditions or its timeout.
    - Add a small test or assertion that shows the directory is gone after the failure path, where that is feasible without a real build (for example by running the helper that owns the directory with a failing build command stand-in and asserting the path no longer exists). If it cannot be done without changing the wheel test's behaviour, record why in the task notes.
    - Verify: `tests/unit/test_flow_packaging.py` passes on Windows, and a temp directory name search shows no `gs-wheel-*` left in the system temp directory by the run.
    - _Requirements: 3.1, 3.6_

  - [x] 8.3 Reword publisher Requirement 23.7 (documentation only)
    - Read `.kiro/specs/publisher/requirements.md` criterion 23.7 (around line 491). It reads: the Publisher SHALL NOT attempt to recover a user id that is logged on, SHALL NOT send `RECONNECT` and SHALL NOT retry a Call, followed by the stale parenthetical "(Assumptions: recovery belongs to a follow-up spec)".
    - Remove only that parenthetical. Keep the requirement's meaning true: the logon-recovery spec is done, recovery lives in the bundled `tk5-logon` and `tk5-system-info` Flows (they send `RECONNECT` when the host answers `IN USE`), and the Publisher changed only `_session_clean`, so the Publisher itself still does no recovery. A short clause saying recovery is done by the bundled logon Flow, not by the Publisher, is allowed; no new obligation is added.
    - Read the matching sentences in `.kiro/specs/publisher/design.md` (the "Recovery of a locked TSO user id" row near line 20 and the "No recovery logic in the Publisher" bullet near line 470). Change nothing there. List in the task notes any other text in the publisher spec that still says recovery is future work, flagged and not edited.
    - Edit no other file. Run `validate_spec_format` on the edited `requirements.md` and report the result.
    - _Requirements: 5.3_

  - [x] 8.4 Final re-run and report
    - Run `python -m pytest -m "not integration" -p no:cacheprovider` on Windows. Record passed, skipped, failed, deselected, pytest time and wall time against the last run: 2119 passed, 4 skipped, 0 failed, 399.56 s. Expected: passed rises by any test added in 8.2, skipped unchanged, failed 0. A timing difference is reported, never a failure.
    - Git checks: `git diff --name-only -- greenscreen` lists only files already pending (`greenscreen/publisher/cli.py` is the only change for Requirement 2, plus the earlier `fake.py` and `connector.py`); `git diff --exit-code -- greenscreen/publisher/mcp_server.py`, `-- tests/unit/test_publisher_cli.py` and `-- .kiro/steering` are clean; `git diff --cached --name-only` prints nothing; `git log` has no new commit. The only files changed by task 8 are `tests/publisher_sigterm_entry.py`, `tests/unit/test_publisher_stdio_sigterm_portable.py`, `tests/unit/test_flow_packaging.py` and `.kiro/specs/publisher/requirements.md` (and this spec's two documents).
    - Final report: counts and timings, the files changed, and the Reviewer_Check commands below. Requirement 2 status: "verified on 3.14.4, 3.11 to 3.13 reviewer-only". Requirements 1, 3, 4 and 5 are already verified by the reviewer.
    - Reviewer_Check on the Linux box for these items:
      ```bash
      pytest tests/unit/test_publisher_stdio_sigterm_portable.py -q            # the failing test now passes
      for i in $(seq 20); do pytest tests/unit/test_publisher_stdio_sigterm_portable.py -q || break; done
      for i in $(seq 20); do pytest tests/unit/test_publisher_cli.py::test_stdio_sigterm_stops_cleanly -q || break; done
      ls -d /tmp/gs-wheel-* 2>/dev/null | wc -l                                  # note the count, then: rm -rf /tmp/gs-wheel-*
      pytest tests/unit/test_flow_packaging.py -q                                # then repeat the ls: count stays 0
      pytest -m "not integration" -q -rs 2>&1 | tail -15                         # expect 0 failed
      git diff -- .kiro/specs/publisher/requirements.md                          # one parenthetical removed
      git status --short                                                         # no commit, nothing staged, steering untouched
      ```
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 2.8, 2.9, 5.1, 5.2, 5.3, 5.4_

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
    { "id": 2, "tasks": ["1.3", "1.4", "2.2", "3.3", "6.1"] },
    { "id": 3, "tasks": ["6.2"] },
    { "id": 4, "tasks": ["6.3"] },
    { "id": 5, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 6, "tasks": ["8.4"] }
  ]
}
```
