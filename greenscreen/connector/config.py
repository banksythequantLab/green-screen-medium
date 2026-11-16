from __future__ import annotations

"""ConnectorConfig: runtime configuration for the tn3270-connector."""

import os
from dataclasses import dataclass, field

from greenscreen.connector.exceptions import ConfigurationError

_UNSET_PORT = -1  # sentinel: user did not supply a port argument


@dataclass
class ConnectorConfig:
    """All runtime parameters for one Connector instance.

    Fields with environment-variable fallbacks:
      binary  ← GS_S3270_BINARY
      host    ← GS_HOST
      port    ← GS_PORT  (integer)

    Fields with built-in defaults (no env-var fallback):
      model           = "3279-2"
      default_timeout = 30.0

    Validation happens in __post_init__. ConfigurationError is raised at
    construction time before any subprocess is started.
    """

    binary:          str   = ""         # path to s3270 / ws3270 binary
    host:            str   = ""         # TN3270 host address
    port:            int   = _UNSET_PORT  # TN3270 port; -1 means "use env/default"
    model:           str   = "3279-2"   # terminal model string
    default_timeout: float = 30.0       # seconds; range 1.0–3600.0

    def __post_init__(self) -> None:
        # ── Env-var fallbacks ──────────────────────────────────────────
        if not self.binary:
            self.binary = os.environ.get("GS_S3270_BINARY", "")
        if not self.host:
            self.host = os.environ.get("GS_HOST", "")
        if self.port == _UNSET_PORT:
            env_port = os.environ.get("GS_PORT", "")
            if env_port:
                try:
                    self.port = int(env_port)
                except ValueError:
                    raise ConfigurationError(
                        f"GS_PORT environment variable is not a valid integer: {env_port!r}",
                        parameter_name="port",
                    )
            else:
                self.port = 23  # default port when neither arg nor env var is set

        self._validate()

    def _validate(self) -> None:
        """Raise ConfigurationError for missing or out-of-range fields."""
        if not self.binary:
            raise ConfigurationError(
                "s3270 binary path is required. Set the 'binary' field or "
                "the GS_S3270_BINARY environment variable.",
                parameter_name="binary",
            )
        if not self.host:
            raise ConfigurationError(
                "Host address is required. Set the 'host' field or "
                "the GS_HOST environment variable.",
                parameter_name="host",
            )
        if not (1 <= self.port <= 65535):
            raise ConfigurationError(
                f"Port must be in range 1–65535, got {self.port}.",
                parameter_name="port",
            )
        if not self.model:
            raise ConfigurationError(
                "Terminal model string must not be empty.",
                parameter_name="model",
            )
        if not (1.0 <= self.default_timeout <= 3600.0):
            raise ConfigurationError(
                f"default_timeout must be in range 1.0–3600.0, got {self.default_timeout}.",
                parameter_name="default_timeout",
            )
