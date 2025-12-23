$ErrorActionPreference = "Stop"

<#
IEEE artifact-evaluation demo runner (Windows PowerShell).

Assumes you have already created and activated a venv and installed deps:
  python -m pip install -e "./.[dev]"
#>

# Ensure all scripts resolve paths under the repository (important for configs/policies/artifacts).
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:HDT_REPO_ROOT = $repoRoot

python scripts/init_sample_config.py
python scripts/init_sample_vault.py

python scripts/demo_ieee_privacy.py
python scripts/demo_ieee_transparency.py
python scripts/demo_ieee_policy_matrix.py

Write-Host ""
Write-Host "Done. See artifacts/telemetry and artifacts/vault for generated demo artifacts."
