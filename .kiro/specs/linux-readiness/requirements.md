# Requirements Document

## Introduction

A reviewer ran the suite on Ubuntu (Python 3.14.4, s3270 4.3, default open-file limit 1024) and found four defects that Windows does not show. This spec fixes them without changing Windows behaviour. The executor works on Windows and cannot run Linux, so every requirement states two things: what the Windows run proves, and which Reviewer_Check the reviewer runs on Linux. A requirement that carries a Reviewer_Check is not closed by a Windows run alone.

Reviewer findings:

1. `FakeS3270` holds 5 file descriptors per instance, has no `close()`, and garbage collection does not release them. Under the default limit the suite ends in "Too many open files" (616 failed). With the limit raised: 2096 passed, 2 failed.
2. `tests/unit/test_publisher_cli.py::test_stdio_sigterm_stops_cleanly` times out on Linux. The HTTP graceful-stop test passes there.
3. `tests/unit/test_flow_packaging.py::test_wheel_contains_exactly_the_three_flow_yaml_files` fails where setuptools is not installed ("Cannot import build backend 'setuptools.build_meta'").
4. `Connector.close()` leaves the last session's three pipe descriptors open until the object is collected. Measured: flat at 7 over 40 sessions, so no growth.

Recorded observation (not a pass/fail criterion): on Linux the full non-integration suite ran in 109 s.

### Findings from reading the code

**Finding 1.** `FakeS3270.__init__` (`greenscreen/connector/testing/fake.py`, lines 44-63) makes three `os.pipe()` pairs and wraps five ends in file objects: `stdin` (write), `stdout` (read), `stderr` (read), `_stdin_read` and `_stdout_write`. The sixth end, `stderr_write_fd`, is closed at once. Those are the 5 descriptors. The class has `terminate()`, `kill()` and `wait()` (lines 112-125) but no `close()`. `terminate()` closes only `_stdout_write` (via `_close_stdout_write`). `stdin`, `stdout`, `stderr` and `_stdin_read` stay open, and the handler thread `gs-fake-s3270` (`_handle_loop`, `for raw_line in self._stdin_read`) blocks until the write end `stdin` closes, which nothing does. A thread blocked on `_stdin_read` also keeps that file object reachable, so the descriptors do not go away by collection. Whether the reviewer's "not released by garbage collection" comes from this thread reference is a hypothesis to confirm in the design; the five-descriptor count is read from the code. The three construction sites are `tests/conftest.py` line 47 (a `_make` fixture, which keeps `fakes`), `tests/unit/test_fake_s3270.py` line 22 (the same pattern) and `tests/property/test_pf_pa_boundary.py` line 32 (direct, no fixture).

**Finding 4.** `Connector.open()` (`greenscreen/connector/connector.py`, lines 67-103) stores `self._proc`, builds `PipeReader(proc.stdout)` (a daemon thread `gs-pipe-reader` in `greenscreen/connector/_io.py`) and calls `start_stderr_drain(proc.stderr)` (a daemon thread `gs-stderr-drain`). `close()` (lines 105-125) sends `Disconnect()` and `Quit()`, waits up to 5 s, and sets `_closed`. It never closes `proc.stdin`, `proc.stdout` or `proc.stderr`. The session ends through three paths, and none of them closes the pipes: `close()` (line 124), the `open()` failure branch (lines 99-100) and the pipe-timeout branch of `_send_with_deadline` (lines 147-148). A caution for the design: closing `proc.stdout` or `proc.stderr` while `gs-pipe-reader` or `gs-stderr-drain` is blocked in a read on the same buffered object can block or raise on POSIX. The design must decide the order (process exit, thread end, then close) and record it.

**Finding 2.** `_run_stdio` (`greenscreen/publisher/cli.py`, lines 152-173) duplicates fds 0 and 1 (`_stdio_streams`, lines 120-137), wraps them with `anyio.wrap_file`, installs `signal.signal(signal.SIGTERM, _on_sigterm)` (a handler that raises `KeyboardInterrupt`, lines 146-147), then runs `anyio.run(run_stdio(...))` (`greenscreen/publisher/mcp_server.py`, lines 100-120). The HTTP path instead overrides `uvicorn.Server.handle_exit` (lines 107-116) and passes. The test (`test_publisher_cli.py`, lines 653-678) keeps stdin open as a pipe, waits for `publishing 1 of 3` on stderr, sleeps 1 s and sends SIGTERM, then expects exit code 0 within 30 s.

