"""Runtime helpers for configuring logging and DSPy based on project settings."""

from __future__ import annotations

import logging
from typing import Any

import dspy

from app.baml_adapter import BAMLAdapter
from app.config.settings import Settings, get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"


class _MissingAdapter:
    """Sentinel for detecting whether an adapter was provided."""


_MISSING = _MissingAdapter()


def _resolve_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


def configure_logging(
    settings: Settings | None = None,
    *,
    level: str | None = None,
    force: bool = False,
) -> None:
    """Configure the root logger using project defaults.

    Args:
        settings: Optional settings instance. Defaults to ``get_settings()``.
        level: Optional override for the log level.
        force: Whether to force reconfiguration even if logging is already set up.
    """

    settings = settings or get_settings()
    effective_level = level or settings.log_level
    logging.basicConfig(level=_resolve_level(effective_level), format=_LOG_FORMAT, force=force)


def build_lm(
    settings: Settings | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    cache: bool | None = None,
) -> dspy.LM:
    """Construct a DSPy language model instance using the given settings."""

    settings = settings or get_settings()
    key = api_key if api_key is not None else settings.dspy_api_key
    if not key:
        raise RuntimeError(
            "DSPy API key is not configured; set DSPY_API_KEY / GEMINI_API_KEY or update your settings file."
        )

    return dspy.LM(
        model=model or settings.dspy_model,
        api_key=key,
        temperature=settings.dspy_temperature if temperature is None else temperature,
        max_tokens=settings.dspy_max_tokens if max_tokens is None else max_tokens,
        cache=settings.dspy_cache if cache is None else cache,
    )


def configure_dspy(
    settings: Settings | None = None,
    *,
    adapter: Any | None = _MISSING,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    cache: bool | None = None,
) -> None:
    """Configure DSPy with a language model and optional adapter."""

    settings = settings or get_settings()
    lm = build_lm(settings, model=model, temperature=temperature, max_tokens=max_tokens, cache=cache)
    kwargs: dict[str, Any] = {"lm": lm}

    selected_adapter = BAMLAdapter()
    kwargs["adapter"] = selected_adapter
    dspy.configure(**kwargs)

