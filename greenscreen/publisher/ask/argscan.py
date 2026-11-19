"""Version-independent depth scan for tool-call argument text.

Pure, standard library only, no import at all. The depth of a model's
arguments is decided here, before ``json.loads``, so the answer does not
depend on the interpreter's recursion limit.
"""

MAX_ARGUMENT_DEPTH = 4


def exceeds_depth(text: str, limit: int) -> bool:
    depth, in_string, escaped = 0, False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            if depth > limit:
                return True
        elif ch in "}]" and depth > 0:
            depth -= 1
    return False