Hypotheses to be confirmed, not facts:

- **H1 (blocked stdin reader thread).** The SDK reads stdin through `anyio.wrap_file`, which runs the blocking read in a worker thread. After `_on_sigterm` raises `KeyboardInterrupt` in the main thread, the event loop unwinds, but the worker thread stays blocked reading the open stdin pipe. Loop teardown or interpreter exit then waits for that thread, so the process never ends. Windows does not exercise this path (the test is skipped there).
- **H2 (handler raises at an arbitrary point).** `_on_sigterm` runs on the main thread inside the loop, possibly inside the selector wait or a callback. The `KeyboardInterrupt` can be swallowed or re-raised by asyncio or anyio machinery, so the `finally` in `run_stdio` (shielded `service.drain`) may not run before exit, or the exit code may not be 0.
- **H3 (handler not yet installed when the signal arrives).** The test waits 1 s after the `publishing` log line, and the handler is installed after `_stdio_streams()`. This is unlikely to be the cause on a warm machine and is listed to be ruled out.

No fix is chosen here.

**Finding 3.** `tests/unit/test_flow_packaging.py` (line 69 onward) copies the repo to a temp directory and runs `python -m pip wheel . --no-deps --no-build-isolation --no-index` (lines 91-101). With `--no-build-isolation` the build backend must already be installed. `pyproject.toml` declares `[build-system] requires = ["setuptools>=68", "wheel"]` and `build-backend = "setuptools.build_meta"`, but the `dev` extra lists only `greenscreen-connector[publish]`, `hypothesis>=6.170.15`, `pytest>=8.0` and `pyyaml>=6.0.3`. A fresh venv built from `.[dev]` therefore has no setuptools on Python 3.12 and later. Also, three guard tests pin the whole `dev` list, so changing the `dev` extra needs all three updated: `EXPECTED_OPTIONAL` in `tests/unit/test_flow_packaging.py` (lines 28-37, asserted in `test_pyproject_dependencies_are_unchanged`), `EXPECTED_OPTIONAL` in `tests/unit/test_flow_model.py` (lines 28-37, asserted in `test_pyproject_dependency_lists_unchanged`), and the literal list in `test_dev_extra_unchanged` in `tests/unit/test_recognizer_packaging.py` (lines 37-42). `tests/unit/test_publisher_packaging.py` only checks that `dev` contains `greenscreen-connector[publish]` and that web packages stay under `publish`, so it needs no change.

### Decisions

1. **Finding 3 (Requirement 3): approved.** The user approved adding `setuptools>=70.1` to the `dev` extra. No `wheel` package is added. The skip-with-message alternative was not chosen.
2. **Finding 2, the fix itself.** It cannot be chosen until the root cause is confirmed (Requirement 2). The design must record the evidence. IF the cause cannot be confirmed on Windows, THEN the design records the diagnostic for the reviewer, the Requirement 2 task stops there, and Requirements 1, 3 and 4 proceed.
3. **Python versions.** Python 3.11 through 3.14 are in scope for the SIGTERM fix. The reviewer's box runs 3.14.4.
4. **Finding 4 check.** The Reviewer_Check for Requirement 4 uses real s3270.

### Conventions

- IF the work finds a defect in production code outside the files this spec names, THEN the implementer SHALL stop and report it instead of fixing it silently.
- No test, log, message or spec text prints a secret (`TK5_PASSWORD`, `TK5_USERNAME` or the host address).
- No new dependency is added, except `setuptools>=70.1` in the `dev` extra (Requirement 3), which the user approved. No `wheel` package is added. The `dependencies` of `pyproject.toml` stay unchanged.
- DO NOT COMMIT anything. The executor leaves every change in the working tree and the reviewer commits. No requirement or task of this spec asks for a commit, a staged file or a branch.
- The `.kiro/steering` directory is not edited.
- Production code outside the files this spec names is never changed. The files it names are: `greenscreen/connector/testing/fake.py` (Requirement 1), `greenscreen/connector/connector.py` (Requirement 4), `greenscreen/publisher/cli.py` (Requirement 2, and `greenscreen/publisher/mcp_server.py` only if the confirmed cause lies there, which the design must justify), and `pyproject.toml` (Requirement 3).
- The final report of the executor gives the Windows pass, skip and fail counts before and after the change, the timings of the Windows Full_Run before and after, and the exact Reviewer_Check commands for every requirement (Requirement 5, criterion 4).
- Windows behaviour is unchanged by every requirement here, and every test that passes on Windows today keeps passing there.
- A Windows run cannot close a requirement that carries a Reviewer_Check. The executor reports such a requirement as "implemented, awaiting Reviewer_Check" and not as done.

