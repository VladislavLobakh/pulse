"""Central stdlib logging setup for PULSE.

Reads `PULSE_LOG_LEVEL` (default INFO) once and configures the `pulse`
logger tree with a single stderr handler. Also quiets LiteLLM's own noisy
default output (a raw "Provider List" print plus its own INFO/DEBUG logger)
unless the user explicitly asked for DEBUG output.

No import-time network calls — this loads `.env` (if present) and touches
only the logging module.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

PULSE_LOGGER_NAME = "pulse"

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    # Runs at import time, before any module calls load_dotenv() itself —
    # without this, PULSE_LOG_LEVEL/PULSE_VERBOSE set only in .env are invisible.
    load_dotenv()

    level = logging.getLevelName(os.getenv("PULSE_LOG_LEVEL", "INFO").upper())
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger(PULSE_LOGGER_NAME)
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()  # stderr by default
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
        root.addHandler(handler)
    root.propagate = False

    _quiet_litellm(debug=level <= logging.DEBUG)


def _quiet_litellm(*, debug: bool) -> None:
    # LiteLLM prints a raw "Provider List" banner (not via logging) on certain
    # errors unless this flag is set, and runs its own "LiteLLM"/"LiteLLM
    # Router"/"LiteLLM Proxy" loggers that are chatty at INFO by default.
    try:
        import litellm

        litellm.suppress_debug_info = not debug
    except ImportError:
        pass

    litellm_level = logging.INFO if debug else logging.WARNING
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
        logging.getLogger(name).setLevel(litellm_level)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the `pulse` tree, configuring it on first use."""
    _configure()
    return logging.getLogger(name)
