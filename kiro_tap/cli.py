"""CLI entry points for kiro-tap."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from aiohttp import web

from kiro_tap.certs import CertificateAuthority, ensure_ca, is_macos_ca_trusted, trust_macos_ca
from kiro_tap.forward_proxy import ForwardProxyServer
from kiro_tap.history import cleanup_trace_sessions, migrate_legacy_traces
from kiro_tap.proxy import proxy_handler
from kiro_tap.shared_dashboard import (
    DEFAULT_DASHBOARD_PORT,
    dashboard_url,
    ensure_shared_dashboard,
    is_dashboard_healthy,
    is_legacy_dashboard_healthy,
    resolve_dashboard_port,
)
from kiro_tap.trace import TraceWriter
from kiro_tap.trace_log_handler import SQLiteLogHandler
from kiro_tap.trace_store import get_trace_store, resolve_db_path

# Force UTF-8 + line-buffered stdout/stderr so emoji output works on Windows
# consoles (GBK/cp936) and `uv tool` doesn't fully buffer our progress prints.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

log = logging.getLogger("kiro-tap")

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("kiro-tap")
except Exception:
    __version__ = "0.0.0"


def _open_browser(url: str) -> None:
    """Open URL in browser without blocking. Silently ignores failures in headless environments."""
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()


async def _is_dashboard_reusable(host: str, port: int) -> bool:
    return await is_dashboard_healthy(host, port) or await is_legacy_dashboard_healthy(host, port)


@dataclass(frozen=True)
class ClientConfig:
    """Per-client configuration for supported AI CLI tools."""

    cmd: str
    label: str
    install_url: str
    base_url_env: str
    base_url_suffix: str  # appended to http://127.0.0.1:{port}
    default_target: str
    extra_base_url_envs: tuple[str, ...] = ()
    nesting_env_keys: tuple[str, ...] = ()  # env vars to clear before launch
    # Some CLIs need process env duplicated into a CLI settings payload.
    inject_settings_env: bool = False
    # Some CLIs need a base URL in both env and a native config override.
    base_url_config_key: str | None = None
    # Reverse proxy URL normalization.
    strip_path_prefix: str = ""
    strip_path_prefix_unless_target_contains: tuple[str, ...] = ()
    # Default proxy mode when --tap-proxy-mode is not explicitly set.
    default_proxy_mode: str = "reverse"
    # Some non-Python/non-Node macOS clients do not honor per-process CA env
    # variables, so they need the forward-proxy CA in the user login keychain.
    auto_trust_ca_macos: bool = False
    # Some clients honor a native provider URL for the core model API but ignore
    # HTTPS_PROXY for that API. In forward mode, point those env vars back at the
    # local proxy and let the forward proxy bridge selected paths to target.
    forward_base_url_envs: tuple[str, ...] = ()
    forward_base_url_allowed_path_prefixes: tuple[str, ...] = ()

    @property
    def missing_help(self) -> str:
        return (
            f"\nError: '{self.cmd}' command not found in PATH.\nPlease install {self.label} first: {self.install_url}\n"
        )

    def reverse_base_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}{self.base_url_suffix}"

    @property
    def reverse_base_url_envs(self) -> tuple[str, ...]:
        seen: set[str] = set()
        env_keys: list[str] = []
        for env_key in (self.base_url_env, *self.extra_base_url_envs):
            if env_key in seen:
                continue
            seen.add(env_key)
            env_keys.append(env_key)
        return tuple(env_keys)

    def reverse_base_url_env_map(self, port: int) -> dict[str, str]:
        base_url = self.reverse_base_url(port)
        return {env_key: base_url for env_key in self.reverse_base_url_envs}

    def reverse_strip_path_prefix(self, target: str) -> str:
        if not self.strip_path_prefix:
            return ""
        if any(marker in target for marker in self.strip_path_prefix_unless_target_contains):
            return ""
        return self.strip_path_prefix


CLIENT_CONFIGS: dict[str, ClientConfig] = {
    "kiro": ClientConfig(
        cmd="kiro-cli-chat",
        label="Kiro CLI",
        install_url="https://kiro.dev",
        base_url_env="KIRO_BASE_URL",
        base_url_suffix="",
        default_target="https://q.us-east-1.amazonaws.com",
        default_proxy_mode="forward",
    ),
    "kiro-ide": ClientConfig(
        cmd="kiro",
        label="Kiro IDE",
        install_url="https://kiro.dev",
        base_url_env="KIRO_BASE_URL",
        base_url_suffix="",
        default_target="https://q.us-east-1.amazonaws.com",
        default_proxy_mode="forward",
    ),
}


async def run_client(
    port: int,
    extra_args: list[str],
    client: str = "kiro",
    proxy_mode: str = "forward",
    ca_cert_path: Path | None = None,
) -> int:
    cfg = CLIENT_CONFIGS[client]

    # asyncio.create_subprocess_exec uses CreateProcess on Windows, which only
    # auto-appends `.exe`; resolve here so npm `.cmd`/`.bat` shims also work.
    resolved_cmd = shutil.which(cfg.cmd)
    if resolved_cmd is None:
        print(cfg.missing_help)
        return 1

    env = os.environ.copy()

    cmd_args = list(extra_args)
    has_base_url_config_override = bool(
        cfg.base_url_config_key and _has_config_override(cmd_args, cfg.base_url_config_key)
    )

    if proxy_mode == "forward":
        proxy_url = f"http://127.0.0.1:{port}"
        # Set both upper/lower-case variants for tools that read one form only.
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["ALL_PROXY"] = proxy_url
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url
        env["all_proxy"] = proxy_url
        _extend_no_proxy(env, ("localhost", "127.0.0.1", "::1"))
        forward_base_url = cfg.reverse_base_url(port)
        for env_key in cfg.forward_base_url_envs:
            env[env_key] = forward_base_url
        if ca_cert_path:
            env["SSL_CERT_FILE"] = str(ca_cert_path)
            env["NODE_EXTRA_CA_CERTS"] = str(ca_cert_path)
            env["REQUESTS_CA_BUNDLE"] = str(ca_cert_path)

        if cfg.inject_settings_env:
            if not _has_settings_arg(cmd_args):
                settings_payload: dict[str, dict[str, str]] = {
                    "env": {
                        "HTTP_PROXY": proxy_url,
                        "HTTPS_PROXY": proxy_url,
                        "ALL_PROXY": proxy_url,
                        "http_proxy": proxy_url,
                        "https_proxy": proxy_url,
                        "all_proxy": proxy_url,
                    }
                }
                if ca_cert_path:
                    settings_payload["env"]["NODE_EXTRA_CA_CERTS"] = str(ca_cert_path)
                cmd_args = _settings_arg(settings_payload["env"]) + cmd_args
        # Don't set reverse-mode provider-specific base URL in forward mode.
    else:
        reverse_env = cfg.reverse_base_url_env_map(port)
        env.update(reverse_env)
        env["NO_PROXY"] = "127.0.0.1"
        if cfg.inject_settings_env and not _has_settings_arg(cmd_args):
            cmd_args = _settings_arg(reverse_env) + cmd_args
        base_url_config_overrides: list[str] = []
        if cfg.base_url_config_key and not has_base_url_config_override:
            base_url = cfg.reverse_base_url(port)
            base_url_config_overrides.append(f'{cfg.base_url_config_key}="{base_url}"')
        if base_url_config_overrides:
            injected: list[str] = []
            for override in base_url_config_overrides:
                injected.extend(["-c", override])
            cmd_args = injected + cmd_args

    for key in cfg.nesting_env_keys:
        env.pop(key, None)

    cmd = [resolved_cmd] + cmd_args
    print(f"\n🚀 Starting {cfg.label}: {' '.join([cfg.cmd, *cmd_args])}")
    if proxy_mode == "forward":
        print(f"   HTTPS_PROXY=http://127.0.0.1:{port}")
        for env_key in cfg.forward_base_url_envs:
            print(f"   {env_key}={cfg.reverse_base_url(port)}")
        if ca_cert_path:
            print(f"   SSL_CERT_FILE={ca_cert_path}")
            print(f"   NODE_EXTRA_CA_CERTS={ca_cert_path}")
    else:
        for env_key, base_url in cfg.reverse_base_url_env_map(port).items():
            print(f"   {env_key}={base_url}")
    print()

    # Give child its own process group and make it the foreground group
    # so the TUI app has full terminal control (e.g. Cmd+Delete, Ctrl+U).
    use_fg = hasattr(os, "tcsetpgrp") and sys.stdin.isatty()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdin=None,
        stdout=None,
        stderr=None,
        **({"process_group": 0} if use_fg else {}),
    )

    if use_fg:
        try:
            os.tcsetpgrp(sys.stdin.fileno(), proc.pid)
        except OSError:
            pass

    # --- Signal handling: graceful Ctrl+C / Ctrl+Z ---
    loop = asyncio.get_running_loop()

    # SIGTSTP is Unix-only; on Windows the attribute is absent.
    sigtstp = getattr(signal, "SIGTSTP", None)
    old_sigtstp = signal.signal(sigtstp, signal.SIG_IGN) if sigtstp is not None else None

    sigint_count = 0

    def _handle_sigint():
        nonlocal sigint_count
        sigint_count += 1
        if sigint_count == 1:
            if proc.returncode is None:
                proc.terminate()
                print(f"\n⏳ Shutting down {cfg.label}... (Ctrl+C again to force)")
        else:
            if proc.returncode is None:
                proc.kill()

    def _handle_sigtstp():
        if proc.returncode is None:
            proc.terminate()
            print(f"\n⏳ Shutting down {cfg.label}...")

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        if sigtstp is not None:
            loop.add_signal_handler(sigtstp, _handle_sigtstp)
    except (NotImplementedError, OSError):
        pass

    code = await proc.wait()

    # Restore parent as foreground process group.
    # Ignore SIGTTOU first — the parent is still in the background group
    # and any terminal write (including tcsetpgrp) would suspend it.
    if use_fg:
        old_sigttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(sys.stdin.fileno(), os.getpgrp())
        except OSError:
            pass
        signal.signal(signal.SIGTTOU, old_sigttou)

    # Restore original SIGTSTP handler and remove async signal handlers
    if sigtstp is not None and old_sigtstp is not None:
        signal.signal(sigtstp, old_sigtstp)
    try:
        loop.remove_signal_handler(signal.SIGINT)
    except (NotImplementedError, OSError):
        pass
    if sigtstp is not None:
        try:
            loop.remove_signal_handler(sigtstp)
        except (NotImplementedError, OSError):
            pass

    print(f"\n📋 {cfg.label} exited with code {code}")
    return code


def _extend_no_proxy(env: dict[str, str], values: tuple[str, ...]) -> None:
    """Append local proxy bypasses without discarding existing settings."""
    existing: list[str] = []
    for key in ("NO_PROXY", "no_proxy"):
        raw = env.get(key, "")
        existing.extend(part.strip() for part in raw.split(",") if part.strip())

    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *values]:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        merged.append(value)

    no_proxy = ",".join(merged)
    env["NO_PROXY"] = no_proxy
    env["no_proxy"] = no_proxy


def _has_config_override(args: list[str], key: str) -> bool:
    """Return True when argv already contains a matching -c/--config override."""
    prefixes = (f"{key}=",)
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-c", "--config"):
            if i + 1 < len(args) and args[i + 1].startswith(prefixes):
                return True
            i += 2
            continue
        if arg.startswith("--config="):
            value = arg.split("=", 1)[1]
            if value.startswith(prefixes):
                return True
        i += 1
    return False


def _has_settings_arg(args: list[str]) -> bool:
    return any(arg == "--settings" or arg.startswith("--settings=") for arg in args)


def _settings_arg(env_values: dict[str, str]) -> list[str]:
    settings_payload = {"env": env_values}
    return ["--settings", json.dumps(settings_payload, separators=(",", ":"))]


def _trust_ca_for_current_user(ca_cert_path: Path) -> int:
    """Trust the forward-proxy CA in the current user's macOS login keychain."""
    if sys.platform != "darwin":
        print("--tap-trust-ca is currently only supported on macOS.", file=sys.stderr)
        print(f"CA certificate: {ca_cert_path}", file=sys.stderr)
        return 1

    if is_macos_ca_trusted(ca_cert_path):
        print(f"🔐 CA already trusted in the macOS login keychain: {ca_cert_path}")
        return 0

    result = trust_macos_ca(ca_cert_path)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        print("Error: failed to trust kiro-tap CA in the macOS login keychain.", file=sys.stderr)
        if details:
            print(details, file=sys.stderr)
        print("This command does not use sudo; macOS may require unlocking your login keychain.", file=sys.stderr)
        return result.returncode or 1

    if not is_macos_ca_trusted(ca_cert_path):
        print("Error: macOS did not report the kiro-tap CA as trusted after installation.", file=sys.stderr)
        print(f"CA certificate: {ca_cert_path}", file=sys.stderr)
        return 1

    print(f"🔐 Trusted kiro-tap CA in the current user's macOS login keychain: {ca_cert_path}")
    return 0


