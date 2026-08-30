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

### Clients & CLI

`cli.py` holds `CLIENT_CONFIGS` keyed by `--tap-client`:

| Client | cmd | default_target | extra intercept hosts |
|--------|-----|----------------|-----------------------|
| `kiro` (default) | `kiro-cli-chat` | `https://q.us-east-1.amazonaws.com` | `runtime.us-east-1.kiro.dev`, `management.us-east-1.kiro.dev` |
| `kiro-ide` | `kiro` | same | same |

Both default to forward mode and `auto_trust_ca_macos=True`. Forward mode injects `SSL_CERT_FILE` (local CA) + `HTTPS_PROXY` into the client subprocess env; for Kiro CLI 2.7.0+ (native TLS via `Security.framework`) the CA is also trusted in the macOS **login keychain** (no sudo). Reverse mode sets `KIRO_BASE_URL=http://127.0.0.1:<port>`.

CLI flag namespace is `--tap-*` (parsed via `parse_known_args` so unknown args pass through to the wrapped client). Notable flags: `--tap-port/--tap-host/--tap-client/--tap-target/--tap-proxy-mode/--tap-trust-ca/--tap-allow-path/--tap-output-dir/--tap-max-traces/--tap-store-stream-events/--tap-no-update-check/--tap-auto-update`. Subcommands: `export`, `update`, `trust-ca`, `dashboard`.

### Module responsibilities

> Module sizes (lines) shown for scale orientation; the three largest (`cli.py`, `forward_proxy.py`, `trace_store.py`) are the core.

- `cli.py` (~1150) — Entry point. `CLIENT_CONFIGS`, `parse_args` (`--tap-*` namespace + subcommands), proxy startup, session lifecycle, PyPI update check (`--tap-auto-update`).
- `forward_proxy.py` (~1010) — `ForwardProxyServer`: raw asyncio TCP server. CONNECT tunneling, per-host TLS cert generation, HTTP/1.1-forced ALPN (prevents h2 in MitM tunnel), streaming/non-streaming split, WebSocket upgrade passthrough (`_forward_websocket`), upstream-proxy chaining for passthrough hosts. `_should_intercept` decides MitM vs raw TCP relay per host.
- `proxy.py` (~460) — `proxy_handler` (reverse mode) + shared request logic. Security surfaces:
  - `ALLOWED_PATH_PREFIXES` — path allowlist (see Key invariants).
  - `SENSITIVE_HEADER_KEYS` — redacted set: `authorization`, `cookie`, `set-cookie`, `x-api-key`, `cosy-key/machinetoken/machineid/machinetype/user*`.
  - `PREFIX_REDACTED_HEADER_KEYS` = `{authorization, x-api-key}` (kept with prefix marker, value dropped).
  - `filter_headers(headers, redact_keys=False)`.
- `aws_event_stream.py` (~420) — AWS Event Stream binary frame parser. `Frame`, `parse_frame` (prelude CRC + message CRC32 validation), `iter_frames`, `_ToolUseAccumulator`, `AWSEventStreamReassembler` (feed → drain → reconstruct). Used for Kiro's `q.us-east-1.amazonaws.com` traffic.
- `sse.py` (~300) — Standard SSE text-stream reassembler (fallback for non-AWS-eventstream responses).
- `ws_proxy.py` (~500) — WebSocket proxy for both modes. `_handle_websocket`, `_build_ws_record`, `_parse_ws_messages`, `reconstruct_ws_request_body/response_body`.
- `trace_store.py` (~940) — `TraceStore` singleton, SQLite at `~/.local/share/kiro-tap/traces.sqlite3` (override: `KIROTAP_DB`). Tables: `sessions`, `records`, `proxy_logs`, `migration_state`. Thread-safe via `RLock` + thread-local connections; writes offloaded by caller. **Schema v3** with `v2→v3` migration (`_migrate_v2_to_v3`). Methods: `create_session/append_record/append_log/finalize_session/load_*/export_jsonl/export_log/dashboard_snapshot/list_dates/delete_sessions_by_date/cleanup_old_sessions/migrate_legacy_directory`.
- `trace.py` (~100) — `TraceWriter`: async wrapper around `TraceStore`; accumulates token stats per session; offloads SQLite writes to thread pool.
- `trace_log_handler.py` (~34) — `logging.Handler` → SQLite `proxy_logs` table (keeps TUI clean).
- `live.py` (~490) — `LiveViewerServer`: aiohttp server. Routes: dashboard index, SSE stream, per-session/per-date records, JSONL+log export, agents/sessions lists, delete-by-date. `_is_same_origin` enforced.
- `shared_dashboard.py` (~340) — Single shared dashboard process across concurrent kiro-tap sessions. File lock at `<db-parent>/dashboard.lock` (default DB parent `~/.local/share/kiro-tap/`). Default port `19528` (override: `KIROTAP_DASHBOARD_PORT`). `ensure_shared_dashboard` / `wait_for_dashboard_healthy` / `_kill_process_on_port`.
- `dashboard.py` (~890) — SQLite query helpers + dashboard HTML template loader. `list_trace_sessions/agents`, `dashboard_trace_snapshot`, `load_trace_session`, `merge_record_into_summary`, plus extractors (`_record_usage/_record_model/_response_status/_duration_ms/_record_error/_infer_agent`).
- `viewer.py` (~770) — `_generate_html_viewer`: self-contained HTML viewers (zero deps). Gemini/OpenAI/Anthropic-specific extractors. Kiro history split into a dedicated History section.
- `certs.py` (~290) — Local CA at `~/.kiro-tap/ca.pem`. `CertificateAuthority.get_host_cert_pem/make_ssl_context`. macOS login-keychain trust (no sudo): `macos_login_keychain_path`, `build_macos_verify/trust_ca_command`, `is_macos_ca_trusted`, `trust_macos_ca`.
- `history.py` (~34) — `cleanup_trace_sessions/delete_trace_history/migrate_legacy_traces` (JSONL→SQLite for legacy `.traces/`).
- `export.py` (~315) — `kiro-tap export`: SQLite/JSONL → Markdown/JSON/HTML.
- `usage.py` (~35) — Normalises token usage fields across API response shapes.

