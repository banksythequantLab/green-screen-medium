"""Load the eight bundled flows shipped as package data."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import resources
from typing import TYPE_CHECKING

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import Flow

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.recognizer import ScreenSignature

_MANIFEST = (
    "tk5-logon",
    "tk5-logoff",
    "tk5-system-info",
    "tk5-time",
    "tk5-list-datasets",
    "tk5-dataset-info",
    "tk5-library-members",
    "tk5-job-status",
)


def load_bundled_flows(
    signatures: Iterable[ScreenSignature] | None = None,
) -> dict[str, Flow]:
    """Return the bundled flows in manifest order, or raise FlowDefinitionError.

    Each call reads the files again; there is no module-level cache.
    """
    if signatures is None:
        from greenscreen.recognizer import load_bundled_signatures

        signatures = load_bundled_signatures()
    else:
        signatures = list(signatures)
    root = resources.files("greenscreen.flow.flows")
    flows: dict[str, Flow] = {}
    for name in _MANIFEST:
        filename = f"{name}.yaml"
        prefix = f"bundled flow file {filename}"
        text: str | None = None
        problem: str | None = None
        try:
            text = root.joinpath(filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            problem = "file is missing"
        except UnicodeDecodeError:
            problem = "file is not valid UTF-8"
        except OSError:
            problem = "file could not be read"
        if problem is not None or text is None:
            raise FlowDefinitionError(f"{prefix}: {problem}")
        try:
            flow = Flow.from_yaml(text, signatures)
        except FlowDefinitionError as exc:
            problem = str(exc)
        if problem is not None:
            raise FlowDefinitionError(f"{prefix}: {problem}")
        if flow.name != name:
            raise FlowDefinitionError(f"{prefix}: flow name differs from file name")
        flows[name] = flow
    return flows