def _print_upstream_proxy_hint(args: argparse.Namespace) -> None:
    proxy = (
        args.upstream_proxy
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("all_proxy")
    )
    if proxy:
        print(f"🌍 Upstream proxy: {proxy}")
    else:
        print("💡 No upstream proxy detected. If Kiro requires a VPN/proxy to reach AWS,")
        print("   run: kiro-tap --proxy http://127.0.0.1:<port>")


def _ensure_ca_trust_for_forward_proxy(args: argparse.Namespace, ca_cert_path: Path) -> int:
    """Ensure CA trust when forward-proxy clients need macOS keychain trust."""
    if args.proxy_mode != "forward":
        return 0

    if args.trust_ca:
        return _trust_ca_for_current_user(ca_cert_path)

    cfg = CLIENT_CONFIGS[args.client]
    if sys.platform != "darwin" or not cfg.auto_trust_ca_macos:
        return 0

    if is_macos_ca_trusted(ca_cert_path):
        return 0

    print(f"🔐 {cfg.label} needs the kiro-tap CA trusted in your macOS login keychain.")
    print("   Installing for the current user only; no sudo or System keychain write is used.")
    return _trust_ca_for_current_user(ca_cert_path)


async def async_main(args: argparse.Namespace):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.live_viewer:
        migrate_legacy_traces(output_dir)

    store = get_trace_store()
    trace_metadata = {"client": args.client, "proxy_mode": args.proxy_mode}

    ca_cert_path: Path | None = None
    ca_key_path: Path | None = None
    if args.proxy_mode == "forward":
        ca_cert_path, ca_key_path = ensure_ca()
        trust_result = _ensure_ca_trust_for_forward_proxy(args, ca_cert_path)
        if trust_result != 0:
            return trust_result

    session_id = store.create_session(client=args.client, proxy_mode=args.proxy_mode)

    # Ensure the shared dashboard is running (one port for all sessions).
    dashboard_url_value: str | None = None
    if args.live_viewer:
        dashboard_host = args.host
        dashboard_port = resolve_dashboard_port(args.live_port)
        try:
            dashboard_url_value, spawned = await ensure_shared_dashboard(
                host=dashboard_host,
                port=dashboard_port,
                output_dir=output_dir,
                open_browser=args.open_viewer,
                open_browser_fn=_open_browser,
                session_id=session_id,
            )
            if spawned:
                print(f"🌐 Dashboard: {dashboard_url_value}")
            else:
                print(f"🌐 Dashboard: {dashboard_url_value} (shared)")
        except RuntimeError as exc:
            print(f"⚠️  {exc}", file=sys.stderr)

    writer = TraceWriter(session_id, live_server=None, metadata=trace_metadata, store=store)

    # Proxy logs go to SQLite, not terminal (avoids polluting Kiro TUI)
    sqlite_handler = SQLiteLogHandler(session_id, store=store)
    sqlite_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(sqlite_handler)
    log.setLevel(logging.DEBUG)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    aiohttp_server_log = logging.getLogger("aiohttp.server")
    aiohttp_server_log.addHandler(sqlite_handler)
    aiohttp_server_log.propagate = False
    asyncio_log = logging.getLogger("asyncio")
    asyncio_log.addHandler(sqlite_handler)
    asyncio_log.propagate = False

    # If user specified an upstream proxy, inject it so aiohttp trust_env picks it up.
    # Normalize: bare port number → http://127.0.0.1:<port>
    if args.upstream_proxy:
        proxy_val = args.upstream_proxy
        if proxy_val.isdigit():
            proxy_val = f"http://127.0.0.1:{proxy_val}"
        elif "://" not in proxy_val:
            proxy_val = f"http://{proxy_val}"
        args.upstream_proxy = proxy_val
        os.environ["HTTPS_PROXY"] = args.upstream_proxy
        os.environ["HTTP_PROXY"] = args.upstream_proxy
        os.environ["ALL_PROXY"] = args.upstream_proxy
        os.environ["https_proxy"] = args.upstream_proxy
        os.environ["http_proxy"] = args.upstream_proxy
        os.environ["all_proxy"] = args.upstream_proxy

    # Honor system proxy env (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY) for
    # outbound upstream requests. This is important when users route traffic
    # through tools like Clash/VPN.
    session = aiohttp.ClientSession(auto_decompress=False, trust_env=True)

    # Forward proxy mode: raw TCP server with CONNECT/TLS termination
    # Reverse proxy mode: aiohttp web app (current behavior)
    forward_server: ForwardProxyServer | None = None
    runner: web.AppRunner | None = None
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print(
            f"⚠️  SECURITY: binding to {args.host} exposes this proxy on all interfaces "
            "with NO authentication. Anyone who can reach this host can read intercepted "
            "traffic (including request/response bodies) and use it as an open relay. "
            "Use 127.0.0.1 unless you fully trust the network."
        )
    exit_code = 0
    try:
        if args.proxy_mode == "forward":
            assert ca_cert_path is not None
            assert ca_key_path is not None
            ca = CertificateAuthority(ca_cert_path, ca_key_path)
            forward_server = ForwardProxyServer(
                host=args.host,
                port=args.port,
                ca=ca,
                writer=writer,
                session=session,
                local_reverse_target=args.target,
                local_reverse_allowed_path_prefixes=CLIENT_CONFIGS[args.client].forward_base_url_allowed_path_prefixes,
                store_stream_events=args.store_stream_events,
            )
            actual_port = await forward_server.start()
            print(f"🔍 kiro-tap v{__version__} forward proxy on http://{args.host}:{actual_port}")
            print(f"   CA cert: {ca_cert_path}")
        else:
            app = web.Application(client_max_size=0)  # No body size limit (proxy must forward everything)
            app["trace_ctx"] = {
                "target_url": args.target,
                "writer": writer,
                "session": session,
                "turn_counter": 0,
                "extra_allowed_path_prefixes": tuple(args.extra_allowed_paths),
                "store_stream_events": args.store_stream_events,
                **_reverse_proxy_trace_options(args.client, args.target),
            }
            app.router.add_route("*", "/{path_info:.*}", proxy_handler)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, args.host, args.port)
            await site.start()

            # Resolve actual port (site._server is a private API; fall back to args.port)
            try:
                actual_port = site._server.sockets[0].getsockname()[1]
            except (AttributeError, IndexError, OSError):
                actual_port = args.port
            print(f"🔍 kiro-tap v{__version__} listening on http://{args.host}:{actual_port}")

        print(f"📁 Trace session: {session_id}")
        print(f"🗄️  Trace database: {resolve_db_path()}")
        _print_upstream_proxy_hint(args)

        # Background update check
        if not args.no_update_check:
            try:
                latest = await _check_pypi_version()
                if latest and _version_key(latest) > _version_key(__version__):
                    print(f"⬆️  Update available: {__version__} → {latest}")
                    if args.auto_update:
                        installer = _detect_installer()
                        _start_background_update(installer)
                        print(f"   Downloading update in background ({installer})...")
            except Exception:
                pass

        if not args.no_launch:
            try:
                exit_code = await run_client(
                    actual_port,
                    args.client_args,
                    client=args.client,
                    proxy_mode=args.proxy_mode,
                    ca_cert_path=ca_cert_path,
                )
            except asyncio.CancelledError:
                pass
        else:
            print("\n--no-launch mode: proxy running. Press Ctrl+C to stop.")
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
    finally:
        if forward_server:
            try:
                await asyncio.wait_for(forward_server.stop(), timeout=10)
            except asyncio.TimeoutError:
                log.warning("Timed out stopping forward proxy")
            except Exception:
                pass
        if runner:
            try:
                await runner.cleanup()
            except Exception:
                pass

        # Shared dashboard runs in a detached process; nothing to stop here.
        try:
            await asyncio.wait_for(session.close(), timeout=5)
        except asyncio.TimeoutError:
            log.warning("Timed out closing upstream HTTP session")
        except Exception:
            pass

        writer.close()

        if args.max_traces > 0:
            cleaned = cleanup_trace_sessions(args.max_traces, protected_session_id=session_id)
            if cleaned:
                print(f"\n🧹 Cleaned up {cleaned} old trace session(s)")

        # Print summary with cost estimation
        stats = writer.get_summary()
        print("\n📊 Trace summary:")
        print(f"   API calls: {stats['api_calls']}")

        # Token breakdown
        total_tokens = stats["input_tokens"] + stats["output_tokens"]
        if total_tokens > 0:
            print(f"   Tokens: {stats['input_tokens']:,} in / {stats['output_tokens']:,} out", end="")
            if stats["cache_read_tokens"] > 0:
                print(f" / {stats['cache_read_tokens']:,} cache_read", end="")
            if stats["cache_create_tokens"] > 0:
                print(f" / {stats['cache_create_tokens']:,} cache_write", end="")
            print()

        print(f"   Session: {session_id}")
        print(f"   Database: {resolve_db_path()}")
        if dashboard_url_value:
            print(f"   Dashboard: {dashboard_url_value}")

    return exit_code


