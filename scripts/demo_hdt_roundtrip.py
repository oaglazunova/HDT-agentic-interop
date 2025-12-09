#!/usr/bin/env python3
"""
Demo: call 3 MCP tools in sequence and print JSON snippets.

Prereqs:
- Your Flask API is running (for live fetch fallback), OR your vault has data.
- ENV: MCP_CLIENT_ID, HDT_API_BASE, HDT_API_KEY (or MODEL_DEVELOPER_1_API_KEY)

Run:
  python scripts/demo_hdt_roundtrip.py
"""

import os, json, sys
from pprint import pprint

# Import MCP tools from the server module
from HDT_MCP.server import (
    consent_status,          # consent.status@v1
    tool_get_walk_data,      # hdt.get_walk_data@v1
    intervention_time,       # intervention_time@v1
)

def _print(title, obj, max_chars=600):
    print(f"\n=== {title} ===")
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(txt) > max_chars:
        print(txt[:max_chars] + "\n... (truncated)")
    else:
        print(txt)

def main():
    # 1) Who am I allowed to access?
    client_id = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
    allowed = consent_status(client_id=client_id)
    _print("consent.status@v1 (allowed users)", allowed)

    users = allowed.get("users", [])
    if not users:
        print("\nNo permitted users for this client. Configure config/user_permissions.json.")
        sys.exit(0)

    # pick the first user with any permissions
    target = users[0]["user_id"]

    # 2) Fetch walk data for that user (MCP tool)
    walk = tool_get_walk_data(user_id=str(target))
    _print(f"hdt.get_walk_data@v1 (user_id={target})", walk)

    # 3) Ask for an intervention window (agentic, minimal heuristic)
    timing = intervention_time(local_tz="Europe/Amsterdam")
    _print("intervention_time@v1", timing)

    print("\nOK ✅ Demo completed.")

if __name__ == "__main__":
    main()
