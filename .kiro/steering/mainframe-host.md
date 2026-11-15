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
- 5250 (AS/400) support. Out of scope until the 3270 path works end to end.

## Rules for tests
- Unit and property tests must not need the live host. Use recorded screen
  fixtures or a fake 3270 host.
- Tests that do use the live host are marked as integration tests and are
  skipped when the host is unreachable.

## Verified 2026-11-15 (raw captures in /captures)
- /captures holds exact s3270 stdout for the logo and logon screens, in both
  Ascii() and ReadBuffer(Ascii) form, captured on the host with s3270 4.3.
  Build fixtures from these files; do not invent screen data.
- ReadBuffer(Ascii) returns one `data:` line per row. Each cell is a 2-digit
  hex ASCII code (`4c 6f 67 6f 6e` is "Logon"); `00` is a null cell.
- A field start appears as an `SF(c0=xx)` token that occupies one cell.
  Seen values: e0, e8, f0, f8 (all protected) and c8 (unprotected: the input
  field right after `Logon ===>`). Bit 0x20 of c0 set means protected.
- `SA(42=xx)` tokens (color attributes) also appear on the logon screen.
- The logon screen shows the current date and time in its top-right corner.
  Screen fingerprints must ignore volatile content like this.
- From Windows, `D:\tools\wc3270\ws3270.exe` (v4.5ga6) reached the host at
  192.168.68.72:3270 and returned the logon screen with the same response
  format as s3270 4.3 on Linux. Piped CRLF line endings were accepted.
- SA tokens do NOT occupy a cell (settled by counting the captures): every row
  in both ReadBuffer captures has exactly 80 non-SA tokens, including the 13
  logon rows that carry SA tokens (up to 88 tokens in a row). Hex is lowercase.
