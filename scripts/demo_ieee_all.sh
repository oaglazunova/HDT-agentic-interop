#!/usr/bin/env bash
set -euo pipefail

# IEEE artifact-evaluation demo runner (Linux/macOS/Git Bash).
#
# IMPORTANT (Windows/Git Bash):
# - Ensure the repo root is resolved to a Windows path for the Python subprocesses.
# - Prefer PowerShell runner (scripts/demo_ieee_all.ps1) if you hit any stdio/anyio edge cases.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_POSIX="$(cd "$SCRIPT_DIR/.." && pwd)"

# Export an explicit repo root so Python resolves config/artifacts under the repository.
if command -v cygpath >/dev/null 2>&1; then
  export HDT_REPO_ROOT="$(cygpath -w "$REPO_POSIX")"
else
  export HDT_REPO_ROOT="$REPO_POSIX"
fi

cd "$REPO_POSIX"

python scripts/init_sample_config.py
python scripts/init_sample_vault.py

python scripts/demo_ieee_privacy.py
python scripts/demo_ieee_transparency.py
python scripts/demo_ieee_policy_matrix.py

echo
echo "Done. See artifacts/telemetry and artifacts/vault for generated demo artifacts."
