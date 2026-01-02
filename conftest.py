"""Pytest configuration.

Goals:
- Keep unit tests fast and hermetic (no MCP runtime, no subprocesses by default).
- Make integration tests opt-in via --run-integration.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (spawns MCP subprocesses; may require local config/tokens).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return

    skip = pytest.mark.skip(reason="integration tests are opt-in; pass --run-integration to run them")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
