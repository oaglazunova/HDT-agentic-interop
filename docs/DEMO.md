# Demo

This repo includes a deterministic, offline-friendly demo that showcases key features around privacy, transparency, and policy management:
- purpose-based access control (lanes)
- deny-fast vs modeling-safe outputs
- redaction/shaping for analytics vs coaching
- auditable telemetry with correlation IDs
- policy matrix across clients × purposes × tools

## Prerequisites

- Windows + PowerShell
- Python environment (use the repo’s `.venv` if you have it; otherwise create one)
- Dependencies installed (recommended: editable install with dev extras)

From repo root:

```powershell
# create venv if needed
python -m venv .venv

# activate
.\.venv\Scripts\Activate.ps1

# install deps
python -m pip install -U pip
python -m pip install -e "./.[dev]"
````

## Run the full demo

From the repository root:

```powershell
.\scripts\demo_ieee_all.ps1
```

If PowerShell blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_ieee_all.ps1
```

### What you should see

The script runs three parts in sequence:

1. **Privacy & purpose lanes**

   * modeling + `hdt.walk.fetch.v1` → denied
   * modeling + `hdt.walk.features.v1` → allowed, modeling-safe aggregate features
   * coaching vs analytics redaction differences on `hdt.walk.fetch.v1`
   * policy explain for a tool/purpose

2. **Transparency / traceability (telemetry)**

   * a correlated call to `hdt.walk.fetch.v1` (prefer_data=vault)
   * telemetry via `hdt.telemetry.recent.v1`
   * a JSONL summary filtered by `corr_id` (includes tool, purpose, status, policy, request_id)

3. **Policy matrix**

   * runs a compact matrix across representative clients and purposes for a small tool set
   * prints a “Full JSON” payload suitable for paper appendix capture

## Outputs (artifacts)

The demo writes all outputs under `artifacts/`:

* **Vault DB (seeded demo data)**
  `artifacts/vault/hdt_vault_ieee_demo.sqlite`

* **Telemetry (JSONL + per-run folders)**
  `artifacts/telemetry/demo_ieee_*`
  Example: `artifacts/telemetry/demo_ieee_trace_YYYYMMDD_HHMMSS/mcp-telemetry.jsonl`

These artifacts are intended for local runs and paper screenshots; they should not be committed.

## Run individual demo scripts (optional)

You can run each part independently from repo root:

```powershell
python scripts/demo_ieee_privacy.py
python scripts/demo_ieee_transparency.py
python scripts/demo_ieee_policy_matrix.py
```

The transparency demo is often the one you want for appendix screenshots because it produces:

* a tool output excerpt
* a recent telemetry readout
* a filtered JSONL summary for the same `corr_id`

## Deterministic/offline behavior

The demo is designed to run without external systems by seeding a local vault database and using:

* `prefer_data=vault` in calls where appropriate
* a fixed demo policy file:
  `config/policy_ieee_demo.json`

If you want to force vault usage from the environment, set:

```powershell
$env:HDT_VAULT_ENABLE="1"
$env:HDT_VAULT_PATH="$(Resolve-Path .\artifacts\vault\hdt_vault_ieee_demo.sqlite)"
```

## Troubleshooting

### “running scripts is disabled on this system”

Run with bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_ieee_all.ps1
```

### Demo hangs on a tool call

The transparency demo uses a timeout (`HDT_DEMO_TIMEOUT_SEC`, default 30s). You can increase it:

```powershell
$env:HDT_DEMO_TIMEOUT_SEC="60"
python scripts/demo_ieee_transparency.py
```

### Missing policy file

Ensure this exists:

* `config/policy_ieee_demo.json`

### Telemetry file not found

The demo writes telemetry under the printed “Telemetry dir”. If the folder exists but is empty, verify:

* `HDT_TELEMETRY_DIR` is set by the script (it is)
* the run is not failing before any tool is called
