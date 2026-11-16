# Requirements Document

## Introduction

The screen-recognizer is the `greenscreen.recognizer` Python package, built on top of `greenscreen.connector`. It identifies which known screen a `Screen` object is. This is Core Piece 2 of Green Screen Medium: the runtime checks the recognized screen at every flow step and stops on any unexpected screen, so recognition must be deterministic, offline and auditable, with no LLM involved.

A `ScreenSignature` is a named, YAML-serializable definition made of matchers. There are seven kinds: required text at a fixed position, required text anywhere on a row, the layout of unprotected fields, the cursor's field, an optional regular expression on a region, the last non-blank row, and the text just before the cursor. The last two kinds identify TSO line-mode screens, where rows shift and the text above varies. A signature can declare volatile regions that recognition ignores, such as the date and time on the logon screen or the time on the ISPF primary option menu. The function `recognize(screen, signatures)` returns the single matching signature name, or raises `UnknownScreenError` or `AmbiguousScreenError`.

Two facts from the `mainframe-host` steering file shape the design. First, "unprotected" does not mean "input field": the TSO line-mode prompt text itself sits in an unprotected field, so field matching also uses the cursor position and the hidden flag. Second, hidden fields hold passwords, so the text of a hidden field must never appear in any signature, error, log record or summary.

The package ships signatures for the screens already captured in the repo-relative `captures/` directory, a `suggest_signature(screen)` helper that the recorder will use later, and Hypothesis property tests alongside unit tests that use the `captures/` data and need no live host. Tests resolve `captures/` relative to the repository root.

## Glossary

- **Recognizer**: The `greenscreen.recognizer` package described by these requirements.
- **Screen**: The `greenscreen.connector.models.Screen` object holding the 3270 cell grid, cursor position and fields.
- **Field**: The `greenscreen.connector.models.Field` object with `start_row`, `start_col`, `byte_length`, `protected`, `hidden` and `text` attributes.
- **Signature**: A `ScreenSignature` object: a unique name of at most 64 characters, an optional description of at most 500 characters, a list of 1 to 50 Matchers and a list of 0 to 50 Volatile_Regions.
- **Signature_Name**: The non-empty string of at most 64 characters identifying a Signature. Valid characters are lowercase ASCII letters, digits, `-` and `_`.
- **Matcher**: One condition that a Screen either satisfies or does not. There are seven kinds: Text_At_Matcher, Row_Contains_Matcher, Field_Layout_Matcher, Cursor_Field_Matcher, Region_Regex_Matcher, Last_Row_Matcher and Before_Cursor_Matcher. A Signature matches a Screen only when every one of its Matchers is satisfied.
- **Text_At_Matcher**: A Matcher requiring an exact, case-sensitive string at zero-origin `(row, col)`.
- **Row_Contains_Matcher**: A Matcher requiring an exact, case-sensitive string to occur anywhere within one given row.
- **Field_Layout_Matcher**: A Matcher that uses positions only. It requires that the Screen has exactly the declared number of Unprotected_Fields and that their `(row, col)` start positions equal the declared list, in `Screen.fields` order. It declares and compares no Field length.
- **Cursor_Field_Matcher**: A Matcher requiring that the cursor lies in an Input_Field whose `(start_row, start_col)` equals the declared position and whose `hidden` flag equals the declared value.
- **Region_Regex_Matcher**: A Matcher requiring that a Python regular expression of at most 200 characters, applied with `re.search` to the Visible_Text of a rectangular region (`row`, `col`, `length`) within a single row, finds a match.
- **Last_Row_Matcher**: A Matcher requiring that the last row of the Visible_Text that contains at least one non-space, non-null cell, with trailing spaces removed, equals the declared string exactly. Leading spaces are significant (for example ` ***` and ` READY`). It is unsatisfied when the Screen has no non-blank row.
- **Before_Cursor_Matcher**: A Matcher requiring that the Visible_Text of the cursor row, from column 0 up to but excluding the cursor column, with trailing spaces removed, ends with the declared string. It is unsatisfied when the cursor lies outside the Screen.
- **Unprotected_Field**: A Field whose `protected` attribute is False. This term does not imply that the Field accepts operator input.
- **Input_Field**: An Unprotected_Field whose `hidden` attribute is True or within which the cursor position lies.
- **Volatile_Region**: A rectangle (`row`, `col`, `length`) within one row whose character content changes between visits to the same screen (for example a clock). The Recognizer ignores the content of Volatile_Regions. A Volatile_Region that lies partly or fully outside the Screen is clipped to the Screen dimensions.
- **Visible_Text**: The view of the Screen built from `Screen.cell_grid` in which every cell of a hidden Field is replaced by a space and every cell inside a Volatile_Region of the Signature under evaluation is replaced by a space.
- **Hidden_Content**: The `text` of any Field with `hidden` set to True, and every cell position covered by that text.
- **Redacted_Summary**: A structured, text-only description of a Screen that contains no Hidden_Content, with each hidden cell shown as `*` (see Requirement 6). It holds the Visible_Text of each row and the Field tuples, and is available on the `summary` attribute of `UnknownScreenError`.
- **UnknownScreenError**: The exception raised when no Signature matches. Its message is short and holds only counts and the cursor position; the full Redacted_Summary is on its `summary` attribute.
- **AmbiguousScreenError**: The exception raised when more than one Signature matches.
- **SignatureError**: The exception raised when a Signature is invalid or a YAML document cannot be loaded as a Signature.
- **Capture**: One of the files under the repo-relative `captures/` directory recording exact s3270 output (`<name>.ascii.txt` and `<name>.readbuffer.txt`).
- **Recorder**: The future Green Screen Medium component that calls `suggest_signature`.

