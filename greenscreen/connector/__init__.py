"""Public API of the greenscreen connector (headless 3270 via s3270/ws3270).

The ``greenscreen.connector.testing`` subpackage is not imported here; import
it explicitly (it requires pyyaml).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import (
    ConfigurationError,
    ConnectorError,
    ConnectorTimeoutError,
    ParseError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.connector.models import (
    Field,
    Response,
    SAToken,
    Screen,
    SFToken,
    StatusLine,
)
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.renderer import ScreenRenderer

try:
    __version__ = _version("greenscreen-connector")
except PackageNotFoundError:  # not installed
    __version__ = "0+unknown"

__all__ = [
    "Connector",
    "ConnectorConfig",
    "Response",
    "StatusLine",
    "Screen",
    "Field",
    "SFToken",
    "SAToken",
    "ScreenParser",
    "ScreenRenderer",
    "ConnectorError",
    "ConfigurationError",
    "S3270Error",
    "ConnectorTimeoutError",
    "ParseError",
    "SessionClosedError",
]
