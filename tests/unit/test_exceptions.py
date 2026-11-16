"""Unit tests for the exception hierarchy. Validates Requirements 7.1-7.6."""
import pytest

from greenscreen.connector import exceptions as ex
from greenscreen.connector.exceptions import (
    ConfigurationError, ConnectorError, ConnectorTimeoutError, ParseError,
    S3270Error, SessionClosedError,
)

ALL = [ConfigurationError, S3270Error, ConnectorTimeoutError, ParseError, SessionClosedError]


@pytest.mark.parametrize("cls", ALL)
def test_subclass_connector_error(cls):
    assert issubclass(cls, ConnectorError)
    assert issubclass(cls, Exception)


def test_base_is_exception():
    assert issubclass(ConnectorError, Exception)


def test_timeout_name_not_builtin():
    assert ConnectorTimeoutError is not TimeoutError
    assert not issubclass(ConnectorTimeoutError, TimeoutError)
    assert not hasattr(ex, "TimeoutError") or ex.TimeoutError is TimeoutError


def test_configuration_error_attrs():
    e = ConfigurationError("bad", parameter_name="port")
    assert e.parameter_name == "port" and str(e) == "bad"


def test_s3270_error_defaults():
    e = S3270Error("boom")
    assert e.action == "" and e.data_lines == [] and e.status_line is None and e.exit_code is None


def test_s3270_error_values():
    sl = object()
    e = S3270Error("boom", action="Enter", data_lines=["a"], status_line=sl, exit_code=3)
    assert (e.action, e.data_lines, e.status_line, e.exit_code) == ("Enter", ["a"], sl, 3)


def test_s3270_data_lines_not_shared():
    a, b = S3270Error("x"), S3270Error("y")
    a.data_lines.append("z")
    assert b.data_lines == []


def test_timeout_attrs():
    e = ConnectorTimeoutError("t", operation="wait", deadline=2.5)
    assert e.operation == "wait" and e.deadline == 2.5


def test_parse_error_raw():
    assert ParseError("p", raw="junk").raw == "junk"


def test_session_closed_no_extra_attrs():
    e = SessionClosedError("closed")
    assert vars(e) == {}


@pytest.mark.parametrize("exc", [
    ConfigurationError("m", parameter_name="p"),
    S3270Error("m"),
    ConnectorTimeoutError("m", operation="o", deadline=1.0),
    ParseError("m", raw="r"),
    SessionClosedError("m"),
])
def test_catchable_as_connector_error(exc):
    with pytest.raises(ConnectorError):
        raise exc
