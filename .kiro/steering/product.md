---
inclusion: always
---

# Product: Green Screen Medium

## What it is
A bridge that logs in to a legacy terminal host the way a human operator would,
reads its 24x80 character screens, and replays recorded keystroke sequences on
demand. Every recorded sequence ("flow") is published as an MCP tool and a REST
endpoint.

## Who it is for
Mid-size organizations running mainframe or AS/400 systems they cannot afford
to rewrite: insurers, credit unions, distributors, county governments. The
buyer wants AI agents and modern apps to use those systems this quarter.

## Core pieces
1. Connector: a headless terminal session to the host (3270 first, 5250 later).
2. Screen recognizer: fingerprints each screen by title text and field layout.
3. Recorder: web terminal where a person walks through a transaction once; an
   LLM proposes names and types for the inputs and outputs.
4. Runtime: replays a flow deterministically. NO LLM at runtime. It checks the
   screen fingerprint at every step and fails with a clear error on any
   unexpected screen.
5. Publisher: each saved flow becomes an MCP tool and a REST endpoint with
   generated API docs.
6. Console: web UI with flow library, live session view and call log. Visual
   theme: a medium contacting the dead (green phosphor, seance).

## Non-negotiables
- Runtime is deterministic and auditable; the LLM only helps at recording time.
- A flow never guesses: unknown screen means stop and report.
- Host credentials come from environment/config, never from source code.
- The repo is open source (MIT). The `.kiro` directory is never git-ignored.

## Hackathon context
Kiroween 2026, Resurrection category. Judged equally on impact, use of Kiro
(specs, hooks, steering, MCP, property-based tests, custom agents), design,
innovation and a demo video under three minutes. Deadline: Dec 4, 2026.
