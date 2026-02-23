# HDT-agentic-interop

Prototype codebase for **agentic interoperability** around longitudinal, user-controlled lifestyle/context data (HDT-like),
with **policy-aware transparency**, deterministic validation, and an **A2A-based negotiation loop** that produces
a machine-executable **Mapping Plan**.

> Scope note: this repo targets *lifestyle & context* data (not EHR/medical files). It supports lifestyle coaching
> and research instrumentation (e.g., intervention studies).

---

## What this repo provides

### Core building blocks
- **Mapping Plan format + validator** (`src/hdt_mapping_plan/`)
  - JSON Schema (`schema/mapping-plan.schema.json`)
  - Deterministic validator (schema + semantic/type checks)
  - Optional deterministic linter/scorer
  - Canonicalization/normalization for stable diffs

- **A2A agents + host runner** (`src/hdt_a2a/`, `src/hdt_provider_a2a/`, `src/hdt_user_a2a/`)
  - **Provider Agent** serves contract bundle (contract + input/output schemas + hash)
  - **User Agent** synthesizes a Mapping Plan Candidate via **Ollama structured outputs** + repair loop
  - **Host runner** orchestrates calls, validates deterministically, writes artifacts

- **MCP servers** (existing flows)
  - `src/hdt_mcp/gateway.py`
  - `src/hdt_sources_mcp/server.py`

---

## Repository layout (high-level)

- `src/hdt_mapping_plan/` — Mapping Plan schema, validator, linter, normalization
- `src/hdt_a2a/` — shared A2A utilities + host runner
- `src/hdt_provider_a2a/` — Provider A2A server + contract registry
- `src/hdt_user_a2a/` — User A2A server + LLM/repair loop integration
- `artifacts/` — generated outputs (plans, run manifests, demo vaults, logs)
- `data/` — sample data assets (e.g., example vault DB)
- `tests/` — unit tests

---

## Prerequisites

- Python (use the version pinned by `.python-version` if you use `pyenv`)
- Windows/macOS/Linux supported
- Optional but recommended: `uv` or `pip` for virtualenv management

### Ollama (for LLM structured outputs)
Install Ollama and ensure `ollama serve` is running.

Pull at least one model. Example:
```powershell
ollama pull qwen2.5:7b-instruct-q4_0
ollama list
```

---

## Install (dev)

From repo root:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Run tests:
```powershell
pytest -q
```

---

## A2A Mapping Plan negotiation (Phase-1)

Phase-1 workflow to synthesize a `MappingPlanCandidate` using:

- **Provider A2A agent**: deterministic contract bundle (schema + expected hash)
- **User A2A agent**: uses Ollama (`/api/chat`) with JSON Schema **structured outputs** to generate a plan and iteratively repairs it using deterministic validator feedback
- **Host runner**: orchestrates calls and writes artifacts to `artifacts/mapping_plans/`

### PowerShell note about line continuation
PowerShell uses backtick (`` ` ``) for line continuation — **not** `\`.

### Start the A2A agents (two terminals)

**Terminal 1 — Provider agent**
```powershell
hdt-provider-a2a
# If you don't have console scripts yet, equivalent:
# python -m hdt_provider_a2a.server
```

**Terminal 2 — User agent**
```powershell
$env:OLLAMA_URL="http://localhost:11434"
$env:OLLAMA_MODEL="qwen2.5:7b-instruct-q4_0"
hdt-user-a2a
# Equivalent:
# python -m hdt_user_a2a.server
```

### Run the host negotiation (writes artifacts)

Use a Vault SQLite DB as the source-of-truth catalog (Phase-1 MVP):

```powershell
hdt-a2a-negotiate `
  --algo-id provider.obesityCoach `
  --algo-version 0.1.0 `
  --vault-db artifacts\vault\hdt_vault_ieee_demo.sqlite `
  --dataset-id vault_dataset_A `
  --table-name transactions `
  --ollama-url http://localhost:11434 `
  --model qwen2.5:7b-instruct-q4_0
```

Outputs:
- `artifacts/mapping_plans/<plan_id>.json` — **plan only**
- `artifacts/mapping_plans/<plan_id>.run.json` — run manifest (inputs + hashes + reports + iterations)

### Common issues

**Model not found**
If you see `model '...' not found`, run:
```powershell
ollama list
```
Then pass exactly one of the listed names via `--model`, or pull the model with:
```powershell
ollama pull <model-name>
```

**Wrong shell line breaks**
If you copied a command that uses `\` line continuation (bash style), rewrite using backtick (PowerShell) or put the command on one line.

---

## Mapping Plan validation (deterministic critic)

The deterministic validator is the source of truth (reproducible and enclave-friendly later).

- Schema: `src/hdt_mapping_plan/schema/mapping-plan.schema.json`
- Validator: `src/hdt_mapping_plan/validate.py`

Typical checks include:
- referenced columns exist in the selected dataset/table schema
- operations are allowlisted
- contract hash integrity
- JSON pointers exist in the provider input schema
- type compatibility between vault columns and contract fields
- output confinement rules (e.g., destination allowlists)

---

## Configuration

### Env vars (used by LLM adapter / user agent)
- `OLLAMA_URL` (default: `http://localhost:11434`)
- `OLLAMA_MODEL` (example: `qwen2.5:7b-instruct-q4_0`)
- `OLLAMA_TIMEOUT_S` (default: `300`)
- `OLLAMA_NUM_PREDICT` (default: `1600`)
- `OLLAMA_NUM_CTX` (default: `4096`)
- `OLLAMA_STRUCTURED_MODE` (default: `json`)
- `OLLAMA_FALLBACK_TO_JSON` (default: `0`)

### Host runner CLI
```powershell
hdt-a2a-negotiate --help
```

Useful flags:
- `--user-url` and `--provider-url` (override default agent endpoints)
- `--ollama-url` and `--model` (forwarded to User Agent per run)
- `--max-iters` (repair iterations inside User Agent)
- `--out-dir` (where artifacts are written)

---

## MCP servers (existing)

These are already present and can be run independently of A2A:
```powershell
python -m hdt_mcp.gateway
python -m hdt_sources_mcp.server
```

---

## Development notes

### Style + QA
- Run formatting/linting hooks (if configured) via `pre-commit`
- Ensure tests pass: `pytest -q`

### Artifacts
Generated artifacts go under `artifacts/`. Keep large or sensitive files out of git.

---

## License
See `LICENSE`.
