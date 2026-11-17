# Design Document: flow-runtime

## Overview

`greenscreen.flow` is Core Piece 4 of Green Screen Medium. It loads recorded transactions (Flows) from YAML and replays them against a Session. Before every key it checks the screen with `greenscreen.recognizer.recognize`, and it stops with a `FlowError` on any screen it does not expect. No LLM is involved at runtime.

A Flow has typed Inputs, typed Outputs, `steps`, a `finally` list and Timeouts. There are five Step kinds: `expect`, `type`, `key`, `extract` and `handle`. The package ships three Flows (`tk5-logon`, `tk5-logoff`, `tk5-system-info`) as package data.

**Design goals**

- Deterministic and auditable. The runner reads time and sleeps only through an injected Clock. The same Flow, Inputs and Screen sequence produce the same outputs, the same Session calls and the same audit trail (apart from durations).
- Fail closed. A key is sent only when the current host screen is, by recognition, the screen the previous accepted check named. Anything else stops the run.
- No secret or hidden cell leaves the runner. The runner is the only code that holds a `Screen` with hidden cells, and it never stores, logs or raises one. Failures travel inside the runner as plain data (`_Failure`) and are turned into a `FlowError` only after every `Screen` has been released.
- Same conventions as `greenscreen.connector` and `greenscreen.recognizer`: `from __future__ import annotations`, frozen dataclasses with `slots=True`, a package logger, exceptions that do not derive from `ConnectorError` or `RecognizerError`, YAML data shipped as package data and read with `importlib.resources`.
- No new dependencies. The package uses `pyyaml` (already a runtime dependency) and the standard library. `pytest` and `hypothesis` stay in the `dev` extra.

### Research summary

