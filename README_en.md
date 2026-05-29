# kiro-tap

[![PyPI version](https://img.shields.io/pypi/v/kiro-tap)](https://pypi.org/project/kiro-tap/)
[![Python version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[中文文档](README.md)

`kiro-tap` is a local proxy and trace viewer for Kiro CLI and Kiro IDE. Run Kiro through it to inspect real API traffic: system prompts, conversation history, tool schemas, tool calls, streaming responses, and token usage.

Supports [Kiro CLI](https://kiro.dev) (`kiro-cli-chat`) and [Kiro IDE](https://kiro.dev).

## Why use it

- 👀 **See the exact context**: inspect every request sent to the Kiro API, including system prompts, message history, tool definitions, tool calls, and responses
- 🔎 **Debug with evidence**: compare adjacent requests and pinpoint which message, tool, or parameter changed
- 📦 **Share one portable artifact**: each run writes a local trace that can be exported to a self-contained HTML viewer for review or archiving
- 🔒 **Keep traces on your machine**: no hosted dashboard required, and common auth headers are redacted before recording
- ⚡ **Native AWS Event Stream support**: correctly parses Kiro's AWS Event Stream binary frame protocol and fully reconstructs streaming responses

## Install

Requires Python 3.11+.

```bash
# Recommended
uv tool install kiro-tap

# Or with pipx
pipx install kiro-tap

# Or with pip
pip install kiro-tap
```

Upgrade: `kiro-tap update`, `uv tool upgrade kiro-tap`, or `pip install --upgrade kiro-tap`

## Quick Start

```bash
# Kiro CLI (default, live dashboard enabled by default)
kiro-tap

# Kiro IDE
kiro-tap --tap-client kiro-ide

# Disable live dashboard
kiro-tap --tap-no-live

# Don't auto-open browser
kiro-tap --tap-no-open
```

## How it works

```
kiro-tap starts a local forward proxy
    ↓
Injects HTTPS_PROXY + SSL_CERT_FILE into the child process environment
    ↓
Launches kiro-cli-chat (or kiro)
    ↓
All HTTPS traffic → local proxy → TLS termination → forwarded to q.us-east-1.amazonaws.com
    ↓
AWS Event Stream binary frame parsing → full response reconstruction
    ↓
Written to local SQLite trace database
    ↓
Pushed to browser dashboard in real time (SSE)
```

kiro-tap uses **forward proxy mode** (CONNECT + TLS termination) because Kiro CLI does not expose a base URL environment variable. The proxy auto-generates a local CA certificate and injects it into the child process — no sudo required.

## CLI Options

All flags except `--tap-*` are forwarded to the selected Kiro client.

```
--tap-client CLIENT      Client to launch: kiro (default) or kiro-ide
--tap-target URL         Upstream API URL (default: https://q.us-east-1.amazonaws.com)
--tap-live               Start real-time dashboard while client runs (default: on)
--tap-no-live            Disable the real-time dashboard
--tap-live-port PORT     Port for the live dashboard (default: 19528)
--tap-no-open            Don't auto-open dashboard or generated HTML in a browser
--tap-output-dir DIR     Legacy trace directory (default: ./.traces)
--tap-port PORT          Proxy port (default: auto)
--tap-host HOST          Bind address (default: 127.0.0.1)
--tap-no-launch          Only start the proxy, don't launch client
--tap-max-traces N       Max trace sessions to keep (default: 50, 0 = unlimited)
--tap-store-stream-events Persist raw AWS Event Stream frame arrays (default: off)
--tap-no-update-check    Disable PyPI update check on startup
--tap-no-auto-update     Check for updates but don't auto-download
--tap-trust-ca           Trust local CA in macOS user login keychain (no sudo)
```

## Subcommands

```bash
# Browse trace history
kiro-tap dashboard

# Export a JSONL trace to HTML / Markdown / JSON
kiro-tap export .traces/session.jsonl -o trace.html

# Upgrade kiro-tap
kiro-tap update

# Trust local CA in macOS keychain (needed for forward proxy mode)
kiro-tap trust-ca
```

## Proxy-only mode

```bash
# Start proxy only, launch Kiro manually in another terminal
kiro-tap --tap-no-launch --tap-port 8080

# Then in another terminal:
HTTPS_PROXY=http://127.0.0.1:8080 SSL_CERT_FILE=~/.kiro-tap/ca.pem kiro-cli-chat
```

## Viewer Features

The generated HTML viewer (zero external dependencies) supports:

- **Structural diff** — compare consecutive requests to see exactly what changed: new/removed messages, system prompt diffs, character-level inline highlighting
- **Path filtering** — filter by API endpoint (e.g. `/generateAssistantResponse` only)
- **Token usage breakdown** — input / output / cache read / cache creation
- **Tool inspector** — expandable cards with tool name, description, and parameter schema
- **Search** — full-text search across messages, tools, prompts, and responses
- **Dark mode** — toggle light/dark themes (respects system preference)
- **Keyboard navigation** — `j`/`k` or arrow keys
- **Copy helpers** — one-click copy of request JSON or cURL command
- **i18n** — English, 简体中文, 日本語, 한국어, Français, العربية, Deutsch, Русский

## AWS Event Stream Parsing

The Kiro API uses the AWS Event Stream binary framing protocol (not standard SSE). kiro-tap implements a full frame parser:

- CRC32 verification (ISO-HDLC, matching the AWS SDK)
- All header value types (bool, byte, short, int, long, bytes, string, timestamp, uuid)
- Event types: `assistantResponseEvent`, `toolUseEvent`, `meteringEvent`, `contextUsageEvent`, `codeReferenceEvent`
- Error and exception message types

## License

MIT
