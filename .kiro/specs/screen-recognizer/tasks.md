# Implementation Plan: screen-recognizer

## Overview

Implement the `greenscreen.recognizer` Python 3.11+ package, which identifies a `greenscreen.connector.Screen` by evaluating named, YAML-serializable `ScreenSignature` objects. The build follows the dependency order of the design: scaffold and test support → signature model → `ScreenView` → matching → summary and `recognize` → YAML → `suggest_signature` → hidden-field protection tests → bundled signatures → public API and packaging checks.

Every task, including every property test, is required. Tests are written in Python with pytest and Hypothesis; the only third-party packages used are `pyyaml`, `hypothesis` and `pytest`, and no entry is added to the `dependencies` of `pyproject.toml`. All paths are repo-relative.

Test rules that apply to every task below:

- Screens for the seven captures come only from `captures/*.readbuffer.txt`, through `load_capture_screen` and the existing `ScreenParser`.
- Recognizer tests need no fake s3270 and must not start one. If a test ever needs a fake s3270, it builds it through the existing `fake_s3270_factory` fixture in `tests/conftest.py`, never ad hoc.
- Each property test is one `@given` test with `@settings(max_examples=100, deadline=None)` or more and starts with the comment `# Feature: screen-recognizer, Property N: <title>`.

## Tasks

- [x] 1. Scaffold package, packaging entry and test support
  - [x] 1.1 Create the package skeleton, `errors.py` and the package-data entry
    - Create `greenscreen/recognizer/__init__.py` (empty for now), `greenscreen/recognizer/signatures/__init__.py` (empty) and `greenscreen/recognizer/errors.py`
    - In `errors.py` define `RecognizerError(Exception)`, `SignatureError(RecognizerError)`, `UnknownScreenError(RecognizerError)` with keyword-only `summary` and `AmbiguousScreenError(RecognizerError)` with keyword-only `names`; each calls `super().__init__(message)` with one string and stores no `Screen`, grid or `Field`; none derives from `ConnectorError`
    - In `pyproject.toml` add `"greenscreen.recognizer.signatures" = ["*.yaml"]` under `[tool.setuptools.package-data]` and change nothing under `dependencies`
    - _Requirements: 6.1, 8.12, 12.1, 12.4, 12.8_

  - [x] 1.2 Create test support modules
    - Create `tests/screen_support.py` with `CAPTURE_NAMES` (the seven names `tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready`, `tso-pause-2`), `load_capture_screen(name)` and `make_screen(rows, columns, text=..., fields=..., cursor=...)`
    - `load_capture_screen` resolves `captures/` from `Path(__file__).parents[1] / "captures"`, collects the `data: ` lines and the status line before `ok` of the last block in `captures/<name>.readbuffer.txt`, and builds the `Screen` with `ScreenParser.parse_status_line` and `parse_readbuffer`; the `.ascii.txt` files are not used
    - `make_screen` builds a `cell_grid` of `0x00` cells with `SFToken`s and text bytes and empty `sa_tokens` lists
    - Create `tests/property/_recognizer_strategies.py` with Hypothesis strategies for small screens (1 to 24 rows, 1 to 80 columns, mostly blank cells with printable runs, optional SF layouts including zero and one SF), signatures of all seven matcher kinds, sentinel-bearing screens with hidden fields (attribute byte with bits `0x0C` set, sentinel alphabet Latin-1 `0xC0..0xFF` that appears in no other cell) and line-mode screens
    - Do not modify `tests/conftest.py`
    - _Requirements: 10.2, 11.7, 11.8, 13.6_

  - [x] 1.3 Write the capture inventory test
    - Create `tests/unit/test_recognizer_capture_inventory.py`
    - Glob `captures/*.readbuffer.txt` and assert the set of names equals exactly the 7 files `tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready`, `tso-pause-2` and that the glob returned exactly 7 paths, so a missing or extra capture (for example a capture of the residual-password screen) fails loudly
    - Assert that every name in `CAPTURE_NAMES` loads through `load_capture_screen` as a 24 by 80 screen
    - _Requirements: 10.2, 13.6_

  - [x] 1.4 Write the capture facts test
    - Create `tests/unit/test_recognizer_capture_facts.py` with one test per row of the facts table in the design, read through `ScreenParser` on every run
    - Assert for `tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready` and `tso-pause-2`: cursor position, unprotected field starts, hidden flag and `c0` of the password field, the text and position of every string a bundled matcher will use, and the date and time value positions found by scanning `text_grid` for the date and time patterns
    - Assert the hidden field of `tso-password-prompt` holds only blank cells
    - This test file may read `Screen.text_grid` and `Screen.fields`; it must never be applied to a screen holding a typed password
    - _Requirements: 8.2, 8.7, 8.8, 8.9, 8.10, 8.13, 10.2_

