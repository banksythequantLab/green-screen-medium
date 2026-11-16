"""``recognize``: identify which known screen a ``Screen`` is."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING

from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.signature import ScreenSignature
from greenscreen.recognizer.summary import build_summary
from greenscreen.recognizer.view import ScreenView

if TYPE_CHECKING:
    from greenscreen.connector import Screen

logger = logging.getLogger("greenscreen.recognizer")


def recognize(screen: Screen, signatures: Iterable[ScreenSignature]) -> str:
    """Return the name of the single signature matching ``screen``.

    Raises ``UnknownScreenError`` when none match and ``AmbiguousScreenError``
    when several do. Pure: no I/O, and neither argument is modified.
    """
    sigs = list(signatures)
    for s in sigs:
        if not isinstance(s, ScreenSignature):
            del screen  # keep the traceback frame free of the screen
            raise TypeError("signatures must contain only ScreenSignature instances")

    counts = Counter(s.name for s in sigs)
    duplicated = sorted(n for n, c in counts.items() if c > 1)
    if duplicated:
        del screen  # keep the traceback frame free of the screen
        raise SignatureError("duplicate signature name(s): " + ", ".join(duplicated))

    view = ScreenView(screen)
    matched = sorted(s.name for s in sigs if signature_matches(s, view))
    evaluated = len(sigs)

    if len(matched) == 1:
        logger.debug(
            "recognize outcome=%s evaluated=%d matched=%s",
            "matched", evaluated, matched[0],
        )
        return matched[0]

    if not matched:
        summary = build_summary(view)
        message = (
            f"no signature matches: {summary.rows}x{summary.columns} screen, "
            f"cursor ({summary.cursor[0]}, {summary.cursor[1]}), "
            f"{summary.field_count} fields "
            f"({summary.unprotected_count} unprotected, "
            f"{summary.hidden_count} hidden), "
            f"{evaluated} signatures evaluated"
        )
        logger.debug(
            "recognize outcome=%s evaluated=%d matched=%s",
            "unknown", evaluated, "",
        )
        del screen, view
        raise UnknownScreenError(message, summary=summary) from None

    names = tuple(matched)
    message = f"{len(names)} signatures match: " + ", ".join(names)
    logger.debug(
        "recognize outcome=%s evaluated=%d matched=%s",
        "ambiguous", evaluated, ",".join(names),
    )
    del screen, view
    raise AmbiguousScreenError(message, names=names) from None
