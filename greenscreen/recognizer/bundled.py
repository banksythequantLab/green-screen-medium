"""Load the ten bundled signatures shipped as package data."""

from __future__ import annotations

import logging
from importlib import resources

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import ScreenSignature

logger = logging.getLogger("greenscreen.recognizer")

_MANIFEST = (
    "tk5-logo",
    "tk5-logon",
    "tso-input-not-recognized",
    "tso-password-prompt",
    "ispf-primary-menu",
    "tso-ready",
    "tso-pause",
    "tso-userid-in-use",
    "tso-reconnect-password-prompt",
    "tso-reconnect-ok",
)


def load_bundled_signatures() -> list[ScreenSignature]:
    """Return the bundled signatures in manifest order, or raise SignatureError."""
    root = resources.files("greenscreen.recognizer.signatures")
    sigs: list[ScreenSignature] = []
    for name in _MANIFEST:
        filename = f"{name}.yaml"
        prefix = f"bundled signature file {filename}"
        try:
            text = root.joinpath(filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SignatureError(f"{prefix}: file is missing") from None
        except UnicodeDecodeError:
            raise SignatureError(f"{prefix}: file is not valid UTF-8") from None
        except OSError:
            raise SignatureError(f"{prefix}: file could not be read") from None
        try:
            sig = ScreenSignature.from_yaml(text)
        except SignatureError as exc:
            raise SignatureError(f"{prefix}: {exc}") from None
        if sig.name != name:
            raise SignatureError(f"{prefix}: signature name differs from file name")
        sigs.append(sig)
    logger.debug("loaded %d signatures", len(sigs))
    return sigs