- [x] 2. Implement the signature model and validation
  - [x] 2.1 Implement `signature.py`
    - Define the seven frozen, slotted matcher dataclasses (`TextAtMatcher`, `RowContainsMatcher`, `FieldLayoutMatcher`, `CursorFieldMatcher`, `RegionRegexMatcher`, `LastRowMatcher`, `BeforeCursorMatcher`), `MATCHER_KINDS`, `VolatileRegion` and `ScreenSignature`, normalizing sequences to tuples in `__post_init__`
    - Validate in `__post_init__` and raise `SignatureError` without echoing matcher text: name fullmatch `[a-z0-9_-]{1,64}`; description at most 500 characters; 1 to 50 matchers and 0 to 50 volatile regions; `row`, `col` as `type(v) is int` in 0..255, `length >= 1`, last column at most 255; regex at most 200 characters and accepted by `re.compile` (message uses `exc.pos` only); no shared cell between a `text_at` or `region_regex` rectangle and a volatile region; `hidden` exactly `bool`
    - Add the two conditions the earlier requirements missed: an empty text in `text_at`, `row_contains`, `last_row` or `before_cursor` raises `SignatureError` (Requirement 1.17), and a `field_layout` whose `count` differs from `len(positions)` raises `SignatureError` (Requirement 1.18)
    - Implement `to_yaml` and `from_yaml` as methods that import `yamlio` inside the method body
    - _Requirements: 1.1, 1.2, 1.9, 1.10, 1.11, 1.12, 1.13, 1.17, 1.18, 4.1_

  - [x] 2.2 Write unit tests for signature validation
    - Create `tests/unit/test_recognizer_signature.py` with at least one test per `SignatureError` condition of Requirements 1 and 4 that belongs to construction: zero matchers, more than 50 matchers, more than 50 regions, bad name (empty, 65 characters, uppercase, trailing newline), over-long description, row or col above 255 or negative or a `bool`, `length` below 1, last column above 255, invalid and over-long regex, matcher and region overlap, empty text for each of the four text-bearing kinds (Requirement 1.17), and `field_layout` count differing from the number of positions (Requirement 1.18)
    - Assert that no `SignatureError` message contains the matcher text or the pattern
    - Assert the seven kinds in `MATCHER_KINDS` and that equal signatures are equal and hashable
    - _Requirements: 1.1, 1.2, 1.9, 1.10, 1.11, 1.12, 1.13, 1.17, 1.18, 10.8_

  - [x] 2.3 Write property test for signature validation (Property 14)
    - **Property 14: Signature validation**
    - Create `tests/property/test_recognizer_validation.py`; generate names, descriptions, matcher and region values at their boundaries (including booleans); assert construction succeeds exactly when the rules hold and otherwise raises `SignatureError` and creates no object
    - **Validates: Requirements 1.1, 1.9, 1.10, 1.11, 1.12, 1.13**

