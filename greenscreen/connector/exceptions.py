"""Exception hierarchy for the tn3270-connector library."""
from __future__ import annotations

from typing import Any


class ConnectorError(Exception):
    """Base class for all tn3270-connector exceptions."""


class ConfigurationError(ConnectorError):
    """A configuration parameter is missing, wrong type, or out of range.

    Attributes:
        parameter_name: The name of the offending configuration parameter.
    """

    def __init__(self, message: str, *, parameter_name: str) -> None:
        super().__init__(message)
        self.parameter_name = parameter_name


class S3270Error(ConnectorError):
    """s3270 returned an error response, or the subprocess exited unexpectedly.

    Attributes:
        action: The s3270 action that triggered the error.
        data_lines: Data lines returned by s3270 in the error response.
        status_line: The parsed StatusLine, if available.  Typed as Any here to
            avoid a circular import — models.py imports exceptions.py, so
            exceptions.py must not import models.py.
        exit_code: The subprocess exit code, if the process exited unexpectedly.
    """

    def __init__(
        self,
        message: str,
        *,
        action: str = "",
        data_lines: list[str] | None = None,
        status_line: Any = None,  # StatusLine | None — see note above
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.data_lines: list[str] = data_lines if data_lines is not None else []
        self.status_line = status_line
        self.exit_code = exit_code


class ConnectorTimeoutError(ConnectorError):
    """A read or wait operation exceeded its configured deadline.

    Named ConnectorTimeoutError (not TimeoutError) to avoid shadowing the
    Python built-in ``TimeoutError``.

    Attributes:
        operation: The name of the operation that timed out.
        deadline: The deadline (in seconds) that was exceeded.
    """

    def __init__(self, message: str, *, operation: str, deadline: float) -> None:
        super().__init__(message)
        self.operation = operation
        self.deadline = deadline


class ParseError(ConnectorError):
    """The ScreenParser could not interpret s3270 output.

    Attributes:
        raw: The raw string that could not be parsed.
    """

    def __init__(self, message: str, *, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


class SessionClosedError(ConnectorError):
    """A method was called on a Session that has already been closed."""