## Glossary

- **Fake_Host**: `FakeS3270` in `greenscreen/connector/testing/fake.py`.
- **Fake_Descriptors**: The five file objects `FakeS3270` holds: `stdin`, `stdout`, `stderr`, `_stdin_read` and `_stdout_write`.
- **Connector**: `greenscreen.connector.Connector`.
- **Session_Pipes**: `proc.stdin`, `proc.stdout` and `proc.stderr` of the process held in `Connector._proc`.
- **Stdio_Server**: The `greenscreen-publish` process with `GS_TRANSPORT=stdio`, started by `cli._run_stdio`.
- **Stdio_SIGTERM_Test**: `tests/unit/test_publisher_cli.py::test_stdio_sigterm_stops_cleanly`.
- **HTTP_Stop_Test**: `tests/unit/test_publisher_cli.py::test_graceful_stop_after_a_call_exits_0_and_closes_the_session`.
- **Wheel_Test**: `tests/unit/test_flow_packaging.py::test_wheel_contains_exactly_the_three_flow_yaml_files`.
- **Dev_Extra_Guard_Tests**: The three tests that pin the `dev` extra: `test_pyproject_dependencies_are_unchanged` in `tests/unit/test_flow_packaging.py`, `test_pyproject_dependency_lists_unchanged` in `tests/unit/test_flow_model.py` and `test_dev_extra_unchanged` in `tests/unit/test_recognizer_packaging.py`.
- **Local_Pythons**: The Python interpreters already installed on the executor's Windows machine, listed by `py -0`. The executor installs none.
- **Backend_Missing_Error**: The pip failure text "Cannot import build backend 'setuptools.build_meta'" or an `ImportError` for `setuptools` in the pip output.
- **Descriptor_Count**: The number of entries in `/proc/self/fd` of the test process (POSIX only).
- **Reviewer_Check**: A check that only the reviewer can run, on the Linux box. The commands are listed in each requirement.
- **Windows_Evidence**: What the executor's Windows run shows. It is stated per requirement, including what it cannot prove.
- **Test_Suite**: The pytest and Hypothesis tests under `tests/`.
- **Full_Run**: `pytest -m "not integration"` over the Test_Suite.

## Requirements

### Requirement 1: FakeS3270 releases its descriptors

**User Story:** As a contributor on Linux, I want the fake host to release its file descriptors, so that the Test_Suite passes under the default limit of 1024 open files.

This amends tn3270-connector Requirement 8, criteria 1, 2 and 5 (the Fake_Host contract). It adds a `close()` and leaves the scripted-response behaviour unchanged.

#### Acceptance Criteria

1. THE Fake_Host SHALL provide a `close()` method that closes every one of the Fake_Descriptors and ends the thread `gs-fake-s3270` within 5 seconds.
2. WHEN `close()` is called a second time, or after `terminate()` or `kill()`, THE Fake_Host SHALL return without raising.
3. WHEN `Connector.close()` has finished on a Connector that uses a Fake_Host as its process, THE Fake_Host SHALL hold no open Fake_Descriptor, without the caller calling `Fake_Host.close()` itself.
4. THE Fake_Host SHALL keep every behaviour it has today for a script, `failure`, `raise_if_failed()`, `wait()`, `poll()`, `terminate()` and `kill()`, so that `tests/unit/test_fake_s3270.py` and every test that uses `FakeS3270` pass without a change to their assertions.
5. THE Test_Suite SHALL close each Fake_Host that a test creates, including the one built directly in `tests/property/test_pf_pa_boundary.py` (line 32), through the fixtures `_make` in `tests/conftest.py` and `tests/unit/test_fake_s3270.py` or an equivalent, so that no test leaves a Fake_Host open.
6. THE Test_Suite SHALL contain a test that, on POSIX, records the Descriptor_Count, creates a Fake_Host and closes it 200 times (through `Connector.open()` and `Connector.close()` for at least half of the cycles and through `Fake_Host.close()` directly for the rest), and asserts that the Descriptor_Count equals the starting value. The test SHALL be skipped with a message that names the platform on Windows, and SHALL NOT report as passed there.
7. THE Test_Suite SHALL contain a test that runs on every platform and asserts, for a Fake_Host closed through `Connector.close()` and for one closed through `Fake_Host.close()`, that each of the five Fake_Descriptors reports `closed` as true and that the handler thread is no longer alive.
8. IF the cause of the leak turns out to differ from the explanation in "Findings from reading the code" (for example because a thread still references a file object after `close()`), THEN THE design SHALL record the evidence and the fix SHALL follow the confirmed cause.