- [x] 3. Implement `ScreenView`
  - [x] 3.1 Implement `view.py`
    - Implement `FieldGeom` and `ScreenView` reading `Screen.cell_grid` only: field geometry with the same wrap arithmetic as `Screen.fields`, `hidden = (c0 & 0x0C) == 0x0C`, `base_rows` and `hidden_mask` with hidden data cells blanked, `visible_rows(volatile)` with clipped, overlapping regions blanked once, `containing_field` (bisect with wrap), `unprotected_fields`, `input_fields` and `summary_rows` (hidden data cells as `*`, trailing spaces removed)
    - Keep no reference to the `Screen` or its grids after construction; use `rstrip(" ")` and `strip(" ")` only, never bare `strip()`
    - Never read `Screen.text_grid`, `Screen.fields`, `Screen.find_field` or `Field.text`
    - _Requirements: 2.1, 2.5, 2.6, 2.7, 3.1, 3.6, 3.7, 3.8, 13.2_

  - [x] 3.2 Write unit tests for `ScreenView` on the captures
    - Create `tests/unit/test_recognizer_view.py`
    - Assert that on `tso-password-prompt` the hidden field at row 1, col 0 is an Input_Field and the unprotected field at row 0, col 0 is not
    - Assert that on `ispf-primary-menu` exactly one field is an Input_Field, the one containing the cursor
    - Assert that on an unformatted synthetic screen `containing_field` returns `None`, a `cursor_field` cannot be satisfied and a `field_layout` with count 0 is satisfied
    - Assert an unprotected hidden field with the cursor outside it is still an Input_Field and raises nothing
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.8, 10.7_

  - [x] 3.3 Write property test for geometry and Input_Field parity (Property 13)
    - **Property 13: Geometry and Input_Field parity**
    - Create `tests/property/test_recognizer_geometry_parity.py`; compare each `ScreenView` field with `Screen.fields`, `containing_field` with `Screen.find_field` for in-range positions, and `input_fields()` with the unprotected fields that are hidden or contain the cursor, including zero-SF, one-SF and wrapping layouts
    - **Validates: Requirements 3.1, 3.8, 1.6, 1.7**

  - [x] 3.4 Write property test for Visible_Text construction (Property 12)
    - **Property 12: Visible_Text construction**
    - Create `tests/property/test_recognizer_visible_text.py`; with overlapping and out-of-range regions, assert `visible_rows` equals `text_grid` with hidden data cells and the clipped union of regions replaced by single spaces, and equals `text_grid` when there are neither hidden fields nor regions
    - **Validates: Requirements 2.1, 2.5, 2.7, 3.6, 13.2**

- [x] 4. Implement matching
  - [x] 4.1 Implement `matching.py`
    - Implement `signature_matches` and `matcher_satisfied` with dict dispatch for all seven kinds on the rows of `view.visible_rows(sig.volatile)`; a matcher addressing a position outside the screen is unsatisfied and raises nothing
    - `last_row` is unsatisfied on a screen with no non-blank row; `before_cursor` is unsatisfied when the cursor is outside the screen (column equal to `columns` counts as outside); `region_regex` uses `re.search` on a slice of at most 256 characters
    - `field_layout` and `cursor_field` read geometry only
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.14, 1.15, 1.16, 2.2, 2.3, 2.4, 3.4, 3.5, 7.5_

  - [x] 4.2 Write unit tests for every matcher kind
    - Create `tests/unit/test_recognizer_matchers.py` with one satisfied and one unsatisfied case per kind, each asserting the boolean result
    - For `last_row` and `before_cursor` assert a satisfied case, the significance of a leading space, a screen with no non-blank row (`last_row` unsatisfied) and a cursor outside the screen (`before_cursor` unsatisfied)
    - Assert that a text matcher over a hidden field's cells sees spaces whatever the cells hold, and that a volatile region of one signature does not affect another signature
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 1.15, 1.16, 2.3, 7.5, 10.1, 10.11_

  - [x] 4.3 Write property test for matchers against a direct model (Property 10)
    - **Property 10: Matchers agree with a direct model**
    - Create `tests/property/test_recognizer_matcher_model.py`; write an independent oracle (Visible_Text from `Screen.text_grid` and non-text `Screen.fields` attributes, cursor field from `Screen.find_field`) in the test file and compare every matcher kind and `all(...)` over a signature, including hidden fields and unformatted screens
    - **Validates: Requirements 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.15, 1.16, 3.4, 3.5**

  - [x] 4.4 Write property test for out-of-screen addressing (Property 11)
    - **Property 11: Out-of-screen addressing never raises**
    - Create `tests/property/test_recognizer_out_of_range.py`; address rows and columns up to 255 against small screens and assert no exception, unsatisfied matchers for outside positions and clipped volatile regions
    - **Validates: Requirements 1.14, 2.6**

  - [x] 4.5 Write property test for `last_row` and `before_cursor` unsatisfied cases (Property 9)
    - **Property 9: `last_row` and `before_cursor` unsatisfied cases**
    - Create `tests/property/test_recognizer_line_matchers.py`; blank screens with any `last_row` text, and cursors that are negative, at or above `rows`, or at or above `columns`, with any `before_cursor` text
    - **Validates: Requirements 1.15, 1.16, 11.11**

