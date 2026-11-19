"""Error codes and fixed texts of the Ask feature.

These tables are separate from the 22-code publisher tables in ``calls.py``.
Every text is fixed: none holds a question, an argument, a model reply or a
tool result.
"""

from __future__ import annotations

# The one sentence the model must answer with when a question is out of scope or no tool
# result answers it (spec ask, Decision 34). Defined here and nowhere else in greenscreen/.
REFUSAL_SENTENCE = "I can only answer questions about this mainframe, using its tools, and I cannot answer that."

ASK_ERROR_CODES: frozenset[str] = frozenset(
    {
        "question_invalid",
        "daily_limit",
        "tool_limit",
        "turn_limit",
        "ask_timeout",
        "model_unreachable",
        "model_refused",
        "model_unusable",
        "model_busy",
    }
)

ASK_HTTP_STATUS: dict[str, int] = {
    "question_invalid": 422,
    "daily_limit": 429,
    "tool_limit": 422,
    "turn_limit": 422,
    "ask_timeout": 504,
    "model_unreachable": 502,
    "model_refused": 502,
    "model_unusable": 502,
    "model_busy": 503,
}

ASK_MESSAGES: dict[str, str] = {
    "question_invalid": "The question is not valid.",
    "daily_limit": (
        "The daily limit of questions has been reached. The count is kept in "
        "memory and resets at 00:00 UTC and when the server restarts."
    ),
    "tool_limit": "The question needed more tool calls than allowed.",
    "turn_limit": "The question needed more model turns than allowed.",
    "ask_timeout": (
        "The question ran out of time and was stopped before the next step "
        "could finish."
    ),
    "model_unreachable": (
        "The language model could not be reached or did not answer in time."
    ),
    "model_refused": "The language model refused the request.",
    "model_unusable": "The language model returned something that cannot be used.",
    "model_busy": "The language model is busy. Try again in a minute.",
}

# Reasons a tool call requested by the model is rejected before it runs.
REJECT_REASONS: dict[str, str] = {
    "unknown_tool": "That tool is not available.",
    "arguments_too_large": "The arguments are too long.",
    "arguments_not_json": "The arguments are not valid JSON.",
    "arguments_not_object": "The arguments must be a JSON object.",
    "arguments_too_deep": "The arguments are nested too deeply.",
    "unknown_argument": "The arguments contain a name that the tool does not accept.",
    "tool_limit": "The limit of tool calls for this question has been reached.",
    "not_enough_time": "There is not enough time left to run this tool.",
    "result_too_large": "The result of the tool was too large to show.",
}
