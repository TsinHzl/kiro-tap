"""Tests for proxy path allowlist filtering."""

from __future__ import annotations

import pytest

from kiro_tap.proxy import _is_allowed_path


def test_kiro_api_path_allowed() -> None:
    assert _is_allowed_path("/generateAssistantResponse") is True


def test_mcp_path_allowed() -> None:
    assert _is_allowed_path("/mcp") is True


def test_anthropic_path_allowed() -> None:
    assert _is_allowed_path("/v1/messages") is True


def test_unknown_path_blocked() -> None:
    assert _is_allowed_path("/etc/passwd") is False


def test_extra_allowed_path() -> None:
    assert _is_allowed_path("/custom/api/endpoint", ("/custom/api",)) is True
    assert _is_allowed_path("/etc/passwd", ("/custom/api",)) is False
