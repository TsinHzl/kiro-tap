"""HTTP body readers and WebSocket upgrade helpers for the forward proxy.

Moved verbatim from forward_proxy.py (pure code relocation, no behavior
change). forward_proxy.py re-imports these names so existing imports and
test monkeypatch targets (`kiro_tap.forward_proxy._read_http_body`) keep
working.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib

from aiohttp.http_websocket import WS_KEY

# Maximum body size for plain-HTTP proxy requests. Requests exceeding this
# limit are rejected to prevent memory exhaustion from malicious clients.
_MAX_BODY_BYTES = 256 * 1024 * 1024  # 256 MB


def _matches_path_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    clean = path.split("?", 1)[0].rstrip("/")
    return any(
        clean == prefix or clean.startswith(prefix + "/") or clean.startswith(prefix + ":") for prefix in prefixes
    )


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        size_line = await asyncio.wait_for(reader.readline(), timeout=60)
        if not size_line:
            break
        size_token = size_line.split(b";", 1)[0].strip()
        try:
            size = int(size_token, 16)
        except ValueError:
            break
        if size == 0:
            while True:
                trailer_line = await asyncio.wait_for(reader.readline(), timeout=30)
                if trailer_line in (b"\r\n", b"\n", b""):
                    break
            break
        total += size
        if total > _MAX_BODY_BYTES:
            raise ValueError(f"Chunked body exceeds maximum size of {_MAX_BODY_BYTES} bytes")
        chunks.append(await asyncio.wait_for(reader.readexactly(size), timeout=60))
        await asyncio.wait_for(reader.readexactly(2), timeout=30)
    return b"".join(chunks)


async def _read_http_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> bytes:
    content_length = headers.get("Content-Length") or headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError:
            return b""
        if length > _MAX_BODY_BYTES:
            raise ValueError(f"Content-Length {length} exceeds maximum size of {_MAX_BODY_BYTES} bytes")
        try:
            return await asyncio.wait_for(reader.readexactly(length), timeout=60)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            return b""
    transfer_encoding = headers.get("Transfer-Encoding") or headers.get("transfer-encoding", "")
    if "chunked" in transfer_encoding.lower():
        return await _read_chunked_body(reader)
    return b""


class _RawWSProtocol:
    """Minimal protocol shim for aiohttp's raw WebSocket helpers."""

    def __init__(self) -> None:
        self._reading_paused = False
        self._paused = False

    def pause_reading(self) -> None:
        self._reading_paused = True

    def resume_reading(self) -> None:
        self._reading_paused = False

    async def _drain_helper(self) -> None:
        return


def _is_websocket_upgrade(headers: dict[str, str]) -> bool:
    upgrade = headers.get("Upgrade", headers.get("upgrade", "")).lower()
    if upgrade != "websocket":
        return False
    connection = headers.get("Connection", headers.get("connection", "")).lower()
    return "upgrade" in connection


def _build_ws_accept(sec_key: str) -> str:
    digest = hashlib.sha1(sec_key.encode("utf-8") + WS_KEY).digest()
    return base64.b64encode(digest).decode("ascii")
