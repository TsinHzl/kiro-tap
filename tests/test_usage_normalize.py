"""Tests for provider token usage normalization."""

from __future__ import annotations

import math

from kiro_tap.usage import normalize_usage


def test_anthropic_thinking() -> None:
    result = normalize_usage({
        "input_tokens": 100,
        "output_tokens": 50,
        "output_tokens_details": {"thinking_tokens": 20},
    })
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 50
    assert result["thinking_tokens"] == 20
    assert "cache_read_input_tokens" not in result
    assert "cache_creation_input_tokens" not in result


def test_openai_chat_reasoning() -> None:
    result = normalize_usage({
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "completion_tokens_details": {"reasoning_tokens": 4},
    })
    assert result["input_tokens"] == 30
    assert result["output_tokens"] == 12
    assert result["thinking_tokens"] == 4


def test_openai_responses_reasoning() -> None:
    result = normalize_usage({
        "input_tokens": 30,
        "output_tokens": 12,
        "output_tokens_details": {"reasoning_tokens": 3},
    })
    assert result["thinking_tokens"] == 3


def test_gemini_thoughts() -> None:
    result = normalize_usage({
        "promptTokenCount": 10,
        "candidatesTokenCount": 100,
        "thoughtsTokenCount": 50,
    })
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 100
    assert result["thinking_tokens"] == 50


def test_thinking_priority_when_multiple_sources() -> None:
    result = normalize_usage({
        "output_tokens_details": {"thinking_tokens": 7, "reasoning_tokens": 9},
        "thoughtsTokenCount": 11,
    })
    assert result["thinking_tokens"] == 7


def test_direct_thinking_precedes_nested_sources() -> None:
    result = normalize_usage({
        "thinking_tokens": 5,
        "output_tokens_details": {"thinking_tokens": 20},
    })
    assert result["thinking_tokens"] == 5


def test_invalid_direct_thinking_falls_back() -> None:
    result = normalize_usage({
        "thinking_tokens": "abc",
        "output_tokens_details": {"reasoning_tokens": 3},
    })
    assert result["thinking_tokens"] == 3


def test_invalid_thinking_omits_key() -> None:
    for value in ("abc", True, [], {}, None, math.nan, math.inf):
        result = normalize_usage({
            "input_tokens": 10,
            "output_tokens": 5,
            "thinking_tokens": value,
        })
        assert "thinking_tokens" not in result
        assert result["input_tokens"] == 10
        assert result["output_tokens"] == 5


def test_nested_container_null_or_non_dict_skipped() -> None:
    result = normalize_usage({
        "output_tokens_details": None,
        "completion_tokens_details": "x",
        "thoughtsTokenCount": 5,
    })
    assert result["thinking_tokens"] == 5


def test_zero_thinking_is_kept() -> None:
    assert normalize_usage({"thinking_tokens": 0})["thinking_tokens"] == 0


def test_null_target_falls_back_to_alias() -> None:
    result = normalize_usage({"input_tokens": None, "prompt_tokens": 50})
    assert result["input_tokens"] == 50


def test_null_target_without_alias_keeps_null() -> None:
    result = normalize_usage({"cache_creation_input_tokens": None})
    assert "cache_creation_input_tokens" in result
    assert result["cache_creation_input_tokens"] is None


def test_cache_read_fallbacks() -> None:
    assert normalize_usage({"cached_tokens": 7})["cache_read_input_tokens"] == 7
    assert normalize_usage({"cachedContentTokenCount": 8})["cache_read_input_tokens"] == 8
    assert normalize_usage({"input_tokens_details": {"cached_tokens": 9}})["cache_read_input_tokens"] == 9
    assert normalize_usage({"prompt_tokens_details": {"cached_tokens": 10}})["cache_read_input_tokens"] == 10


def test_zero_is_present_and_not_overridden() -> None:
    result = normalize_usage({"input_tokens": 0, "prompt_tokens": 50})
    assert result["input_tokens"] == 0


def test_missing_fields_stay_missing() -> None:
    result = normalize_usage({"input_tokens": 10})
    assert "output_tokens" not in result
    assert "thinking_tokens" not in result


def test_unmapped_keys_preserved() -> None:
    result = normalize_usage({"input_tokens": 10, "custom_field": "keep", "service_tier": "standard"})
    assert result["custom_field"] == "keep"
    assert result["service_tier"] == "standard"


def test_non_dict_input() -> None:
    for value in (None, "text", [1, 2], 42, ("a",)):
        assert normalize_usage(value) == {}