## Requirements

### Requirement 1: Signature Definition and Matchers

**User Story:** As a flow author, I want a signature made of explicit matchers so that each known screen has an auditable, deterministic definition.

#### Acceptance Criteria

1. THE Recognizer SHALL provide a `ScreenSignature` type holding a Signature_Name, an optional description string of 0 to 500 characters, a list of 1 to 50 Matchers and a list of 0 to 50 Volatile_Regions.
2. THE Recognizer SHALL support exactly these seven Matcher kinds: Text_At_Matcher, Row_Contains_Matcher, Field_Layout_Matcher, Cursor_Field_Matcher, Region_Regex_Matcher, Last_Row_Matcher and Before_Cursor_Matcher.
3. WHEN a Signature is evaluated against a Screen, THE Recognizer SHALL report a match only if every Matcher of the Signature is satisfied by that Screen.
4. WHEN a Text_At_Matcher is evaluated, THE Recognizer SHALL report satisfaction if and only if the declared string equals the Visible_Text of the same length starting at the declared `(row, col)`, using exact, case-sensitive equality.
5. WHEN a Row_Contains_Matcher is evaluated, THE Recognizer SHALL report satisfaction if and only if the declared string occurs as a contiguous, case-sensitive substring of the Visible_Text of the declared row.
6. WHEN a Field_Layout_Matcher is evaluated, THE Recognizer SHALL report satisfaction if and only if the count of Unprotected_Fields on the Screen equals the declared count and the `(row, col)` start positions of those Fields, in the order of `Screen.fields`, equal the declared position list, with no Field length compared.
7. WHEN a Cursor_Field_Matcher is evaluated, THE Recognizer SHALL report satisfaction if and only if `Screen.find_field` at the cursor position returns an Input_Field whose `(start_row, start_col)` and `hidden` flag equal the declared values.
8. WHEN a Region_Regex_Matcher is evaluated, THE Recognizer SHALL apply `re.search` to the Visible_Text of the declared region and report satisfaction if and only if a match is found.
9. IF a Signature is constructed with zero Matchers, THEN THE Recognizer SHALL raise `SignatureError` indicating that the Signature would match every Screen, and SHALL NOT create the Signature.
10. IF a Signature is constructed with a Signature_Name that is empty, is longer than 64 characters, or contains a character outside the valid set, THEN THE Recognizer SHALL raise `SignatureError` identifying the name, and SHALL NOT create the Signature.
11. IF a Matcher or Volatile_Region declares a `row` or `col` that is not a non-negative integer, a `row` above 255, a `col` above 255, a `length` below 1, or a last column (`col` + `length` - 1) above 255, THEN THE Recognizer SHALL raise `SignatureError` identifying the offending Matcher or Volatile_Region, and SHALL NOT create the Signature. Screen-size checks happen at match time per criterion 1.14.
12. IF a Region_Regex_Matcher declares a pattern that `re.compile` rejects, or a pattern longer than 200 characters, THEN THE Recognizer SHALL raise `SignatureError` identifying the Matcher, and SHALL NOT create the Signature.
13. IF a Text_At_Matcher or Region_Regex_Matcher shares at least one `(row, col)` cell with a Volatile_Region of the same Signature, THEN THE Recognizer SHALL raise `SignatureError` identifying both entries, and SHALL NOT create the Signature.
14. IF a Matcher addresses a row or column outside the dimensions of the Screen under evaluation, THEN THE Recognizer SHALL treat that Matcher as unsatisfied, SHALL report the Signature as not matching, and SHALL NOT raise an exception.
15. WHEN a Last_Row_Matcher is evaluated, THE Recognizer SHALL read the Visible_Text only, with hidden Field cells and the Volatile_Regions of the Signature blank, and SHALL report satisfaction if and only if the Screen has at least one row containing a non-space, non-null cell and the last such row, with trailing spaces removed, equals the declared string exactly, with leading spaces significant. IF the Screen has no non-blank row, THEN THE Recognizer SHALL evaluate the Last_Row_Matcher as unsatisfied.
16. WHEN a Before_Cursor_Matcher is evaluated, THE Recognizer SHALL read the Visible_Text only, with hidden Field cells and the Volatile_Regions of the Signature blank, and SHALL report satisfaction if and only if the Visible_Text of the cursor row from column 0 up to but excluding the cursor column, with trailing spaces removed, ends with the declared string. IF the cursor lies outside the Screen, THEN THE Recognizer SHALL evaluate the Before_Cursor_Matcher as unsatisfied.
17. IF a Text_At_Matcher, Row_Contains_Matcher, Last_Row_Matcher or Before_Cursor_Matcher declares an empty string, THEN THE Recognizer SHALL raise `SignatureError` identifying the offending Matcher, and SHALL NOT create the Signature.
18. IF a Field_Layout_Matcher declares a count that differs from the number of positions in its declared position list, THEN THE Recognizer SHALL raise `SignatureError` identifying the Matcher, and SHALL NOT create the Signature.