**Windows_Evidence.** Criterion 7 runs on Windows and proves that `close()` closes every file object and ends the thread. Windows runs the Full_Run, which proves criterion 4. Windows cannot prove criterion 6 (skipped there) and cannot show the 1024 limit failure, because Windows has no such default.

**Reviewer_Check (on Linux; Windows alone does not close this requirement):**

1. Descriptor count test: `pytest tests/unit/test_fake_s3270_descriptors.py -v` (the executor names the file in the design). The test must show PASSED, not skipped.
2. Default limit: `ulimit -n && ulimit -n 1024 && pytest -m "not integration"`. The first command must print `1024`. The run ends with no "Too many open files" and no failure other than the two listed under "Resolved questions".
3. Optional spot check of the leak: `python - <<'EOF'` loop that creates and closes 200 `Connector`/`FakeS3270` pairs and prints `len(os.listdir('/proc/self/fd'))` before and after. The two numbers must be equal.

### Requirement 2: The stdio server stops on SIGTERM

**User Story:** As an operator running `greenscreen-publish` over stdio, I want SIGTERM to stop the process with exit code 0 and every session closed, so that a supervisor can stop it without a hard kill.

This restores publisher Requirement 16, criteria 1 and 3 for the stdio transport on POSIX.

#### Acceptance Criteria

1. THE implementer SHALL confirm the root cause of the Linux timeout before any change to `cli.py` or `mcp_server.py`, by reproducing it or by an experiment that separates H1, H2 and H3 of "Findings from reading the code", and SHALL record in `design.md` the experiment, the Linux output that shows it and the cause that was confirmed. IF the cause cannot be confirmed from a Windows run, THEN the design SHALL list the experiment as a Reviewer_Check and no code change SHALL start until the reviewer returns the output.
2. WHEN the Stdio_Server receives SIGTERM while its stdin pipe is open and idle, THE Stdio_Server SHALL stop accepting Calls, close every open session, and exit with code 0 within 30 seconds.
3. THE Stdio_SIGTERM_Test SHALL pass on Linux without any edit to `tests/unit/test_publisher_cli.py`.
4. WHEN the Stdio_Server receives SIGTERM while a Call is in flight, THE Stdio_Server SHALL answer further Calls with `shutting_down`, wait up to `GS_SHUTDOWN_GRACE` seconds for the Call, and then tear down every session that is still open (publisher Requirement 16, criteria 1 and 2).
5. WHEN the stdin pipe of the Stdio_Server reaches end of file, THE Stdio_Server SHALL stop with exit code 0 as it does today (the test `test_stdio_stdout_holds_only_json_rpc_even_when_a_handler_prints` keeps passing).
6. THE Stdio_Server SHALL write nothing to stdout except JSON-RPC messages, and SHALL log no secret, during and after the stop (publisher Requirements 8 and 14).
7. THE HTTP path (`_run_http`, `_Server.handle_exit`) and the Windows behaviour of `main()` SHALL stay unchanged, and the HTTP_Stop_Test SHALL keep passing on both platforms.
8. WHERE the confirmed mechanism does not depend on POSIX (for example a blocked reader thread), THE Test_Suite SHALL gain a test that runs on Windows and fails without the fix. WHERE it does, THE design SHALL say so and the Stdio_SIGTERM_Test remains the only proof.

9. THE fix SHALL hold on Python 3.11, 3.12, 3.13 and 3.14. THE design SHALL record the output of `py -0` on the executor's machine, which versions of the Local_Pythons the executor ran the stdio and publisher tests on, and which versions only the reviewer can run (at least 3.14.4 if no local 3.14 exists). The executor SHALL NOT install any interpreter.
10. IF the root cause of the Linux timeout cannot be confirmed on Windows, THEN THE design SHALL record, for the reviewer, the exact diagnostic commands to run on the Linux box (each command, the expected output that separates H1, H2 and H3, and the file where the reviewer pastes the output), AND the Requirement 2 task SHALL stop at that point with no change to `cli.py` or `mcp_server.py`, AND the work for Requirements 1, 3 and 4 SHALL proceed.
11. WHEN the executor reports Requirement 2 as stopped under criterion 10, THE final report SHALL name the Stdio_SIGTERM_Test as failing on Linux and open, and SHALL list the diagnostic commands.

