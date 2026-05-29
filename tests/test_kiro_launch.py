"""Tests for kiro client configuration and launch."""

from __future__ import annotations

import asyncio

import pytest

from kiro_tap.cli import CLIENT_CONFIGS, parse_args, run_client


class _DummyProc:
    def __init__(self) -> None:
        self.pid = 12345
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def test_kiro_registered_in_client_configs() -> None:
    cfg = CLIENT_CONFIGS["kiro"]
    assert cfg.cmd == "kiro-cli-chat"
    assert cfg.default_proxy_mode == "forward"


def test_kiro_ide_registered_in_client_configs() -> None:
    cfg = CLIENT_CONFIGS["kiro-ide"]
    assert cfg.cmd == "kiro"
    assert cfg.default_proxy_mode == "forward"


def test_parse_args_kiro_defaults_to_forward_mode() -> None:
    args = parse_args(["--tap-client", "kiro"])
    assert args.client == "kiro"
    assert args.proxy_mode == "forward"


def test_parse_args_kiro_ide_defaults_to_forward_mode() -> None:
    args = parse_args(["--tap-client", "kiro-ide"])
    assert args.client == "kiro-ide"
    assert args.proxy_mode == "forward"


def test_parse_args_default_client_is_kiro() -> None:
    args = parse_args([])
    assert args.client == "kiro"


@pytest.mark.asyncio
async def test_run_client_kiro_forward_sets_proxy_env(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return _DummyProc()

    ca_cert = tmp_path / "ca.crt"
    ca_cert.write_text("fake-cert")

    monkeypatch.setattr("kiro_tap.cli.shutil.which", lambda _: "/tmp/kiro-cli-chat")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    code = await run_client(43200, [], client="kiro", proxy_mode="forward", ca_cert_path=ca_cert)

    assert code == 0
    env = captured["env"]
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:43200"
    assert env["SSL_CERT_FILE"] == str(ca_cert)


def test_client_matrix_contains_only_kiro_clients() -> None:
    assert set(CLIENT_CONFIGS.keys()) == {"kiro", "kiro-ide"}
