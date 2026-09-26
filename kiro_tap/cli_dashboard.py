"""Standalone dashboard subcommand for kiro-tap.

Moved verbatim from cli.py (pure code relocation, no behavior change).
`_open_browser` / `_is_dashboard_reusable` are also relocated here; cli.py
re-imports them so existing imports of those names from kiro_tap.cli keep
working.
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import webbrowser
from pathlib import Path

from kiro_tap.history import migrate_legacy_traces
from kiro_tap.shared_dashboard import (
    dashboard_url,
    is_dashboard_healthy,
    is_legacy_dashboard_healthy,
    resolve_dashboard_port,
)
from kiro_tap.trace_store import resolve_db_path


def _open_browser(url: str) -> None:
    """Open URL in browser without blocking. Silently ignores failures in headless environments."""
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()


async def _is_dashboard_reusable(host: str, port: int) -> bool:
    return await is_dashboard_healthy(host, port) or await is_legacy_dashboard_healthy(host, port)



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