### Data flow (forward proxy mode)

```
kiro-cli-chat (kiro | kiro-ide)
  → env: HTTPS_PROXY=http://127.0.0.1:<port>, SSL_CERT_FILE=<ca.pem>
  → ForwardProxyServer (asyncio TCP)
    → CONNECT handshake → _should_intercept?
        ├ intercept: TLS termination (per-host cert, HTTP/1.1 ALPN)
        │   → HTTP request → proxy.py (allowlist + header redaction)
        │   → AWSEventStreamReassembler (binary frames → full response)
        │   → TraceWriter.write() → TraceStore (SQLite, thread pool)
        │   → SSE broadcast → LiveViewerServer (shared dashboard :19528)
        └ passthrough: raw TCP relay (may chain through upstream proxy)
  → upstream: https://q.us-east-1.amazonaws.com (+ runtime/management.us-east-1.kiro.dev)
```

### Key invariants

- **Path allowlist (security gate)** — `ALLOWED_PATH_PREFIXES` in `proxy.py`: paths not matching return 404 and are never forwarded or recorded. Covers Kiro (`/generateAssistantResponse`, `/mcp`), Anthropic (`/v1/messages`, `/v1/complete`), OpenAI (`/v1/responses`, `/v1/chat/completions`, …), Gemini (`/v1beta/models`, `/v1alpha/models`), Google Code Assist (`/v1internal`), Kimi Code (`/search`, `/fetch`, `/usages`, `/feedback`). Match = exact, or prefix + `/`, or prefix + `:`.
- **Header redaction** — `SENSITIVE_HEADER_KEYS` (`authorization`, `cookie`, `set-cookie`, `x-api-key`, `cosy-*`) redacted before persisting; `authorization`/`x-api-key` keep a prefix marker, value dropped.
- **TraceStore singleton** — process-wide; `reset_trace_store()` in tests for a fresh instance.
- **SQLite schema v3** — `trace_store.py` auto-migrates `v2→v3`; `migration_state` table tracks version.
- **Shared dashboard** — one process per machine (file-locked), port `19528`; concurrent kiro-tap sessions reuse it.
- **Versioning** — `setuptools-scm` from git tags, format `v*` (e.g. `v0.3.6`); runtime falls back to `importlib.metadata` or `0.0.0`.

## Testing notes

- `asyncio_mode = "auto"` in `pyproject.toml` — async tests work without `@pytest.mark.asyncio`.
- `--run-real-e2e` (in `conftest.py`) gates tests requiring `kiro-cli-chat` in `PATH`.
- `KIROTAP_DB` env redirects SQLite to a temp file; call `reset_trace_store()` after. `--tap-allow-path` widens the allowlist in E2E.
- Test files: `test_aws_event_stream.py`, `test_path_allowlist.py`, `test_kiro_launch.py`, `test_audit_batch_3.py` — coverage is limited (no TraceStore/forward-proxy/dashboard unit tests yet).
- `pytest-timeout` default 60s. Test venv with dev deps: `.venv-test/`; production deps only: `.venv/`.
- `ruff check .` (target py311, line-length 120, ignore E501) before committing.
