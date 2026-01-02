#!/usr/bin/env bash
# scripts/demo_quickstart.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
echo "Repo: $REPO_ROOT"

if [[ ! -d ".venv" ]]; then
  if command -v py >/dev/null 2>&1; then
    echo "Creating venv with: py -3"
    py -3 -m venv .venv
  elif command -v python3 >/dev/null 2>&1; then
    echo "Creating venv with: python3"
    python3 -m venv .venv
  else
    echo "Creating venv with: python"
    python -m venv .venv
  fi
fi

# Activate venv (Windows Git Bash vs POSIX)
if [[ -f ".venv/Scripts/activate" ]]; then
  source ".venv/Scripts/activate"
else
  source ".venv/bin/activate"
fi

which python
python --version

python -m pip install -U pip
python -m pip install -e ".[dev]"

echo
echo "== Smoke: Sources MCP =="
python scripts/test_sources_mcp.py

echo
echo "== Smoke: HDT MCP (Option D) =="
python scripts/test_hdt_mcp_option_d.py

echo
echo "== Unit tests =="
python -m pytest -q

echo
echo "Done."
