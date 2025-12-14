"""HDT MCP server entrypoint.

This module is intentionally small. Some MCP launchers import a server module
by *file path* (not as a normal package import). In that mode, absolute imports
like `hdt_mcp.mcp_app` would fail unless the repo root is on sys.path.

Therefore we:
1) ensure the repo root is on sys.path
2) import the real wiring from `hdt_mcp.mcp_app`
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hdt_mcp.mcp_app import build_mcp, run  # noqa: E402

mcp, settings = build_mcp()


def main() -> None:
    run(mcp)


if __name__ == "__main__":
    main()
