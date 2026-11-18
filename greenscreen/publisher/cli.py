"""``greenscreen-publish``: startup, logging, the HTTP or stdio loop, and exit codes.

Module level imports only the standard library, so the console script can name a
missing ``publish`` extra instead of failing with a bare ``ImportError``
(Requirement 16.5). Exit codes: 0 clean stop, 2 startup check or missing module.

Nothing here reads a log level from the environment: the HTTP server always runs
at INFO (``uvicorn``'s ``trace`` level logs the ASGI scope, which holds the path
and query string).
"""
from __future__ import annotations

import asyncio
import importlib
import io
import logging
import math
import os
import signal
import sys
import traceback
from typing import Any

__all__ = ["main", "build_uvicorn_config", "StripTraceback", "UVICORN_LOG_LEVEL"]

PROG = "greenscreen-publish"
REQUIRED_MODULES = ("mcp", "fastapi", "uvicorn")
BIND_PREFIX = "GS_BIND_"
#: Fixed. Never below INFO, never taken from the environment (Requirement 8.5).
UVICORN_LOG_LEVEL = "info"

_LOG = logging.getLogger("greenscreen.publisher")
_EXTRA_FIELDS = (
    "call_id",
    "flow",
    "transport",
    "outcome",
    "duration_ms",
    "step_index",
    "close_failed",
    "session_clean",
)


# -- logging -----------------------------------------------------------------


class StripTraceback(logging.Filter):
    """Replace any traceback by one fixed line (Requirement 8.7).

    The line names the exception class and the file, line and function of the
    innermost frame. It never reads the exception message or a frame local.
    A defence for a future defect in a dependency; no requirement relies on it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        info = record.exc_info
        if info and info[0] is not None:
            where = "unknown"
            tb = info[2]
            if tb is not None:
                while tb.tb_next is not None:
                    tb = tb.tb_next
                code = tb.tb_frame.f_code
                where = f"{os.path.basename(code.co_filename)}:{tb.tb_lineno} in {code.co_name}"
            record.msg = f"{record.getMessage()} [{info[0].__name__} at {where}]"
            record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class _Formatter(logging.Formatter):
    """One line per record; appends the fixed Call_Log_Record fields when present."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = [f"{k}={getattr(record, k)}" for k in _EXTRA_FIELDS if hasattr(record, k)]
        return f"{line} {' '.join(extras)}" if extras else line


def _install_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(StripTraceback())
    handler.setFormatter(_Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


# -- environment -------------------------------------------------------------


def _scrub_environment() -> None:
    """Remove GS_API_KEY and every Binding_Variable (Requirement 15.8)."""
    for name in list(os.environ):
        if name == "GS_API_KEY" or name.startswith(BIND_PREFIX):
            os.environ.pop(name, None)


def _check_modules() -> str | None:
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            return (
                f"{PROG}: required module '{name}' is not installed; "
                "install the extra 'publish' (pip install \"greenscreen-connector[publish]\")"
            )
    return None


# -- HTTP --------------------------------------------------------------------


def build_uvicorn_config(asgi: Any, host: str, port: int, grace: float) -> Any:
    """The one uvicorn ``Config`` of the Publisher.

    ``log_config`` is None, the access log is off and the level is the fixed
    ``UVICORN_LOG_LEVEL``. There is deliberately no parameter or environment
    lookup for the level: ``trace`` makes uvicorn log the ASGI scope.
    """
    import uvicorn

    return uvicorn.Config(
        asgi,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        log_level=UVICORN_LOG_LEVEL,
        lifespan="on",
        timeout_graceful_shutdown=max(1, math.ceil(grace)),
    )


def _run_http(app: Any, settings: Any) -> None:
    import uvicorn

    service = app.service

    class _Server(uvicorn.Server):
        def handle_exit(self, sig: int, frame: Any) -> None:
            # Not super(): uvicorn re-raises captured signals after a graceful stop,
            # which kills the process before the final drain and gives a non-zero exit.
            service.begin_shutdown()
            if self.should_exit and sig == signal.SIGINT:
                self.force_exit = True
            else:
                self.should_exit = True

    config = build_uvicorn_config(
        app.asgi, settings.publish_host, settings.publish_port, settings.shutdown_grace
    )
    _Server(config).run()


# -- stdio -------------------------------------------------------------------


def _stdio_streams() -> tuple[Any, Any]:
    """Duplicate fds 0 and 1 for the protocol, then point fd 1 and sys.stdout at stderr.

    Afterwards a ``print`` or a write to descriptor 1 anywhere in the process goes
    to stderr, and only the SDK writer holds the duplicate of the original stdout
    (Requirement 14.11).
    """
    import anyio

    try:
        sys.stdout.flush()
    except Exception:
        pass
    in_fd = os.dup(0)
    out_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    stdin = io.TextIOWrapper(
        os.fdopen(in_fd, "rb"), encoding="utf-8", errors="replace", newline="\n"
    )
    stdout = io.TextIOWrapper(os.fdopen(out_fd, "wb"), encoding="utf-8", newline="\n")
    return anyio.wrap_file(stdin), anyio.wrap_file(stdout)


def _on_sigterm(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def _run_stdio(app: Any, settings: Any) -> None:
    import anyio

    from greenscreen.publisher.mcp_server import run_stdio

    stdin, stdout = _stdio_streams()
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):  # not the main thread
        pass
    try:
        anyio.run(
            lambda: run_stdio(
                app.server,
                app.service,
                grace=settings.shutdown_grace,
                stdin=stdin,
                stdout=stdout,
            )
        )
    except KeyboardInterrupt:
        pass


# -- main --------------------------------------------------------------------


def main() -> int:
    missing = _check_modules()
    if missing is not None:
        print(missing, file=sys.stderr)
        return 2

    from greenscreen.publisher.app import StartupError, build_app, prepare

    try:
        prepared = prepare(os.environ)
    except StartupError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # message of an unknown error is not printed
        print(f"{PROG}: startup failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    _scrub_environment()
    _install_logging()

    settings = prepared.settings
    app = build_app(prepared)
    _LOG.info(
        "publishing %d of %d flows over %s",
        len(prepared.registry),
        prepared.loaded_count,
        settings.transport,
    )
    code = 0
    try:
        if settings.transport == "stdio":
            _run_stdio(app, settings)
        else:
            _run_http(app, settings)
    except KeyboardInterrupt:
        pass
    except SystemExit as exc:  # uvicorn exits with 1 when it cannot bind
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        _LOG.error("server stopped: %s", type(exc).__name__)
        code = 1
    finally:
        # No session may outlive the process (Requirement 16.3).
        try:
            asyncio.run(app.service.drain(0))
        except Exception:
            _LOG.error("final drain failed")
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