### Requirement 2: Volatile Regions

**User Story:** As a flow author, I want to mark clocks and dates as volatile so that the same screen is recognized at any time of day.

#### Acceptance Criteria

1. WHEN a Signature is evaluated against a Screen, THE Recognizer SHALL replace every cell inside each Volatile_Region of that Signature, clipped per criterion 2.6, with a single space character (U+0020) in the Visible_Text before any text-based Matcher is evaluated.
2. WHEN two Screens differ only in the character content of cells inside the Volatile_Regions of a Signature, THE Recognizer SHALL return the same match result for that Signature on both Screens.
3. WHEN the Recognizer evaluates a Signature, THE Recognizer SHALL apply only the Volatile_Regions declared by that Signature and SHALL NOT apply the Volatile_Regions of any other Signature.
4. WHEN the Recognizer evaluates a Field_Layout_Matcher or a Cursor_Field_Matcher, THE Recognizer SHALL produce the same result regardless of whether the Signature declares Volatile_Regions, because those Matchers do not read character content.
5. WHERE a Signature declares no Volatile_Regions, THE Recognizer SHALL evaluate every cell outside hidden Fields with its character content unchanged.
6. WHEN a Volatile_Region of a Signature lies partly or fully outside the Screen dimensions, THE Recognizer SHALL clip that Volatile_Region to the Screen dimensions when the Visible_Text is built, SHALL give a Volatile_Region that lies fully outside the Screen no effect, SHALL NOT raise an exception because of the Volatile_Region (consistent with criterion 1.14), and SHALL leave the evaluation of all other Signatures unaffected.
7. WHEN Volatile_Regions of one Signature overlap, THE Recognizer SHALL treat the union of their cells as volatile, and SHALL replace each cell in the union with a space exactly once.

### Requirement 3: Input Field Semantics and Hidden Fields

**User Story:** As a flow author, I want input fields identified by more than the protected bit so that the TSO prompt text field is not mistaken for the field the operator types in.

#### Acceptance Criteria

1. THE Recognizer SHALL classify a Field as an Input_Field if and only if its `protected` attribute is False and either its `hidden` attribute is True or the cursor position lies within the Field.
2. WHEN the Screen is the TSO password prompt Capture (`tso-password-prompt`), THE Recognizer SHALL classify the hidden Field starting at row 1, col 0 as an Input_Field and SHALL NOT classify the unprotected Field starting at row 0, col 0 as an Input_Field.
3. WHEN the Screen is the ISPF primary option menu Capture (`ispf-primary-menu`), THE Recognizer SHALL classify exactly one Field as an Input_Field, the Field that contains the cursor.
4. WHEN the Screen is an unformatted Screen (`Screen.find_field` returns None at the cursor position), THE Recognizer SHALL evaluate a Cursor_Field_Matcher as unsatisfied.
5. WHEN the Screen is an unformatted Screen (`Screen.find_field` returns None at the cursor position), THE Recognizer SHALL evaluate a Field_Layout_Matcher declaring zero Unprotected_Fields as satisfied.
6. WHEN THE Recognizer evaluates a text-based Matcher, THE Recognizer SHALL evaluate it against Visible_Text, in which each cell belonging to a hidden Field is a space character and every cell outside hidden Fields is unchanged from the Screen.
7. THE Recognizer SHALL NOT read `Field.text` of a hidden Field in any code path.
8. IF a Screen contains a hidden Field that is unprotected and the cursor lies outside it, THEN THE Recognizer SHALL still classify that Field as an Input_Field and SHALL NOT raise an error.

### Requirement 4: YAML Serialization

**User Story:** As a contributor, I want signatures stored as YAML so that humans can review them in version control and the recorder can write them.

#### Acceptance Criteria