- [x] 5. Checkpoint - model, view and matching complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the redacted summary and `recognize`
  - [x] 6.1 Implement `summary.py`
    - Implement the frozen `RedactedSummary` (rows, columns, cursor, `field_count`, `unprotected_count`, `hidden_count`, field tuples, `row_text`), `to_text()` with exactly `rows` lines, `to_dict()` with only `str`, `int`, `bool`, lists and dicts, and `build_summary(view)`
    - Show every hidden data cell as `*`, including blank ones; a screen with zero fields gives counts of 0 and no field tuples; the default `repr` shows only redacted values
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.7, 6.10_

  - [x] 6.2 Implement `recognizer.py`
    - Implement `recognize(screen, signatures)`: consume the iterable once, `TypeError` for a non-`ScreenSignature` element, `SignatureError` naming duplicated names before any matcher runs, build one `ScreenView`, return the single matching name, raise `UnknownScreenError` (message with integers and fixed words only, `summary` attached) or `AmbiguousScreenError` (sorted unique `names`, message with names and count only)
    - Run `del screen, view` and raise with `from None` outside any `except` block so `__cause__` and `__context__` are `None`
    - Log exactly one DEBUG record per call on the logger `greenscreen.recognizer` with only names, counts and the outcome (`matched`, `unknown`, `ambiguous`)
    - Perform no network, subprocess or file I/O and modify neither the screen nor any signature
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 6.2, 6.6, 6.8, 6.9, 13.1, 13.4_

  - [x] 6.3 Write unit tests for `recognize`
    - Create `tests/unit/test_recognizer_recognize.py`
    - Assert the single-match, empty-list, ambiguous (names sorted, every matching name and no non-matching name, no screen text), duplicate-name (each duplicated name in the message, before any matcher runs), iterator-once and order-independence cases
    - Assert that removing `ispf-primary-menu` from the bundled set makes `recognize` on the ISPF capture raise `UnknownScreenError` whose `summary.to_text()` contains `Option  ===>` (two spaces) and no hidden content
    - Assert the `UnknownScreenError` message is one line of counts and the cursor position, and that `RecognizerError` subclasses are not `ConnectorError`
    - Assert `recognize` runs with `socket.socket`, `subprocess.Popen` and `builtins.open` patched to fail, and that the suite starts no subprocess and opens no connection
    - Add a benchmark test: 100 signatures of up to 10 matchers each on a 24 by 80 screen finishes within 2 seconds
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.9, 5.10, 6.1, 6.6, 10.5, 10.6, 10.9_

  - [x] 6.4 Write property test for the redacted summary (Property 15)
    - **Property 15: Redacted summary shape**
    - Create `tests/property/test_recognizer_summary.py`; include blank hidden fields and zero-field screens; assert counts, field tuples, exactly `rows` lines in `to_text()`, `*` for every hidden data cell, unchanged text for all other cells and a `to_dict()` made only of `str`, `int`, `bool`, `list` and `dict`
    - **Validates: Requirements 6.3, 6.4, 6.5, 6.10**

  - [x] 6.5 Write property test for recognition outcomes and messages (Property 16)
    - **Property 16: Recognition outcomes and messages**
    - Create `tests/property/test_recognizer_outcomes.py`; assert the `UnknownScreenError` summary equals `build_summary` of the screen and the message matches `^[^\n]*$` with integers and fixed words, the `AmbiguousScreenError.names` are sorted, unique and exact, a deep-copy comparison shows no change to screen or signatures whether `recognize` returns or raises, and duplicate names raise `SignatureError` containing each name
    - **Validates: Requirements 5.3, 5.4, 5.5, 5.8, 6.2, 6.6, 6.8**

  - [x] 6.6 Write property test for order and iterator independence (Property 7)
    - **Property 7: Recognition ignores signature order and iterator form**
    - Create `tests/property/test_recognizer_order.py`; 0 to 10 signatures with distinct names (use copies of one suggested signature under new names to force ambiguity); every permutation and an iterator give the same name or the same exception type with the same sorted `names`
    - **Validates: Requirements 5.2, 5.4, 5.6, 5.7, 11.6**

  - [x] 6.7 Write property test for exceptions holding no Screen reference (Property 19)
    - **Property 19: Exceptions hold no Screen reference**
    - Create `tests/property/test_recognizer_exception_refs.py`; walk `args`, `vars()`, `__cause__`, `__context__` and the locals of traceback frames inside `greenscreen.recognizer` using `gc.get_referents`, and find no identity reference to the screen, its `cell_grid`, its rows or any `Field`; `__cause__` and `__context__` are `None`
    - **Validates: Requirements 13.1, 13.4**

