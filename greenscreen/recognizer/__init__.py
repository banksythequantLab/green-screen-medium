"""Public API of the screen recognizer."""

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    RecognizerError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import ScreenSignature
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.yamlio import load_signatures

__all__ = [
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
