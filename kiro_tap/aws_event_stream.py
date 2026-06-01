"""AWS Event Stream parser for Kiro API responses.

Kiro CLI communicates with the AWS CodeWhisperer/Q API using the AWS Event Stream
binary framing protocol. This module parses those binary frames and reconstructs
the full response from streaming events.

Frame format:
    ┌──────────────┬──────────────┬──────────────┬──────────┬──────────┬───────────┐
    │ Total Length │ Header Length│ Prelude CRC  │ Headers  │ Payload  │ Msg CRC   │
    │   (4 bytes)  │   (4 bytes)  │   (4 bytes)  │ (var)    │ (var)    │ (4 bytes) │
    └──────────────┴──────────────┴──────────────┴──────────┴──────────┴───────────┘

Event types emitted by Kiro:
    - assistantResponseEvent: streaming text content
    - toolUseEvent: tool call (name, toolUseId, input, stop)
    - meteringEvent: token usage (usage, cacheReadInputTokens, cacheCreationInputTokens)
    - contextUsageEvent: context window usage percentage
    - codeReferenceEvent: open-source license reference
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass, field
from typing import Iterator

# ---------------------------------------------------------------------------
# CRC32 (ISO-HDLC / Ethernet / ZIP standard, same as AWS Event Stream)
# ---------------------------------------------------------------------------

def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Header value types
# ---------------------------------------------------------------------------

_HEADER_TYPE_BOOL_TRUE = 0
_HEADER_TYPE_BOOL_FALSE = 1
_HEADER_TYPE_BYTE = 2
_HEADER_TYPE_SHORT = 3
_HEADER_TYPE_INT = 4
_HEADER_TYPE_LONG = 5
_HEADER_TYPE_BYTES = 6
_HEADER_TYPE_STRING = 7
_HEADER_TYPE_TIMESTAMP = 8
_HEADER_TYPE_UUID = 9

PRELUDE_SIZE = 12  # total_len(4) + header_len(4) + prelude_crc(4)
MIN_MESSAGE_SIZE = PRELUDE_SIZE + 4  # + message_crc(4)
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MB
# Maximum reassembly buffer size. Prevents OOM if the stream never delivers a
# complete frame (e.g. malformed or adversarial input).
_MAX_BUF_BYTES = 64 * 1024 * 1024  # 64 MB


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------

@dataclass
class Frame:
    headers: dict[str, object]
    payload: bytes

    @property
    def message_type(self) -> str:
        return self.headers.get(":message-type", "event")  # type: ignore[return-value]

    @property
    def event_type(self) -> str:
        return self.headers.get(":event-type", "unknown")  # type: ignore[return-value]

    @property
    def exception_type(self) -> str:
        return self.headers.get(":exception-type", "UnknownException")  # type: ignore[return-value]

    @property
    def error_code(self) -> str:
        return self.headers.get(":error-code", "UnknownError")  # type: ignore[return-value]

    def payload_as_json(self) -> object:
        try:
            return json.loads(self.payload)
        except (json.JSONDecodeError, ValueError):
            return self.payload.decode("utf-8", errors="replace")

    def payload_as_str(self) -> str:
        return self.payload.decode("utf-8", errors="replace")


def _parse_header_value(data: bytes, offset: int) -> tuple[object, int]:
    """Parse one header value starting at offset. Returns (value, new_offset)."""
    if offset >= len(data):
        raise ValueError("Truncated header value type")
    vtype = data[offset]
    offset += 1

    if vtype == _HEADER_TYPE_BOOL_TRUE:
        return True, offset
    if vtype == _HEADER_TYPE_BOOL_FALSE:
        return False, offset
    if vtype == _HEADER_TYPE_BYTE:
        if offset >= len(data):
            raise ValueError("Truncated byte header")
        val = struct.unpack_from(">b", data, offset)[0]
        return val, offset + 1
    if vtype == _HEADER_TYPE_SHORT:
        if offset + 2 > len(data):
            raise ValueError("Truncated short header")
        val = struct.unpack_from(">h", data, offset)[0]
        return val, offset + 2
    if vtype == _HEADER_TYPE_INT:
        if offset + 4 > len(data):
            raise ValueError("Truncated int header")
        val = struct.unpack_from(">i", data, offset)[0]
        return val, offset + 4
    if vtype == _HEADER_TYPE_LONG:
        if offset + 8 > len(data):
            raise ValueError("Truncated long header")
        val = struct.unpack_from(">q", data, offset)[0]
        return val, offset + 8
    if vtype == _HEADER_TYPE_BYTES:
        if offset + 2 > len(data):
            raise ValueError("Truncated bytes header length")
        length = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        if offset + length > len(data):
            raise ValueError("Truncated bytes header value")
        val = data[offset:offset + length]
        return val, offset + length
    if vtype == _HEADER_TYPE_STRING:
        if offset + 2 > len(data):
            raise ValueError("Truncated string header length")
        length = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        if offset + length > len(data):
            raise ValueError("Truncated string header value")
        val = data[offset:offset + length].decode("utf-8", errors="replace")
        return val, offset + length
    if vtype == _HEADER_TYPE_TIMESTAMP:
        if offset + 8 > len(data):
            raise ValueError("Truncated timestamp header")
        val = struct.unpack_from(">q", data, offset)[0]
        return val, offset + 8
    if vtype == _HEADER_TYPE_UUID:
        if offset + 16 > len(data):
            raise ValueError("Truncated UUID header")
        val = data[offset:offset + 16]
        return val, offset + 16
    raise ValueError(f"Unknown header value type: {vtype}")


def _parse_headers(data: bytes) -> dict[str, object]:
    """Parse all headers from the headers section bytes."""
    headers: dict[str, object] = {}
    offset = 0
    while offset < len(data):
        if offset >= len(data):
            break
        name_len = data[offset]
        offset += 1
        if offset + name_len > len(data):
            break
        name = data[offset:offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        value, offset = _parse_header_value(data, offset)
        headers[name] = value
    return headers


def parse_frame(buffer: bytes) -> tuple[Frame, int] | None:
    """Try to parse one complete frame from buffer.

    Returns (frame, bytes_consumed) or None if buffer is incomplete.
    Raises ValueError on malformed data.
    """
    if len(buffer) < PRELUDE_SIZE:
        return None

    total_length = struct.unpack_from(">I", buffer, 0)[0]
    header_length = struct.unpack_from(">I", buffer, 4)[0]
    prelude_crc = struct.unpack_from(">I", buffer, 8)[0]

    if total_length < MIN_MESSAGE_SIZE:
        raise ValueError(f"Frame too small: {total_length} < {MIN_MESSAGE_SIZE}")
    if total_length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Frame too large: {total_length} > {MAX_MESSAGE_SIZE}")

    if len(buffer) < total_length:
        return None

    actual_prelude_crc = _crc32(buffer[:8])
    if actual_prelude_crc != prelude_crc:
        raise ValueError(f"Prelude CRC mismatch: expected {prelude_crc:#010x}, got {actual_prelude_crc:#010x}")

    message_crc = struct.unpack_from(">I", buffer, total_length - 4)[0]
    actual_message_crc = _crc32(buffer[:total_length - 4])
    if actual_message_crc != message_crc:
        raise ValueError(f"Message CRC mismatch: expected {message_crc:#010x}, got {actual_message_crc:#010x}")

    headers_start = PRELUDE_SIZE
    headers_end = headers_start + header_length
    if headers_end > total_length - 4:
        raise ValueError("Header length exceeds message boundary")

    headers = _parse_headers(buffer[headers_start:headers_end])
    payload = buffer[headers_end:total_length - 4]

    return Frame(headers=headers, payload=payload), total_length


def iter_frames(data: bytes) -> Iterator[Frame]:
    """Yield all complete frames from a byte buffer, skipping parse errors."""
    offset = 0
    while offset < len(data):
        try:
            result = parse_frame(data[offset:])
        except ValueError:
            # Skip one byte and try to resync
            offset += 1
            continue
        if result is None:
            break
        frame, consumed = result
        yield frame
        offset += consumed


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVENT_TYPE_ASSISTANT_RESPONSE = "assistantResponseEvent"
EVENT_TYPE_TOOL_USE = "toolUseEvent"
EVENT_TYPE_METERING = "meteringEvent"
EVENT_TYPE_CONTEXT_USAGE = "contextUsageEvent"
EVENT_TYPE_CODE_REFERENCE = "codeReferenceEvent"


# ---------------------------------------------------------------------------
# AWSEventStreamReassembler
# ---------------------------------------------------------------------------

@dataclass
class _ToolUseAccumulator:
    name: str = ""
    tool_use_id: str = ""
    input_parts: list[str] = field(default_factory=list)
    complete: bool = False

    def to_dict(self) -> dict:
        input_str = "".join(self.input_parts)
        try:
            input_parsed = json.loads(input_str) if input_str else {}
        except (json.JSONDecodeError, ValueError):
            input_parsed = input_str
        return {
            "type": "tool_use",
            "id": self.tool_use_id,
            "name": self.name,
            "input": input_parsed,
        }


class AWSEventStreamReassembler:
    """Parse raw AWS Event Stream bytes from Kiro API and reconstruct the full response.

    Kiro uses AWS Event Stream binary framing (not SSE). This class accumulates
    streaming frames and builds a response object compatible with the trace viewer.
    """

    def __init__(self, *, store_events: bool = True):
        self._store_events = store_events
        self.events: list[dict] = []
        self._buf = b""
        self._text_parts: list[str] = []
        self._tool_uses: dict[str, _ToolUseAccumulator] = {}
        self._tool_use_order: list[str] = []
        self._metering: dict = {}
        self._context_usage: float | None = None
        self._snapshot: dict | None = None
        self._error: dict | None = None

    def feed_bytes(self, chunk: bytes) -> None:
        self._buf += chunk
        if len(self._buf) > _MAX_BUF_BYTES:
            import logging
            logging.getLogger("kiro-tap").warning(
                "AWSEventStreamReassembler: buffer exceeded %d bytes, resetting (stream may be malformed)",
                _MAX_BUF_BYTES,
            )
            self._buf = b""
            return
        self._drain()

    def _drain(self) -> None:
        offset = 0
        while offset < len(self._buf):
            try:
                result = parse_frame(self._buf[offset:])
            except ValueError:
                offset += 1
                continue
            if result is None:
                break
            frame, consumed = result
            try:
                self._process_frame(frame)
            except Exception:
                pass
            offset += consumed
        self._buf = self._buf[offset:]

    def _process_frame(self, frame: Frame) -> None:
        msg_type = frame.message_type
        if msg_type == "event":
            self._process_event(frame)
        elif msg_type == "error":
            self._error = {
                "error_code": frame.error_code,
                "message": frame.payload_as_str(),
            }
            if self._store_events:
                self.events.append({"event": "error", "data": self._error})
        elif msg_type == "exception":
            self._error = {
                "exception_type": frame.exception_type,
                "message": frame.payload_as_str(),
            }
            if self._store_events:
                self.events.append({"event": "exception", "data": self._error})

    def _process_event(self, frame: Frame) -> None:
        event_type = frame.event_type
        payload = frame.payload_as_json()

        if self._store_events:
            self.events.append({"event": event_type, "data": payload})

        if not isinstance(payload, dict):
            return

        if event_type == EVENT_TYPE_ASSISTANT_RESPONSE:
            content = payload.get("content", "")
            if isinstance(content, str) and content:
                self._text_parts.append(content)

        elif event_type == EVENT_TYPE_TOOL_USE:
            tool_use_id = payload.get("toolUseId", "")
            name = payload.get("name", "")
            input_chunk = payload.get("input", "")
            stop = payload.get("stop", False)

            if tool_use_id not in self._tool_uses:
                acc = _ToolUseAccumulator(name=name, tool_use_id=tool_use_id)
                self._tool_uses[tool_use_id] = acc
                self._tool_use_order.append(tool_use_id)
            else:
                acc = self._tool_uses[tool_use_id]
                if name:
                    acc.name = name

            if isinstance(input_chunk, str) and input_chunk:
                acc.input_parts.append(input_chunk)
            if stop:
                acc.complete = True

        elif event_type == EVENT_TYPE_METERING:
            # usage is in "credits" units for Kiro, but we map to token fields
            # for viewer compatibility. Kiro also provides cache token counts.
            usage_val = payload.get("usage", 0)
            self._metering = {
                "input_tokens": int(usage_val) if isinstance(usage_val, (int, float)) else 0,
                "output_tokens": 0,
            }
            cache_read = payload.get("cacheReadInputTokens")
            cache_create = payload.get("cacheCreationInputTokens")
            if cache_read is not None:
                self._metering["cache_read_input_tokens"] = int(cache_read) if isinstance(cache_read, (int, float)) else 0
            if cache_create is not None:
                self._metering["cache_creation_input_tokens"] = int(cache_create) if isinstance(cache_create, (int, float)) else 0

        elif event_type == EVENT_TYPE_CONTEXT_USAGE:
            pct = payload.get("contextUsagePercentage", 0)
            self._context_usage = float(pct) if isinstance(pct, (int, float)) else 0.0

    def reconstruct(self) -> dict | None:
        """Build a response snapshot compatible with the trace viewer."""
        if self._error:
            return {
                "type": "error",
                "error": self._error,
                "usage": self._metering,
            }

        text = "".join(self._text_parts)
        content: list[dict] = []

        if text:
            content.append({"type": "text", "text": text})

        for tool_use_id in self._tool_use_order:
            acc = self._tool_uses[tool_use_id]
            content.append(acc.to_dict())

        if not content and not self._metering:
            return None

        snapshot: dict = {
            "type": "message",
            "role": "assistant",
            "content": content,
            "usage": self._metering,
        }

        if self._context_usage is not None:
            snapshot["context_usage_percentage"] = self._context_usage

        self._snapshot = snapshot
        return snapshot