1. THE Recognizer SHALL provide `ScreenSignature.to_yaml() -> str` and `ScreenSignature.from_yaml(text: str) -> ScreenSignature` that convert between a Signature and a YAML document containing exactly one Signature mapping.
2. WHEN `load_signatures(path)` is called with a path to a readable YAML file containing one Signature mapping or a list of Signature mappings, THE Recognizer SHALL return a list of Signatures in file order, with a single-mapping file returning a list of length 1 and an empty list (zero Signatures) returning an empty list.
3. FOR ALL valid Signatures, THE Recognizer SHALL satisfy `from_yaml(to_yaml(sig)) == sig` (round-trip property), including Signatures whose strings contain quotes, backslashes, colons, leading or trailing spaces, and non-ASCII printable characters.
4. THE Recognizer SHALL parse YAML with `yaml.safe_load` only and SHALL emit YAML with `yaml.safe_dump` only.
5. THE Recognizer SHALL emit YAML with a `version` key whose value is the integer 1, and, FOR ALL Signatures, two calls to `to_yaml()` on equal Signatures SHALL return identical strings, with mapping keys in the same order on every call.
6. IF a YAML document is malformed, is not a mapping or list of mappings, has an unknown key, lacks a required key, or has a value of the wrong type, THEN THE Recognizer SHALL raise `SignatureError` whose message names the offending key (or states that the document structure is invalid when no key applies) and, for a list, the zero-origin index of the Signature, and SHALL return no partial result.
7. IF a YAML document declares a `version` that is not the integer 1, including a value of another type such as a string or a boolean, THEN THE Recognizer SHALL raise `SignatureError` naming the unsupported version value.
8. THE Recognizer SHALL NOT include in any `SignatureError` message the text of a YAML scalar other than the key name, the Signature_Name and the Matcher kind.
9. IF `load_signatures` is given a list in which two Signatures share a Signature_Name, THEN THE Recognizer SHALL raise `SignatureError` naming the duplicate Signature_Name and the zero-origin indexes of both Signatures, and SHALL return no partial result.
10. IF `load_signatures(path)` is given a path that does not exist or cannot be read, THEN THE Recognizer SHALL raise `SignatureError` indicating the file could not be read.
11. THE Recognizer SHALL serialize and load all seven Matcher kinds in YAML, representing a Last_Row_Matcher and a Before_Cursor_Matcher each by its kind and its declared string, and a Field_Layout_Matcher by its declared count and its list of `(row, col)` positions.

### Requirement 5: Recognition

**User Story:** As the runtime, I want one call that returns the name of the current screen or fails clearly so that a flow never guesses.

#### Acceptance Criteria

1. THE Recognizer SHALL provide `recognize(screen, signatures) -> str` that accepts a Screen and an iterable of Signatures.
2. WHEN exactly one Signature in `signatures` matches the Screen, THE Recognizer SHALL return the Signature_Name of that Signature.
3. IF no Signature in `signatures` matches the Screen, including when `signatures` is empty, THEN THE Recognizer SHALL raise `UnknownScreenError` and leave the Screen and all Signatures unchanged.
4. IF more than one Signature in `signatures` matches the Screen, THEN THE Recognizer SHALL raise `AmbiguousScreenError` whose `names` attribute lists every matching Signature_Name in ascending lexicographic order by Unicode code point, with no duplicates, and whose message contains every one of those names.
5. IF two or more Signatures in `signatures` share a Signature_Name, THEN THE Recognizer SHALL raise `SignatureError` before evaluating any Matcher, and the error message SHALL contain each duplicated Signature_Name.
6. IF `signatures` is an iterator, THEN THE Recognizer SHALL consume it at most once and SHALL produce the same result as when the same Signatures are supplied as a list.
7. THE Recognizer SHALL return the same result, or raise the same exception type with the same `names` attribute where applicable, for the same Screen and the same set of Signatures regardless of the order in which the Signatures are supplied.
8. THE Recognizer SHALL NOT modify the Screen or any Signature passed to `recognize`, whether `recognize` returns or raises.
9. THE Recognizer SHALL perform `recognize` without network I/O, subprocess creation or file I/O.
10. THE test suite SHALL include a benchmark test asserting that `recognize` with 100 Signatures of up to 10 Matchers each and a 24-row by 80-column Screen finishes within 2 seconds, a deliberately generous bound that avoids flaky failures.

### Requirement 6: Errors and Redacted Summary

**User Story:** As an operator reading a failed flow log, I want an unknown-screen error that shows what was on screen without exposing passwords so that I can diagnose the failure safely.

#### Acceptance Criteria

1. THE Recognizer SHALL define `RecognizerError` as the base class of `UnknownScreenError`, `AmbiguousScreenError` and `SignatureError`; `RecognizerError` SHALL NOT inherit from `ConnectorError`.
2. WHEN `UnknownScreenError` is raised, THE Recognizer SHALL attach a `summary` attribute holding a Redacted_Summary of the Screen.
3. THE Redacted_Summary SHALL contain: the row and column counts, the cursor position as a (row, column) pair, the total Field count, the Unprotected_Field count, the hidden Field count, the `(start_row, start_col, byte_length, protected, hidden)` tuple of each Field, and the Visible_Text of each row with trailing spaces removed.
4. THE Redacted_Summary SHALL show each cell belonging to a hidden Field as the character `*` so that the extent of the Field is visible while its content is not, and, IF a hidden Field contains only spaces or null characters, THEN THE Redacted_Summary SHALL still show every cell of that Field as `*`.
5. THE Redacted_Summary SHALL provide a `to_text()` method returning a multi-line string with exactly one line per Screen row, and a `to_dict()` method returning only strings, integers and booleans, plus lists or mappings of those types.
6. THE Recognizer SHALL build the message of `UnknownScreenError` as a short single line containing only the row and column counts, the cursor position, the total, unprotected and hidden Field counts, and the number of Signatures evaluated (0 to the number of registered Signatures), with no row text and no Field tuples. The full Redacted_Summary SHALL stay available on the `summary` attribute for callers who choose to print it.
7. THE Recognizer SHALL make `str()` and `repr()` of `UnknownScreenError`, `AmbiguousScreenError` and the Redacted_Summary free of Hidden_Content, so that no character of any hidden Field's content appears in either string, including when that content differs from `*`.
8. WHEN `AmbiguousScreenError` is raised, THE Recognizer SHALL include only the Signature_Names of the matching Signatures and their count in the exception message and attributes, and SHALL NOT include any Screen text.
9. THE Recognizer SHALL emit log records only through the standard `logging` module under the logger name `greenscreen.recognizer`, at DEBUG level, and each record SHALL contain only Signature_Names, counts and the recognition outcome (one of matched, unknown, ambiguous).
10. IF a Screen has zero Fields, THEN THE Redacted_Summary SHALL report Field counts of 0, an empty Field tuple list, and the Visible_Text of each row, without raising an error.