- [x] 7. Implement YAML serialization
  - [x] 7.1 Implement `yamlio.py`
    - Implement version-1 schema emit with `yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=False, width=10_000, indent=2)` and fixed key order; parse only with `yaml.safe_load`
    - Implement `from_yaml`, `_signature_from_mapping` and `load_signatures(path)`; checks for unknown, missing and wrongly typed keys; `version` accepted only when `type(v) is int and v == 1`; `field_layout` count equal to `len(positions)`; no partial result on any failure
    - Errors use only the key name, the signature name, the matcher kind, line and column numbers and the zero-origin index; never `str(yaml_error)` and never a YAML scalar except the truncated `version` value; raise with `from None`
    - Duplicate names in a file give one `SignatureError` naming the name and both indexes; an unreadable path or invalid UTF-8 gives `signature file could not be read`; an empty document is `document structure is invalid`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 1.18_

  - [x] 7.2 Write unit tests for YAML loading and emission
    - Create `tests/unit/test_recognizer_yaml.py`
    - Cover `load_signatures` with a single mapping, a list, an empty list, a missing file, an unreadable file and invalid UTF-8; `version` values `2`, `"1"` and `True`; malformed YAML; an unknown key, a missing key and a wrong type with the key name and list index in the message; duplicate names with both indexes; the `field_layout` count mismatch from YAML (Requirement 1.18); and the representation of `last_row`, `before_cursor` and `field_layout`
    - Assert that `to_yaml` begins with `version: 1` and that calls on equal signatures return identical strings
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 10.8_

  - [x] 7.3 Write property test for the YAML round trip (Property 6)
    - **Property 6: YAML round trip and determinism**
    - Create `tests/property/test_recognizer_yaml_roundtrip.py`; use all seven matcher kinds and strings from all code points except surrogates, plus the edge strings `"\x85"`, `" "` and `"''"`; assert `from_yaml(sig.to_yaml()) == sig`, identical output on repeated calls and a document starting with `version: 1`
    - **Validates: Requirements 4.1, 4.3, 4.5, 4.11, 11.5**

  - [x] 7.4 Write property test for load errors that never echo scalars (Property 18)
    - **Property 18: Load errors never echo scalars**
    - Create `tests/property/test_recognizer_load_errors.py`; mutate one key or value of a valid dict with a sentinel scalar, dump with `safe_dump`, reload; assert `SignatureError`, the key name (and list index) in the message and no sentinel; malformed YAML raises `SignatureError` without quoting its source
    - **Validates: Requirements 4.6, 4.8**

