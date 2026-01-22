#!/usr/bin/env bash
set -euo pipefail

# MCP Inspector → External HDT Gateway (stdio)
# Run from repo root with an activated venv.

npx -y @modelcontextprotocol/inspector \
  -e HDT_VAULT_ENABLE=1 \
  -e HDT_VAULT_PATH=artifacts/vault/hdt_vault_ieee_demo.sqlite \
  -- python -m hdt_mcp.gateway