| Question | Finding | Effect on the design |
|---|---|---|
| `yaml.safe_load` and `yaml.safe_dump` ([PyYAML documentation](https://pyyaml.org/wiki/PyYAMLDocumentation)) | `safe_load` builds only standard Python types and returns `None` for an empty document. `safe_dump` takes the emitter keywords, including `sort_keys`. Verified locally on PyYAML 6.0.3: `sort_keys=False` keeps insertion order. `version: true` loads as `True` and `version: 1.0` as `1.0`. A repeated mapping key silently keeps the last value. A 30,000-string fuzz (quotes, colons, `#`, `yes`, `null`, `NEL` U+0085, U+2028, U+FEFF, tabs, newlines, NUL) round-trips with `allow_unicode=False, width=10_000, indent=2, default_flow_style=False`. A float such as `1e-05` is emitted as `1.0e-05` and loads back as a float. | `to_yaml` uses exactly the emit options of `greenscreen.recognizer.yamlio`. The loader checks `type(v) is int` for `version` and for every integer field, because `True == 1`. Duplicate keys cannot be detected without a custom loader and are listed under Known limits. Timeouts are normalized to `float`, so `10` and `10.0` give equal Flows. |
| `raise ... from None` ([Python reference, raise statement](https://docs.python.org/3/reference/simple_stmts.html#the-raise-statement)) | Verified locally: inside an `except` block, `raise X from None` sets `__cause__` to `None` but leaves `__context__` set to the handled exception (`__suppress_context__` is `True`). Raised after the `except` block has ended, both are `None`. | Requirements 6.8, 7.6 and 14.6 ask for `__context__` of `None`. Every `FlowError`, `FlowInputError` and `FlowDefinitionError` is raised outside any `except` block. Code that catches an exception records a plain value (a flag, a class name) and raises after the block. |
| `importlib.resources.files` ([Python documentation](https://docs.python.org/3/library/importlib.resources.html)) | `files(anchor)` returns a `Traversable` for a package. `joinpath(name).read_text(encoding="utf-8")` works from a source tree, a wheel and a zip. Verified locally with `greenscreen.recognizer.signatures`. | `load_bundled_flows` reads each file by name from `files("greenscreen.flow.flows")`. The `flows` directory gets an `__init__.py`, like `recognizer/signatures`, so `setuptools` finds it as a package. |
| Package data ([setuptools data files](https://setuptools.pypa.io/en/stable/userguide/datafiles.html)) | `[tool.setuptools.package-data]` maps a dotted package name to glob patterns. A wheel contains the files those patterns match. | Add `"greenscreen.flow.flows" = ["*.yaml"]` to `pyproject.toml`. Verified locally: `pip wheel . --no-deps --no-build-isolation` builds a wheel offline with the installed `setuptools` 69.5.1 and `wheel` 0.43.0 and includes the existing signature YAML files. |
| Hypothesis `settings` ([max_examples, deadline](https://hypothesis.readthedocs.io/en/latest/reference/api.html), [test-case count](https://hypothesis.readthedocs.io/en/latest/explanation/test-case-count.html)) | `max_examples` defaults to 100. A test runs exactly `max_examples` times unless the search space is exhausted early. `deadline=None` disables the per-example time limit. Installed version: 6.170.15. | Each property test uses `@settings(max_examples=100, deadline=None)` and the property bodies stay small enough for the 35-second budget (Requirement 19.9). Strategies draw from cached in-memory Screens. |
| Per-call cost of `recognize` | Measured locally: 0.72 ms per `recognize` call against the seven bundled signatures on the ISPF menu capture. | A run with about 30 reads costs about 25 ms. 100 examples of two runs per property stay inside the budget (see Testing Strategy). |
| Capture facts for typed screens | Measured on `captures/` through `load_capture_screen`: the `tk5-logon` cursor field starts at row 22 col 10 and has 128 data cells from the cursor. The ISPF menu field starts at row 1 col 13 with 125 data cells. The hidden password field starts at row 1 col 0 with 1838 data cells. The `tso-ready` cursor field starts at row 0 col 7 with 1911 data cells and the cursor is on row 1 col 0. The fields wrap across rows. | Drives the typing edge case and the bounds of Property 8. |

Content from the sources above was paraphrased. The behaviors marked "verified locally" were run on Python 3.11.9 with PyYAML 6.0.3.

---

## Architecture

### Package layout

```
greenscreen/flow/
    __init__.py        # exports exactly the 9 public names
    errors.py          # FlowError, FlowInputError, FlowDefinitionError, REASON_CODES
    clock.py           # Clock protocol, SystemClock
    model.py           # frozen dataclasses: Flow, Timeouts, InputSpec, OutputSpec, 5 Step kinds,
                       #   AuditRecord, FlowResult; plan(flow) = Step_Index numbering
    validate.py        # Flow_Validator: structural_violations, reference_violations, check_flow
    yamlio.py          # Flow <-> YAML (schema version 1), load_flow
    bundled.py         # load_bundled_flows
    inputs.py          # validate and render Input values (Requirement 2.6 to 2.9)
    screens.py         # the only module that reads Screen cells: geometry, comparison, region reads
    runner.py          # run_flow, _RunState, polling, step executors, finally handling, logging
    flows/
        __init__.py    # empty; makes the directory a package
        tk5-logon.yaml
        tk5-logoff.yaml
        tk5-system-info.yaml
```

Imports are limited to the standard library, PyYAML, `greenscreen.connector` (`Screen`, `SFToken`, and `ConnectorError` for the `session_error` mapping) and `greenscreen.recognizer`. The runner also imports two recognizer submodules that are not in the recognizer's nine public names: `greenscreen.recognizer.view.ScreenView` and `greenscreen.recognizer.summary.build_summary`. The recognizer exports no way to build a Redacted_Summary for a screen that was recognized, and Requirement 14.2 needs one for `unexpected_screen` and `timeout`. Adding to the recognizer's public names would break its public-API test, so the flow package imports the submodules directly.

```mermaid
graph TD
    Caller["API / console / tests"] --> Init["__init__ (9 names)"]
    Init --> Runner["runner.run_flow"]
    Init --> YamlIO["yamlio.load_flow / Flow.from_yaml"]
    Init --> Bundled["bundled.load_bundled_flows"]
    Runner --> Inputs["inputs"]
    Runner --> Screens["screens (cells, geometry, comparison)"]
    Runner --> Model["model (plan, AuditRecord, FlowResult)"]
    Runner --> Validate["validate.check_flow"]
    Runner --> Clock["clock.Clock"]
    Runner --> Recognize["greenscreen.recognizer.recognize"]
    Runner --> Summary["recognizer.summary.build_summary + view.ScreenView"]
    Runner --> Session["Session protocol (Connector or Scripted_Session)"]
    YamlIO --> Model
    YamlIO --> Validate
    Bundled --> YamlIO
    Bundled --> Data["flows/*.yaml (package data)"]
    Screens --> ConnectorModels["connector.models (Screen, SFToken)"]
    Validate --> Model
```

### Run structure

```mermaid
sequenceDiagram
    participant C as caller
    participant R as run_flow
    participant S as _RunState
    participant H as Session
    C->>R: flow, session, inputs
    R->>R: validate inputs (no Session call yet)
    R->>S: new state (Current_Screen absent)
    R->>S: run main steps (budget: timeouts.run)
    S->>H: read_screen / string / key (through the Clock-guarded wrappers)
    S-->>R: None or _Failure (plain data)
    R->>S: run finally steps, or skip them (budget: timeouts.finally)
    S-->>R: None or _Failure
    R->>S: release() drops every Screen, the ScreenView cache and the inputs mapping
    alt no failure
        R-->>C: FlowResult
    else failure
        R->>R: del inputs, state; build FlowError from the _Failure
        R-->>C: raise FlowError from None (outside any except block)
    end
```

### Runner state

The runner keeps one `_RunState`. The four facts that decide whether a key may be sent are:

| Name | Holds | Set | Cleared |
|---|---|---|---|
| Current_Screen | `_Accepted(screen, name, view, geometry)` | when an Expect or Handle accepts a screen | when a key is sent |
| Pre_Key_Screen | the `Screen` read just before the last key | when a key is sent | when a screen is accepted |
| Pre_Key_Name | name of the Current_Screen when the last key was sent | when a key is sent | when a screen is accepted |
| Typed_Fields | `set[tuple[int, int, int]]` of (start_row, start_col, byte_length) | by each Type_Step that types | when a screen is accepted and when a key is sent |

```mermaid
stateDiagram-v2
    [*] --> NoScreen
    NoScreen --> Accepted: Expect or Handle accepts a screen
    Accepted --> Accepted: Type_Step adds a Typed_Field
    Accepted --> Accepted: Extract_Step reads the Current_Screen
    Accepted --> KeySent: Key_Step passes the pre-key check and sends the key
    KeySent --> KeySent: poll sees Pre_Key_Screen, Pre_Key_Name, tolerated or unknown screen
    KeySent --> Accepted: poll sees an accepted name on a screen that differs from Pre_Key_Screen
    NoScreen --> Failed: unknown, ambiguous, unexpected or timeout
    KeySent --> Failed: unknown, ambiguous, unexpected or timeout
    Accepted --> Failed: bad_target, secret_target, pre-key check, output errors, loop_limit
    Failed --> [*]
```

`NoScreen` is the start state and also the state after a key. `Failed` is a returned `_Failure`, not an exception.

---

## Components and Interfaces

### `errors.py`

```python
REASON_CODES: tuple[str, ...] = (
    "input_invalid", "timeout", "run_timeout", "unknown_screen", "ambiguous_screen",
    "unexpected_screen", "loop_limit", "bad_target", "secret_target", "hidden_output",
    "output_type", "screen_size", "session_error",
)

class FlowError(Exception):
    reason: str                       # one of REASON_CODES
    step_index: int | None
    expected: tuple[str, ...]         # sorted ascending
    summary: RedactedSummary | None   # never a Screen
    audit: tuple[AuditRecord, ...]
    def __init__(self, reason, *, step_index, kind, expected, summary, audit, detail=""): ...

class FlowInputError(FlowError): ...  # reason "input_invalid", step_index None, no summary, empty audit
class FlowDefinitionError(Exception): ...
```

`FlowError` and `FlowDefinitionError` derive from `Exception` only (Requirement 1.7). `args` is `(message,)`. The message is one line of at most 500 characters:

```
{reason} at step {step_index|none} ({kind|none}): expected {names joined by ","|none} ({count})[; {detail}]
```

`detail` is the exception class name for `session_error`, and for `FlowInputError` it is `input NAME violates RULE`. `NAME` is an Input name; for a supplied name that no Input declares it is the string only when it matches `[A-Za-z][A-Za-z0-9_]{0,31}`, otherwise `<invalid name>`. `detail` never contains an Input value, a cell or a screen row. `FlowError` has no `__reduce__` override; it is not meant to be pickled.

### `clock.py`

```python
class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...

class SystemClock:            # time.monotonic and time.sleep
```

The runner reads the time and sleeps only through the Clock it receives (Requirement 12.4).

### `model.py`

Frozen, slotted dataclasses (see Data Models). Besides the types it provides one numbering function, used by the validator, the runner and the tests so that the three agree:

```python
@dataclass(frozen=True, slots=True)
class PlanItem:
    index: int                     # Step_Index
    phase: str                     # "steps" or "finally"
    step: Step
    children: tuple[PlanItem, ...] # handle body items, else ()

def plan(flow: Flow) -> tuple[tuple[PlanItem, ...], tuple[PlanItem, ...]]:
    """(steps plan, finally plan). Depth-first; a Handle_Step takes its index before its body."""
```

### `validate.py` (Flow_Validator)

```python
@dataclass(frozen=True, slots=True)
class Violation:
    step_index: int | None
    requirement: int     # 1..5
    criterion: int
    field: str
    rule: str            # short fixed text; never a YAML scalar

def structural_violations(flow: Flow) -> list[Violation]       # needs no Signature set
def reference_violations(flow: Flow, names: frozenset[str]) -> list[Violation]   # Requirement 5.1
def check_flow(flow: Flow, signatures: Iterable[ScreenSignature]) -> None
```

`Flow.__post_init__` calls `structural_violations` and raises `FlowDefinitionError` for the first violation (so no invalid `Flow` object exists, Requirement 4.8). `check_flow` adds `reference_violations` against the names of the given Signatures. `Flow.from_yaml`, `load_flow`, `load_bundled_flows` and `run_flow` call `check_flow`. The validator algorithm is in "Validator algorithm" below.

### `yamlio.py`

```python
def to_yaml(flow: Flow) -> str
def from_yaml(text: str, signatures: Iterable[ScreenSignature] | None = None) -> Flow
def load_flow(path: str | os.PathLike[str], signatures=None) -> Flow
```

`Flow.to_yaml()` and `Flow.from_yaml(text, signatures=None)` (a `staticmethod`) delegate here with a local import, the same pattern as `ScreenSignature.to_yaml`. Parsing uses `yaml.safe_load` only, emitting uses `yaml.safe_dump` only. The parse layer checks key sets and value types and raises on the first problem in document order. Model and reference checks run after it. Details are in "YAML schema".

### `bundled.py`

```python
def load_bundled_flows(signatures=None) -> dict[str, Flow]
```

Reads `tk5-logon.yaml`, `tk5-logoff.yaml` and `tk5-system-info.yaml` in that fixed order from `files("greenscreen.flow.flows")`. Each failure (missing file, not UTF-8, unreadable, YAML or validation error, Flow_Name different from the file name) raises `FlowDefinitionError("bundled flow file NAME.yaml: ...")` and no dict is returned. There is no module-level cache; each call builds a new dict (Requirement 21.4).

### `inputs.py`

```python
@dataclass(frozen=True, slots=True)
class PreparedInputs:
    values: dict[str, str]        # rendered values of non-secret Inputs that were supplied
    supplied_secrets: frozenset[str]   # names only

def prepare_inputs(flow: Flow, supplied: Mapping[str, object]) -> PreparedInputs
```

Checks run for each declared Input in declaration order: missing (when required), type (`type(v) is str` or `type(v) is int`), rendered length, printable ASCII, `re.fullmatch`. Then supplied names that no Input declares are checked in sorted order. The first failure raises `FlowInputError` that names the Input and the rule. The function never stores or returns the value of a secret Input and never includes any value in a message (Requirements 2.6 to 2.9). It runs before the first Session call.

### `screens.py`

The only module in the package that reads `Screen.cell_grid`. It never reads `Screen.text_grid`, `Screen.fields`, `Screen.find_field` or `Field.text` (Requirements 10.7, 16.3).

```python
MDT = 0x01   # 3270 modified-data-tag bit of the attribute byte

Geometry = tuple[int, int, tuple[tuple[int, int], ...]]   # (rows, columns, ((linear_start, c0 & ~MDT), ...))

def geometry(screen: Screen) -> Geometry
def build_comparison(pre: Screen, current: Screen, typed: Collection[tuple[int, int, int]]) -> Screen
def read_region(screen: Screen, view: ScreenView, row: int, col: int, length: int) -> str | None  # None if any cell is hidden
def same_screen(a: Screen, b: Screen) -> bool        # cells, sa_tokens and cursor; Screen.__eq__
```

`geometry` visits `cell_grid`, keeps only `SFToken` cells and never decodes an integer cell. Two screens have equal geometry exactly when they have the same size and the same field start positions with the same attribute bytes (the start positions determine the lengths). The MDT bit is cleared before comparing, because typing into a field sets that bit on the host (`c8` becomes `c9`, verified live; see "Pre-key check and Comparison_Screen").

### `runner.py`

```python
def run_flow(
    flow: Flow,
    session: Session,
    inputs: Mapping[str, str | int],
    *,
    signatures: Iterable[ScreenSignature] | None = None,
    clock: Clock | None = None,
    poll_interval: float = 0.1,
) -> FlowResult
```

`Session` is a `typing.Protocol` with `read_screen`, `string`, `enter`, `clear`, `pf`, `pa` and `close`. `close` is declared but never called (Requirement 7.2). `poll_interval` outside 0.01 to 1 raises `ValueError` before any Session call. Internals (the polling loop, the step executors and the finally logic) are described in "Runner algorithm".

### `__init__.py`

Exports exactly `Flow`, `load_flow`, `load_bundled_flows`, `run_flow`, `FlowResult`, `AuditRecord`, `FlowError`, `FlowInputError` and `FlowDefinitionError` in `__all__`. The Session protocol, the Clock and the validator are importable from their modules but are not public names.

### Packaging

`pyproject.toml` gets one new line under `[tool.setuptools.package-data]`:

```toml
"greenscreen.flow.flows" = ["*.yaml"]
```

`dependencies` and `optional-dependencies` stay as they are. `[tool.setuptools.packages.find]` already includes `greenscreen*`, so `greenscreen.flow` and `greenscreen.flow.flows` are found because both contain an `__init__.py`.

---

## Data Models

### Flow definition

```python
@dataclass(frozen=True, slots=True)
class InputSpec:
    name: str; type: str; required: bool; max_length: int
    regex: str | None = None; secret: bool = False; description: str = ""

@dataclass(frozen=True, slots=True)
class OutputSpec:
    name: str; type: str; signature: str; row: int; col: int; length: int

@dataclass(frozen=True, slots=True)
class Timeouts:
    step: float = 10.0; run: float = 120.0; finally_: float = 30.0   # YAML key is "finally"

@dataclass(frozen=True, slots=True)
class ExpectStep:  signatures: tuple[str, ...]; tolerate: tuple[str, ...] = (); timeout: float | None = None
@dataclass(frozen=True, slots=True)
class TypeStep:    text: str | None = None; input: str | None = None
@dataclass(frozen=True, slots=True)
class KeyStep:     key: str; n: int | None = None
@dataclass(frozen=True, slots=True)
class ExtractStep: output: str
@dataclass(frozen=True, slots=True)
class HandleStep:  signature: str; max_count: int; steps: tuple[TypeStep | KeyStep, ...]; settle: float = 0.0

@dataclass(frozen=True, slots=True)
class Flow:
    name: str
    steps: tuple[Step, ...]
    description: str = ""
    inputs: tuple[InputSpec, ...] = ()
    outputs: tuple[OutputSpec, ...] = ()
    finally_steps: tuple[Step, ...] = ()
    timeouts: Timeouts = Timeouts()
```

- Each Step class has a `kind: ClassVar[str]` (`"expect"`, `"type"`, `"key"`, `"extract"`, `"handle"`). Step classes validate nothing themselves; the Flow validator checks them with their Step_Index so every message can name the index.
- `__post_init__` of `Flow` turns lists into tuples (and `Timeouts` numbers and Step timeouts and `settle` into `float`) with `object.__setattr__`, then runs `structural_violations`. Assigning to or deleting a field raises `dataclasses.FrozenInstanceError` (an `AttributeError`), verified locally with `frozen=True, slots=True` (Requirement 1.4).
- The Python field is `finally_` and `finally_steps` because `finally` is a keyword. The YAML keys are `finally` in both places.
- `Flow` equality compares every field. Steps are tuples of frozen dataclasses, so equality is structural and order-sensitive.

### Run results

```python
@dataclass(frozen=True, slots=True)
class AuditRecord:
    step_index: int; kind: str; phase: str            # "steps" | "finally"
    iteration: int | None; signature: str | None
    status: str                                        # "ok" | "skipped" | "failed"
    duration_seconds: float

@dataclass(frozen=True, slots=True)
class FlowResult:
    flow: str
    outputs: Mapping[str, str | int]   # types.MappingProxyType over a dict, declaration order
    audit: tuple[AuditRecord, ...]
```

`AuditRecord` holds names, integers and a float only. Its `repr` is the dataclass default and so shows no input value. `FlowResult.repr` is overridden to show `flow`, the Output names and the number of audit records, never an Output value (Requirement 15.5, 15.3).

`signature` of a record is: for `expect`, the accepted name; for `handle`, the name of the screen that ended it; for `type` and `key`, the Current_Screen name at the time of the Step; for `extract`, the Current_Screen name; `None` when no screen was accepted (for example a skipped Step or an Expect that failed). The iteration count of a Handle_Step (Requirement 9.3) is the highest `iteration` among its body records and the `count` of its DEBUG log record. The Handle_Step's own record has `iteration=None`.

### Internal run data

These never leave `runner.py` and none is stored in any exception, result or log.

```python
@dataclass(slots=True)
class _Accepted:
    screen: Screen            # holds hidden cells; released by _RunState.release()
    name: str
    geometry: Geometry
    view: ScreenView | None   # built lazily; holds no hidden cell text (hidden cells are marked in hidden_mask only)

@dataclass(frozen=True, slots=True)
class _Failure:
    reason: str               # a Reason_Code, or "definition" (internal; becomes FlowDefinitionError)
    step_index: int | None
    kind: str | None
    expected: tuple[str, ...]
    summary: RedactedSummary | None
    detail: str = ""

class _Halt(Exception):       # internal control flow only; carries one _Failure; never leaves run_flow
    failure: _Failure
```

### Reason_Code mapping

| Reason_Code | Raised by | `step_index` | `expected` | `summary` | `finally` after it |
|---|---|---|---|---|---|
| `input_invalid` | `prepare_inputs` (before any Session call) | `None` | `()` | `None` | not run |
| `timeout` | Expect or Handle poll, last read was tolerated, Pre_Key_Name or equal to Pre_Key_Screen | failing Step | sorted accepted names | last screen read | skipped |
| `run_timeout` | budget check before a Session call (main phase, or `finally` phase) | Step that was about to call | `()` | `None` | skipped (main) |
| `unknown_screen` | poll: last recognize raised `UnknownScreenError`; Key_Step: Comparison_Screen unknown | failing Step | sorted accepted names (Key_Step: the Current_Screen name) | last screen read (Key_Step: the Pre_Key_Screen) | skipped |
| `ambiguous_screen` | any `AmbiguousScreenError` | failing Step | as above | as above | skipped |
| `unexpected_screen` | poll: a name no rule accepts; Key_Step: geometry differs or Comparison_Screen recognized as another name; Extract_Step: Current_Screen name differs | failing Step | as above (Extract_Step: `(Output signature,)`) | as above (Extract_Step: the Redacted_Summary of the Current_Screen, `None` when none is held; Requirements 11.3, 14.11) | runs only if a Current_Screen is held |
| `loop_limit` | Handle_Step after `max_count` iterations | Handle_Step | `()` | `None` | runs if a Current_Screen is held |
| `bad_target` | Type_Step: no cursor field or it is protected | Type_Step | `()` | Redacted_Summary of the Current_Screen | runs if a Current_Screen is held |
| `secret_target` | Type_Step of a Secret_Input into a field that is not hidden | Type_Step | `()` | as above | as above |
| `hidden_output` | Extract_Step: a cell of the region is in a hidden field | Extract_Step | `()` | as above | as above |
| `output_type` | Extract_Step: `int` text does not match `[0-9]{1,18}` | Extract_Step | `()` | as above | as above |
| `screen_size` | Extract_Step: screen smaller than 24 by 80 | Extract_Step | `()` | as above | as above |
| `session_error` | a Session method raised any `Exception` that is not a `FlowError` (`ConnectorError`, `OSError`, `RuntimeError`, any other class; Requirement 7.6) | Step that called | `()` | `None` | skipped |
| `definition` (internal, not a Reason_Code) | `recognize` raised `SignatureError` or `TypeError` (Requirement 8.16) | failing Step | `()` | `None` | skipped (Requirement 13.3) |

For a Handle_Step `expected` is `(signature,)` when the reason is one of the four screen reasons. For `definition` the runner raises `FlowDefinitionError` with only the exception class name and sends no further key (Requirement 8.16). Its Finally_Steps get `skipped` records like those of any other skip reason, so the list `_FINALLY_SKIP_REASONS` in the runner holds `definition` next to the six Reason_Codes of Requirement 13.3. `FlowDefinitionError` carries no `audit`, so the tests of the `definition` path (Requirement 18.22) read the audit trail from a `_RunState` driven directly.

A Session method that raises a `BaseException` that is not an `Exception`, or a `FlowError`, produces no `_Failure` at all: it propagates out of `run_flow` unchanged after the Run_State is released (see "Session access" and "Entry and exit").

### Log record shape

One logger, `logging.getLogger("greenscreen.flow")`, DEBUG only. Every record's message is built from `%s` and `%d` placeholders whose arguments are `str` or `int` values from this list: Flow_Name, Step_Index, Step kind, Signature_Name, a count, a Reason_Code and a duration in milliseconds. No other field exists, so the records are:

```
flow=%s step=%d kind=%s                                    # a Step begins
flow=%s step=%d kind=%s signature=%s count=%d ms=%d        # a Step ends (count = reads, keys or iterations)
flow=%s step=%s reason=%s                                  # the run stops (step is a number or "none")
flow=%s count=%d ms=%d                                     # the run ends without error (count = audit records)
```

No `Screen`, `Field`, cell text or input value is ever passed as an argument.

---

## YAML schema

Schema version 1. Top-level keys are emitted in this fixed order, and every key is emitted. The loader requires `version`, `name` and `steps`; the others default as shown.

| Key | Type | Default | Notes |
|---|---|---|---|
| `version` | integer `1` | required | `type(v) is int and v == 1`; `true`, `"1"`, `1.0` and a missing key are rejected |
| `name` | string | required | Flow_Name |
| `description` | string | `""` | 0 to 500 characters |
| `inputs` | list of Input mappings | `[]` | Input keys: `name`, `type`, `required`, `max_length`, `secret` (always emitted), `regex` (emitted only when set), `description` (emitted only when not empty). No other key is accepted. |
| `outputs` | list of Output mappings | `[]` | keys `name`, `type`, `signature`, `row`, `col`, `length` |
| `timeouts` | mapping `step`, `run`, `finally` | 10, 120, 30 | numbers (not booleans), normalized to `float`; always emitted with all three keys |
| `steps` | list of Step mappings | required | 1 to 200 Steps |
| `finally` | list of Step mappings | `[]` | 0 to 50 Steps |

Step mappings always start with `kind`. Key order after `kind`:

| kind | keys in emitted order | Emitted only when |
|---|---|---|
| `expect` | `signatures`, `tolerate`, `timeout` | `tolerate` is not empty, `timeout` is set |
| `type` | exactly one of `text` or `input` | |
| `key` | `key`, `n` | `n` is set (`pf`, `pa`) |
| `extract` | `output` | |
| `handle` | `signature`, `max_count`, `settle`, `steps` | `settle` is always emitted |

Emit options: `yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=False, width=10_000, indent=2)`. Because every default is normalized and every optional key is omitted exactly when it holds its default, two equal Flows emit identical text and `from_yaml(to_yaml(flow)) == flow`.

Parse errors name the key and, for list items, the zero-origin index, for example `steps[3]: unknown key 'foo'` or `inputs[1]: key 'max_length' must be an integer`. They never contain a YAML scalar value other than a truncated unknown key name. The unsupported Step kind is the one scalar value that Requirements 1.3 and 4.9 require; it is echoed only when it matches `[A-Za-z0-9_-]{1,32}` and replaced by `<invalid>` otherwise. A YAML syntax error reports `malformed YAML at line L, column C` from `problem_mark`, never `str(yaml_error)`.

### Shipped flows

`greenscreen/flow/flows/tk5-logon.yaml`:

```yaml
version: 1
name: tk5-logon
description: Log on to TSO on the TK5 demo host and stop at the ISPF primary option menu.
inputs:
- name: userid
  type: str
  required: true
  max_length: 8
  secret: false
  regex: '[A-Za-z0-9@#$]{1,8}'
  description: TSO user id.
- name: password
  type: str
  required: true
  max_length: 8
  secret: true
  description: TSO password.
outputs: []
timeouts:
  step: 10.0
  run: 120.0
  finally: 30.0
steps:
- kind: handle
  signature: tk5-logo
  max_count: 1
  settle: 3.0
  steps:
  - kind: key
    key: enter
- kind: handle
  signature: tso-input-not-recognized
  max_count: 1
  settle: 0.0
  steps:
  - kind: key
    key: clear
- kind: expect
  signatures:
  - tk5-logon
- kind: type
  input: userid
- kind: key
  key: enter
- kind: expect
  signatures:
  - tso-password-prompt
- kind: type
  input: password
- kind: key
  key: enter
- kind: handle
  signature: tso-pause
  max_count: 5
  settle: 0.0
  steps:
  - kind: key
    key: enter
- kind: expect
  signatures:
  - ispf-primary-menu
finally: []
```

`greenscreen/flow/flows/tk5-logoff.yaml`:

```yaml
version: 1
name: tk5-logoff
description: Leave ISPF with X, log off at READY and end on the logon screen.
inputs: []
outputs: []
timeouts:
  step: 10.0
  run: 120.0
  finally: 30.0
steps:
- kind: expect
  signatures:
  - ispf-primary-menu
- kind: type
  text: X
- kind: key
  key: enter
- kind: expect
  signatures:
  - tso-ready
- kind: type
  text: LOGOFF
- kind: key
  key: enter
- kind: expect
  signatures:
  - tk5-logon
finally: []
```

`greenscreen/flow/flows/tk5-system-info.yaml` (the first and last blocks of `steps` are the Steps of the two files above, written out in full in the file; `inputs` are the two of `tk5-logon`):

```yaml
version: 1
name: tk5-system-info
description: Log on, read the user id, terminal, release and system id from the ISPF menu, log off.
inputs:
- name: userid
  type: str
  required: true
  max_length: 8
  secret: false
  regex: '[A-Za-z0-9@#$]{1,8}'
  description: TSO user id.
- name: password
  type: str
  required: true
  max_length: 8
  secret: true
  description: TSO password.
outputs:
- {name: USERID,   type: str, signature: ispf-primary-menu, row: 2,  col: 71, length: 8}
- {name: SYSTEMID, type: str, signature: ispf-primary-menu, row: 12, col: 71, length: 8}
- {name: RELEASE,  type: str, signature: ispf-primary-menu, row: 10, col: 71, length: 8}
- {name: TERMINAL, type: str, signature: ispf-primary-menu, row: 4,  col: 71, length: 8}
timeouts:
  step: 10.0
  run: 120.0
  finally: 30.0
steps:
# --- the 10 Steps of tk5-logon, unchanged ---
# --- extracts, in screen order ---
- kind: extract
  output: USERID
- kind: extract
  output: TERMINAL
- kind: extract
  output: RELEASE
- kind: extract
  output: SYSTEMID
# --- the 7 Steps of tk5-logoff, unchanged ---
finally:
- kind: handle
  signature: ispf-primary-menu
  max_count: 1
  settle: 0.0
  steps:
  - kind: type
    text: X
  - kind: key
    key: enter
- kind: handle
  signature: tso-ready
  max_count: 1
  settle: 0.0
  steps:
  - kind: type
    text: LOGOFF
  - kind: key
    key: enter
- kind: expect
  signatures:
  - tk5-logon
```

(The `outputs` lines are shown in flow style to save space. The shipped file is written exactly as `to_yaml()` emits it, in block style.) The four regions were read from `captures/ispf-primary-menu.readbuffer.txt` on 2026-11-16: the label for each row (`USERID   :`, `TERMINAL :`, `RELEASE  :`, `SYSTEMID :`) starts at col 60 and the value region at col 71 is eight cells with no hidden field. A unit test re-reads this on every run (Requirement 17.14).

Design choices that the three files rely on:

- `max_count` is 1 for the logo and `INPUT NOT RECOGNIZED` Handle_Steps (Requirements 17.5 and 17.6 do not fix it). One Enter or one Clear is the verified recovery.
- Every Handle_Step is followed by an Expect_Step before the next Type_Step or Key_Step (Requirement 5.8).
- No `text` literal in any shipped file holds a userid, a password or `${`.

---

## Validator algorithm

`structural_violations(flow)` returns every violation; the first by the ordering below is raised.

1. **Flow fields** (Requirements 1.1, 1.6, 5.12, 5.13 numbering aside): Flow_Name pattern, `description` length, counts of `inputs`, `outputs`, `steps`, `finally_steps` (a Handle_Step body counts toward the 200 and 50 limits), Timeouts ranges.
2. **Inputs** (Requirement 2.1 to 2.5): name pattern and uniqueness (case-sensitive), `type`, `required`, `max_length` (`type(v) is int`, 1 to 255), `regex` (1 to 200 characters and `re.compile` succeeds), `secret` implies `type: str`, description length.
3. **Outputs** (Requirement 3.1): name pattern and uniqueness, `type`, `row`, `col`, `length`, `col + length <= 80`.
4. **Steps**, by walking `plan(flow)` (Step_Index order) with this state per Step list:
   - `armed: bool` (initially `False` for a top-level list, `True` for a handle body) and `arming: ExpectStep | None`.
   - `ExpectStep`: check 1 to 5 distinct `signatures`, 0 to 5 distinct `tolerate` names not in `signatures`, `timeout` in 0.1 to 60. Then `armed = True`, `arming = step`.
   - `TypeStep`: exactly one of `text` (1 to 255 printable ASCII characters, no `${`) or `input` (declared; a Secret_Input is allowed here and nowhere else). Requires `armed`. Does not change `armed`.
   - `KeyStep`: `key` in `enter, clear, pf, pa`; `n` required (1 to 24, `type(v) is int`) for `pf` and `pa` and rejected otherwise. Requires `armed`. Then `armed = False`, `arming = None`.
   - `ExtractStep`: `output` declared. Allowed only in `steps`, outside handle bodies. Requires `arming is not None` and `output.signature in arming.signatures` (Requirement 5.9). Does not change `armed`.
   - `HandleStep`: `signature`, `max_count` 1 to 20, `settle` 0 to 10, 1 to 50 body Steps that are `TypeStep` or `KeyStep` only (a nested Handle_Step is rejected at any depth). The body is walked with `armed = True`. Afterwards `armed = False`, `arming = None` (Requirement 5.8).
   - Any other Step class raises a `kind` violation; any unknown field is a parse-layer error and cannot reach this point.
   - After the walk: each declared Output is named by exactly one Extract_Step (Requirement 4.7).
5. **Secret references** (Requirement 5.10) fall out of step 4: the only place a Step names an Input is `TypeStep.input`, and the YAML parser rejects an `input` key on any other kind. The `${` check covers literals (Requirement 5.11).

`reference_violations(flow, names)` reports every Signature_Name used by an Expect_Step (`signatures`, `tolerate`), a Handle_Step or an Output that is not in `names`.

**Ordering when several violations exist** (Requirement 5.14): violations with a Step sort first, by `(step_index, requirement, criterion)`. Violations without a Step follow, by `(requirement, criterion, field)`. The error message is `FlowDefinitionError: step 4 (type): field 'input' violates rule 'unarmed'` or, without a Step, `field 'inputs' violates rule 'too_many'`. It contains only the Step_Index, the Step kind, field names, fixed rule text, the Flow_Name, Signature_Names and Input or Output names (Requirement 5.15).

The validator never reads an environment variable (Requirement 16.5), a file or the Session.

---

## Pre-key check and Comparison_Screen

### The check at every Key_Step

```mermaid
sequenceDiagram
    participant K as Key_Step
    participant H as Session
    participant G as screens
    participant Rz as recognize
    K->>H: read_screen()  (exactly once, Pre_Key_Screen)
    K->>G: geometry(pre) == current.geometry ?
    alt geometry differs
        K-->>K: _Failure unexpected_screen (no recognize call, no key)
    else equal
        K->>G: build_comparison(pre, current.screen, typed)
        K->>Rz: recognize(comparison, Flow_Signatures)
        K->>K: del comparison
        alt unknown / ambiguous
            K-->>K: _Failure with summary of pre
        else name != current.name
            K-->>K: _Failure unexpected_screen with summary of pre
        else name == current.name
            K->>H: key call (enter, clear, pf n, pa n)
            K->>K: pre_key_screen = pre, pre_key_name = current.name, current = None, typed cleared
        end
    end
```

### Building the Comparison_Screen without exposing hidden text

`Screen` is a mutable dataclass: `cell_grid: list[list[int | SFToken]]` and `sa_tokens: list[list[tuple[int, SAToken]]]`. Integer cells and `SFToken` cells are immutable values. `build_comparison` copies the row lists of the Pre_Key_Screen, overwrites the data cells of each Typed_Field with the integer cells of the Current_Screen, and wraps the result in a new `Screen`:

```python
def build_comparison(pre, current, typed):
    cols, total = pre.columns, pre.rows * pre.columns
    grid = [row[:] for row in pre.cell_grid]              # new row lists; cells are immutable
    for (row, col, length) in typed:                      # geometry only; no cell content is kept in Typed_Fields
        base = row * cols + col                           # linear position of the SF cell
        for offset in range(1, length + 1):               # same wrap arithmetic as Screen._build_field
            r, c = divmod((base + offset) % total, cols)
            grid[r][c] = current.cell_grid[r][c]
    return Screen(rows=pre.rows, columns=cols,
                  cursor_row=pre.cursor_row, cursor_col=pre.cursor_col,
                  cell_grid=grid, sa_tokens=[list(t) for t in pre.sa_tokens])
```

Facts that make this safe:

- The function runs only after `geometry(pre) == geometry(current)`, so every position inside a Typed_Field is a data cell on both screens (never an `SFToken`).
- It reads integer cells by index. It never calls `Screen.text_grid`, `Screen.fields`, `Screen.find_field` or `Field.text`, so no hidden field is turned into a `str`.
- For a hidden Typed_Field the restored cells are the Current_Screen cells (typically blank, or residual content that is already on that screen). `ScreenView` marks hidden cells in `hidden_mask` and never copies their characters, so `recognize` cannot see them either way. Restoring hidden fields is kept because Requirement 8.19 asks for it and because it keeps one code path.
- The Comparison_Screen exists as a local variable of `_key_check` only. `_key_check` ends with `del comparison` on every path and returns a plain value (a name or a `_Failure`). No exception is in flight while the Comparison_Screen exists, so no traceback frame can hold it. The `_Failure` carries `build_summary(ScreenView(pre))`, which shows every hidden cell as `*`.
- `Typed_Fields` stores `(start_row, start_col, byte_length)` triples. No typed text and no cell content is stored anywhere (Requirement 8.19).
- The Pre_Key_Screen stays in `_RunState` until the next screen is accepted, because the stale-read rule compares against it. It can hold a typed password in its hidden cells. It is dropped by `release()` before any `FlowError` is created.

### Why the check needs the restore step

`ScreenView` (and so `recognize`) sees typed text in visible fields. A typed screen can stop matching its own signature. The case in the bundled signatures is `tso-ready`, which has one matcher: `last_row` equal to ` READY`. Typing `LOGOFF` at the cursor on row 1 makes row 1 the last non-blank row, so the typed screen is unknown. Restoring the typed field to its Current_Screen content gives back a screen whose last non-blank row is ` READY`, and the check passes.

The other three typed screens use `cursor_field`, which resolves the field that contains the cursor. Checked against `greenscreen/recognizer/signatures/*.yaml` and the captures:

| Signature | Matchers that look at typed or cursor cells | Effect of typing `n` characters at the cursor |
|---|---|---|
| `tk5-logon` | `text_at` on rows 0, 1 and 22; `field_layout`; `cursor_field` (22, 10) | The typed cells are restored. The cursor moves from (22, 11) to (22, 11+n), still in the same field while `n` is below the 128 data cells, so `cursor_field` matches. |
| `tso-password-prompt` | `region_regex` on row 0; `cursor_field` (1, 0) hidden | Typed cells are hidden and restored. Cursor stays in the hidden field while `n` is below 1838. |
| `ispf-primary-menu` | `text_at` on rows 0 and 1; `field_layout`; `cursor_field` (1, 13) | The cursor stays in the field while `n` is below 125. |
| `tso-ready` | `last_row` only | No cursor matcher. Restoring the typed field fixes the match for any `n`. |
| `tso-pause` | `last_row`, `before_cursor` | Never typed into by a shipped flow. |

### Edge case: typing fills the field and the cursor leaves it

The Comparison_Screen keeps the Pre_Key_Screen cursor (Requirement 8.9). If a Type_Step types as many characters as the cursor field has data cells left, the host cursor moves out of the field. For a signature with a `cursor_field` matcher the Comparison_Screen then does not match its own signature: `recognize` raises `UnknownScreenError` (or returns another name), the Key_Step raises `FlowError` with `reason` `unknown_screen` (or `unexpected_screen`), and no key is sent. The failure is safe and its Redacted_Summary shows the cursor outside the field, but it is a false stop: the screen was right.

How the design handles it:

- **No runtime limit.** The runner does not refuse the Type_Step. The shipped Flows cannot reach the case: the longest typed text is the 8-character userid or password, against 128, 1838 and 125 available cells, and the literals `X` and `LOGOFF` are 1 and 6 characters. The case needs a text at least as long as the room left in the field.
- **Cursor behavior is not verified.** Where the real host puts the cursor after the last cell of a field was not observed on the demo host. The runner does not depend on it: any cursor outside the field gives the same stop. A live check belongs in the first run of the integration test (a note in the tasks, not a code dependency).
- **`tso-ready` is immune** because it has no cursor matcher.
- **Property 8** (Requirement 19.11) avoids the case for screens whose signature contains a `cursor_field` matcher by drawing the length from 1 to `min(255, R - 1)`, where `R` is the number of data cells from the cursor to the end of the field. For `tso-ready`, the draw is 1 to `min(255, R)`. A separate unit test types exactly `R` characters into the `tk5-logon` and `ispf-primary-menu` fields, places the cursor outside the field, and asserts `FlowError` with `reason` `unknown_screen` and zero key calls, so the behavior is pinned and documented.
- **Alternative, not chosen:** refuse a Type_Step with `bad_target` when the rendered text is at least `R` characters. This turns a confusing `unknown_screen` into a clear error but rejects a fill that may be valid. It needs an extra rule in Requirement 10 and is listed under the decisions to confirm.

### Other consequences of the restore rule

- **The whole Typed_Field is restored, not only the typed span.** For `tso-ready` the typed field is the one that starts at row 0 col 7 and has 1911 data cells, which is nearly the whole screen. After typing `LOGOFF`, any change the host makes elsewhere in that field (a broadcast message, for instance) is hidden by the restore and does not stop the key. The check still verifies geometry, every `cursor_field` and `field_layout` matcher, and every `text_at` matcher outside the field. Restoring only the typed span would be tighter for line-mode screens; Requirement 8 names whole fields, so the design follows it.
- **The modified bit.** Typing into a field makes a 3270 host set the MDT bit (`0x01`) in that field's attribute byte, and `ReadBuffer` then shows `c9` instead of `c8`. Verified on the live host: typing into the `tk5-logon` input field changes its attribute byte from `c8` to `c9` (MDT bit `0x01` set), and `EraseInput` returns it to `c8`. `geometry` therefore compares `c0 & ~0x01` (MDT cleared on both sides), so a typed field does not count as a changed field. The unit tests for typed screens run with the bit set and with it clear. Two further tests pin the comparison: a `tk5-logon` screen against a copy whose input field attribute is `c9` must pass the geometry check, and a copy whose field is `e8` (protected) instead of `c8` must fail it. The bit `0x20` (protected) is not masked, so a change from unprotected to protected is a geometry change.
- **Consecutive identical screens.** After a key, a screen equal to the Pre_Key_Screen in cells and cursor means "the host has not answered". Two real consecutive screens that are exactly equal cannot be told apart from a stale read and end in `timeout`. The Scripted_Session tests for the two `tso-pause` screens therefore use two distinct variants.

---

## Runner algorithm

### Entry and exit

```python
def run_flow(flow, session, inputs, *, signatures=None, clock=None, poll_interval=0.1):
    # 1. validate poll_interval (ValueError); resolve clock (SystemClock if None)
    # 2. sigs = Signatures whose names the Flow references (default load_bundled_signatures());
    #    a referenced name missing from `signatures` raises FlowDefinitionError (no Session call)
    # 3. prepared = prepare_inputs(flow, inputs)             -> FlowInputError, no Session call
    # 4. state = _RunState(flow, session, sigs, clock, poll_interval, prepared, inputs)
    # 5. try:
    #        failure = state.run_phase("steps")              -> None | _Failure
    #        finally_failure = state.run_finally(failure)    -> None | _Failure (skips per Requirement 13)
    #    except BaseException:                               # not a _Halt: those never get here
    #        state.release(); _clear_frames(sys.exc_info()[2]); del state, inputs, prepared
    #        raise                                           # same object (Requirements 7.8, 7.9)
    # 6. outputs = {o.name: state.outputs[o.name] for o in flow.outputs}   # declaration order
    #    audit = tuple(state.audit); state.release(); del state, inputs, prepared
    # 7. decide: failure = failure or finally_failure         (main wins, Requirement 13.5 and 13.6)
    #    None  -> return FlowResult(flow.name, outputs, audit)
    #    "definition" -> raise FlowDefinitionError(...) from None
    #    else  -> raise FlowError(...) from None   # outside any except block
```

`session.close` is never called. `run_phase` and `run_finally` contain `try/except _Halt` only to turn a halt into a returned `_Failure`; the `raise` of the final error is in step 7, outside any handler, in a frame that holds no `Screen` (Requirements 14.6, 14.7).

**Output order (Requirement 3.10, 15.8).** `state.outputs` is filled in the order the Extract_Steps run. Step 6 rebuilds it from `flow.outputs`, so `list(result.outputs)` is the declaration order whatever the order of the Extract_Steps. The rebuild is safe on the success path because the validator requires exactly one Extract_Step per declared Output in `steps` (Requirement 4.7), and a run that reaches step 6 without a failure has run all of them. On a failure path `outputs` is not used. For `tk5-system-info` the Extract_Steps run as `USERID`, `TERMINAL`, `RELEASE`, `SYSTEMID` and the result keys are `USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`. `FlowResult.outputs` is a `MappingProxyType` over that dict, which keeps insertion order.

**Release on the escape path (Requirements 7.8, 7.9).** A `KeyboardInterrupt`, `SystemExit` or `FlowError` that a Session method raises, or any bug exception of the runner, is not a `_Halt`, so it leaves `run_phase` or `run_finally` and reaches the `except BaseException` clause of step 5. That clause does four things in this order and then re-raises with a bare `raise`, so the exception object is the same and no Finally_Step has run (`run_finally` is inside the `try`) and no key is sent afterwards:

1. `state.release()` drops the Screens, the Typed_Fields, the Comparison_Screen if one is alive and the inputs mapping reference of the state.
2. `_clear_frames(tb)` walks the traceback of the propagating exception. It skips the first entry (the `run_flow` frame, which is still executing) and, for every later entry whose frame belongs to a module whose `__name__` starts with `greenscreen.flow`, calls `frame.clear()`. Those frames have finished unwinding, so `clear()` is allowed; it empties the locals that held a `Screen`, the typed text of `string(text)`, the cached view or a `_Accepted`. Frames of the Session implementation are left alone, because they are not the runner's.
3. `del state, inputs, prepared` removes the `run_flow` locals that name the state, the caller's mapping and the prepared values. `_clear_frames` is called with `sys.exc_info()[2]` as an argument and no local of `run_flow` names the traceback, so the clause adds no reference of its own.
4. The bare `raise`.

Verified locally on Python 3.11: after this sequence the `f_locals` of the inner frames of a propagating `KeyboardInterrupt` are empty and the `run_flow` frame keeps no parameter. The `_Halt` path needs none of this: a `_Halt` is caught and dropped inside `run_phase` or `run_finally`, and the `FlowError` of step 7 is created after the release, with only the `run_flow` frame and the small builder frame in its traceback.

### Session access

All Session calls go through three helper methods of `_RunState`: `read`, `string` and `key`. Each one first runs `_budget()`, which compares `clock.monotonic() - phase_start` with the phase limit (`timeouts.run` for `steps`, `timeouts.finally_` for `finally`) and halts with `run_timeout` before the call (Requirements 12.2, 12.3). Each wraps the call in the same three-way pattern, which is the one `runner.py` already uses for failures as data:

```python
failed = None
try:
    result = self.session.read_screen()        # or string(text), enter(), clear(), pf(n), pa(n)
except FlowError:
    raise                                      # Requirement 7.9: unchanged, released by run_flow
except Exception as exc:                       # Requirement 7.6: any class, no whitelist
    failed = type(exc).__name__                # a str; exc is dropped when the block ends
# a BaseException that is not an Exception (KeyboardInterrupt, SystemExit) is not caught here (7.8)
if failed is not None:
    raise _Halt(_Failure("session_error", idx, kind, (), None, failed)) from None
```

Rules that follow from this pattern:

- **Where exceptions are caught.** Only in the three helpers, one `try` each (`read` for `read_screen`, `string` for `string`, `key` for `enter`, `clear`, `pf` and `pa`). No executor and no other method of the runner catches a Session exception. This replaces the earlier whitelist of `ConnectorError` and `OSError` and the secret-only `except Exception`: the wider rule needs no `secret` flag, so `string()` loses its `secret` keyword and `_type_secret` calls it like any other typing.
- **Failure as data, raise after the handler.** The `except` block records one string (the class name) and ends. The `_Halt` is raised after the block, so it has no `__context__`; `from None` marks `__suppress_context__` and is correct because it sits outside any `except` block. The Session exception is unreachable once the block ends: no variable holds it, and the `_Failure` holds the class name only.
- **Release before the `FlowError`.** The `_Halt` travels up to `run_phase` or `run_finally` and becomes a returned `_Failure`. `run_flow` releases the Run_State (step 6 of "Entry and exit") and only then builds and raises the `FlowError` from that `_Failure`. The Finally phase is skipped for `session_error` (Requirement 13.3), so no further Session call follows.
- **`FlowError` from a Session** is the one `Exception` excluded from conversion. `except FlowError: raise` lets it pass; the escape-path clause of `run_flow` releases and re-raises the same object.
- **`BaseException` that is not an `Exception`.** Not caught by any helper. It leaves through `run_flow`'s escape clause, unchanged, after release and frame clearing (see "Release on the escape path").
- **A Session that returns `None` from `read_screen`** is treated as a `session_error` with the class name `NoScreen`, as before.
- **The secret value.** `_type_secret` keeps the value in one local and deletes it in a `finally` block. The helper `string(text)` holds it as a parameter, so a `session_error` or an escape from `string` leaves it in a frame; for the `_Halt` path the frame is freed when `run_phase` drops the halt, and for the escape path `_clear_frames` empties it.

### Polling (Expect_Step, and the waits of Handle_Step)

```
def _poll(step, accepted, tolerate, timeout, accept_any):
    start = clock.monotonic()
    reads = 0
    while True:
        screen = _read();  reads += 1
        pre = state.pre_key_screen
        if pre is not None and screen == pre:              # Requirement 8.12: no answer yet
            last = "same"
        else:
            outcome = _recognize(screen)                   # ("name", n) | ("unknown",) | ("ambiguous",) | ("definition",)
            if unknown:      last = "unknown"
            elif ambiguous:  halt ambiguous_screen          # before any further read or sleep
            elif definition: halt definition
            else:
                n = outcome.name
                if accept_any or n in accepted:  accept(screen, n); return n
                elif n in tolerate:              last = "tolerated"
                elif pre is not None and n == state.pre_key_name:  last = "prekey"   # Requirement 8.20
                else:  halt unexpected_screen                                       # Requirement 8.8, 8.21
        if clock.monotonic() - start >= timeout:
            halt unknown_screen if last == "unknown" else timeout
        clock.sleep(poll_interval)
```

- At least one attempt is made. The last read happens at or after the deadline, then the loop halts. Reads are `poll_interval` apart as measured on the Clock.
- A halted poll builds the Redacted_Summary of the last screen read (`recognize` supplies it for unknown screens; `build_summary(ScreenView(screen))` is used otherwise) and drops the `Screen` before returning the `_Failure`.
- `accept(screen, name)` sets Current_Screen to `_Accepted(screen, name, geometry(screen), None)` and clears Pre_Key_Screen, Pre_Key_Name and Typed_Fields (Requirements 8.18, 8.20).
- `recognize` is called with the Flow_Signatures. A `SignatureError` or `TypeError` becomes the internal `definition` failure (Requirement 8.16).
- An `AmbiguousScreenError` halts at once, so no second read or sleep happens (Requirement 8.7). The same holds for `unexpected_screen`.

### Step executors

| Step | Behavior |
|---|---|
| `expect` | `_poll(accepted=signatures, tolerate=tolerate, timeout=step.timeout or timeouts.step, accept_any=False)`. Always reads at least once, even when a Current_Screen is held. |
| `type` | See "Type_Step". |
| `key` | See the sequence under "The check at every Key_Step". Sends exactly one of `enter()`, `clear()`, `pf(n)`, `pa(n)`. |
| `extract` | See "Extract_Step". |
| `handle` | See "Handle_Step". |

Each Step appends one `AuditRecord` when it begins to run, with status updated on exit. A Step skipped by Requirement 10.6 or by the finally rules gets `skipped` and `0.0`. When a Step halts, its record becomes `failed` and the halt continues up. Records of later Steps are not created (Requirement 14.8).

### Type_Step

1. Require a Current_Screen (an internal guard; the validator makes this unreachable).
2. Optional Input not supplied: record `skipped`, make no Session call.
3. Resolve the cursor field with `ScreenView.containing_field(cursor_row, cursor_col)` on the cached `view` of the Current_Screen. This gives a `FieldGeom` (start, length, `protected`, `hidden`) and no cell text. If it is `None` or `protected`: `bad_target`.
4. A Secret_Input into a field with `hidden` false: `secret_target`.
5. Call `session.string(text)` exactly once with the literal, the rendered non-secret value, or the secret value read from `inputs` at this moment.
6. Add `(start_row, start_col, byte_length)` to Typed_Fields. Nothing else is kept. Current_Screen is not replaced and no screen is read.

Requirement 10.1 names `ScreenView.containing_field`, and the runner uses exactly that. It returns the field geometry and the `protected` and `hidden` flags and never reads `Field.text`, which is what Requirements 10.7 and 14.7 need. `Screen.find_field` is not used in the package: it builds a `Field` whose `text` holds the hidden cells before the caller can look at `hidden`. A unit test (Requirement 18.24) spies on `containing_field` to show that every Type_Step goes through it and that no `Field.text` of a hidden field is read. A second unit test uses `find_field` only as a test-side oracle and checks that it agrees with `containing_field` on start position, length, `protected` and `hidden` for the cursor of every capture.

### Extract_Step

On the Current_Screen, in this order: the Current_Screen name must equal the Output `signature` (`unexpected_screen`, no cell read); `rows >= 24` and `columns >= 80` (`screen_size`); `view.hidden_mask` must have no mark inside the region (`hidden_output`, no cell read); then the cells are read from `cell_grid` (an `SFToken` and `0x00` are spaces, any other value is `chr(value)`) and trimmed of U+0020. `int` text must match `[0-9]{1,18}` (`output_type`, the text is not put in the error). `read_screen` is not called.

For the wrong-screen case (Requirements 11.3, 14.11) the failure has `step_index` of the Extract_Step, `expected` equal to `(output.signature,)` and `summary` equal to `build_summary(ScreenView(current.screen))`, or `None` when no Current_Screen is held. The summary shows every hidden cell as `*`. "No cell of the Output region is read" refers to the extraction path: the region read is `screens.read_region`, which this branch never reaches. The summary is a different path, it covers the whole screen and so also touches the cells of the region through `ScreenView`, which marks hidden cells without copying their text. The unit test of Requirement 18.23 therefore counts calls to `read_region` (a spy on the function the runner imported) and checks that the count is zero. A cell-level counter on the Screen double would also count the summary and could not pass.

### Handle_Step

```
def _handle(step):
    name = current.name if a Current_Screen is held else _poll(accept_any=True, timeout=timeouts.step)   # Requirement 9.1
    iterations = 0
    if name == step.signature and step.settle > 0:
        start = clock.monotonic()
        while clock.monotonic() - start < step.settle:      # Requirement 9.5
            clock.sleep(poll_interval); screen = _read(); outcome = _recognize(screen)
            unknown -> continue; ambiguous -> halt; name != signature -> accept(screen, name); break
            same name -> accept(screen, name)               # newest screen becomes Current_Screen
    while name == step.signature:
        if iterations == step.max_count: halt loop_limit    # Requirement 9.4
        run body Steps with audit iteration = iterations + 1 (Type_Steps and Key_Steps use the normal executors)
        iterations += 1
        name = _poll(accept_any=True, timeout=timeouts.step)  # timeout restarts; same-as-Pre_Key_Screen is "no answer yet"
    if iterations == 0:
        self._skip_body(item)                               # Requirements 13.10, 15.7: Unmatched_Handle
    record ok with count = iterations
```

- A handled screen that ends the settle early is kept as the Current_Screen and the body does not run. If the settle ends with the screen still on the handled name, the body runs; its Key_Step still does the pre-key check, which catches a screen that changed after the last settle read.
- The body is limited to Type_Steps and Key_Steps; by the validator at most one Key_Step, and it is last. A body without a Key_Step types again on each iteration until `max_count` is reached and then ends with `loop_limit`. The validator does not reject it because no requirement asks for that.
- Handle polling treats every recognized name as accepted, so a partial repaint recognized as the Pre_Key_Name counts as the next screen. This follows Requirement 9.1.

**Skipped records for an Unmatched_Handle (Requirements 13.10 to 13.14, 15.7).**

- **Who emits them.** `exec_handle` itself, as its last action before it returns `_StepDone("ok", ...)`, and only when `iterations == 0`. That covers every way to zero iterations: the first recognized screen is not the handled name (Requirement 9.6), and the settle period ends on another name (Requirement 9.5). `_skip_body(item)` appends one `AuditRecord(child.index, child.step.kind, item.phase, None, None, "skipped", 0.0)` per entry of `item.children`, in body order. It reads no clock, so `duration_seconds` is exactly 0.0, and it makes no Session call. Handle bodies hold no nested Handle_Step (Requirement 5.5), so one level is enough.
- **Order.** `run_item` appends the Handle_Step record (placeholder `failed`) before it calls the executor, and replaces it by index when the executor returns. A zero-iteration handle runs no body, so nothing else is appended between the Handle_Step record and the `_skip_body` records. The skipped records therefore sit immediately after the Handle_Step record, in depth-first order, and the Handle_Step record itself ends as `ok` (Requirement 13.10).
- **The same code on every path.** The records are appended during the run, not when the result is built, so a run that returns, a run that ends in `FlowError` later and a run that ends in `FlowDefinitionError` later all keep them. A Handle_Step that was never begun (the run stopped before it) gets no record from `exec_handle`; in `steps` that is Requirement 14.8, in `finally` the `_skip_finally` pass covers it.
- **`loop_limit` and failed handles.** `loop_limit` is halted inside the `while` loop after `max_count` iterations ran, so `iterations` is at least 1 and `_skip_body` is not reached. Iterations 1 to `max_count` keep their normal records and the Handle_Step record is `failed` (Requirement 13.13). A halt inside a body iteration or in the polling of a handle also skips `_skip_body`. In `steps` the later Steps have no record (Requirement 14.8). In `finally` the failed Step's remaining body Steps are covered by `_skip_finally` (Requirement 13.14).
- **A matched handle.** With k at least 1, Body_Steps that began carry `iteration` 1 to k and no `skipped` record is appended (Requirement 13.12).

### Finally

```
def run_finally(main_failure):
    if main_failure is None:                         run the plan with Current_Screen carried over
    elif main_failure.reason in SKIP or current is None:   append `skipped` records for every Step_Index of finally; send nothing
    else:                                            run the plan
SKIP = {unknown_screen, ambiguous_screen, timeout, run_timeout, session_error, input_invalid, definition}
```

A failing Finally_Step ends the phase: every later Step_Index of `finally` gets a `skipped` record (Requirements 13.5, 13.8). The `skipped` records cover every Step_Index of the flattened `finally` plan, so a Handle_Step and each Step of its body each get one.

**No duplicates with `_skip_body`.** `_skip_finally` walks the finally plan depth-first and appends a record only for a Step_Index that has no record yet (`recorded` is the set of `step_index` values of the `finally` records already in the audit list). A Handle_Step in `finally` that ran zero iterations has already given one record to itself and one to each body Step through `_skip_body`, so the walk finds every index recorded and appends nothing for it. A Handle_Step whose body failed midway has records for the Steps that began, and the walk adds `skipped` records (with `iteration` None) only for the Body_Steps that have none (Requirement 13.14). The `skipped` records of the walk come after all existing records, in plan order, and the set check makes a second call of `_skip_finally` a no-op. Each `(step_index, iteration)` pair therefore appears at most once, the invariant that the unit test of Requirement 18.21 asserts. The Finally budget is `timeouts.finally_`; exceeding it halts with `run_timeout`.

### Logging, audit and determinism

- `_log` is the only function that touches the logger. It takes the allowed fields as keyword-only `str` or `int` values and never receives a `Screen`.
- Durations come from `clock.monotonic()` differences, so they are `0.0` or exact sums on the fake Clock.
- Nothing in the runner reads the wall clock, a random source, the environment or a file. Session calls and Clock calls are the only channels out of the process (Requirement 7.7).

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Scope: the pure logic of the flow package (YAML round trip, validation, the runner state machine over Screens held in memory, redaction). The live host, the wheel build and the per-rule examples are covered by example and integration tests (see Testing Strategy). Property reflection removed these overlaps: Requirements 14.4 to 14.6 and 15.3 to 16.4 are asserted inside Property 3 rather than as separate properties; 8.14 (one key per accepted screen) is asserted inside Properties 4 and 6; the unarmed-Step rules 5.6, 5.7 and 5.8 are one property; 9.2, 9.3, 9.4, 9.6 and 9.7 are one property over the handled-screen count. The numbering matches Requirement 19.

### Property 1: YAML round trip and determinism

*For any* valid Flow built from all five Step kinds, Inputs with every option (`regex`, `secret`, `description`, optional) and Outputs, with strings that contain quotes, backslashes, colons, `#`, leading and trailing spaces, YAML-special words (`yes`, `null`, `1`), non-ASCII characters and the empty string, `Flow.from_yaml(flow.to_yaml(), signatures) == flow`; two calls of `to_yaml()` on the same Flow return identical strings; and the first key of the emitted document is `version` with the integer value 1.

**Validates: Requirements 1.1, 6.3, 6.4, 6.5**

### Property 2: Runs are deterministic and terminate

*For any* runnable Flow and any Screen script (stale reads, transient unknown screens, partial repaints and, optionally, a screen that makes the run fail), two runs with fresh Scripted_Sessions and fresh fake Clocks either both return a `FlowResult` with equal `outputs` or both raise `FlowError` with equal `reason`, `step_index` and `expected`; both record the same ordered sequence of Session calls; their audit trails are equal in every field except `duration_seconds`; each returned `FlowResult` has `list(outputs)` equal to the declared Output names in declaration order, whatever the order of the Extract_Steps; and each run makes a finite number of Session calls bounded by the Step timeouts, `max_count` and the Step count.

**Validates: Requirements 3.9, 3.10, 8.4, 12.6, 15.6, 15.8**

### Property 3: No secret or hidden content leaves the runner

*For any* Flow that types a Secret_Input, any sentinel Secret_Value of 1 to 8 characters from an alphabet used in no other generated text, and any script that ends in success or in any Reason_Code (including the residual-password Screen, unknown screens, and a Session that raises exceptions whose messages contain the sentinel), the sentinel appears in none of: the `FlowResult` fields and `repr`; every Audit_Record; the `str`, `repr`, `args` and attributes of every raised error, including its Redacted_Summary; `"".join(traceback.format_exception(err))` with chain, for every raised error; and the message and arguments of every `greenscreen.flow` log record. The raising-Session mode draws the failing call from `read_screen`, `string`, `enter`, `clear`, `pf` and `pa`. Every raised error has `__cause__` and `__context__` equal to `None` and a one-line message of at most 500 characters containing the Reason_Code and the Step_Index. Every `greenscreen.flow` log record is at DEBUG level and its message matches one of the four record shapes.

**Validates: Requirements 7.6, 10.9, 14.4, 14.5, 14.6, 14.9, 14.10, 15.3, 15.5, 16.1, 16.2, 16.4, 16.8, 16.9**

### Property 4: A key is sent only after a verified screen, and an unknown screen stops the run

*For any* Screen script that contains at least one unknown or ambiguous screen that the runner reads, when the run raises `unknown_screen` or `ambiguous_screen`, the Session receives no `string` call and no key call after the read that caused the error, and no Finally_Step sends a key. *For any* generated run, every key the Session receives was preceded by a Pre_Key_Screen whose field geometry equals the geometry of the Current_Screen, and the Comparison_Screen built from that Pre_Key_Screen by an independent model (typed fields restored from the Current_Screen) is recognized as the name of the Current_Screen. The number of key calls never exceeds the number of accepted screens.

**Validates: Requirements 8.7, 8.9, 8.11, 8.14, 13.3**

### Property 5: A Handle_Step runs at most `max_count` iterations

*For any* `max_count` N from 1 to 20 and any Session that shows the handled screen k times (k from 0 to 20) and then another screen, the run sends exactly k keys and returns when k is at most N. *For any* N and any Session that shows distinct handled screens without end, or k greater than N times, the run raises `loop_limit` after exactly N body iterations, sends exactly N keys, records the Handle_Step as `failed` and sends no further key.

**Validates: Requirements 9.2, 9.3, 9.4, 9.6, 9.7, 12.6**

### Property 6: Stale reads and partial repaints add no key

*For any* runnable Flow, any run of it with 0 to 5 stale reads after each key and 0 to 3 partial repaints (screens recognized as the Pre_Key_Name that differ from the Pre_Key_Screen in cell content) before each expected screen sends exactly the same key calls and string calls and returns the same `outputs` as the same run with no stale reads and no repaints, and raises no FlowError.

**Validates: Requirements 8.12, 8.14, 8.20**

### Property 7: Every Key_Step and Type_Step needs an arming Step

*For any* otherwise valid Flow in which a Key_Step or Type_Step in `steps` or `finally` (outside a handle body) has no arming Step (no Expect_Step earlier in the same list with no Key_Step between, and not directly after a Handle_Step), the Flow_Validator raises `FlowDefinitionError` that names the Step_Index of the first such Step, and inserting an Expect_Step immediately before that Step makes the Flow valid.

**Validates: Requirements 5.6, 5.7, 5.8**

### Property 8: Typing never blocks the following key

*For any* accepted screen of `tk5-logon`, `tso-password-prompt`, `ispf-primary-menu` or `tso-ready` from `captures/`, any printable-ASCII text (U+0020 to U+007E) of length 1 to L, and any state of the MDT bit on the typed field, where L is the smaller of 255 and the number of data cells from the cursor to the end of the field minus one for the three screens whose Signature has a `cursor_field` matcher, and the smaller of 255 and that number of cells for `tso-ready`, the Key_Step that follows a Type_Step of that text on a Pre_Key_Screen built in memory by writing the text into the cursor field cells sends the key and raises no FlowError.

**Validates: Requirements 8.9, 8.17, 8.19, 10.4, 10.5**

---

## Error Handling

| Situation | Behavior |
|---|---|
| Invalid YAML, wrong type, unknown key, wrong `version`, unreadable file | `FlowDefinitionError` naming the key (and list index) or the path, raised after the `except` block so `__cause__` and `__context__` are `None`. No partial Flow. |
| Violation of Requirements 1 to 5 | `FlowDefinitionError` for the violation that sorts first (see Validator algorithm). No Flow object exists. |
| Bad Input value | `FlowInputError` before any Session call. Message names the Input and the rule, never a value. |
| Unknown, ambiguous or unexpected screen | `_Failure` returned to `run_flow`; `FlowError` raised after release. No key is sent after it. |
| Session method raises any `Exception` other than `FlowError` (`ConnectorError`, `OSError`, `RuntimeError`, any class), in any Step | `session_error`; the message holds the Reason_Code, the class name and the Step_Index only (Requirements 7.6, 14.9). The exception object is dropped at the end of the helper's `except` block, the Run_State is released, and the `FlowError` is raised `from None` outside any handler. |
| Session method raises a `FlowError` | Released by `run_flow`'s escape clause and propagated unchanged (Requirement 7.9). |
| Session method raises a `BaseException` that is not an `Exception` (`KeyboardInterrupt`, `SystemExit`) | Not caught by the helpers. `run_flow` releases the Run_State, clears the `greenscreen.flow` traceback frames, runs no Finally_Step, sends no key and re-raises the same object (Requirement 7.8). |
| `recognize` raises `SignatureError` or `TypeError` | `FlowDefinitionError` naming the exception class. No further key. |
| Bad `poll_interval` | `ValueError` before any Session call. |
| A bug inside the runner | Propagates as the original exception through the escape clause of `run_flow`, which releases the Run_State and clears the `greenscreen.flow` frames first. |

### Where a secret or hidden cell could escape, and the guard

| Path | Guard |
|---|---|
| `FlowError` message, `args`, attributes | Built only from Reason_Code, indexes, kind, sorted Signature_Names, a class name and a `RedactedSummary` (hidden cells are `*`). |
| Traceback frames of the raised error | The error is created in `run_flow` after `state.release()` and `del inputs`; the only frames are `run_flow` and one small builder function. |
| Traceback frames of a propagating `BaseException` or Session `FlowError` | The escape clause of `run_flow` releases the state, calls `_clear_frames` on the `greenscreen.flow` frames of the traceback and deletes the `run_flow` locals before the bare `raise`. |
| `traceback.format_exception` with chain of a `session_error` | The Session exception is not chained (`__cause__` and `__context__` are `None`), so its text cannot appear. The `FlowError` message holds the class name only. |
| `__context__` and `__cause__` | Errors are raised outside any `except` block (verified locally that `from None` inside a block leaves `__context__` set). |
| Logs | Only the four record shapes of the log section; arguments are `str` or `int`. |
| Audit and result | Names, integers and a float; the `FlowResult.repr` shows Output names only. |
| Typed_Fields, Comparison_Screen | Geometry triples only; the Comparison_Screen is a local of `_key_check` and is deleted before any failure value is built. |
| The Session's own logging | Handled by the Connector, not by the flow package. Without redaction, `Connector._write` would log `direction=sent action=%s` at DEBUG on `greenscreen.connector` and `Connector.string` sends `String("<text>")`, so a typed password would appear in that record, in `S3270Error` and `ConnectorTimeoutError` messages and in `S3270Error.action`. Requirement 12 of `.kiro/specs/tn3270-connector` (helper `redact_action` in `greenscreen/connector/_redact.py`) removes this. The flow package converts exceptions to class names and cannot filter the Connector's log, so the integration test (Requirement 20.8) depends on that change. |

**Prerequisite in `tn3270-connector` (implemented first).** Requirement 12 of `.kiro/specs/tn3270-connector` and its design section "Action Redaction" specify `redact_action` in `greenscreen/connector/_redact.py`. It renders `String(...)` actions as `String(<N chars>)` in log lines, exception messages and `S3270Error.action`, while the real action is still written to s3270. That work must be implemented and passing before the flow-runtime integration test is written or run. flow-runtime itself changes nothing in `greenscreen.connector`. The integration test assertion stays: `TK5_PASSWORD` is absent from `repr(result)`, from `str()` of every error and from every log record captured at all levels. It fails if the prerequisite is missing.

### Decisions and limits

| # | Decision or limit | Reason |
|---|---|---|
| 1 | The cursor field is found with `ScreenView.containing_field`, as Requirement 10.1 now says. `Screen.find_field` is used only as a test oracle. | `find_field` builds a `Field` whose `text` holds the hidden cells; Requirements 10.7 and 14.7 forbid that in the runner. A unit test checks that both agree on geometry and flags for every capture. |
| 2 | Field "attributes" in the geometry comparison are `c0` with the MDT bit cleared. | A typed field gets MDT set on the demo host (`c8` becomes `c9` in `tk5-logon`, verified live); comparing the raw byte would reject every typed screen. |
| 3 | No runtime limit on text that fills the field; Property 8 stops at one cell short for `cursor_field` screens. | See "Edge case: typing fills the field and the cursor leaves it". |
| 4 | The Comparison_Screen restores whole Typed_Fields, as Requirement 8.19 says. | For `tso-ready` this hides host changes inside the huge typed field from the pre-key check. Restoring only the typed span would be tighter. |
| 5 | The runner imports `recognizer.view.ScreenView` and `recognizer.summary.build_summary`. | The recognizer has no public way to summarize a recognized screen. |
| 6 | A failed `finally` budget uses `run_timeout`. | The Reason_Code list has no separate code. |
| 7 | `expected` of a Handle_Step failure is `(signature,)`; of a Key_Step failure it is `(Current_Screen name,)`. | Requirement 14.2 says "accepted Signature_Names"; a Handle_Step accepts every name, and a Key_Step has no Expect list. |
| 8 | `skipped` audit records cover every Step_Index of the finally plan, including handle body Steps. | Requirement 13 says "each Finally_Step". |
| 9 | The Handle_Step audit record has `iteration=None`; its iteration count is the highest body `iteration` and the `count` of its log record. | `AuditRecord` has no count field. |
| 10 | The unsupported Step kind is echoed when it matches `[A-Za-z0-9_-]{1,32}`. | Requirements 1.3 and 4.9 ask for it; 5.15 lists no such exception. |
| 11 | Duplicate YAML mapping keys cannot be detected (`safe_load` keeps the last). | Same limit as `greenscreen.recognizer`. |
| 12 | A Handle_Step accepts the Pre_Key_Name, so a partial repaint of the handled screen counts as the next iteration. | Requirement 9.1. |
| 13 | No Signature exists for `IKJ56700A ENTER USERID`; `tk5-logon` ends with `unknown_screen` and sends no key there. | Known Limits of the requirements. |
| 14 | `FlowDefinitionError` has no `audit`, so the `skipped` records of the `definition` path are checked on a `_RunState` driven directly, not on the raised error. | Requirement 13.10 asks for the records "on every path", and Requirement 14 gives the audit to `FlowError` only. To confirm: add an `audit` attribute to `FlowDefinitionError` instead. |
| 15 | "No cell of the Output region was read" (Requirement 18.23) is checked with a spy on `read_region`, not a cell counter on the Screen. | The Redacted_Summary that the same failure must carry reads the whole screen. |
| 16 | The `string` helper no longer takes a `secret` flag; every Session exception in every Step becomes `session_error`. | Requirement 7.6 widened the rule; a Session bug in a non-secret Step is now reported, not propagated. |
| 17 | The runner clears `greenscreen.flow` traceback frames with `frame.clear()` on the escape path. | Requirement 7.8 and 18.19 need no Screen or inputs mapping in the locals of those frames. |
| 18 | Open item: `recognize()` builds a `ScreenView` per read, measured far above the 0.72 ms estimate; revisit in the publisher spec (no production change now). | The per-read cost drives the stale_reads and handle_bound times in the budget table. |

---

## Testing Strategy

### Approach

Dual approach. Hypothesis property tests (library already in the `dev` extra, no new dependency) cover the eight properties. Example tests cover each rule, each Reason_Code, each YAML error and the three shipped Flows. Every test passes without a host, a socket or a subprocess. Property tests use `@settings(max_examples=100, deadline=None)`, one `@given` test per property, and start with `# Feature: flow-runtime, Property N: <title>`.

PBT applies because the runner is a deterministic function of a Flow, Inputs and a sequence of in-memory Screens, and the YAML layer is a serializer. It does not apply to the Connector or the live host (integration test) or to the wheel (packaging test).

### Test support (`tests/flow_support.py`)

```python
class FakeClock:                      # starts at 0.0; sleep(s) adds s and returns at once; records `sleeps`
@dataclass(frozen=True)
class ScriptedState:
    screen: Screen
    stale_reads: int = 0              # 0..10: previous screen served for the first N reads after a key
    repaints: tuple[Screen, ...] = () # served once each after the stale reads, before `screen` (may be a blank screen)
class ScriptedSession:                # methods: read_screen, string, enter, clear, pf, pa, close; nothing else
    calls: list[tuple]                # ("read",), ("string", text), ("enter",), ("clear",), ("pf", n), ("pa", n), ("close",)
    def __init__(self, states, *, echo_typing=False): ...
```

- A key call moves to the next state and stays on the last one. `read_screen` returns a copy of the Screen, so the runner can never alias a test Screen. With `echo_typing=True`, `string` writes the text into the cursor field of the served screen, like a host.
- Screens come from `load_capture_screen` (cached at import) or `make_screen`. Helpers: `typed_screen(screen, text, *, mdt=False, cursor="inside"|"outside")`, `pause_variant(i)` (distinct `tso-pause` screens), `partial_repaint(name, i)` (cell changes that keep the name, found once at import by scanning cells and calling `recognize`), `blank_screen()` (always unknown), `sentinel_password_screen(sentinel)` (a copy of `tso-password-prompt` whose hidden cells hold the sentinel; the sentinel is checked to be absent from every file in `captures/`).
- No capture of the typed password is ever written (Requirement 18.10); the sentinel screen exists only in memory.
- `live_connector_config()` repeats the binary and host lookup of the existing integration tests (`GS_S3270_BINARY`, `GS_HOST`, `GS_PORT`, same defaults) without editing those tests.

Shared strategies live in `tests/property/_flow_strategies.py`: `flows()` (valid Flows of all kinds, built from one drawn tuple of small integers by `build_from_parts`; see "Strategy cost"), `chain_scripts()` (a chain of 2 to 6 capture names with adjacent names different, optional typed literal per screen, the matching Flow, and per-state stale reads, repaints and blank screens), `handle_counts()`, `typed_cases()` (capture name, text, MDT flag), and `secrets()`. Strategies draw small integers and indexes into cached Screens, not Screens, to keep the Hypothesis health checks quiet.

Two more helpers in `tests/flow_support.py` serve the `session_error` tests (Requirements 18.17 to 18.19):

- `ScriptedSession(..., raise_on={"enter": exc})` records the call, then raises the given exception from that method (`read_screen`, `string`, `enter`, `clear`, `pf` or `pa`). The call is in `calls` before the raise, so a test can assert that nothing follows it.
- `runner_frame_locals(err)` walks `err.__traceback__` and yields `(module, name, value)` for every local of every frame whose `f_globals["__name__"]` starts with `greenscreen.flow`. `assert_no_runner_leak(err, sentinel, inputs)` uses it: no value is a `Screen` or a `Field`, none is the `inputs` mapping (identity) or an input value, and no `str` value or `repr` of a container value contains the sentinel. It builds the verdict as a boolean list and asserts that the list is empty, so a failing assertion cannot print the sentinel.

### Strategy cost

**Measured problem.** Drawing 100 `flows()` examples takes about 3.8 s, and about 6.3 s with the YAML round trip. Properties 1 and 7 use `flows()`, so they would take about 10 s of the 35 s that Requirement 19.9 allows for all flow property modules, and the whole of `tests/property` has a 90 s ceiling. The target is under 35 s for the flow modules and under 90 s for `tests/property`.

**Where the time goes** (read from `_flow_strategies.py`):

| Cost | Cause |
|---|---|
| Size | One Flow can hold 4 Inputs, 4 Outputs, up to 4 action blocks of 1 to 5 Steps, 4 output blocks and a Finally list of up to 5 Steps. That is about 30 Steps, and the YAML round trip is pure-Python PyYAML (`safe_dump`, `safe_load`; the CSafe variants are excluded by Requirement 6.2), so it scales with size. The round trip alone costs about 2.5 s per 100. |
| Strategy objects built per draw | `_text()`, `_plain()`, `_expect_step()` and `_input_spec()` call `st.one_of`, `st.lists(..., unique=True)`, `st.sampled_from(rest)` and `st.text(...)` inside the draw, so Hypothesis constructs, validates and wraps new strategy objects on every example. |
| `st.from_regex` for the Flow_Name | Compiles and builds a regex strategy for each draw, and shrinks slowly. |
| About 60 draws per Flow | Nested `@st.composite` helpers each draw several primitives; every primitive has a fixed Hypothesis cost. |
| Validator at construction | `Flow.__post_init__` runs `structural_violations` over the whole plan; this cost grows with Step count. |

**Trimmed `flows()`.**

1. *Smaller bounds.* At most 6 top-level `steps`, 2 Inputs, 2 Outputs, handle bodies of 1 to 2 Steps, and at most 2 Steps in `finally`. Larger Flows (up to 200 Steps, 20 Inputs, 20 Outputs) are covered by example tests: one maximal Flow in `test_flow_yaml.py` that must round-trip, the limit tests of Requirement 1.6 in `test_flow_model.py`, and the three shipped Flows. Property 1 needs variety of kinds and strings, not size.
2. *Module-level pools, built once at import.* Every strategy object and every reusable value is created at import time and never inside a draw:
   - `FLOW_NAMES`: 12 valid names (1 character, 64 characters, with `-` and `_`). Replaces `from_regex`.
   - `TEXT_POOL`: about 30 printable-ASCII strings (the tricky texts of today, quotes, backslashes, colons, `#`, YAML words, leading and trailing spaces, an empty string for descriptions, the 255-character string), used for literals and descriptions. A single `st.text(alphabet=..., max_size=8)` is added to the literal choice so random text still appears.
   - `INPUT_POOL` and `INPUT_SETS`: 16 `InputSpec` objects (8 names, 2 variants each) that together use every option (`str` and `int`, required and optional, `regex` set and unset, `secret` true and false, empty and non-empty `description`, `max_length` 1, 8 and 255). `INPUT_SETS` is the precomputed tuple of all subsets of 0 to 2 specs with distinct names (129 entries). One `st.sampled_from(INPUT_SETS)` draw gives the Inputs.
   - `OUTPUT_POOL` and `OUTPUT_SETS`: the same for Outputs (7 names, `str` and `int`, different signatures and regions that fit in 80 columns), subsets of 0 to 2.
   - `EXPECT_SHAPES`: precomputed `ExpectStep` objects with 1 to 2 `signatures`, 0 to 1 `tolerate` and a `timeout` of `None`, 0.1, 5.0 or 60.0, plus `EXPECT_FOR[name]`, the shapes whose `signatures` hold `name`. One draw per Expect_Step.
   - `KEYS` (enter, clear, pf 1, pf 24, pa 1, pa 3), `HANDLE_BODIES` (1 to 2 Steps: a Key_Step, or a literal Type_Step then a Key_Step), `TIMEOUT_SETS` (4 `Timeouts` values: default, small, large, and the minimum of each range). Steps and specs are frozen, so one object is shared by every Flow that uses it.
   - Every `st.integers`, `st.sampled_from` and `st.tuples` that the strategy needs is created once at module level.
3. *`build_from_parts` with few draws.* `flows()` is `PARTS.map(build_from_parts)`, with no `@st.composite` and no `draw` calls. `PARTS` is one `st.builds(FlowParts, ...)` over about 14 integers: indexes into the pools above, a count of action blocks (0 to 3), per block a kind (Expect then Key, Expect then Type then Key, Handle_Step), a shape index, a key index, a text index and an Input reference (an index taken modulo the number of drawn Inputs, so no reference to an undeclared name), and a finally mode. `build_from_parts(parts, *, unarm=None) -> Flow` is a pure function: it assembles the Step tuple, inserts one Expect_Step plus Extract_Step per Output with `EXPECT_FOR[output.signature]`, truncates whole action blocks from the end until `len(steps) <= 6` (Output blocks are never dropped, so every Output keeps its single Extract_Step), builds the `Flow` once and returns it. The keyword `unarm` removes the arming Step of one action block, so `test_flow_arming.py` gets its unarmed Flow and the repaired Flow from the same parts, without a second strategy.
4. *Shared screen caches.* Scripts do not rebuild Screens: `pause_variant(i)`, `partial_repaint(name, i)`, `blank_screen()` and `capture(name)` each keep a module-level `functools.lru_cache` prototype, and `ScriptedState` holds the shared prototype. `ScriptedSession.read_screen` already returns a copy per read (`copy_screen` slices the row lists), so no test can mutate a prototype and the runner never aliases one. The `typed_cases()` bounds (`_TYPED_MAX`) are computed once at import, as today.
5. *No heavy object per draw.* No regex, no `re.compile`, no `Timeouts` or `InputSpec` construction and no recognizer call inside a strategy. The only per-draw constructions are the `Flow` itself and, for `chain_scripts()`, a small `ChainScript`.
6. `chain_scripts()` follows the same rules (pools for literals, one integer tuple per screen, cached Screens) but keeps its ranges, because Requirements 19.2, 19.4 and 19.6 fix them. If the run properties exceed their ceilings, the order of fixes is: cap the chain at 4 screens, cap `stale_reads` at 3 in Property 2 only, never reduce `max_examples`.

**Measurable acceptance.** On the development machine, drawing 100 `flows()` examples and round-tripping each through `Flow.from_yaml(flow.to_yaml(), signatures)` takes **under 1.5 s** (about 15 ms per example, against about 63 ms today). The check is `tests/unit/test_flow_strategy_cost.py`. It draws 100 examples with `@settings(max_examples=100, deadline=None, database=None, derandomize=True)`, times the loop with `time.perf_counter`, takes the best of three runs to remove one-off noise, and asserts the best time is below 1.5 s and that every drawn Flow respects the bounds of item 1 (at most 6 top-level Steps, at most 2 Inputs, at most 2 Outputs, handle bodies of 1 to 2 Steps). It is marked `perf` so a slow CI machine can deselect the timing assertion with `-m "not perf"`; the bounds assertion is not marked. Expected from the size reduction: the Step count falls from about 30 to about 7, and YAML cost scales with size, so the round trip falls from about 25 ms to about 6 ms, and the draw from about 38 ms to about 8 ms.

**Budget per property.** The flow property modules run in the budget below (wall-clock seconds for 100 examples on the development machine, fake Clock, in-memory Screens). The basis for the run properties is 0.72 ms per `recognize` call over seven Signatures; the runner passes only the Signatures that a Flow names, so a chain run of about 14 reads costs 3 to 5 ms.

| Property | Module | Ceiling | Where the time goes |
|---|---|---|---|
| 1 | `test_flow_yaml_roundtrip.py` | 2.6 s | 100 draws plus 100 round trips (the acceptance above) |
| 2 | `test_flow_determinism.py` | 3.0 s | two runs per example, 2 to 6 screens |
| 3 | `test_flow_secret_leak.py` | 1.6 s | one run per example, `format_exception`, log capture |
| 4 | `test_flow_unknown_stops.py` | 2.3 s | one run per example, stops early on the unknown screen |
| 5 | `test_flow_handle_bound.py` | 5.0 s | up to 20 iterations, about 45 reads in the longest run |
| 6 | `test_flow_stale_reads.py` | 8.5 s | two runs per example, up to 5 stale reads and 3 repaints per key |
| 7 | `test_flow_arming.py` | 0.4 s | validator only, no run |
| 8 | `test_flow_typing_never_blocks.py` | 3.0 s | one typed screen and one Key_Step per example, large fields |
| | import and setup (captures, pools, alias Signature) | 1.5 s | once per session |
| | **Sum** | **27.9 s** | **7.1 s under the 35 s of Requirement 19.9** |

The ceilings above come from measurement on a loaded machine (CPU 46 to 90% during the runs, other processes running), three runs, best run taken. Each ceiling is the best per-module call time rounded up with about 25% headroom to a clean number. Best call times in seconds: stale_reads 6.62, handle_bound 4.01, typing_never_blocks 2.41, determinism 2.30, yaml_roundtrip 2.05, unknown_stops 1.81, secret_leak 1.23, arming 0.30 (sum 20.43). The eight flow modules together took a best wall time of 28.2 s (runs 29.5, 28.2, 31.5; pytest-reported total best 25.72 s; sum of call durations 23.2 to 23.5 s). That is over the earlier 25 s limit, so the limit for the eight flow modules together is now 35 s. No test was trimmed and no `max_examples` was lowered. Property 1 measured 2.05 s against the earlier 1.58 s figure; the earlier figure is accepted as a lighter-load result and the 2.6 s ceiling replaces it. The `perf`-marked strategy test (`test_flow_strategy_cost.py`) passed in 3 of 3 runs (call times 3.03, 3.33 and 4.12 s under load, including Hypothesis setup); its own 1.5 s body budget is unchanged, so `perf` stays in the default run and no `addopts` is added.

**Suite-level margin for the 90 s limit.** The whole `tests/property` suite (123 tests) had a best wall time of 84.5 s (runs 84.5, 97.0, 84.8). The 90 s limit stays, but the margin is thin: one run exceeded it under load. A failure of that limit on a loaded machine should be rerun on an idle machine before generators are changed. The other property modules keep the remaining time of the 90 s total; this feature changes none of them. The fake Clock means zero real sleeps.

### Property-to-test mapping

| Property | File | Generated input | Oracle |
|---|---|---|---|
| 1 | `test_flow_yaml_roundtrip.py` | `flows()` | equality, identical text, first key |
| 2 | `test_flow_determinism.py` | `chain_scripts()` with optional failure point | two runs compared; call count bound |
| 3 | `test_flow_secret_leak.py` | secret Flow, `secrets()`, script ending in each Reason_Code, raising Session | substring search over every observable, plus log-shape regex |
| 4 | `test_flow_unknown_stops.py` | `chain_scripts()` with a persistent blank or ambiguous screen (ambiguity from a synthetic alias Signature that matches the same screen and is named in the Flow) | Session call log, and a test-side model of the Comparison_Screen |
| 5 | `test_flow_handle_bound.py` | `handle_counts()`: N, k, forever | key count and failure reason |
| 6 | `test_flow_stale_reads.py` | `chain_scripts()` and variation counts | equal calls and outputs against the baseline |
| 7 | `test_flow_arming.py` | `PARTS` through `build_from_parts(parts, unarm=k)` (Flow and repaired Flow from the same parts) | error text and repaired Flow validity |
| 8 | `test_flow_typing_never_blocks.py` | `typed_cases()` | one key sent, no FlowError |

The cost of each property is budgeted under "Strategy cost" above (about 27.9 s in total against the 35 s of Requirement 19.9).

### Unit tests (`tests/unit/`)

| File | Covers |
|---|---|
| `test_flow_model.py` | immutability, bounds, five kinds, error class hierarchy (Requirement 1) |
| `test_flow_inputs.py` | each input rule of Requirement 2, no Session call, no value in messages |
| `test_flow_validate.py` | each rule of Requirements 3 to 5, ordering of several violations, error text content |
| `test_flow_yaml.py` | each YAML error of Requirement 6 including `__cause__` and `__context__`, unreadable files, empty text |
| `test_flow_runner_expect.py` | polling, tolerate, unknown, ambiguous, unexpected, timeout (three kinds), first-Expect rule, stale-read rule, partial repaint, `Pre_Key_Name`, fake-Clock read and sleep counts |
| `test_flow_runner_type_key.py` | cursor field rules, `bad_target`, `secret_target`, optional Inputs, `pf`/`pa`, Typed_Fields, typed screens of the four shipped screens (Requirement 18.11) with and without the MDT bit, geometry change (18.12), full-field case, spy on `containing_field` and no `Field.text` read of a hidden field (18.24) |
| `test_flow_runner_handle.py` | settle rules, zero iterations, `loop_limit`, body pre-key rules; `skipped` records of Requirement 18.21: an Unmatched_Handle in `steps` and one in `finally`, each on a returning run and on a failing run (one `skipped` record per Body_Step, `duration_seconds` 0.0, `iteration` None, `signature` None, Handle_Step record `ok`, the skipped records directly after it, no duplicate `(step_index, iteration)`); a Handle_Step with k of 1 and 3 iterations (records `iteration` 1 to k, no `skipped`); a `loop_limit` failure (Handle_Step `failed`, iterations 1 to `max_count` recorded, no `skipped`); a Handle_Step in `finally` that fails in its body (remaining Body_Steps `skipped` once, none duplicated by `_skip_finally`) |
| `test_flow_runner_extract.py` | trimming, `int`, `output_type`, `hidden_output`, `screen_size`, wrong screen with `expected` `(Output signature,)` and a summary (and `None` without a Current_Screen), no `read_region` call (18.23), result key order: `tk5-system-info` from `captures/` gives `USERID`, `SYSTEMID`, `RELEASE`, `TERMINAL`, and a generated Flow whose Extract_Steps run in another order than its `outputs` still returns declaration order (18.20) |
| `test_flow_runner_finally.py` | every skip reason, carried screen, main error wins, failed finally Step, audit records, `FlowDefinitionError` during the run (a Signature_Name that `recognize` reports through `SignatureError`): zero keys in the Finally phase and every Finally_Step `skipped` (18.22, read from a `_RunState`) |
| `test_flow_runner_errors.py` | one test per Reason_Code; `run_timeout`; attributes and message shape; no Screen reachable from a raised error (`gc.get_referrers` and traceback frame locals); Comparison_Screen released. Requirements 18.17 to 18.19: a parametrized test over the six Session calls (`read_screen`, `string` on a Secret_Input Type_Step, `enter`, `clear`, `pf`, `pa`) where `ScriptedSession(raise_on=...)` raises `RuntimeError` with the sentinel in message and `args`; each asserts `FlowError` with `reason` `session_error` and the failing `step_index`, the sentinel absent from `str()`, `repr()`, `args` and every attribute, `__cause__` and `__context__` `None`, a message that holds `RuntimeError` and no other exception text, the sentinel absent from `"".join(traceback.format_exception(err))`, and `assert_no_runner_leak` on the traceback frames. A `KeyboardInterrupt` test: the same object propagates, no key follows, no Finally_Step runs, no `greenscreen.flow` frame holds a Screen or the inputs mapping. A `FlowError` raised by a Session propagates unchanged (Requirement 7.9). A non-secret Step whose Session raises a `ValueError` becomes `session_error` too (Requirement 7.6) |
| `test_flow_bundled.py` | three files, load from another directory, broken file, no cache, `importlib.resources` use, scripted runs of the three Flows (Requirements 17.16, 18.8, 18.9) |
| `test_flow_captures.py` | output regions and labels in `captures/ispf-primary-menu`, `containing_field` against `find_field` on every capture, the sentinel absent from `captures/`, no new capture file |
| `test_flow_packaging.py` | `pyproject.toml` checks and an offline wheel build in a temporary copy (`pip wheel . --no-deps --no-build-isolation`) that must list exactly the three YAML files; failure messages carry the build error or the missing names (Requirements 21.2, 21.5, 21.6) |
| `test_flow_strategy_cost.py` | `flows()` bounds (at most 6 top-level Steps, 2 Inputs, 2 Outputs, handle bodies of 1 to 2 Steps) and, marked `perf`, 100 draws with round trip in under 1.5 s (see "Strategy cost") |
| `test_flow_public_api.py` | the nine names |
| `test_flow_support.py` | self-tests of `ScriptedSession` and `FakeClock` (Requirements 18.1 to 18.6) |
| `test_flow_static.py` | no `text_grid`, `fields`, `find_field` or `.text` use in `screens.py` and `runner.py`; no `os.environ` read in the loader; `safe_load` and `safe_dump` only; no real clock calls; no credential in shipped YAML |

### Integration test

`tests/integration/test_flow_live_system_info.py`, marked `@pytest.mark.integration`, uses the session-scoped `host_reachable` fixture and the `live_connector_config()` helper. It skips with a message naming each unset or empty variable of `TK5_USERNAME` and `TK5_PASSWORD` before it touches the host, runs `tk5-system-info` through `Connector` in a `with` block, and asserts non-empty `SYSTEMID` and `RELEASE`, `USERID` equal to the username ignoring case, a final recognized `tk5-logon` screen, and the leak checks below. The first successful run also records one fact that is still unverified: the host cursor position after a field is filled. It is noted in the task log, and the code does not depend on it.

**Log capture (Requirements 20.8, 20.9).** The test uses `caplog` with `caplog.set_level(logging.DEBUG)` (root logger) and `caplog.set_level(logging.DEBUG, logger="greenscreen.connector")`, set before the `Connector` is created and active for the whole logon, run and logoff. Records of every logger and every level are collected, so the DEBUG `direction=sent` and `direction=received` records of the Connector are included.

**What is searched.** For each record the test builds the list of texts `str(record.msg)`, `record.getMessage()`, and `str(a)` and `repr(a)` for every element `a` of `record.args` (a single mapping argument contributes its values), plus the output of `logging.Formatter().format(record)`, which covers `exc_info`. It also searches `repr(result)` and, for every error raised or returned, `str()`, `repr()` and `args`.

**Forms searched.** With `P = TK5_PASSWORD` and `h = P.encode("ascii").hex()`:

| Form | Value |
|---|---|
| plain text | `P` |
| hex, lowercase, no space | `h` |
| hex, uppercase, no space | `h.upper()` |
| hex, lowercase, spaced | `" ".join(h[i:i+2] for i in range(0, len(h), 2))` |
| hex, uppercase, spaced | the spaced form in uppercase |

The spaced lowercase form is the one that matters most: `ReadBuffer(Ascii)` shows each cell as a two-digit lowercase hex code separated by spaces, so a logged response line that held the hidden password cells would contain exactly that string. Substring tests are case-sensitive, because the four hex forms are listed separately.

**Short passwords.** If `len(P) < 4`, the hex forms (fewer than 8 hex digits, so ambiguous) are skipped and the plain-text checks of criteria 8 and 9 still run (Requirement 20.10).

**No leak in the failure message.** pytest prints the compared values of a failed `assert`, which would print the password. The test therefore computes `leaks = [(location, form_name), ...]` where `location` is a record index and field name or the name of the checked object, and asserts `not leaks`. The assertion message holds locations and form names, never a form value.

**Cross-reference.** This is the flow-side counterpart of `tn3270-connector` Requirement 12, criteria 29 to 45: criteria 29 to 33 define the one Received_Record that carries no response data, 34 to 37 keep response data out of exception texts, 38 to 43 prevent hidden bytes in plain and hex form from reaching a log record or exception (Hex_Forms of at least 8 digits), 44 is the Connector's own live logon test, and 45 keeps response content out of every other log statement. The test depends on the `redact_action` prerequisite. When it fails, the cause is in `greenscreen.connector` and the failing criterion of that spec (the form found and the location in the message) points to it; the flow package converts exceptions to class names and cannot filter the Connector's log.

### Requirements covered by examples, not properties

Requirements 1.2 to 1.7, 2, 3.1 to 3.8, 4, 5.1 to 5.5 and 5.9 to 5.15, 6.1 to 6.2 and 6.6 to 6.9, 7, 8.1 to 8.3, 8.5, 8.6, 8.8, 8.10, 8.13, 8.15 to 8.18 and 8.21, 9.1, 9.5, 9.8, 10.1 to 10.8, 11, 12.1 to 12.5, 13.1 to 13.14 (apart from 13.3 in Property 4), 14.1 to 14.3, 14.7, 14.8, 14.11, 15.1, 15.2, 15.4, 15.7, 16.3, 16.5 to 16.7, 17, 18, 20 and 21 are checked by the unit, static, packaging and integration tests above.
