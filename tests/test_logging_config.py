"""Tests for pulse.logging_config."""

from __future__ import annotations

import logging

import pulse.logging_config as logging_config


def test_get_logger_returns_child_of_pulse_logger() -> None:
    logger = logging_config.get_logger("pulse.some.module")

    assert logger.name == "pulse.some.module"


def test_get_logger_is_idempotent_about_handlers(monkeypatch) -> None:
    monkeypatch.setattr(logging_config, "_configured", False)

    logging_config.get_logger(__name__)
    handler_count = len(logging.getLogger(logging_config.PULSE_LOGGER_NAME).handlers)
    logging_config.get_logger(__name__)

    assert len(logging.getLogger(logging_config.PULSE_LOGGER_NAME).handlers) == handler_count


def test_configure_reads_level_from_env(monkeypatch) -> None:
    monkeypatch.setattr(logging_config, "_configured", False)
    monkeypatch.setenv("PULSE_LOG_LEVEL", "DEBUG")

    logging_config.get_logger(__name__)

    assert logging.getLogger(logging_config.PULSE_LOGGER_NAME).level == logging.DEBUG


def test_configure_defaults_to_info_for_invalid_level(monkeypatch) -> None:
    monkeypatch.setattr(logging_config, "_configured", False)
    monkeypatch.setenv("PULSE_LOG_LEVEL", "NOT_A_LEVEL")

    logging_config.get_logger(__name__)

    assert logging.getLogger(logging_config.PULSE_LOGGER_NAME).level == logging.INFO


def test_quiet_litellm_suppresses_noise_when_not_debug() -> None:
    import litellm

    logging_config._quiet_litellm(debug=False)

    assert litellm.suppress_debug_info is True
    assert logging.getLogger("LiteLLM").level == logging.WARNING


def test_quiet_litellm_allows_info_when_debug() -> None:
    import litellm

    logging_config._quiet_litellm(debug=True)

    assert litellm.suppress_debug_info is False
    assert logging.getLogger("LiteLLM").level == logging.INFO


def test_configure_calls_load_dotenv_before_reading_level(monkeypatch) -> None:
    """Regression: get_logger() runs at import time, before llm.py/tavily.py
    would otherwise call load_dotenv() — so a PULSE_LOG_LEVEL set only in
    .env (not exported in the shell) must still be picked up here. Mocks
    load_dotenv itself rather than relying on dotenv's file-discovery walk,
    which searches from the caller's file location, not the test's cwd."""
    monkeypatch.setattr(logging_config, "_configured", False)
    monkeypatch.delenv("PULSE_LOG_LEVEL", raising=False)

    def _fake_load_dotenv(*args, **kwargs) -> bool:
        monkeypatch.setenv("PULSE_LOG_LEVEL", "WARNING")
        return True

    monkeypatch.setattr(logging_config, "load_dotenv", _fake_load_dotenv)

    logging_config.get_logger(__name__)

    assert logging.getLogger(logging_config.PULSE_LOGGER_NAME).level == logging.WARNING