- [x] 8. Implement `suggest_signature`
  - [x] 8.1 Implement `suggest.py`
    - Implement `suggest_signature(screen, name=None)` reading the screen only through `ScreenView.base_rows`, `hidden_mask` and geometry
    - Raise `SignatureError("screen has no identifying features")` only when every row is blank and there are no fields
    - Detect `HH:MM:SS`, `HH:MM` and `DD.MM.YY` runs with the ASCII-digit pattern of the design, declare them as volatile regions (first 50 in reading order, all excluded from text matchers)
    - Select the first row with stable text (Requirement 9.5, moving to the next row when the first is entirely volatile); build at most three `text_at` candidates from segments split on two consecutive spaces; discard any candidate with a cell in `hidden_mask` and do not fall through to later rows when all are discarded (Requirement 7.6)
    - Add exactly one `FieldLayoutMatcher` listing unprotected fields in order when any exist (a hidden unprotected field appears by position only, Requirement 7.4), exactly one `CursorFieldMatcher` when the cursor is in an Input_Field, and the count-0 `FieldLayoutMatcher` fallback when no other matcher was produced
    - Use a supplied `name` unchanged; otherwise derive the name from the stable text of the selected row (volatile and hidden cells blank), lowercase, runs outside `a-z0-9-` replaced by `-`, trimmed, at most 64 characters, `unnamed-screen` when empty
    - _Requirements: 7.2, 7.3, 7.4, 7.6, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12, 9.13_

  - [x] 8.2 Write unit tests for `suggest_signature`
    - Create `tests/unit/test_recognizer_suggest.py`
    - Cover the empty screen (`screen has no identifying features`), a screen with only a field, the count-0 `field_layout` fallback (Requirement 9.13) and a supplied name used unchanged
    - Cover Requirement 9.5 row selection: a first row consisting only of a clock moves selection to the next row with stable text
    - Cover Requirement 9.7 naming: the stable-text name excludes a date or time, the `unnamed-screen` case, and the derived name for the `tk5-logon` and `ispf-primary-menu` captures
    - Cover Requirements 7.4 and 7.6: a hidden unprotected field is recorded by position in the `field_layout` and, when the cursor is in it, by `hidden` in the `cursor_field`, with no text; when every candidate overlaps a hidden field, the signature has no text matcher derived from those cells, still has the `field_layout`, and the screen is unchanged
    - _Requirements: 7.3, 7.4, 7.6, 9.1, 9.5, 9.6, 9.7, 9.9, 9.12, 9.13_

  - [x] 8.3 Write property test for suggest then recognize (Property 1)
    - **Property 1: Suggest then recognize**
    - Create `tests/property/test_recognizer_suggest_roundtrip.py`; screens with and without fields, with hidden fields and with planted times; assert the suggested signature matches the screen and `recognize(screen, [sig])` returns its name
    - **Validates: Requirements 5.2, 9.2, 11.1**

  - [x] 8.4 Write property test for volatile content (Property 2)
    - **Property 2: Volatile content does not affect the result**
    - Create `tests/property/test_recognizer_volatile.py`; plant `HH:MM` and `DD.MM.YY` runs, replace the characters inside the suggested volatile regions with random text and assert an unchanged match result
    - **Validates: Requirements 2.2, 2.4, 9.8, 11.2**

  - [x] 8.5 Write property test for one-cell mutation (Property 3)
    - **Property 3: Changing one text-matched cell breaks the match**
    - Create `tests/property/test_recognizer_text_mutation.py`; pick one cell of a `text_at` matcher outside every volatile region and hidden field, replace it with a different character and assert the signature stops matching
    - **Validates: Requirements 1.4, 11.3**

  - [x] 8.6 Write property test for suggested signature structure (Property 17)
    - **Property 17: Suggested signature structure**
    - Create `tests/property/test_recognizer_suggest_structure.py`; plant valid and invalid time and date runs (hour 24, minute 60, day 32 and 00); assert exactly one `field_layout` and `cursor_field` where required, `text_at` only on the first stable row clear of volatile and hidden cells, valid runs covered and invalid runs not, a supplied name unchanged, a derived name that is `unnamed-screen` or matches `[a-z0-9-]{1,64}`, equal results on repeated calls and an unchanged screen
    - **Validates: Requirements 7.3, 7.4, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.10, 9.12**

- [x] 9. Checkpoint - recognition, YAML and suggestion complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Verify hidden-field protection
  - [x] 10.1 Write property test for hidden content in output (Property 4)
    - **Property 4: Hidden content never appears in any output**
    - Create `tests/property/test_recognizer_hidden_leak.py`; screens with hidden fields holding a sentinel of 1 to 80 characters found in no other cell; assert that no sentinel character, nor its `\xNN` escape form, appears in the suggested signature and its `to_yaml()`, in `str()`, `repr()`, `args` and attributes of `UnknownScreenError` and `AmbiguousScreenError`, in the summary `to_text()`, `to_dict()` and `repr()`, or in any DEBUG record (message and arguments) on `greenscreen.recognizer`
    - **Validates: Requirements 6.7, 7.1, 7.4, 9.11, 13.1, 11.4**

  - [x] 10.2 Write property test for residual hidden content on non-password screens (Property 5)
    - **Property 5: Residual hidden content on non-password screens**
    - Create `tests/property/test_recognizer_residual_hidden.py` using only synthetic screens: a line-mode screen that is not the password prompt (a `***` row, the cursor on that row, a hidden field holding a sentinel elsewhere, with non-blank cells inside the hidden extent in rows below the `***` row that would otherwise move the last non-blank row)
    - Assert the sentinel appears in none of the suggested signature, its `to_yaml()`, the `str()`, `repr()`, `args` and `vars()` of every recognizer exception, the summary `to_text()` and `to_dict()` and the DEBUG records, and that `recognize` returns the same result with the residual content present and with it replaced by spaces
    - **Validates: Requirements 13.1, 13.3, 13.7**

  - [x] 10.3 Write property test for hidden-only differences (Property 20)
    - **Property 20: Hidden-only differences change nothing**
    - Create `tests/property/test_recognizer_hidden_invariance.py`; two screens that differ only in hidden data cells give the same `recognize` result (or the same exception type with equal `names`) and equal `suggest_signature` output; a text matcher whose cells lie inside a hidden field is evaluated as if those cells held spaces
    - **Validates: Requirements 3.7, 7.2, 7.5, 13.2, 13.5**

