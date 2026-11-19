"""Static console assets and their loader (standard library only)."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass

ROUTES = (  # the explicit allow-list: (route path, file name, media type)
    ("/", "index.html", "text/html; charset=utf-8"),
    ("/console/console.css", "console.css", "text/css; charset=utf-8"),
    ("/console/console.js", "console.js", "text/javascript; charset=utf-8"),
    ("/console/snippets.js", "snippets.js", "text/javascript; charset=utf-8"),
    ("/console/codes.json", "codes.json", "application/json"),
    ("/console/favicon.svg", "favicon.svg", "image/svg+xml"),
)

PAIRS = frozenset(("GET", path) for path, _, _ in ROUTES)

HEADERS = {  # exactly these four on every console response, no other route
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'none'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store, no-transform",
}


@dataclass(frozen=True, slots=True)
class Asset:
    path: str
    file: str
    media_type: str
    body: bytes


class ConsoleAssetError(Exception):
    """A console asset could not be read. The message is the file name only."""

    def __init__(self, file: str) -> None:
        super().__init__(file)
        self.file = file


def load_assets() -> tuple[Asset, ...]:
    """Read every asset named in ROUTES; raise ConsoleAssetError(file) on failure."""
    assets = []
    for path, file, media_type in ROUTES:
        try:
            body = (
                importlib.resources.files("greenscreen.publisher.console")
                .joinpath(file)
                .read_bytes()
            )
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            raise ConsoleAssetError(file) from None
        assets.append(Asset(path, file, media_type, body))
    return tuple(assets)
