"""pytest configuration for kiro-tap tests."""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-real-e2e",
        action="store_true",
        default=False,
        help="Run real E2E tests requiring kiro-cli",
    )
