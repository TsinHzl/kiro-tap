"""Tests for the heuristic token estimator used when upstreams omit usage."""

from __future__ import annotations

from kiro_tap.token_estimate import estimate_payload_tokens, estimate_text_tokens


def test_estimate_empty_text_is_zero() -> None:
    assert estimate_text_tokens("") == 0


def test_estimate_ascii_roughly_four_chars_per_token() -> None:
    text = "The quick brown fox jumps over the lazy dog." * 10  # 450 chars
    tokens = estimate_text_tokens(text)
    assert 100 <= tokens <= 130


def test_estimate_cjk_is_denser_than_ascii() -> None:
    ascii_text = "a" * 100
    cjk_text = "好" * 100
    assert estimate_text_tokens(cjk_text) > estimate_text_tokens(ascii_text)


def test_estimate_mixed_language() -> None:
    mixed = "hello world " * 20 + "你好世界" * 20
    tokens = estimate_text_tokens(mixed)
    assert tokens > 0


def test_estimate_payload_walks_nested_strings() -> None:
    payload = {
        "model": "claude-haiku-5.5",
        "input": [
            {"role": "user", "content": "Explain this code please." * 5},
            {"role": "assistant", "content": "Sure, it does X."},
        ],
    }
    assert estimate_payload_tokens(payload) > 20


def test_estimate_payload_handles_none_and_scalars() -> None:
    assert estimate_payload_tokens(None) == 0
    assert estimate_payload_tokens(42) > 0


def test_estimate_payload_empty_structure() -> None:
    assert estimate_payload_tokens({}) == 0
    assert estimate_payload_tokens([]) == 0