### Requirement 7: Hidden Field Protection

**User Story:** As a security-conscious maintainer, I want a guarantee that password text cannot leak through the recognizer so that logs and stored signatures stay clean.

#### Acceptance Criteria

1. THE Recognizer SHALL NOT include any character of Hidden_Content in any Signature, YAML document produced by `to_yaml`, exception message, exception attribute, log record, or Redacted_Summary, regardless of whether the data was produced by `suggest_signature`, `recognize`, `to_yaml`, or `load_signatures`.
2. WHEN `suggest_signature` generates a Matcher, THE Recognizer SHALL derive the Matcher text only from Visible_Text.
3. WHEN `suggest_signature` evaluates a candidate Matcher for a Screen containing a hidden Field, THE Recognizer SHALL discard the candidate if at least 1 of its cells lies within the cell range of any hidden Field.
4. WHEN the Screen contains a hidden Field, THE Recognizer SHALL record that Field in the Signature only by its `(start_row, start_col)` position in a Field_Layout_Matcher (when the Field is unprotected) and, when the cursor lies in the Field, also by the `hidden` flag of a Cursor_Field_Matcher, with no text and no other attribute.
5. WHEN the Recognizer evaluates a text-based Matcher loaded from YAML against a Screen, THE Recognizer SHALL compare every Matcher cell that lies within a hidden Field of that Screen as a space character (U+0020), regardless of the actual cell content.
6. IF `suggest_signature` discards all candidates because each overlaps a hidden Field, THEN THE Recognizer SHALL return a Signature that contains no text-based Matcher derived from those cells, SHALL still record the hidden Field positions through the Field_Layout_Matcher, and SHALL leave the Screen unchanged.

### Requirement 8: Shipped Signatures

**User Story:** As a developer, I want signatures for the screens already captured so that the runtime can recognize the TK5 logon path out of the box.

#### Acceptance Criteria

