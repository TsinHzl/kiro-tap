"""Tests for AWS Event Stream parser."""

from __future__ import annotations

import json
import struct
import zlib

import pytest

from kiro_tap.aws_event_stream import (  # noqa: E402
    AWSEventStreamReassembler,
    Frame,
    iter_frames,
    parse_frame,
)


# ---------------------------------------------------------------------------
# Helper: build a valid AWS Event Stream frame
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
    # total = prelude(12) + headers + payload + message_crc(4)
    total_length = 12 + header_length + len(payload) + 4

    prelude = struct.pack(">I", total_length) + struct.pack(">I", header_length)
    prelude_crc = zlib.crc32(prelude) & 0xFFFFFFFF
    prelude_with_crc = prelude + struct.pack(">I", prelude_crc)

    body = prelude_with_crc + headers_bytes + payload
    message_crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(">I", message_crc)


# ---------------------------------------------------------------------------
# parse_frame tests
# ---------------------------------------------------------------------------

def test_parse_frame_insufficient_data() -> None:
    assert parse_frame(b"\x00\x00\x00") is None
    assert parse_frame(b"") is None


def test_parse_frame_assistant_response_event() -> None:
    payload = json.dumps({"content": "Hello, world!"}).encode()
    frame_bytes = build_frame(
        {":message-type": "event", ":event-type": "assistantResponseEvent"},
        payload,
    )
    result = parse_frame(frame_bytes)
    assert result is not None
    frame, consumed = result
    assert consumed == len(frame_bytes)
    assert frame.message_type == "event"
    assert frame.event_type == "assistantResponseEvent"
    assert frame.payload_as_json() == {"content": "Hello, world!"}


def test_parse_frame_tool_use_event() -> None:
    payload = json.dumps({
        "toolUseId": "tool-123",
        "name": "read_file",
        "input": '{"path": "/tmp/f"}',
        "stop": False,
    }).encode()
    frame_bytes = build_frame(
        {":message-type": "event", ":event-type": "toolUseEvent"},
        payload,
    )
    result = parse_frame(frame_bytes)
    assert result is not None
    frame, _ = result
    assert frame.event_type == "toolUseEvent"
    data = frame.payload_as_json()
    assert data["toolUseId"] == "tool-123"
    assert data["name"] == "read_file"


def test_parse_frame_metering_event() -> None:
    payload = json.dumps({
        "usage": 42,
        "cacheReadInputTokens": 10,
        "cacheCreationInputTokens": 5,
    }).encode()
    frame_bytes = build_frame(
        {":message-type": "event", ":event-type": "meteringEvent"},
        payload,
    )
    result = parse_frame(frame_bytes)
    assert result is not None
    frame, _ = result
    assert frame.event_type == "meteringEvent"
    data = frame.payload_as_json()
    assert data["usage"] == 42


def test_parse_frame_error() -> None:
    payload = b"Service unavailable"
    frame_bytes = build_frame(
        {":message-type": "error", ":error-code": "ServiceUnavailable"},
        payload,
    )
    result = parse_frame(frame_bytes)
    assert result is not None
    frame, _ = result
    assert frame.message_type == "error"
    assert frame.error_code == "ServiceUnavailable"
    assert frame.payload_as_str() == "Service unavailable"


# ---------------------------------------------------------------------------
# AWSEventStreamReassembler tests
# ---------------------------------------------------------------------------

def test_reassembler_text_accumulation() -> None:
    r = AWSEventStreamReassembler()
    for chunk in ["Hello", ", ", "world!"]:
        frame_bytes = build_frame(
            {":message-type": "event", ":event-type": "assistantResponseEvent"},
            json.dumps({"content": chunk}).encode(),
        )
        r.feed_bytes(frame_bytes)
    result = r.reconstruct()
    assert result is not None
    assert result["content"][0]["text"] == "Hello, world!"


def test_reassembler_tool_use_accumulation() -> None:
    r = AWSEventStreamReassembler()
    # First frame: name + first input chunk
    r.feed_bytes(build_frame(
        {":message-type": "event", ":event-type": "toolUseEvent"},
        json.dumps({"toolUseId": "t1", "name": "bash", "input": '{"cmd":', "stop": False}).encode(),
    ))
    # Second frame: more input
    r.feed_bytes(build_frame(
        {":message-type": "event", ":event-type": "toolUseEvent"},
        json.dumps({"toolUseId": "t1", "name": "", "input": '"ls"}', "stop": True}).encode(),
    ))
    result = r.reconstruct()
    assert result is not None
    tool = result["content"][0]
    assert tool["type"] == "tool_use"
    assert tool["name"] == "bash"
    assert tool["input"] == {"cmd": "ls"}


def test_reassembler_metering() -> None:
    r = AWSEventStreamReassembler()
    r.feed_bytes(build_frame(
        {":message-type": "event", ":event-type": "meteringEvent"},
        json.dumps({"usage": 100, "cacheReadInputTokens": 20, "cacheCreationInputTokens": 5}).encode(),
    ))
    result = r.reconstruct()
    assert result is not None
    usage = result["usage"]
    assert usage["input_tokens"] == 100
    assert usage["cache_read_input_tokens"] == 20
    assert usage["cache_creation_input_tokens"] == 5


def test_reassembler_reconstruct_empty() -> None:
    r = AWSEventStreamReassembler()
    assert r.reconstruct() is None


def test_reassembler_store_events_false() -> None:
    r = AWSEventStreamReassembler(store_events=False)
    r.feed_bytes(build_frame(
        {":message-type": "event", ":event-type": "assistantResponseEvent"},
        json.dumps({"content": "hi"}).encode(),
    ))
    assert r.events == []
    result = r.reconstruct()
    assert result is not None
    assert result["content"][0]["text"] == "hi"


def test_iter_frames() -> None:
    frames_bytes = b""
    for text in ["one", "two", "three"]:
        frames_bytes += build_frame(
            {":message-type": "event", ":event-type": "assistantResponseEvent"},
            json.dumps({"content": text}).encode(),
        )
    frames = list(iter_frames(frames_bytes))
    assert len(frames) == 3
    texts = [f.payload_as_json()["content"] for f in frames]
    assert texts == ["one", "two", "three"]


def test_reassembler_feed_bytes_chunked() -> None:
    payload = json.dumps({"content": "chunked"}).encode()
    frame_bytes = build_frame(
        {":message-type": "event", ":event-type": "assistantResponseEvent"},
        payload,
    )
    r = AWSEventStreamReassembler()
    # Feed in 5-byte chunks
    for i in range(0, len(frame_bytes), 5):
        r.feed_bytes(frame_bytes[i:i + 5])
    result = r.reconstruct()
    assert result is not None
    assert result["content"][0]["text"] == "chunked"
