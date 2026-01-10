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

## Guardian auditor demo (optional)

This optional demo shows how a monitoring agent can be built *only* by calling telemetry tools (no direct file access).

1) Generate denied traces by simulating a misbehaving coaching agent:

```powershell
$env:HDT_POLICY_PATH="config/policy.guardian_demo.json"
$env:MCP_CLIENT_ID="COACHING_AGENT"
$env:HDT_TELEMETRY_SUBJECT_SALT="demo-salt"
python -u scripts/demo_coaching_agent_suspicious.py
```

2) Run the guardian to detect repeated policy denies via `hdt.telemetry.query.v1`:

```powershell
$env:HDT_POLICY_PATH="config/policy.guardian_demo.json"
$env:MCP_CLIENT_ID="GUARDIAN_AGENT"
$env:HDT_TELEMETRY_SUBJECT_SALT="demo-salt"
python -u scripts/demo_guardian_agent.py
```

Notes:

* The demo policy `config/policy.guardian_demo.json` denies raw fetch tools for `purpose=coaching`, so denied attempts are deterministic.
* `HDT_TELEMETRY_SUBJECT_SALT` enables a privacy-preserving `subject_hash` field in telemetry for per-subject governance.


## Demo: “What does the HDT know about me?” (user-facing transparency)

Purpose: demonstrate **user-facing transparency** using the same MCP tool surface as integration and governance.

### Steps

1) (Optional) Prepare deterministic data:

```bash
python scripts/init_sample_config.py
python scripts/init_sample_vault.py
````

2. Run the transparency agent:

PowerShell:

```powershell
$env:MCP_CLIENT_ID="TRANSPARENCY_AGENT"
$env:HDT_TELEMETRY_SUBJECT_SALT="demo-salt"
$env:HDT_VAULT_ENABLE="1"
$env:HDT_VAULT_PATH="artifacts/vault/hdt_vault_ieee_demo.sqlite"
python -u scripts/<YOUR_TRANSPARENCY_AGENT_SCRIPT>.py
```

Git Bash / macOS / Linux:

```bash
export MCP_CLIENT_ID="TRANSPARENCY_AGENT"
export HDT_TELEMETRY_SUBJECT_SALT="demo-salt"
export HDT_VAULT_ENABLE="1"
export HDT_VAULT_PATH="artifacts/vault/hdt_vault_ieee_demo.sqlite"
python -u scripts/<YOUR_TRANSPARENCY_AGENT_SCRIPT>.py
```

### Expected output (high level)

* Data inventory: which HDT domains exist (walk/diabetes/etc.), which sources are configured (e.g., GameBus/Google Fit/Vault).
* Recent access history (telemetry-derived): tool calls grouped by purpose (lane) and client_id.
* Traceability: correlation ids (`corr_id`) suitable for audit and debugging.

---

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
