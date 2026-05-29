"""kiro-tap: Proxy to trace Kiro CLI and Kiro IDE API requests.

A CLI tool that wraps Kiro CLI with a local forward proxy to intercept
and record all API requests. Useful for studying Kiro's context engineering.
"""

from __future__ import annotations

from kiro_tap.certs import CertificateAuthority, ensure_ca
from kiro_tap.cli import (
    __version__,
    _build_update_command,
    _detect_installer,
    _version_tuple,
    async_main,
    dashboard_main,
    main_entry,
    parse_args,
    parse_dashboard_args,
    parse_trust_ca_args,
    parse_update_args,
    trust_ca_main,
    update_main,
)
from kiro_tap.forward_proxy import ForwardProxyServer
from kiro_tap.history import cleanup_trace_sessions, delete_trace_history, migrate_legacy_traces
from kiro_tap.live import LiveViewerServer
from kiro_tap.proxy import filter_headers
from kiro_tap.aws_event_stream import AWSEventStreamReassembler
from kiro_tap.trace import TraceWriter
from kiro_tap.trace_store import get_trace_store, reset_trace_store, resolve_db_path
from kiro_tap.viewer import _generate_html_viewer

__all__ = [
    "__version__",
    "_build_update_command",
    "_detect_installer",
    "_version_tuple",
    "main_entry",
    "parse_args",
    "parse_dashboard_args",
    "parse_trust_ca_args",
    "parse_update_args",
    "trust_ca_main",
    "update_main",
    "async_main",
    "dashboard_main",
    "CertificateAuthority",
    "ensure_ca",
    "ForwardProxyServer",
    "AWSEventStreamReassembler",
    "TraceWriter",
    "LiveViewerServer",
    "filter_headers",
    "_generate_html_viewer",
    "cleanup_trace_sessions",
    "delete_trace_history",
    "migrate_legacy_traces",
    "get_trace_store",
    "reset_trace_store",
    "resolve_db_path",
]