- [x] 11. Implement bundled signatures
  - [x] 11.1 Create the seven bundled YAML files and `bundled.py`
    - Create `greenscreen/recognizer/signatures/tk5-logo.yaml`, `tk5-logon.yaml`, `tso-input-not-recognized.yaml`, `tso-password-prompt.yaml`, `ispf-primary-menu.yaml`, `tso-ready.yaml` and `tso-pause.yaml` from the matchers table of the design, using only values asserted by the capture facts test (task 1.4)
    - `tk5-logon` declares the date and time values as volatile regions; `ispf-primary-menu` declares the time value; `tso-password-prompt` uses the prompt regex and `cursor_field(1, 0, true)` and contains no user ID; `tso-ready` uses only `last_row(" READY")`; `tso-pause` uses `last_row(" ***")` and `before_cursor(" ***")` with no field layout and no fixed-row text matcher
    - Implement `load_bundled_signatures()` in `greenscreen/recognizer/bundled.py` reading the manifest of seven names from `importlib.resources.files("greenscreen.recognizer.signatures")`; raise `SignatureError` naming the file for a missing file, a decoding error, an invalid signature or a name that differs from its file stem; return a list only after all seven loaded and keep no module-level state
    - _Requirements: 8.1, 8.2, 8.7, 8.8, 8.9, 8.10, 8.12, 8.13, 8.14, 8.18, 8.19_

  - [x] 11.2 Write unit tests for bundled signatures
    - Create `tests/unit/test_recognizer_bundled.py`
    - Assert that each bundled signature recognizes its own capture (`tk5-logo`, `tk5-logon`, `tso-password-prompt`, `ispf-primary-menu`, `tso-input-not-recognized`, `tso-ready`, and `tso-pause` against `tso-pause-2`)
    - Add `test_bundled_matchers_match_capture_cells`: check every bundled `text_at` against the capture's `text_grid`, every volatile region against the date and time pattern, and every `cursor_field` and `field_layout` against `Screen.fields`
    - Assert that exactly seven signatures are bundled, `load_bundled_signatures()` gives the same result from an unrelated working directory (`monkeypatch.chdir(tmp_path)`), a missing or invalid bundled file raises an error naming the file with no partial list, and no YAML under `signatures/` contains the user ID `HERC01`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.13, 8.14, 8.15, 8.16, 8.17, 10.3_

  - [x] 11.3 Write the 7-by-7 capture matrix test
    - Create `tests/unit/test_recognizer_capture_matrix.py` as its own test module
    - Parametrize over all seven captures; evaluate every one of the seven bundled signatures against every capture and assert that each capture matches exactly its own signature and no other (`tso-pause-2` maps to `tso-pause`), that `recognize` over the seven bundled signatures returns exactly that name, and that the glob over `captures/*.readbuffer.txt` still finds exactly 7 files so the matrix cannot silently shrink
    - Screens come only from `load_capture_screen`; the matrix covers 49 evaluations
    - _Requirements: 8.11, 8.21, 10.2, 10.4_

  - [x] 11.4 Write unit tests for `tso-pause` and `tso-ready`
    - Create `tests/unit/test_recognizer_line_mode_signatures.py`
    - Assert that `tso-pause` matches the `tso-pause-2` capture and synthetic screens with the same `***` last row and cursor, different text above and the `***` row on row 10 and on row 11, and does not match when text sits below the `***` row
    - Assert that `tso-ready` does not match the `ispf-primary-menu` capture and that `tso-input-not-recognized` and `tso-ready` differ on their own captures
    - _Requirements: 8.18, 8.19, 8.20, 10.10_

  - [x] 11.5 Write property test for `tso-pause` position independence (Property 8)
    - **Property 8: `tso-pause` matches wherever the `***` row sits**
    - Create `tests/property/test_recognizer_pause_signature.py`; printable text above, row `n` from 1 to 22 holding `***` with its leading space, cursor on row `n` at column 5; assert the bundled `tso-pause` signature matches
    - **Validates: Requirements 8.19, 8.20, 11.10**