1. THE Recognizer SHALL ship Signatures as YAML package data and SHALL provide `load_bundled_signatures()` that returns all bundled Signatures when the current working directory is empty or unrelated to the project.
2. THE Recognizer SHALL ship exactly seven bundled Signatures, one for each of these screens: the Hercules/TK5 logo (`tk5-logo`), the TK5 logon screen (`tk5-logon`), the `INPUT NOT RECOGNIZED` screen (`tso-input-not-recognized`), the TSO password prompt (`tso-password-prompt`), the ISPF primary option menu (`ispf-primary-menu`), the TSO `READY` screen (`tso-ready`) and the TSO `***` pause screen (`tso-pause`), each verified against its Capture (`tso-pause` against `tso-pause-2`), and SHALL ship no other bundled Signatures.
3. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tk5-logo` Capture, THE Recognizer SHALL return `tk5-logo`.
4. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tk5-logon` Capture, THE Recognizer SHALL return `tk5-logon`.
5. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tso-password-prompt` Capture, THE Recognizer SHALL return `tso-password-prompt`.
6. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `ispf-primary-menu` Capture, THE Recognizer SHALL return `ispf-primary-menu`.
7. THE `tk5-logon` Signature SHALL declare the date value and the time value in the top-right corner of the Capture as Volatile_Regions, each covering exactly the row, start column and length of that value in the Capture, and THE `ispf-primary-menu` Signature SHALL declare the time value as a Volatile_Region covering exactly the row, start column and length of that value in the Capture.
8. THE `tso-password-prompt` Signature SHALL match the prompt text `ENTER CURRENT PASSWORD FOR` followed by a user ID of 1 to 8 characters, SHALL declare the hidden Field at row 1, col 0 through a Cursor_Field_Matcher with `hidden` set to True, and SHALL NOT contain the user ID or any password.
9. THE `ispf-primary-menu` Signature SHALL require exactly one Unprotected_Field and a Cursor_Field_Matcher on that Field, and SHALL NOT include the user ID value shown on the screen.
10. THE `tso-input-not-recognized` Signature SHALL be built from `captures/tso-input-not-recognized` and SHALL match a Screen on which the text `INPUT NOT RECOGNIZED` is at row 3, col 0 (a Text_At_Matcher) and a Last_Row_Matcher with the declared string `INPUT NOT RECOGNIZED` (no leading space, because the text starts at col 0).
11. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from any one of the seven Captures (`tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready`, `tso-pause-2`), THE Recognizer SHALL find exactly one matching bundled Signature, and that Signature SHALL be the one named for that Capture (the `tso-pause-2` Capture maps to `tso-pause`).
12. THE Recognizer SHALL declare the bundled YAML files as package data in `pyproject.toml` so that a wheel built from the project contains every bundled YAML file.
13. THE Recognizer SHALL build every bundled Signature only from text, positions and attributes present in a Capture in `captures/` or stated in the `mainframe-host` steering file.
14. IF a bundled YAML file is missing from the package data or fails Signature validation, THEN `load_bundled_signatures()` SHALL raise an error that names the affected file and SHALL return no partial Signature list.
15. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tso-input-not-recognized` Capture, THE Recognizer SHALL return `tso-input-not-recognized`.
16. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tso-ready` Capture, THE Recognizer SHALL return `tso-ready`.
17. WHEN `recognize` is called with the bundled Signatures and the Screen parsed from the `tso-pause-2` Capture, THE Recognizer SHALL return `tso-pause`.
18. THE `tso-ready` Signature SHALL use a Last_Row_Matcher with the declared string ` READY` (with a leading space), and SHALL NOT match the Screen parsed from the `ispf-primary-menu` Capture.
19. THE `tso-pause` Signature SHALL use a Last_Row_Matcher with the declared string ` ***` and a Before_Cursor_Matcher with the declared string ` ***`, and SHALL use no Field_Layout_Matcher and no fixed-row Text_At_Matcher.
20. WHEN a Screen has ` ***` as its last non-blank row and the cursor on that row just after it, THE `tso-pause` Signature SHALL match that Screen whatever text appears above that row and whether the ` ***` row is row 10 or row 11.
21. THE Recognizer SHALL ensure that no bundled Signature matches the Screen parsed from a Capture of a different screen.

### Requirement 9: Signature Suggestion

**User Story:** As the recorder, I want to propose a signature from a screen so that a person only has to review and name it.

#### Acceptance Criteria

1. THE Recognizer SHALL provide `suggest_signature(screen, name=None) -> ScreenSignature`.
2. WHEN `suggest_signature` is called with a Screen that has at least one non-blank Visible_Text cell or at least one Field, THE Recognizer SHALL return a Signature for which `recognize` reports a match against that same Screen, with no Matcher in the Signature failing.
3. WHEN `suggest_signature` is called with a Screen that contains at least one Unprotected_Field, THE Recognizer SHALL include exactly one Field_Layout_Matcher declaring the count of Unprotected_Fields and the list of their `(row, col)` start positions, in `Screen.fields` order.
4. WHEN `suggest_signature` is called with a Screen whose cursor lies inside an Input_Field, THE Recognizer SHALL include exactly one Cursor_Field_Matcher referencing that Input_Field.
5. WHEN `suggest_signature` is called with a Screen that contains non-blank Visible_Text, THE Recognizer SHALL include at least one Text_At_Matcher or Row_Contains_Matcher built from the first row, in row order, that contains stable text (non-blank Visible_Text outside Volatile_Regions and hidden Fields), and SHALL build it from the text of that row excluding Volatile_Region cells and Hidden_Content. IF the first non-blank row consists only of volatile runs, THEN THE Recognizer SHALL use the next row that contains stable text.
6. WHERE a `name` is supplied, THE Recognizer SHALL use it unchanged as the Signature_Name.
7. IF `name` is None, THEN THE Recognizer SHALL derive the Signature_Name from the stable text of the row selected under criterion 9.5 (volatile and hidden cells blank), so that a date or time never appears in the name, converted to lowercase, with each run of characters outside `a-z`, `0-9` and `-` replaced by a single `-`, leading and trailing `-` removed, and truncated to at most 64 characters, and SHALL use `unnamed-screen` when the Screen has no non-blank Visible_Text or when the derived value is empty.
8. WHEN `suggest_signature` finds a run of cells matching `HH:MM`, `HH:MM:SS` or `DD.MM.YY`, where `HH` is 00 to 23, `MM` and `SS` are 00 to 59, `DD` is 01 to 31 and the month and year digits are `00` to `99`, THE Recognizer SHALL declare that run as a Volatile_Region and SHALL NOT use any cell of that run in any text-based Matcher.
9. IF and only if the Screen has no non-blank Visible_Text and no Fields, THEN THE Recognizer SHALL raise `SignatureError` with a message indicating that the Screen has no identifying features, and SHALL NOT return a Signature. A Screen that has non-blank Visible_Text or at least one Field always yields a Signature, using criterion 9.13 when no other Matcher applies.
10. WHEN `suggest_signature` is called more than once with equal Screen and `name` arguments, THE Recognizer SHALL return Signatures that are equal in every Matcher, Volatile_Region and Signature_Name, regardless of call order or elapsed time.
11. THE Recognizer SHALL NOT include any character, or any Matcher derived from a character, from a Hidden_Content cell in the returned Signature (see Requirement 7).
12. THE Recognizer SHALL NOT modify the Screen passed to `suggest_signature`.
13. IF the Screen has no text-based Matcher candidate, no Unprotected_Field and no Input_Field, but has non-blank Visible_Text or at least one Field, THEN THE Recognizer SHALL include a Field_Layout_Matcher with count 0 and an empty position list, so that the returned Signature holds at least one Matcher.

### Requirement 10: Unit Tests with Captures

**User Story:** As a contributor, I want unit tests built on the recorded captures so that the suite runs anywhere without the live host.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests in `tests/unit` for every Matcher kind, covering at least one satisfied case and one unsatisfied case per kind, where each case asserts the Matcher's boolean result.
2. THE unit tests SHALL build the Screens for all seven Capture-based screens (`tk5-logo`, `tk5-logon`, `tso-input-not-recognized`, `tso-password-prompt`, `ispf-primary-menu`, `tso-ready`, `tso-pause-2`) from the files in `captures/`, resolved relative to the repository root, through the existing `greenscreen.connector.ScreenParser`, and SHALL NOT define screen data for those seven screens outside the Capture files.
3. THE unit tests SHALL assert that each bundled Signature recognizes its own Capture.
4. THE unit tests SHALL assert that `recognize`, run against all seven bundled Signatures, returns exactly one Signature name for each of the seven Capture-based Screens, and that the name equals the name of the Signature for that Capture (the `tso-pause-2` Capture maps to `tso-pause`).
5. IF the `ispf-primary-menu` Signature is removed from the Signature set, THEN THE unit tests SHALL assert that `recognize` on the ISPF Capture raises `UnknownScreenError`, that the `summary` attribute of the error contains the `Option  ===>` text (with two spaces before `===>`), and that the `summary` contains no Hidden_Content.
6. IF two Signatures both match the same Screen, THEN THE unit tests SHALL assert that `recognize` raises `AmbiguousScreenError` and that the error names every matching Signature, with no non-matching Signature named.
7. THE unit tests SHALL assert that the hidden Field of the `tso-password-prompt` Capture is classified as an Input_Field, and that the unprotected Field on row 0 of the same Capture is not classified as an Input_Field.
8. THE unit tests SHALL assert, for each condition that Requirements 1 and 4 define as a `SignatureError`, that triggering that condition raises `SignatureError`, with at least one test per condition.
9. WHILE the unit tests run, THE test suite SHALL open no network connection and start no subprocess.
10. THE unit tests SHALL assert that the `tso-pause` Signature matches the Screen parsed from the `tso-pause-2` Capture and matches synthetic Screens with the same ` ***` last row and cursor, with different text above that row and with ` ***` on row 10 and on row 11, and that the `tso-ready` Signature does not match the Screen parsed from the `ispf-primary-menu` Capture.
11. THE unit tests SHALL assert for the Last_Row_Matcher and the Before_Cursor_Matcher at least one satisfied case, the significance of a leading space, a Screen with no non-blank row (Last_Row_Matcher unsatisfied) and a cursor outside the Screen (Before_Cursor_Matcher unsatisfied).

### Requirement 11: Property-Based Tests

**User Story:** As a contributor, I want property-based tests so that the recognizer's guarantees hold for arbitrary screens and not only the captured ones.

#### Acceptance Criteria

1. THE test suite SHALL include a Hypothesis property test asserting that, for any generated Screen with at least one identifying feature, `suggest_signature(screen)` matches that Screen, and `recognize(screen, [suggest_signature(screen)])` returns the Signature_Name of that Signature.
2. THE test suite SHALL include a Hypothesis property test asserting that, for any Signature from `suggest_signature` and any replacement of the characters in cells inside its Volatile_Regions with other characters, the match result for the Screen is identical to the match result before the replacement.
3. THE test suite SHALL include a Hypothesis property test asserting that, for any Signature from `suggest_signature`, replacing the character in exactly one cell covered by a Text_At_Matcher (outside every Volatile_Region and outside every hidden Field) with a different character makes the Signature stop matching the Screen.
4. THE test suite SHALL include a Hypothesis property test asserting that, for any generated Screen containing one or more hidden Fields whose text is a sentinel string of 1 to 80 characters that appears in no other cell, the sentinel appears in none of the following: the output of `suggest_signature` and its `to_yaml()`, the `str()`, `repr()` and attributes of `UnknownScreenError` and `AmbiguousScreenError` raised for that Screen, the Redacted_Summary `to_text()` and `to_dict()`, and the log records (message and arguments) captured at DEBUG level on `greenscreen.recognizer`.
5. THE test suite SHALL include a Hypothesis property test asserting that `ScreenSignature.from_yaml(sig.to_yaml()) == sig` for every generated Signature.
6. THE test suite SHALL include a Hypothesis property test asserting that, for any list of 0 to 10 Signatures and any permutation of that list, `recognize` returns the same Signature_Name, or raises the same exception type (`UnknownScreenError` or `AmbiguousScreenError`) with the same set of candidate Signature_Names, for every ordering.
7. THE property tests SHALL be placed in `tests/property`, SHALL use `hypothesis.strategies` to generate Screens by building `cell_grid` values directly, and SHALL NOT require network access or a subprocess.
8. THE property tests SHALL run each test with at least 100 generated examples, unless Hypothesis exhausts the strategy's input space earlier.
9. THE test suite SHALL complete all property tests in `tests/property` in under 60 seconds in total.
10. THE test suite SHALL include a Hypothesis property test asserting that, for any text generated above the ` ***` row and with the ` ***` row on any row from 1 to 22 and the cursor on that row just after it, the bundled `tso-pause` Signature still matches the Screen.
11. THE test suite SHALL include Hypothesis property tests asserting that a Last_Row_Matcher is unsatisfied for any generated Screen with no non-blank row, and that a Before_Cursor_Matcher is unsatisfied for any cursor position outside the generated Screen.

### Requirement 12: Packaging and Dependencies

**User Story:** As a maintainer, I want the recognizer to fit the existing project layout so that installation and testing work as before.

#### Acceptance Criteria

1. THE Recognizer SHALL reside in the package `greenscreen.recognizer`, and its `__init__` module SHALL export exactly these public names: `ScreenSignature`, `recognize`, `suggest_signature`, `load_signatures`, `load_bundled_signatures`, `RecognizerError`, `UnknownScreenError`, `AmbiguousScreenError` and `SignatureError`.
2. WHEN a user runs `from greenscreen.recognizer import <name>` for each of the 9 names listed in criterion 1, THE Recognizer SHALL complete the import without raising an exception.
3. THE Recognizer SHALL import only modules from the Python standard library, `greenscreen.connector` and PyYAML.
4. THE Recognizer SHALL be compatible with the PyYAML version constraint `pyyaml>=6.0.3` already declared in `pyproject.toml`, and SHALL NOT add any new entry to the dependencies declared in `pyproject.toml`.
5. THE Recognizer SHALL run without error on Python 3.11 and on every later Python 3 minor version supported by the project's `pyproject.toml`.
6. THE Recognizer SHALL NOT modify the public API of `greenscreen.connector`, meaning no removal, renaming or signature change of any name exported from `greenscreen.connector`.
7. WHEN the existing `greenscreen.connector` unit, property and integration test suites run after the Recognizer is added, THE Recognizer SHALL leave the results of all tests that passed before the Recognizer was added unchanged (0 new failures or errors).
8. IF the Recognizer is installed with the project's standard install procedure, THEN THE Recognizer SHALL be importable as `greenscreen.recognizer`, including any bundled signature data that `load_bundled_signatures` reads.

### Requirement 13: Hidden Field Content Is Never Retained

**User Story:** As a security-conscious maintainer, I want the Recognizer to never retain the raw content of hidden Fields, including residual content on screens other than the password prompt, so that a typed password cannot leak through signatures, errors, logs or caches.

#### Acceptance Criteria

1. THE Recognizer SHALL NOT store, log or serialize the raw `cell_grid` or `text_grid` content of any hidden Field in any Signature, YAML document, exception message, exception attribute, exception `args`, log record, cache, module-level state or Redacted_Summary.
2. THE Recognizer SHALL build Visible_Text from `Screen.cell_grid` by blanking the cell range of every hidden Field, using only the Field position and extent, and SHALL NOT rely on `Screen.text_grid`, which does not blank hidden Fields (see the SECURITY note in the `mainframe-host` steering file).
3. WHILE a Screen that is not the TSO password prompt contains a hidden Field that holds residual text, such as the Screen after the password is sent where the hidden Field still holds the typed password, THE Recognizer SHALL treat that residual text as Hidden_Content under criteria 1 and 2.
4. IF the Recognizer raises an exception, THEN THE Recognizer SHALL ensure that the exception `args`, `vars()`, `__cause__`, `__context__` and the traceback frames inside `greenscreen.recognizer` hold no reference to the Screen object or its grids. The frames of the caller, which hold the caller's own Screen, are out of scope.
5. WHEN two Screens differ only in the cell content of hidden Fields, THE Recognizer SHALL return the same result from `recognize` and the same output from `suggest_signature` for both Screens.
6. THE test suite SHALL use synthetic Screens for the residual-password case, and the repository SHALL contain no Capture or fixture of the screen that holds the residual password.
7. THE test suite SHALL include a Hypothesis property test asserting that, for generated Screens that are not the password prompt (for example line-mode Screens with a ` ***` row, the cursor on that row, and a hidden Field holding a sentinel string anywhere else, including with cell content in rows that would otherwise look like the last non-blank row), the sentinel appears in none of: the `suggest_signature` output and its `to_yaml()`; the `str()`, `repr()`, `args` and `vars()` of every Recognizer exception; the Redacted_Summary `to_text()` and `to_dict()`; and the DEBUG log records on `greenscreen.recognizer`, and that `recognize` returns identical results with and without the hidden content.
