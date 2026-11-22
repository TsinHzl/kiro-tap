"""Heuristic token estimation for responses that omit usage counters.

Some upstreams (notably Kiro CLI 2.7.0+ on ``/v1/responses``) return only
credits and a context-usage percentage — no ``input_tokens`` / ``output_tokens``.
For those we fall back to a cheap character-based estimate.

The heuristic intentionally avoids a real BPE tokenizer (tiktoken): its
encoding tables are ~1.9 MB and are downloaded on first use, which would stall
the proxy's capture path. The constants below are calibrated so that ASCII
prose lands close to ``len / 4`` and CJK close to ``len / 1.5``.
"""

from __future__ import annotations

import json
import re

# Average characters per token. ASCII/Latin text clusters near 4; CJK text
# (Chinese/Japanese/Korean, where one character is usually ≥1 token) near 1.5.
_ASCII_CHARS_PER_TOKEN = 4.0
_CJK_CHARS_PER_TOKEN = 1.5

# Ranges covering CJK ideographs, kana, Hangul and CJK punctuation.
_CJK_RE = re.compile(
    r"[　-〿぀-ヿ㐀-䶿一-鿿"
    r"가-힯＀-￯]"
)


def estimate_text_tokens(text: str) -> int:
    """Estimate token count for ``text`` using cached regex character classes."""
    if not text:
        return 0
    cjk = sum(1 for _ in _CJK_RE.finditer(text))
    ascii_like = len(text) - cjk
    tokens = ascii_like / _ASCII_CHARS_PER_TOKEN + cjk / _CJK_CHARS_PER_TOKEN
    return max(1, round(tokens))


def _iter_strings(value: object):
    """Yield every string contained in a nested JSON-like structure.

    Iterative rather than recursive: payload depth is client-controlled, and a
    deep nesting would otherwise raise RecursionError on the proxy's request
    path.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def estimate_payload_tokens(value: object) -> int:
    """Estimate tokens for all string content in a JSON-like payload.

    Non-string scalars are re-serialised so numbers/booleans still contribute
    a token or two; ``None`` is skipped.
    """
    total = 0
    for text in _iter_strings(value):
        total += estimate_text_tokens(text)
    if total == 0 and value is not None and not isinstance(value, (str, dict, list)):
        total = estimate_text_tokens(json.dumps(value, ensure_ascii=False))
    return total
