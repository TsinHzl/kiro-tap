"""Regression tests for fix-audit-batch-3 security and robustness fixes."""

from __future__ import annotations

import json
import struct
import zlib

import pytest

# ---------------------------------------------------------------------------
# S1: open-proxy 403 block
# ---------------------------------------------------------------------------

class TestS1OpenProxyBlock:
    """forward_proxy._handle_plain_proxy must reject absolute-URL requests."""

    def _make_server(self):
        """Build a minimal ForwardProxyServer with no local reverse target."""
        from unittest.mock import AsyncMock, MagicMock

        from kiro_tap.forward_proxy import ForwardProxyServer

        ca = MagicMock()
        writer = MagicMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        session = MagicMock()
        trace_writer = MagicMock()
        trace_writer.write = AsyncMock()

        server = ForwardProxyServer.__new__(ForwardProxyServer)
        server._ca = ca
        server._writer = trace_writer
        server._session = session
        server._local_reverse_target = None
        server._local_reverse_allowed_path_prefixes = ()
        server._store_stream_events = False
        server._intercept_hostname = None
        server._client_tasks = set()
        server._client_writers = set()
        return server

    @pytest.mark.asyncio
    async def test_absolute_url_returns_403(self):
        """GET http://example.com/ must be blocked with 403."""
        from unittest.mock import AsyncMock, MagicMock, patch

        server = self._make_server()

        writer = MagicMock()
        written = []
        writer.write = lambda data: written.append(data)
        writer.drain = AsyncMock()

        reader = MagicMock()
        reader.readline = AsyncMock(return_value=b"\r\n")

        with patch("kiro_tap.forward_proxy._read_http_body", new=AsyncMock(return_value=b"")):
            await server._handle_plain_proxy(
                "GET", "http://example.com/path", "HTTP/1.1", reader, writer
            )

        combined = b"".join(written)
        assert b"403" in combined
        assert b"Forbidden" in combined

    @pytest.mark.asyncio
    async def test_schemeless_path_not_blocked(self):
        """A scheme-less path (local reverse proxy) must not be blocked."""
        from unittest.mock import AsyncMock, MagicMock, patch

        server = self._make_server()
        server._local_reverse_target = "http://localhost:8080"
        server._local_reverse_allowed_path_prefixes = ("/api",)

        writer = MagicMock()
        written = []
        writer.write = lambda data: written.append(data)
        writer.drain = AsyncMock()

        reader = MagicMock()
        reader.readline = AsyncMock(return_value=b"\r\n")

        forwarded_calls = []

        async def fake_forward(method, path, headers, body, url, w):
            forwarded_calls.append(url)

        server._forward_and_record = fake_forward

        with patch("kiro_tap.forward_proxy._read_http_body", new=AsyncMock(return_value=b"")):
            await server._handle_plain_proxy(
                "GET", "/api/test", "HTTP/1.1", reader, writer
            )

        assert len(forwarded_calls) == 1
        assert "403" not in b"".join(written).decode(errors="replace")


# ---------------------------------------------------------------------------
# S3: same-origin check (three states)
# ---------------------------------------------------------------------------

class TestS3SameOriginCheck:
    """_is_same_origin must correctly classify requests."""

    def _make_request(self, headers: dict) -> object:
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers = headers
        return req

    def test_cross_site_sec_fetch_blocked(self):
        from kiro_tap.live import _is_same_origin
        req = self._make_request({"Sec-Fetch-Site": "cross-site", "Host": "127.0.0.1:19528"})
        assert _is_same_origin(req) is False

    def test_same_origin_sec_fetch_allowed(self):
        from kiro_tap.live import _is_same_origin
        req = self._make_request({"Sec-Fetch-Site": "same-origin", "Host": "127.0.0.1:19528"})
        assert _is_same_origin(req) is True

    def test_no_origin_no_sec_fetch_allowed(self):
        """Non-browser clients (curl, CLI) send no Origin/Sec-Fetch-Site — must be allowed."""
        from kiro_tap.live import _is_same_origin
        req = self._make_request({"Host": "127.0.0.1:19528"})
        assert _is_same_origin(req) is True

    def test_origin_matches_host_allowed(self):
        from kiro_tap.live import _is_same_origin
        req = self._make_request({
            "Origin": "http://127.0.0.1:19528",
            "Host": "127.0.0.1:19528",
        })
        assert _is_same_origin(req) is True

    def test_origin_mismatches_host_blocked(self):
        from kiro_tap.live import _is_same_origin
        req = self._make_request({
            "Origin": "http://evil.example.com",
            "Host": "127.0.0.1:19528",
        })
        assert _is_same_origin(req) is False