**Windows_Evidence.** The Stdio_SIGTERM_Test is skipped on Windows (`skipif(WIN)`, line 652), so a Windows run proves nothing about criteria 2 to 4. Windows can prove criterion 5 (the stdin-EOF stop test), criterion 7 (the HTTP_Stop_Test with `CTRL_BREAK_EVENT` and the rest of `test_publisher_cli.py`) and, under criterion 8, a portable regression test if one exists.

**Reviewer_Check (on Linux; Windows alone does not close this requirement):**

1. Before the fix, confirm the failure and collect the evidence: `pytest tests/unit/test_publisher_cli.py::test_stdio_sigterm_stops_cleanly -x -q`. Expect a timeout or a non-zero exit.
2. For the hypotheses, the executor lists exact experiments in the design. A typical pair: `py-spy dump --pid <pid>` (or `python -X faulthandler` with `kill -ABRT`) on the hung Stdio_Server to show which threads are alive and where, and the same run with stdin closed.
3. After the fix: `pytest tests/unit/test_publisher_cli.py -q`. All tests pass, including the Stdio_SIGTERM_Test and the HTTP_Stop_Test.
4. Repeat the Stdio_SIGTERM_Test 20 times to rule out a timing pass: `for i in $(seq 20); do pytest tests/unit/test_publisher_cli.py::test_stdio_sigterm_stops_cleanly -q || break; done`.
5. Process check: after a run, `pgrep -fa 's3270|greenscreen-publish'` prints nothing.
6. Python versions: run checks 1 and 3 once per interpreter the box has for 3.11, 3.12, 3.13 and 3.14 (for example `python3.14 -m venv /tmp/gs-314 && /tmp/gs-314/bin/pip install -e ".[dev]" && /tmp/gs-314/bin/pytest tests/unit/test_publisher_cli.py -q`).

### Requirement 3: The wheel test works where setuptools is not installed

**User Story:** As a contributor with a fresh virtual environment, I want the dev extra to install the build backend that the wheel test needs, so that a missing backend is not reported as a packaging defect.

This touches publisher Requirement 18.3 (the `dev` extra) and flow-runtime Requirement 17, criteria 5 and 6 (the wheel test must fail on a real build error).

**Approval recorded.** The user approved adding `setuptools>=70.1` to the `dev` extra. The bound is 70.1 because setuptools older than 70.1 needs the separate `wheel` package for `bdist_wheel`, and the user decided that no `wheel` package is added. The alternative of skipping the Wheel_Test was not chosen.

| Package | Where | Version bound | Why | Status |
| --- | --- | --- | --- | --- |
| `setuptools` | `[project.optional-dependencies] dev` | `>=70.1` | The Wheel_Test runs `pip wheel --no-build-isolation`, which needs the backend installed | Approved by the user |

#### Acceptance Criteria

1. THE Wheel_Test SHALL keep its assertions (exactly the three Flow YAML files in the wheel) and its no-network flags unchanged.
2. IF the wheel build fails for any reason, including a Backend_Missing_Error, THEN THE Wheel_Test SHALL fail and report the build output, as flow-runtime Requirement 17.6 requires.
3. THE `dependencies` of `pyproject.toml` and the `publish` extra SHALL stay unchanged.
4. THE `pyproject.toml` SHALL list the exact string `setuptools>=70.1` as the last entry of the `dev` extra, in no other list, and SHALL leave `[build-system]` unchanged, including its `requires = ["setuptools>=68", "wheel"]`.
5. THE `dev` extra SHALL be exactly `greenscreen-connector[publish]`, `hypothesis>=6.170.15`, `pytest>=8.0`, `pyyaml>=6.0.3`, `setuptools>=70.1`, in that order, and the project SHALL add no other dependency and no `wheel` package.
6. THE Test_Suite SHALL update the expected `dev` list in every one of the Dev_Extra_Guard_Tests to the list in criterion 5, and SHALL change nothing else in those three files. The executor SHALL re-read `tests/` for any further test that pins the `dev` list before it finishes, and SHALL list every file it found in the design.
7. WHEN a fresh virtual environment is created and `pip install -e ".[dev]"` is the only install, THE Wheel_Test SHALL pass there.
8. THE design SHALL state which setuptools version pip resolves in that fresh environment on Windows, and SHALL record that no `wheel` package was needed or, IF the build fails without it, that the executor stopped and reported the failure instead of adding `wheel`.

