# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`kiro-tap` is a Python CLI tool (published to PyPI) that intercepts Kiro CLI / Kiro IDE HTTPS traffic via a local proxy. It parses AWS Event Stream binary frames, persists traces to SQLite, and serves a real-time browser dashboard over SSE.

**代码索引**：`kiro-tap_源码全景解析.md` — 功能→文件:行号速查表，80+ 函数定位，含架构图和数据流。

## Commands

```bash
# Install (editable + dev deps)
pip install -e ".[dev]"

# Lint
ruff check .

# Run all tests
pytest

# Run a single test
pytest tests/test_aws_event_stream.py::test_parse_frame -v

# Run with real-E2E flag (requires kiro-cli in PATH)
pytest --run-real-e2e

# Coverage
coverage run -m pytest && coverage report

# Build distribution
python -m build
```

## Architecture

### Two proxy modes

| Mode | Trigger | Transport |
|------|---------|-----------|
| **Forward** (default for kiro) | `--tap-proxy-mode forward` | Raw TCP, HTTP CONNECT + TLS termination; CA cert injected via `SSL_CERT_FILE`/`HTTPS_PROXY` |
| **Reverse** | `--tap-proxy-mode reverse` | aiohttp web app; sets `KIRO_BASE_URL` to `http://127.0.0.1:<port>` |

### Module responsibilities

- `cli.py` — Entry point. Subcommand dispatch (`export`, `update`, `trust-ca`, `dashboard`), arg parsing, proxy startup, session lifecycle, update check.
- `forward_proxy.py` — `ForwardProxyServer`: raw asyncio TCP server with CONNECT tunneling and per-host TLS cert generation.
- `proxy.py` — `proxy_handler`: aiohttp reverse proxy handler. Contains `ALLOWED_PATH_PREFIXES` allowlist (scanner/crawler rejection) and header redaction logic.
- `aws_event_stream.py` — Binary frame parser for AWS Event Stream (used by Kiro API). CRC32 validation, all header value types, event type reconstruction.
- `sse.py` — Standard SSE text-stream reassembler (fallback for non-AWS-eventstream responses).
- `ws_proxy.py` — WebSocket proxy support for both proxy modes.
- `trace_store.py` — `TraceStore` singleton backed by SQLite at `~/.local/share/kiro-tap/traces.sqlite3`. Override with `KIROTAP_DB` env. Thread-safe via `RLock`; uses thread-local connections.
- `trace.py` — `TraceWriter`: async wrapper around `TraceStore`; accumulates token stats per session. Offloads SQLite writes to thread pool to avoid blocking the event loop.
- `trace_log_handler.py` — Python `logging.Handler` that writes proxy logs to the SQLite `logs` table (keeps TUI output clean).
- `live.py` — `LiveViewerServer`: aiohttp server for the dashboard, SSE event stream, and per-session HTML export. Enforces same-origin checks.
- `shared_dashboard.py` — Manages a single shared dashboard process across concurrent kiro-tap sessions (uses a file lock at `~/.local/share/kiro-tap/dashboard.lock`). Default port: `19528` (override via `KIROTAP_DASHBOARD_PORT`).
- `dashboard.py` — SQLite query helpers and dashboard HTML template loader.
- `viewer.py` — Generates self-contained HTML trace viewers (zero external deps).
- `certs.py` — Generates and persists local CA at `~/.kiro-tap/ca.pem`; optionally trusts it in macOS login keychain (no sudo).
- `history.py` — Session cleanup and JSONL→SQLite migration for legacy `.traces/` directories.
- `export.py` — CLI `kiro-tap export`: converts SQLite or JSONL traces to Markdown / JSON / HTML.
- `usage.py` — Normalises token usage fields across different API response shapes.

### Data flow (forward proxy mode)

```
kiro-cli-chat
  → HTTPS_PROXY=http://127.0.0.1:<port>
  → ForwardProxyServer (asyncio TCP)
    → CONNECT handshake → TLS termination (per-host cert signed by local CA)
    → HTTP request read → proxy.py logic (allowlist check, header redaction)
    → AWSEventStreamReassembler (binary frames → full response)
    → TraceWriter.write() → TraceStore (SQLite, thread pool)
    → SSE broadcast → LiveViewerServer (dashboard)
  → upstream: https://q.us-east-1.amazonaws.com
```

### Key invariants

- `ALLOWED_PATH_PREFIXES` in `proxy.py` is the security gate: paths not in this list return 404 and are never forwarded or recorded.
- Sensitive headers (`authorization`, `x-api-key`, `cosy-*`) are redacted before persisting traces.
- The SQLite `TraceStore` is a process-wide singleton; use `reset_trace_store()` in tests to get a fresh instance.
- Version is derived from git tags via `setuptools-scm`; tag format is `v*` (e.g. `v0.2.0`).

## Testing notes

- `asyncio_mode = "auto"` is set in `pyproject.toml`; async test functions work without `@pytest.mark.asyncio`.
- The `--run-real-e2e` flag in `conftest.py` gates tests that require `kiro-cli-chat` in `PATH`.
- `KIROTAP_DB` env var redirects SQLite to a temp file in tests; call `reset_trace_store()` after.
- Test venv with dev deps lives in `.venv-test/`; production deps only in `.venv/`.
