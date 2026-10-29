"""Token usage normalization helpers."""

from __future__ import annotations

import math

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "input_tokens": ("input_tokens", "prompt_tokens", "promptTokenCount"),
    "output_tokens": ("output_tokens", "completion_tokens", "candidatesTokenCount"),
    "cache_read_input_tokens": (
        "cache_read_input_tokens",
        "cached_tokens",
        "cachedContentTokenCount",
        "input_tokens_details.cached_tokens",
        "prompt_tokens_details.cached_tokens",
    ),
    "cache_creation_input_tokens": ("cache_creation_input_tokens",),
}

_THINKING_ALIASES: tuple[str, ...] = (
    "thinking_tokens",
    "output_tokens_details.thinking_tokens",
    "output_tokens_details.reasoning_tokens",
    "completion_tokens_details.reasoning_tokens",
    "thoughtsTokenCount",
)


def _lookup(usage: dict, path: str) -> object:
    """Resolve a dotted path, returning None when a level is missing or non-dict."""
    current: object = usage
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int | float) and math.isfinite(value)


def normalize_usage(usage: object) -> dict:
    """Return usage with provider-specific token fields mapped to shared names."""
    if not isinstance(usage, dict):
        return {}

    normalized = dict(usage)

    for target, aliases in _FIELD_ALIASES.items():
        if _lookup(usage, target) is not None:
            continue
        for alias in aliases:
            value = _lookup(usage, alias)
            if value is not None:
                normalized[target] = value
                break

    thinking = None
    for alias in _THINKING_ALIASES:
        value = _lookup(usage, alias)
        if _is_finite_number(value):
            thinking = value
            break
    if thinking is None:
        normalized.pop("thinking_tokens", None)
    else:
        normalized["thinking_tokens"] = thinking

    return normalized
