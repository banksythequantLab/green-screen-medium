"""Public API of greenscreen.recognizer (Requirements 12.1, 12.2, 12.6)."""
from __future__ import annotations

import importlib

import pytest

import greenscreen.connector as connector
import greenscreen.recognizer as recognizer

PUBLIC_NAMES = [
    "ScreenSignature",
    "recognize",
    "suggest_signature",
    "load_signatures",
    "load_bundled_signatures",
    "RecognizerError",
    "UnknownScreenError",
    "AmbiguousScreenError",
    "SignatureError",
]

# Pinned copy of greenscreen.connector.__all__ (sorted); the recognizer work
# must not change it.
CONNECTOR_ALL_SORTED = sorted(
    [
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
)


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_name_imports_from_package(name):
    module = importlib.import_module("greenscreen.recognizer")
    assert hasattr(module, name)
    namespace: dict = {}
    exec(f"from greenscreen.recognizer import {name}", namespace)
    assert namespace[name] is getattr(recognizer, name)


def test_all_is_exactly_the_nine_names():
    assert len(recognizer.__all__) == 9
    assert sorted(recognizer.__all__) == sorted(PUBLIC_NAMES)


def test_connector_all_unchanged():
    assert sorted(connector.__all__) == CONNECTOR_ALL_SORTED
    assert len(connector.__all__) == len(set(connector.__all__))