- [x] 12. Wire up the public API and verify packaging and static rules
  - [x] 12.1 Populate `greenscreen/recognizer/__init__.py`
    - Export exactly nine names in `__all__`: `ScreenSignature`, `recognize`, `suggest_signature`, `load_signatures`, `load_bundled_signatures`, `RecognizerError`, `UnknownScreenError`, `AmbiguousScreenError`, `SignatureError`
    - Do not configure logging in `__init__`; matcher classes and helpers stay in submodules
    - Leave the public API of `greenscreen.connector` unchanged
    - _Requirements: 12.1, 12.2, 12.6_

  - [x] 12.2 Write unit tests for the public API
    - Create `tests/unit/test_recognizer_public_api.py`
    - Assert each of the nine names imports from `greenscreen.recognizer`, `__all__` is exactly those nine names, and `greenscreen.connector.__all__` is unchanged
    - _Requirements: 12.1, 12.2, 12.6_

  - [x] 12.3 Write static source-scan tests
    - Create `tests/unit/test_recognizer_static.py` using `ast` over every module in `greenscreen/recognizer`
    - Fail if any module references `text_grid`, `find_field`, `.fields` on a `Screen` or an attribute `text` of a field (including `view.py`); if any `yaml.` call other than `yaml.safe_load` and `yaml.safe_dump` appears; or if an import lies outside the standard library, `yaml` and `greenscreen`
    - _Requirements: 3.7, 4.4, 12.3, 13.2_

  - [x] 12.4 Write the packaging unit test
    - Create `tests/unit/test_recognizer_packaging.py`
    - Using `tomllib`, assert `pyproject.toml` `dependencies` is exactly `["pyyaml>=6.0.3"]`, the `dev` extra is unchanged, and `[tool.setuptools.package-data]` contains the `greenscreen.recognizer.signatures` entry `["*.yaml"]` next to the existing connector entry
    - Assert the seven bundled YAML files exist on disk under `greenscreen/recognizer/signatures/`
    - _Requirements: 8.12, 12.4, 12.8_

- [-] 13. Final checkpoint - full unit and property suites and packaging check
  - Run `pytest tests/unit tests/property` (integration tests are excluded) and confirm zero failures and that the property suite finishes in under 60 seconds
  - Run the packaging check: `pip wheel . --no-deps --no-build-isolation -w <tmp>`, list the archive with `python -m zipfile -l`, confirm it contains the seven `greenscreen/recognizer/signatures/*.yaml` files, then install the wheel into a clean virtual environment and run `python -c "from greenscreen.recognizer import load_bundled_signatures as f; print(len(f()))"` from an unrelated directory and confirm it prints 7
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 8.1, 8.12, 11.9, 12.7, 12.8_

## Notes

- Every task is required, and no sub-task is optional. Each task references the requirement clauses it satisfies; each property task names its design property number and the clauses it validates.
- The wheel check and the clean-virtualenv install in task 13 are shell steps run once at the end, not unit tests, because building a wheel starts a subprocess and Requirement 10.9 forbids that in the unit suite.
- Recognizer tests need no fake s3270. If a later test does, it must use the `fake_s3270_factory` fixture from `tests/conftest.py`.
- Facts about captures are read from `captures/*.readbuffer.txt` by tests on every run; task 1.3 pins the capture set to exactly the seven files, so a new capture (in particular one of a screen holding a residual password, Requirement 13.6) fails the suite until the requirements are updated.
- Requirements 1.17 and 1.18 (empty matcher text, `field_layout` count mismatch) are implemented in task 2.1 and tested in tasks 2.2 and 7.2. Requirements 7.4 and 7.6 are covered by tasks 8.1, 8.2 and 8.6. Requirement 9 row selection, the count-0 fallback and the stable-text name are covered by tasks 8.1, 8.2 and 8.6. Requirement 13 is covered by tasks 6.7, 10.1, 10.2 and 10.3.
- For the future recorder spec: regex patterns proposed by an LLM must be length-limited and reviewed by a person before they are accepted, because Python `re` backtracking is not bounded (design decision D8). The 200-character pattern limit and the 256-character subject bound do not prevent catastrophic backtracking.
- Run the property suite with `pytest tests/property --hypothesis-seed=0` for reproducibility.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "7.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "4.1", "6.1", "7.2", "7.3", "7.4", "8.1", "11.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "6.2"] },
    { "id": 5, "tasks": ["6.3", "6.4", "6.5", "6.6", "6.7", "8.2", "8.3", "8.4", "8.5", "8.6", "10.1", "10.2", "10.3", "11.2", "11.3", "11.4", "11.5", "12.1"] },
    { "id": 6, "tasks": ["12.2", "12.3", "12.4"] }
  ]
}
```
