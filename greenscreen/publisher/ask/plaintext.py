"""Remove paired Markdown emphasis markers from a final answer (pure).

Only marker characters are deleted, so the output is never longer than the
input and holds no character the input lacked. Five fixed substitutions run
once each, in a fixed order; there is no loop. Each pair has at most 200
characters between its markers, so the work is linear in the text length.
"""

import re

_PASSES = (
    re.compile(r"(?<!`)`(?![\s`])([^`\n]{1,200})(?<![\s`])`(?!`)"),  # `x`
    re.compile(r"(?<![\w*])\*\*(?![\s*])(.{1,200}?)(?<![\s*])\*\*(?![\w*])"),  # **x**
    re.compile(r"(?<!\w)__(?![\s_])(.{1,200}?)(?<![\s_])__(?!\w)"),  # __x__
    re.compile(r"(?<![\w*])\*(?![\s*])(.{1,200}?)(?<![\s*])\*(?![\w*])"),  # *x*
    re.compile(r"(?<!\w)_(?![\s_])(.{1,200}?)(?<![\s_])_(?!\w)"),  # _x_
)


def plain_answer(text: str) -> str:
    for pattern in _PASSES:
        text = pattern.sub(r"\1", text)
    return text
