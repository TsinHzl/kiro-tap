"""Tests for usage estimation injected during record building."""

from __future__ import annotations

from kiro_tap.proxy import _build_record, _has_token_count, _is_ai_request


def _build(
    resp_body: dict,
    *,
    path: str = "/v1/responses",
    headers: dict | None = None,
    status: int = 200,
) -> dict:
    return _build_record(
        "req_test",
        1,
        100,
        "POST",
        path,
        headers if headers is not None else {"content-type": "application/json"},
        {"model": "claude-haiku-5.5", "input": [{"role": "user", "content": "hello world " * 20}]},
        status,
        {"content-type": "application/json"},
        resp_body,
    )


def test_estimates_when_upstream_returns_only_credits() -> None:
    record = _build({"output": [{"content": "Hi there, how can I help?"}], "usage": {"kiro:credits": {"value": 0.04}}})
    usage = record["response"]["body"]["usage"]
    assert usage["estimated"] is True
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0


def test_estimates_from_content_when_output_absent() -> None:
    """AWS Event Stream responses expose `content`, not `output`/`choices`."""
    record = _build({"type": "message", "role": "assistant", "content": [{"type": "text", "text": "Hello there " * 30}]})
    usage = record["response"]["body"]["usage"]
    assert usage["estimated"] is True
    assert usage["output_tokens"] > 0


def test_upstream_usage_keys_are_preserved() -> None:
    record = _build(
        {
            "output": [{"content": "ok"}],
            "usage": {"kiro:credits": {"value": 0.04}, "kiro:context_usage_percentage": 12.5},
        }
    )
    usage = record["response"]["body"]["usage"]
    assert usage["kiro:credits"] == {"value": 0.04}
    assert usage["kiro:context_usage_percentage"] == 12.5
    assert usage["estimated"] is True


def test_real_usage_is_never_overwritten() -> None:
    original = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 3}
    record = _build({"output": [{"content": "text"}], "usage": dict(original)})
    usage = record["response"]["body"]["usage"]
    assert usage == original
    assert "estimated" not in usage


def test_provider_aliases_are_not_overwritten() -> None:
    """OpenAI-style keys are real counts and must survive untouched."""
    record = _build({"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    body = record["response"]["body"]
    assert "usage" in body
    assert body["usage"] == {"prompt_tokens": 100, "completion_tokens": 20}


def test_count_tokens_endpoint_is_never_estimated() -> None:
    record = _build({"input_tokens": 1234}, path="/v1/messages/count_tokens")
    assert "usage" not in record["response"]["body"]


def test_cache_only_metering_does_not_double_count_the_cache_prefix() -> None:
    """The request estimate already covers cached prefixes: net them out."""
    record = _build(
        {
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"credits_used": 0.04, "cache_read_input_tokens": 1200, "cache_creation_input_tokens": 300},
        }
    )
    usage = record["response"]["body"]["usage"]
    assert usage.get("input_tokens", 0) == 0
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True
    assert usage["cache_read_input_tokens"] == 1200


def test_reported_zero_input_is_not_overwritten() -> None:
    """Anthropic returns input_tokens: 0 on a full cache hit — that is a real value."""
    record = _build(
        {
            "output": [{"content": "ok"}],
            "usage": {"input_tokens": 0, "cache_read_input_tokens": 5000},
        }
    )
    usage = record["response"]["body"]["usage"]
    # The reported zero survives; only the missing output side is estimated.
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True


def test_flat_body_real_counts_survive_injection() -> None:
    """Flat (unwrapped) token counts must not be masked by the new usage dict."""
    record = _build({"input_tokens": 1000, "output": [{"content": "ok"}]})
    usage = record["response"]["body"]["usage"]
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True


def test_estimation_failure_keeps_raw_usage(monkeypatch) -> None:
    def _boom(_value: object) -> int:
        raise TypeError("boom")

    monkeypatch.setattr("kiro_tap.proxy.estimate_payload_tokens", _boom)
    credits = {"kiro:credits": {"value": 0.04}}
    record = _build({"output": [{"content": "x"}], "usage": dict(credits)})
    assert record["response"]["body"]["usage"] == credits


def test_partial_real_usage_only_fills_the_missing_field() -> None:
    record = _build({"output": [{"content": "ok"}], "usage": {"input_tokens": 42}})
    usage = record["response"]["body"]["usage"]
    assert usage["input_tokens"] == 42
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True


def test_error_status_is_not_estimated() -> None:
    record = _build({"error": {"message": "boom"}}, status=500)
    assert "usage" not in record["response"]["body"]


def test_error_snapshot_is_not_estimated() -> None:
    record = _build({"type": "error", "error": {"message": "boom"}, "usage": {}})
    assert "estimated" not in record["response"]["body"].get("usage", {})


def test_non_ai_path_is_not_estimated() -> None:
    record = _build({"configuration": {"a": True}}, path="/mcp")
    assert "usage" not in record["response"]["body"]


def test_aws_target_generate_assistant_response_is_ai_request() -> None:
    headers = {"x-amz-target": "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"}
    assert _is_ai_request("/", headers) is True


def test_control_plane_target_is_not_ai_request() -> None:
    headers = {"x-amz-target": "KiroRuntimeService.GetFeatureConfiguration"}
    assert _is_ai_request("/", headers) is False


def test_has_token_count_resolves_aliases() -> None:
    assert _has_token_count({"input_tokens": 1}, "input_tokens") is True
    assert _has_token_count({"prompt_tokens": 7}, "input_tokens") is True
    assert _has_token_count({"completion_tokens": 7}, "output_tokens") is True
    assert _has_token_count({"input_tokens": 0}, "input_tokens") is True
    assert _has_token_count({"cache_read_input_tokens": 900}, "input_tokens") is False
    assert _has_token_count({}, "input_tokens") is False
    assert _has_token_count(None, "input_tokens") is False