**Windows_Evidence.** Windows has setuptools, so the Wheel_Test passes there before and after. Windows proves criteria 1 to 6 (the three Dev_Extra_Guard_Tests and `test_publisher_packaging.py` pass, the Wheel_Test still passes). Criterion 7 and 8 can be run on Windows in a fresh virtual environment, if the executor can create one without a network install of anything outside the project; otherwise the executor reports that they were not run. Windows cannot prove that a fresh Linux environment gets the backend.

**Reviewer_Check (on Linux; Windows alone does not close this requirement):**

1. `python3 -m venv /tmp/gs-fresh && /tmp/gs-fresh/bin/pip install -e ".[dev]" && /tmp/gs-fresh/bin/python -m pip list | grep -i -E "setuptools|wheel" && /tmp/gs-fresh/bin/pytest tests/unit/test_flow_packaging.py -q`. All three tests pass, none skipped. The pip list shows setuptools at 70.1 or higher.
2. `/tmp/gs-fresh/bin/pytest tests/unit/test_flow_model.py tests/unit/test_recognizer_packaging.py tests/unit/test_publisher_packaging.py -q`. All pass.
3. `git diff --stat pyproject.toml` shows one added line.
### Requirement 4: Connector.close() closes the session pipes

**User Story:** As a maintainer of a long-running publisher, I want the Connector to close the three pipes of its subprocess when a session ends, so that descriptors do not wait for garbage collection.

This amends tn3270-connector Requirement 2, criteria 4 and 7 (`close()` behaviour). The measured count was flat at 7 over 40 sessions, so this is tidiness and bounded exposure, not a growth fix.

#### Acceptance Criteria

1. WHEN `Connector.close()` has finished, THE Connector SHALL have closed `proc.stdin`, `proc.stdout` and `proc.stderr` of the session's process, except a pipe whose reader thread is still alive after the join bound (`PIPE_JOIN_SECONDS`), which the Connector leaves open and logs at DEBUG (user decision; see design, Open item 2).
2. WHEN a session ends through the pipe-timeout branch of `_send_with_deadline` (line 147) or the failure branch of `open()` (line 99), THE Connector SHALL close the three Session_Pipes as well.
3. WHEN `close()` is called a second time, or on a Connector that was never opened, THE Connector SHALL return without raising (tn3270-connector Requirement 2, criterion 7).
4. IF closing one Session_Pipe raises an `OSError` or `ValueError`, THEN THE Connector SHALL still try to close the other two, SHALL not raise from `close()`, and SHALL log the failure at DEBUG level on the `greenscreen.connector` logger without any response data, command text or secret.
5. THE Connector SHALL close each Session_Pipe in an order that does not block `close()` on the threads `gs-pipe-reader` and `gs-stderr-drain`, even when one of those threads is blocked in a read, and `close()` SHALL return within the existing bound (5 s for the process wait plus a bound the design states for the pipe closing). THE design SHALL record the order chosen and why.
6. THE Connector SHALL change nothing that a caller sees on Windows: the same return values, exceptions, log messages and timing bounds of `open()`, `close()` and every action as before the change.
7. THE existing Connector and publisher test suites (everything under `tests/` that exercises `Connector` or the publisher) SHALL pass on Windows with no change to any test file that exists today, apart from the files Requirements 1 and 3 name.
8. THE Connector SHALL keep every other behaviour of `close()`: `Disconnect()` then `Quit()`, the 5 s wait, the forced terminate with the warning log, and the `S3270Error` of a later action after the process has exited.
9. THE Test_Suite SHALL contain a test that opens and closes a Connector over a Fake_Host (after Requirement 1) and asserts that `proc.stdin.closed`, `proc.stdout.closed` and `proc.stderr.closed` are true, and the same for a session ended by a pipe timeout. The test SHALL run on every platform.
10. THE Test_Suite SHALL contain a test with a process stand-in whose `stdout` read blocks until closed (a pipe that never reaches end of file), and SHALL assert that `close()` returns within its stated bound and does not hang.

