---
inclusion: always
---

# Demo host and 3270 facts

Everything under "Verified" was observed on the real demo host on 2026-11-14.
Do not contradict it. Items under "Not yet verified" must be tested before
code depends on them.

## Verified
- Demo host: MVS 3.8j TK5 (Update 5) on the Hercules emulator 4.9.1.0-SDL.
- Address on the dev LAN: 192.168.68.72, tn3270 on port 3270. The Hercules web
  console is on port 8038. The host address must be configurable.
- The scriptable client is `s3270` (x3270 suite, v4.3). On Windows the same
  suite ships it as `ws3270`. The binary path must be configurable.
- GOTCHA: never pass the host on the s3270 command line. s3270 then runs an
  implicit Wait(InputField), and the first TK5 screen (the Hercules logo) has
  no input field, so it blocks forever. Start s3270 with no host and send
  `Connect(host:port)` as the first command.
- First screen after Connect: Hercules/TK5 logo, all protected fields.
- Sending `Enter()` then `Wait(8,Output)` reaches the MVS logon screen, which
  contains the text `Logon ===>` with the cursor in its input field.
- With `-model 3279-2` the screen is 24 rows by 80 columns.
- s3270 replies to each command with zero or more `data: ` lines, then a
  status line, then `ok` or `error`. `Ascii()` returns the screen as text.
- s3270 block-buffers stdout when it is a pipe; if the process is killed,
  unread output is lost. Always end a session with `Disconnect()` and `Quit()`.

## Not yet verified
- Logging in to TSO with a stock TK5 account and reaching a READY prompt.
- Which transaction will be the demo story (inquiry plus update).
- Field-attribute output from `ReadBuffer(Ascii)` for fingerprinting.
- 5250 (AS/400) support. Out of scope until the 3270 path works end to end.

## Rules for tests
- Unit and property tests must not need the live host. Use recorded screen
  fixtures or a fake 3270 host.
- Tests that do use the live host are marked as integration tests and are
  skipped when the host is unreachable.