# ---------------------------------------------------------------------------
# B1: SSE index upper-bound guard
# ---------------------------------------------------------------------------

class TestB1SSEIndexGuard:
    """SSEReassembler must not OOM on a huge content_block_start index."""

    def _make_event_bytes(self, event_type: str, data: dict) -> bytes:
        data_str = json.dumps(data)
        return f"event: {event_type}\ndata: {data_str}\n\n".encode()

    def test_huge_index_does_not_allocate(self):
        from kiro_tap.sse import _MAX_CONTENT_INDEX, SSEReassembler

        r = SSEReassembler()
        # Prime with a message_start so _snapshot is initialised
        r.feed_bytes(self._make_event_bytes("message_start", {
            "message": {"id": "x", "type": "message", "role": "assistant",
                        "content": [], "model": "claude-3", "usage": {}}
        }))

        # Send a content_block_start with index way beyond the limit
        r.feed_bytes(self._make_event_bytes("content_block_start", {
            "index": _MAX_CONTENT_INDEX + 1,
            "content_block": {"type": "text", "text": ""},
        }))

        # The content list must not have grown to accommodate the huge index
        content = r._snapshot.get("content", []) if r._snapshot else []
        assert len(content) <= _MAX_CONTENT_INDEX

    def test_normal_index_still_works(self):
        from kiro_tap.sse import SSEReassembler

        r = SSEReassembler()
        r.feed_bytes(self._make_event_bytes("message_start", {
            "message": {"id": "x", "type": "message", "role": "assistant",
                        "content": [], "model": "claude-3", "usage": {}}
        }))
        r.feed_bytes(self._make_event_bytes("content_block_start", {
            "index": 0,
            "content_block": {"type": "text", "text": "hello"},
        }))
        assert r._snapshot is not None
        assert len(r._snapshot.get("content", [])) == 1


# ---------------------------------------------------------------------------
# B3: AWS EventStream non-numeric cache token fields
# ---------------------------------------------------------------------------

def _encode_header(name: str, value: str) -> bytes:
    name_bytes = name.encode("utf-8")
    value_bytes = value.encode("utf-8")
    return (
        bytes([len(name_bytes)])
        + name_bytes
        + bytes([7])  # value_type = string
        + struct.pack(">H", len(value_bytes))
        + value_bytes
    )


def build_frame(headers: dict[str, str], payload: bytes) -> bytes:
    headers_bytes = b"".join(_encode_header(k, v) for k, v in headers.items())
    header_length = len(headers_bytes)
    total_length = 12 + header_length + len(payload) + 4
    prelude = struct.pack(">II", total_length, header_length)
    prelude_crc = zlib.crc32(prelude) & 0xFFFFFFFF
    prelude_with_crc = prelude + struct.pack(">I", prelude_crc)
    body = prelude_with_crc + headers_bytes + payload
    msg_crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(">I", msg_crc)


class TestB3CacheTokenGuard:
    """AWSEventStreamReassembler must not crash on non-numeric cache token fields."""

    def _make_metering_frame(self, extra: dict) -> bytes:
        payload = json.dumps({"usage": 10, **extra}).encode("utf-8")
        return build_frame({":event-type": "meteringEvent", ":content-type": "application/json"}, payload)

    def test_string_cache_read_does_not_crash(self):
        from kiro_tap.aws_event_stream import AWSEventStreamReassembler
        r = AWSEventStreamReassembler()
        frame = self._make_metering_frame({"cacheReadInputTokens": "not-a-number"})
        # Must not raise
        r.feed_bytes(frame)
        assert r._metering.get("cache_read_input_tokens", 0) == 0

    def test_dict_cache_create_does_not_crash(self):
        from kiro_tap.aws_event_stream import AWSEventStreamReassembler
        r = AWSEventStreamReassembler()
        frame = self._make_metering_frame({"cacheCreationInputTokens": {"nested": "object"}})
        r.feed_bytes(frame)
        assert r._metering.get("cache_creation_input_tokens", 0) == 0

    def test_valid_numeric_cache_tokens_parsed(self):
        from kiro_tap.aws_event_stream import AWSEventStreamReassembler
        r = AWSEventStreamReassembler()
        frame = self._make_metering_frame({"cacheReadInputTokens": 42, "cacheCreationInputTokens": 7})
        r.feed_bytes(frame)
        assert r._metering.get("cache_read_input_tokens") == 42
        assert r._metering.get("cache_creation_input_tokens") == 7
