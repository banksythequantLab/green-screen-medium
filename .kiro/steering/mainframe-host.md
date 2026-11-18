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
- Which ISPF/TSO transaction will be the demo story (inquiry plus update).
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

## Verified 2026-11-15: TSO logon flow (captures: tso-password-prompt, ispf-primary-menu)
- Flow that works: Connect, wait for the logon screen (see GOTCHA), type the userid at
  `Logon ===>`, Enter, then the line-mode prompt `ENTER CURRENT PASSWORD FOR
  <userid>-` appears, type the password, Enter, then two `***` pauses (press
  Enter at each), then the full-screen `ISPF primary option menu`.
- Credentials are the stock TK5 demo account. They come only from the
  TK5_USERNAME / TK5_PASSWORD environment variables; never write them in code,
  fixtures or logs.
- The password prompt has a hidden input field: `SF(c0=cc)` at row 1 col 0,
  cursor at row 1 col 1. `Field.hidden` is True for it on real data.
- In TSO line mode the prompt TEXT itself sits in an unprotected field (c8).
  "Unprotected" does not mean "the input field"; use the cursor position and
  the hidden flag as well.
- ISPF primary menu: 84 fields, 63 SA tokens, exactly one unprotected field
  (`Option ===>`, row 1 col 13). It shows the time of day, so fingerprints
  must ignore that cell range.
- GOTCHA: `Wait(N,Output)` returns on the FIRST screen update, which is often
  a blank or partial screen. After Enter, poll the screen until the expected
  text appears (or a timeout); never assume one Wait means the screen is ready.
- GOTCHA (corrected after live runs through the Connector): after Connect the
  host sometimes replaces the Hercules logo with the logon screen by itself
  within a second, and sometimes leaves the logo up until Enter is pressed.
  Never press Enter blindly. Poll for `Logon ===>` first; press Enter only if
  the logo is still showing after a few seconds. An Enter with nothing typed on
  the logon screen produces a screen containing only `INPUT NOT RECOGNIZED`.
  Recovery (verified): send Clear(); the logon screen returns.
- A logon abandoned midway can also leave `IKJ56700A ENTER USERID -` showing
  on the next connection; typing the userid there continues the logon.
- Disconnecting while logged on: on 2026-11-15 the host log showed the user ENDED
  and PURGED within seconds. On 2026-11-17 the opposite was observed (see the last
  section): the user id stayed IN USE for minutes after a disconnect from the ISPF
  menu. The difference is unexplained. Do not rely on a disconnect to end the
  session; always exit with ISPF option X, then LOGOFF at READY.
- Clean exit verified through the Connector: type X at `Option ===>`, Enter,
  wait for `READY`, type LOGOFF, Enter; the logon screen returns and the host
  log shows `LOGGED OFF`. Whole logon-to-logoff run took under 6 seconds.
- Verified on ws3270 4.5 against the live host: `Wait(1,Output)` and
  `Wait(1.5,Output)` are both accepted; on an idle screen the error text is
  `Wait(output): Timed out`.
- Verified 2026-11-16 on s3270 4.3 (Linux, on the host): `Wait(1,Output)`,
  `Wait(1.5,Output)` and `Wait(0.001,Output)` are all accepted. An idle-screen
  timeout returns `error` with the text `Wait(): Timed out` (4.5 says
  `Wait(output): Timed out`). Match timeouts case-insensitively on "timed out".
- `Wait(N,Output)` only blocks if the screen has been READ (Ascii, ReadBuffer)
  since the last host output. With no read in between it returns `ok` at once.
  This is why a bare Enter-then-Wait can return before the new screen exists.

## Verified 2026-11-16: more logon-path screens (captures: tso-input-not-recognized, tso-pause-2, tso-ready)
- `INPUT NOT RECOGNIZED`: the text is on row 3 col 0, cursor at (0,0), 2
  fields, everything else blank. `Clear()` returns to the logon screen.
- SECURITY: after the password is typed and Enter pressed, the NEXT screen
  (first `***` pause) still holds the typed password in the cells of the
  hidden field. `ReadBuffer(Ascii)` and `Screen.cell_grid` contain it, and
  `Screen.text_grid` does NOT blank hidden fields. Anything that stores or
  prints a Screen (fixtures, recordings, logs, error messages, signatures)
  must blank hidden-field cells first. That screen was deliberately not
  captured for this reason; never add a capture of it.
- `***` pause screens are TSO line mode: the content above varies (broadcast
  text, a random fortune) and the `***` row varies (row 10, then row 11). The
  stable facts are that ` ***` is the last non-blank row and the cursor sits
  on that row just after it (col 5). Press Enter to continue.
- `READY`: ` READY` on row 0, cursor at (1,0), fields at (0,0) c8, (0,7) c0,
  (23,79) c0. Reached from ISPF with X then Enter.
- Line-mode screens cannot be identified by fixed row positions alone; a
  signature needs a way to say "the last non-blank row is X" or "the text just
  before the cursor is X".


## Verified 2026-11-16/17: typing, echo, and what must never be logged

- Typing into an unprotected field sets its modified bit: the `tk5-logon` input field
  goes from `SF(c0=c8)` to `SF(c0=c9)` after `String(...)`, and `EraseInput()` returns
  it to `c8`. A screen that has been typed into is therefore not cell-identical to its
  capture; compare geometry, not the attribute byte's low bit.
- s3270 does not echo the `String(...)` argument in its error replies (4.3 on Linux,
  4.5 on Windows): no connection gives `Canceled`, a protected field gives
  `Keyboard locked` / `Operator error`. Unknown actions and syntax errors do not echo
  it either.
