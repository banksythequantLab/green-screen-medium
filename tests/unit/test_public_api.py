"""Tests for the greenscreen.connector public API surface."""
import importlib
import subprocess
import sys

import pytest

import greenscreen.connector as pkg

EXPECTED = {
    "Connector": "greenscreen.connector.connector",
    "ConnectorConfig": "greenscreen.connector.config",
    "Response": "greenscreen.connector.models",
    "StatusLine": "greenscreen.connector.models",
    "Screen": "greenscreen.connector.models",
    "Field": "greenscreen.connector.models",
    "SFToken": "greenscreen.connector.models",
    "SAToken": "greenscreen.connector.models",
    "ScreenParser": "greenscreen.connector.parser",
    "ScreenRenderer": "greenscreen.connector.renderer",
    "ConnectorError": "greenscreen.connector.exceptions",
    "ConfigurationError": "greenscreen.connector.exceptions",
    "S3270Error": "greenscreen.connector.exceptions",
    "ConnectorTimeoutError": "greenscreen.connector.exceptions",
    "ParseError": "greenscreen.connector.exceptions",
    "SessionClosedError": "greenscreen.connector.exceptions",
}

SUBMODULES = [
    "greenscreen.connector.models",
    "greenscreen.connector.exceptions",
    "greenscreen.connector.parser",
    "greenscreen.connector.renderer",
    "greenscreen.connector.config",
    "greenscreen.connector.connector",
    "greenscreen.connector.testing.fake",
    "greenscreen.connector.testing.fixtures",
]


def test_all_matches_expected():
    assert sorted(pkg.__all__) == sorted(EXPECTED)
    assert len(pkg.__all__) == len(set(pkg.__all__))


@pytest.mark.parametrize("name,module", sorted(EXPECTED.items()))
def test_name_resolves_to_defining_module_object(name, module):
    assert getattr(pkg, name) is getattr(importlib.import_module(module), name)


def test_no_private_names_exported():
    assert not [n for n in pkg.__all__ if n.startswith("_")]
    assert "PipeReader" not in pkg.__all__


def test_import_does_not_load_yaml():
    code = (
        "import sys, greenscreen.connector; "
        "sys.exit(1 if 'yaml' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


@pytest.mark.parametrize("mod", SUBMODULES)
def test_submodule_imports_first_in_fresh_interpreter(mod):
    result = subprocess.run(
        [sys.executable, "-c", f"import {mod}"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
