"""Smart update check and self-upgrade subcommand for kiro-tap.

Moved verbatim from cli.py (pure code relocation, no behavior change).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request


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