TARGET_DETECTORS: dict[str, object] = {}


def _reverse_proxy_trace_options(client: str, target: str) -> dict[str, object]:
    cfg = CLIENT_CONFIGS[client]
    return {
        "strip_path_prefix": cfg.reverse_strip_path_prefix(target),
        "force_http": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse argv, extracting ``--tap-*`` flags for ourselves and forwarding
    everything else to the selected client.
    """
    if argv is None:
        argv = sys.argv[1:]

    tap_parser = argparse.ArgumentParser(
        prog="kiro-tap",
        description=(
            "Trace Kiro CLI and Kiro IDE API requests via a local proxy. "
            "All flags not listed below are forwarded to the selected client."
        ),
        epilog=(
            "kiro cli:\n"
            "  kiro-tap                              Basic tracing with live viewer enabled by default\n"
            "  kiro-tap --tap-no-live                Disable live viewer server/browser auto-open\n"
            "  kiro-tap --tap-no-open                Keep viewers from auto-opening in a browser\n"
            "\n"
            "kiro ide:\n"
            "  kiro-tap --tap-client kiro-ide        Trace Kiro IDE\n"
            "\n"
            "proxy-only mode (connect from another terminal):\n"
            "  kiro-tap --tap-no-launch --tap-port 8080\n"
            "  # then: KIRO_BASE_URL=http://127.0.0.1:8080 kiro-cli-chat\n"
            "\n"
            "export traces:\n"
            "  kiro-tap export trace.jsonl              Export to markdown\n"
            "  kiro-tap export trace.jsonl -o out.md    Export to file\n"
            "  kiro-tap export trace.jsonl --format json Export as JSON\n"
            "  kiro-tap export trace.jsonl -o out.html  Export as HTML viewer\n"
            "\n"
            "update:\n"
            "  kiro-tap update                          Upgrade kiro-tap in place\n"
            "  kiro-tap update --installer pip          Force pip-based upgrade\n"
            "\n"
            "dashboard:\n"
            "  kiro-tap dashboard                       Browse trace history\n"
            "  kiro-tap dashboard --tap-live-port 3000  Use a fixed dashboard port\n"
            "\n"
            "trust local CA:\n"
            "  kiro-tap trust-ca                        Trust forward-proxy CA in macOS user keychain\n"
            "\n"
            "homepage: https://kiro.dev"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tap_parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    # -- Proxy options --
    proxy_group = tap_parser.add_argument_group("proxy options")
    proxy_group.add_argument("--tap-port", type=int, default=0, dest="port", help="Proxy port (default: auto)")
    proxy_group.add_argument(
        "--tap-host",
        default=None,
        dest="host",
        help="Bind address (default: 127.0.0.1, or 0.0.0.0 with --tap-no-launch)",
    )
    proxy_group.add_argument(
        "--tap-client",
        choices=["kiro", "kiro-ide"],
        default="kiro",
        dest="client",
        help="Client to launch (default: kiro)",
    )
    proxy_group.add_argument(
        "--tap-target",
        default=None,
        dest="target",
        help="Upstream API URL (default: https://q.us-east-1.amazonaws.com)",
    )
    proxy_group.add_argument(
        "--tap-proxy-mode",
        choices=["reverse", "forward"],
        default=None,
        dest="proxy_mode",
        help=(
            "'reverse' sets provider base URL, 'forward' sets HTTPS_PROXY with CONNECT/TLS termination. "
            "Default: 'forward' for all kiro clients."
        ),
    )
    proxy_group.add_argument(
        "--tap-trust-ca",
        action="store_true",
        dest="trust_ca",
        help=(
            "On macOS, explicitly trust the forward-proxy CA in the current user's login keychain before launch "
            "(no sudo required)"
        ),
    )
    proxy_group.add_argument(
        "--tap-no-launch", action="store_true", dest="no_launch", help="Only start the proxy, don't launch client"
    )
    proxy_group.add_argument(
        "--tap-allow-path",
        action="append",
        default=[],
        dest="extra_allowed_paths",
        metavar="PREFIX",
        help="Extra path prefix to allow through the proxy (can be repeated, e.g. --tap-allow-path /custom/api)",
    )
    proxy_group.add_argument(
        "--proxy",
        default=None,
        dest="upstream_proxy",
        metavar="URL",
        help="Upstream proxy for outbound requests (e.g. http://127.0.0.1:7890 for VPN/Clash)",
    )

    # -- Viewer options --
    viewer_group = tap_parser.add_argument_group("viewer options")
    viewer_group.add_argument(
        "--tap-no-open",
        action="store_false",
        dest="open_viewer",
        default=True,
        help="Don't auto-open live or generated HTML viewers in a browser",
    )
    viewer_group.add_argument(
        "--tap-live",
        action="store_true",
        dest="live_viewer",
        default=True,
        help="Use the shared local dashboard while the client runs (default: on)",
    )
    viewer_group.add_argument(
        "--tap-no-live",
        action="store_false",
        dest="live_viewer",
        help="Disable the shared dashboard",
    )
    viewer_group.add_argument(
        "--tap-live-port",
        type=int,
        default=0,
        dest="live_port",
        help=f"Port for the shared dashboard (default: {DEFAULT_DASHBOARD_PORT})",
    )

    # -- Storage & update options --
    storage_group = tap_parser.add_argument_group("storage and update options")
    storage_group.add_argument(
        "--tap-output-dir",
        default="./.traces",
        dest="output_dir",
        help="Legacy trace directory to import once (default: ./.traces)",
    )
    storage_group.add_argument(
        "--tap-max-traces",
        type=int,
        default=50,
        dest="max_traces",
        help="Max trace sessions to keep (default: 50, 0 = unlimited)",
    )
    storage_group.add_argument(
        "--tap-store-stream-events",
        action="store_true",
        dest="store_stream_events",
        help="Persist raw SSE/WebSocket stream events in trace storage and viewer/export output (default: off)",
    )
    storage_group.add_argument(
        "--tap-no-update-check",
        action="store_true",
        dest="no_update_check",
        help="Disable PyPI update check on startup",
    )
    storage_group.add_argument(
        "--tap-auto-update",
        action="store_true",
        dest="auto_update",
        help="Auto-download updates in the background when a newer version is found (default: off)",
    )
    args, client_args = tap_parser.parse_known_args(argv)
    # Strip leading "--" separator if present (argparse leaves it in remainder)
    if client_args and client_args[0] == "--":
        client_args = client_args[1:]
    args.client_args = client_args
    # Default host: 127.0.0.1 (loopback only). Use --tap-host 0.0.0.0 to expose
    # on all interfaces (unauthenticated — see startup warning).
    if args.host is None:
        args.host = "127.0.0.1"
    if args.target is None:
        args.target = CLIENT_CONFIGS[args.client].default_target
    if args.proxy_mode is None:
        args.proxy_mode = CLIENT_CONFIGS[args.client].default_proxy_mode
    if args.trust_ca and args.proxy_mode != "forward":
        tap_parser.error("--tap-trust-ca only applies to forward proxy mode")

    # Validate --tap-allow-path prefixes
    for prefix in args.extra_allowed_paths:
        if not prefix:
            tap_parser.error("--tap-allow-path cannot be empty")
        if not prefix.startswith("/"):
            tap_parser.error(f"--tap-allow-path '{prefix}' must start with '/'")
        if prefix == "/":
            tap_parser.error("--tap-allow-path '/' is too broad and not allowed")
        if prefix.endswith("/"):
            tap_parser.error(f"--tap-allow-path '{prefix}' must not end with '/' (specify exact prefix)")

    return args


def parse_dashboard_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the standalone dashboard command."""
    parser = argparse.ArgumentParser(
        prog="kiro-tap dashboard",
        description="Open a local kiro-tap dashboard for browsing trace history.",
    )
    parser.add_argument(
        "--tap-output-dir",
        default="./.traces",
        dest="output_dir",
        help="Legacy trace directory to import once (default: ./.traces)",
    )
    parser.add_argument(
        "--tap-live-port",
        type=int,
        default=0,
        dest="live_port",
        help="Dashboard server port (default: auto)",
    )
    parser.add_argument(
        "--tap-host",
        default="127.0.0.1",
        dest="host",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--tap-no-open",
        action="store_false",
        dest="open_viewer",
        default=True,
        help="Don't auto-open the dashboard in a browser",
    )
    return parser.parse_args(argv)


async def dashboard_main(args: argparse.Namespace) -> int:
    """Run the standalone dashboard until interrupted."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    host = args.host
    if host not in ("127.0.0.1", "::1", "localhost"):
        print(
            f"⚠️  SECURITY: binding dashboard to {host} exposes trace history on all interfaces "
            "with NO authentication. Anyone who can reach this host can read intercepted "
            "traffic (including request/response bodies) and delete trace history. "
            "Use 127.0.0.1 unless you fully trust the network."
        )
    port = resolve_dashboard_port(args.live_port)
    if await _is_dashboard_reusable(host, port):
        migrate_legacy_traces(output_dir)
        url = dashboard_url(host, port)
        print(f"🌐 kiro-tap dashboard already running: {url}")
        print(f"🗄️  Trace database: {resolve_db_path()}")
        if args.open_viewer:
            _open_browser(url)
        return 0

    from kiro_tap.live import LiveViewerServer

    server = LiveViewerServer(
        port=port,
        host=host,
        migrate_from=output_dir,
        dashboard_mode=True,
    )
    try:
        await server.start()
    except OSError:
        if await _is_dashboard_reusable(host, port):
            migrate_legacy_traces(output_dir)
            url = dashboard_url(host, port)
            print(f"🌐 kiro-tap dashboard already running: {url}")
            if args.open_viewer:
                _open_browser(url)
            return 0
        raise
    print(f"🌐 kiro-tap dashboard: {server.url}")
    print(f"🗄️  Trace database: {resolve_db_path()}")
    if output_dir.exists():
        print(f"📁 Legacy import dir: {output_dir}")
    print("Press Ctrl+C to stop.")
    if args.open_viewer:
        _open_browser(server.url)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
    return 0


# ---------------------------------------------------------------------------
# Smart update check
# ---------------------------------------------------------------------------


def _version_key(v: str) -> tuple:
    """Build a PEP440-aware sort key from a version string.

    Handles release segments plus pre-release/dev/post suffixes so that
    e.g. 0.2.0 > 0.2.0rc1 > 0.2.0b1 > 0.2.0a1 > 0.2.0.dev1, and
    0.2.0.post1 > 0.2.0. Unknown suffixes are ignored gracefully.
    """
    s = v.strip().lower()
    m = re.match(r"(\d+(?:\.\d+)*)(.*)$", s)
    if not m:
        return ((0,), 0, 0)
    release = tuple(int(x) for x in m.group(1).split("."))
    rest = m.group(2)

    pre_rank = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, "c": 2}
    dev_m = re.search(r"\.?dev(\d*)", rest)
    post_m = re.search(r"\.?post(\d*)", rest)
    pre_m = re.search(r"(alpha|beta|rc|a|b|c)\.?(\d*)", rest)

    if post_m:
        phase, phase_num = 2, int(post_m.group(1) or 0)
    elif pre_m:
        phase = 0
        phase_num = pre_rank.get(pre_m.group(1), 0) * 1000 + int(pre_m.group(2) or 0)
    elif dev_m:
        phase, phase_num = -1, int(dev_m.group(1) or 0)
    else:
        phase, phase_num = 1, 0

    return (release, phase, phase_num)


async def _check_pypi_version(timeout: float = 3.0) -> str | None:
    """Check PyPI for the latest version. Returns version string or None."""
    url = os.environ.get("KIROTAP_PYPI_URL", "https://pypi.org/pypi/kiro-tap/json")

    def _fetch() -> str | None:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
                return data.get("info", {}).get("version")
        except Exception:
            return None

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


def _detect_installer() -> str:
    """Detect whether kiro-tap was installed via uv or pip."""
    exe = sys.executable or ""
    if "uv" in exe.lower() or shutil.which("uv"):
        return "uv"
    return "pip"


def _start_background_update(installer: str) -> subprocess.Popen | None:
    """Start a background process to upgrade kiro-tap."""
    try:
        cmd = _build_update_command(installer)
        if cmd is None:
            return None
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return None


def _build_update_command(installer: str) -> list[str] | None:
    """Build the foreground/background self-upgrade command."""
    if installer == "uv":
        uv_path = shutil.which("uv")
        if uv_path is None:
            return None
        return [uv_path, "tool", "upgrade", "kiro-tap"]
    if installer == "pip":
        return [sys.executable, "-m", "pip", "install", "--upgrade", "kiro-tap"]
    raise ValueError(f"unsupported installer: {installer}")


def parse_update_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the update subcommand."""
    parser = argparse.ArgumentParser(
        prog="kiro-tap update",
        description="Upgrade kiro-tap using the detected installer.",
    )
    parser.add_argument(
        "--installer",
        choices=["auto", "uv", "pip"],
        default="auto",
        help="Upgrade backend to use (default: auto-detect uv or pip)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upgrade command without running it",
    )
    return parser.parse_args(argv)


def update_main(argv: list[str] | None = None) -> int:
    """Entry point for the update subcommand."""
    args = parse_update_args(argv)
    installer = _detect_installer() if args.installer == "auto" else args.installer
    cmd = _build_update_command(installer)
    if cmd is None:
        print("Error: 'uv' command not found. Re-run with --installer pip or install uv.", file=sys.stderr)
        return 1

    printable_cmd = " ".join(cmd)
    print(f"Upgrading kiro-tap with {installer}: {printable_cmd}")
    if args.dry_run:
        return 0

    try:
        result = subprocess.run(cmd, check=False)
    except OSError as exc:
        print(f"Error: failed to run update command: {exc}", file=sys.stderr)
        return 1
    return result.returncode


def parse_trust_ca_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments for the trust-ca subcommand."""
    parser = argparse.ArgumentParser(
        prog="kiro-tap trust-ca",
        description=(
            "Trust the kiro-tap forward-proxy CA in the current user's macOS login keychain. "
            "This does not use sudo or the System keychain."
        ),
    )
    return parser.parse_args(argv)


def trust_ca_main(argv: list[str] | None = None) -> int:
    """Entry point for the trust-ca subcommand."""
    parse_trust_ca_args(argv)
    ca_cert_path, _ = ensure_ca()
    return _trust_ca_for_current_user(ca_cert_path)


def main_entry() -> None:
    """Entry point for the kiro-tap CLI."""
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        from kiro_tap.export import export_main

        sys.exit(export_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "update":
        sys.exit(update_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "trust-ca":
        sys.exit(trust_ca_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        args = parse_dashboard_args(sys.argv[2:])
        try:
            code = asyncio.run(dashboard_main(args))
        except KeyboardInterrupt:
            code = 0
        sys.exit(code)

    args = parse_args()
    try:
        code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)