**Windows_Evidence.** Criteria 9 and 10 run on Windows over `FakeS3270` and a stand-in object. They prove that `close()` calls `close` on the three attributes in every ending path and that it does not hang on a blocked reader, as far as Python's file objects behave the same on Windows. They cannot prove how a real `subprocess.Popen` pipe or the real s3270 behaves on Linux when a thread is blocked in `readline` (the buffered-reader lock case in "Findings from reading the code").

**Reviewer_Check (on Linux; Windows alone does not close this requirement):**

1. Pipe tests: `pytest tests/unit -k "connector and close" -q`, with the executor naming the new test file in the design. All pass.
2. Real s3270 descriptor check (needs the live host, so mark it integration and run it by hand): open and close 40 real sessions in a loop and print `ls /proc/$$/fd | wc -l` of the test process (or `len(os.listdir('/proc/self/fd'))`) after each `close()`. After each `close()` returns, the count must equal the count before the first `open()`. The earlier measurement was flat at 7 with the pipes still open, so the new count must be lower than 7 by the three pipe descriptors of the last session.
3. Hang check: `timeout 120 pytest tests/integration -m integration -q -k "connector or logon"` finishes with no hung test.

### Requirement 5: Linux Full_Run and recorded timing

**User Story:** As the reviewer, I want one command on Linux that shows the four fixes work together, so that the readiness claim rests on a run and not on an assumption.

#### Acceptance Criteria

1. WHEN the reviewer runs `ulimit -n 1024 && pytest -m "not integration"` on the Linux box, THE Test_Suite SHALL finish with no "Too many open files" error, no test failure from Requirements 1 to 4, and no test skipped except the Windows-only skips.
2. THE Test_Suite SHALL keep every test that passes on Windows today passing on Windows, and the executor SHALL report the Windows pass, skip and fail counts and the run time before and after the change.
3. THE executor SHALL record the Linux Full_Run duration of 109 s from the reviewer's finding in the design as an observation. No test or criterion SHALL fail because of a duration. IF a later Linux run takes longer than 300 s (about 2.75 times the observation, a generous bound proposed here), THEN the reviewer SHALL report it as a finding, not as a failure of this spec.
4. THE final report of the executor SHALL give the Windows Full_Run pass, skip and fail counts before and after the change, the Windows Full_Run timings before and after, and, for every requirement that carries a Reviewer_Check, the exact Reviewer_Check commands, with each requirement marked "implemented, awaiting Reviewer_Check" or, for a stopped Requirement 2, "stopped, awaiting diagnostic".

**Windows_Evidence.** The Windows Full_Run proves criterion 2 only.

**Reviewer_Check (on Linux; Windows alone does not close this requirement):**

1. `ulimit -n 1024 && pytest -m "not integration" -q -rs 2>&1 | tail -20`.
2. `ls /proc/$$/fd | wc -l` before and after the run, in the same shell, to show that the shell itself holds no leaked descriptor (the count must match).
3. `git status --short` shows no commit and no change under `.kiro/steering`.

## Resolved questions

1. **Two remaining failures.** Confirmed by the user: they are the Stdio_SIGTERM_Test and the Wheel_Test.
2. **Finding 4 and the "flat at 7" measure.** The reviewer measured 7 descriptors for the whole process over 40 sessions. Three pipes per session stay open until collection, so a flat count means collection frees them promptly in that measurement. Finding 1 says collection does not free the Fake_Host descriptors. These fit together only because the Fake_Host has a thread that holds its pipes, and a real `Popen` does not. The design must state this, and Requirement 4.5 of the Reviewer_Check should be run against real s3270.
3. **Wheel in the dev extra.** Resolved by the user: no `wheel` package is added (Requirement 3).
4. **Variant choice.** Resolved by the user: the `setuptools>=70.1` entry in the `dev` extra is approved; the skip alternative was not chosen.
5. **Python 3.14.** Resolved by the user: Python 3.11 through 3.14 are in scope for the SIGTERM fix (Requirement 2, criterion 9).
6. **mainframe-host steering.** Nothing here contradicts it. The steering file states that a disconnect does not end a TSO session, which is why Requirement 4 does not change the logoff steps.

Status update (2026-11): the reviewer's diagnostic on Python 3.14.4 confirmed H1, so criteria 1 and 10 are met and the fix (design, "Requirement 2: SIGTERM root cause confirmed, fix chosen") proceeds as tasks 6 and 7.
