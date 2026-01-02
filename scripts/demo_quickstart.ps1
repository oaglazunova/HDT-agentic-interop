# scripts/demo_quickstart.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Run from repo root regardless of where the script is invoked from
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "Repo: $RepoRoot"

# Prefer Windows py launcher if present (avoids Git Bash python2 traps)
$HasPy = Get-Command py -ErrorAction SilentlyContinue

if (-not (Test-Path ".venv")) {
    if ($HasPy) {
        Write-Host "Creating venv with: py -3"
        py -3 -m venv .venv
    } else {
        Write-Host "Creating venv with: python"
        python -m venv .venv
    }
}

# Activate venv
. .\.venv\Scripts\Activate.ps1

Write-Host "Python:" (Get-Command python).Source
python --version

python -m pip install -U pip
python -m pip install -e ".[dev]"

Write-Host "`n== Smoke: Sources MCP =="
python scripts\test_sources_mcp.py

Write-Host "`n== Smoke: HDT MCP (Option D) =="
python scripts\test_hdt_mcp_option_d.py

Write-Host "`n== Unit tests =="
python -m pytest -q

Write-Host "`nDone."