- `ReadBuffer(Ascii)` replies contain hidden-field cells as hex. On 2026-11-16 a live
  logon with DEBUG logging wrote the password to the connector log three times (the
  password screen after typing and both `***` pause screens). Fixed in the connector
  (Requirement 12): the `received` log record carries only the redacted action, a
  data-line count, the status line and `ok`/`error`. Re-verified live on 2026-11-16:
  34 received records, no cell data, password absent in plain and hex form.

### Rules that follow

- Never log, print, or put into an exception message any s3270 response data line.
- `S3270Error.data_lines` still holds response text as a structured attribute. Nothing
  may log it, return it to a caller outside the process, or serialise it. The publisher
  (MCP + REST) must not include it in any tool result or HTTP body.
- A traceback's frame locals count as output: no frame inside `greenscreen.flow` may
  hold an input mapping, a supplied value or a `Screen` when an error leaves `run_flow`.


## Verified 2026-11-17: one TSO session per user id, and dropped connections

- A second logon for a user id that is already logged on is refused with no password
  prompt. The screen shows `IKJ56425I LOGON REJECTED, USERID <id> IN USE` on row 0
  (cursor 1,0), and after one more Enter also `IKJ56400A ENTER LOGON OR LOGOFF-` on
  row 2 (cursor 3,0). No bundled signature matches either screen, so a flow stops with
  `unknown_screen` at the password-prompt Expect step.
- Closing the connection without `LOGOFF` (Connector `close()`, or killing s3270) leaves
  the TSO session alive. The user id stayed `IN USE` for at least three minutes and did
  not clear by itself. Every later logon for that id failed.
- Recovery that worked: at `Logon ===>` type `<id> RECONNECT`, Enter, give the password
  at `IKJ56714A ENTER CURRENT PASSWORD FOR <id>-`. The host answers
  `IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED`; Enter until the ISPF menu
  repaints (one `***` pause seen), then `X`, then `LOGOFF` at `READY`.

### Rules that follow

- With one demo account, the publisher runs one call at a time (`GS_MAX_CONCURRENCY=1`).
- Any path that ends a call without the flow's `finally` logoff (call timeout, abort,
  process kill, shutdown) locks the account for the next caller. The publisher needs a
  recovery path for this before it is exposed publicly.


## Verified 2026-11-17 (evening): reconnect from the IN USE screen (captures in /captures/incoming)

Run twice with the same result, model 3279-2 (24x80), account locked by a dropped
connection each time. No capture holds the password (checked in plain and hex form).

1. `tso-userid-in-use`: after the user id and Enter at `Logon ===>`. Row 0 holds
   ` IKJ56425I LOGON REJECTED, USERID <id> IN USE`; fields `SF(c0=c8)` at r0c0 and an
   unprotected `SF(c0=c0)` at r0c47; cursor (1,0). No bundled signature matches.
2. Typing `LOGON <id> RECONNECT` there and Enter gives `tso-reconnect-password-prompt`:
   row 1 shows the typed command, row 2 ` IKJ56714A ENTER CURRENT PASSWORD FOR <id>-`,
   hidden field `SF(c0=cc)` at r3c0, cursor (3,1). This is the same prompt text as
   `tso-password-prompt` but two rows lower, so that signature does not match it.
3. Password and Enter gives `tso-reconnect-ok`: row 0
   ` IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED`, cursor (1,0). This
   screen has no hidden field at all, so it cannot hold the password in hidden cells;
   the capture was also searched for the password in plain and hex form (absent). The host waited: after 4 s
   nothing more arrived, and it needed one Enter.
4. That Enter gives a `***` pause under the same message (recognized as `tso-pause`),
   one more Enter gives the ISPF menu (`ispf-primary-menu`), then `X` gives
   `tso-ready` and `LOGOFF` returns to `tk5-logon`. All four are recognized by the
   bundled signatures.

- Running s3270 without `-model 3279-2` gives a 43x80 screen on this host. The
  Connector always passes the model; capture tooling must too.
- The capture inventory tests pin exactly seven files in `/captures`, so the three new
  captures wait in `/captures/incoming` until a spec adds their signatures and updates
  those tests.


## Verified 2026-11-18: the bundled logon recovers a locked account

- The three captures moved from `/captures/incoming` to `/captures`; there are now ten
  captures and ten bundled signatures.
- `tk5-logon` and `tk5-system-info` handle the IN USE screen themselves: they type
  `LOGON <id> RECONNECT`, give the password at the lower prompt, press Enter at the
  reconnect message, and continue to the ISPF menu.
- Live, with the account locked on purpose (logon, then the connection dropped):
  the flow-level recovery test passed in 9.7 s, and a REST call to the real
  `greenscreen-publish` server returned the four outputs with the recovery handle
  bodies run. The next call took the normal path, so the account was left logged off.
- This replaces the earlier rule that the publisher needs a recovery path before it is
  exposed publicly. What still applies:
  - Recovery is verified only for a session orphaned at the ISPF menu. An orphan left
    at `READY`, in a sub-panel or mid-logon is not handled: the call stops and the log
    shows `session_clean=false`. Manual recovery is the reconnect recipe above.
  - One call at a time per user id (`GS_MAX_CONCURRENCY=1` with one demo account).
  - The publisher logs `session_clean=false` for every stop that skips the logoff
    steps: `unknown_screen`, `ambiguous_screen`, `timeout`, `run_timeout`,
    `session_error`, a call timeout, a cancelled call and shutdown teardown.
