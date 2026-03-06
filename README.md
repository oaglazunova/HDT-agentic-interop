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
  - **Provider Agent** serves a contract bundle (contract + input/output schemas + expected hash)
  - **User Agent** synthesizes a Mapping Plan Candidate via **Ollama structured outputs** plus repair loop
  - **Host runner** orchestrates calls, validates deterministically, and writes artifacts

- **MCP servers** (existing flows)
  - `src/hdt_mcp/gateway.py`
  - `src/hdt_sources_mcp/server.py`

>See `docs/EXPERIMENTS.md` for the end-to-end workflow to generate task suites, run the first experiment matrix, and aggregate paper tables.

---

## Repository layout (high-level)

- `src/hdt_mapping_plan/` — Mapping Plan schema, validator, linter, normalization, candidate retrieval
- `src/hdt_a2a/` — shared A2A utilities + host runner
- `src/hdt_provider_a2a/` — Provider A2A server + contract registry
- `src/hdt_user_a2a/` — User A2A server + LLM/repair loop integration
- `demo/` — frozen demonstration scenarios (catalogs + walkthrough assets)
- `scripts/` — helper scripts, demo runners, and evaluation harnesses
  - `scripts/eval_mapping_plans.py` — multi-model evaluation runner for mapping-plan synthesis
- `config/` — runtime config plus sample evaluation task sets
  - `config/eval_tasks.sample.json` — example external task-set for the evaluation harness
- `artifacts/` — generated outputs (plans, run manifests, demo outputs, logs, evaluation JSONL/summary files)
- `data/` — sample data assets (example/demo vaults)
- `datasets/` — working logical vault catalogs for current development
- `docs/` — demo notes, appendix notes, and evaluation documentation
- `tests/` — unit tests and golden regression fixtures

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

Phase-1 synthesizes a `MappingPlanCandidate` using:

- **Provider A2A agent**: deterministic contract bundle (schema + expected hash)
- **User A2A agent**: uses Ollama (`/api/chat`) with JSON Schema **structured outputs** to generate a candidate and iteratively repair it using deterministic validator feedback
- **Host runner**: orchestrates calls and writes artifacts to `artifacts/mapping_plans/`

### Current Phase-1 source-of-truth

At the current architecture-first stage, the **preferred** source-of-truth is a **hand-authored logical vault catalog**:

- Preferred: `--vault-catalog datasets/vault_catalog.json`
- Secondary convenience path: `--vault-db ...` to derive a temporary catalog from a concrete SQLite schema

This keeps the negotiation interface stable **before** the final physical vault schema is fixed.

### PowerShell note about line continuation
PowerShell uses backtick (`` ` ``) for line continuation - **not** `\`.

### Start the A2A agents (two terminals)

**Terminal 1 - Provider agent**
```powershell
hdt-provider-a2a
# Equivalent:
# python -m hdt_provider_a2a.server
```

**Terminal 2 - User agent**
```powershell
$env:OLLAMA_URL="http://localhost:11434"
$env:OLLAMA_MODEL="qwen2.5:7b-instruct-q4_0"
hdt-user-a2a
# Equivalent:
# python -m hdt_user_a2a.server
```

### Run the host negotiation (logical catalog path)

```powershell
hdt-a2a-negotiate `
  --algo-id provider.obesityCoach `
  --algo-version 0.1.0 `
  --vault-catalog datasets\vault_catalog.json `
  --ollama-url http://localhost:11434 `
  --model qwen2.5:7b-instruct-q4_0
```

Outputs:
- `artifacts/mapping_plans/<plan_id>.json` - final Mapping Plan
- `artifacts/mapping_plans/<plan_id>.run.json` - run manifest (inputs + hashes + reports + iterations)

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

## Demonstration scenario

The repo includes a **frozen, presentation-friendly** demo scenario for mapping-plan negotiation:

- Scenario folder: `demo/scenarios/obesitycoach_daily_profile/`
- Frozen demo catalog: `demo/scenarios/obesitycoach_daily_profile/vault_catalog.json`
- Runner script: `scripts/demo_mapping_negotiation.ps1`

### Demo storyline

A provider-side algorithm (`provider.obesityCoach`, version `0.1.0`) publishes the fields it needs.
The user side does **not** expose a finalized physical database schema. Instead, it exposes a **logical vault view**:

- Dataset: `vault_dataset_A`
- Table: `daily_profile`

The negotiation goal is to synthesize a Mapping Plan that safely maps the logical user columns into the provider contract.

### Run the demo

**Terminal 1 - Provider agent**
```powershell
python -m hdt_provider_a2a.server
```

**Terminal 2 - User agent**
```powershell
python -m hdt_user_a2a.server
```

**Terminal 3 - Demo runner**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo_mapping_negotiation.ps1
```

The demo script runs the host against the frozen scenario catalog, writes artifacts to a dedicated demo output folder,
and prints a concise summary of the resulting Mapping Plan.

### What the demo proves

- contract retrieval from the Provider Agent
- use of a **logical** vault catalog instead of a finalized physical DB schema
- synthesis plus deterministic validation
- repair-loop convergence when the first candidate is imperfect
- final artifact persistence (`*.json`, `*.run.json`)

---

## Golden regression fixtures

The repo also includes deterministic end-to-end **golden fixtures** for mapping-plan negotiation under:

- `tests/fixtures/mapping_plan_golden/`

These freeze representative negotiation cases so future changes to prompts, repair logic, or validation do not silently break behavior.

### Demo-aligned golden fixture

The demonstration scenario has a matching test fixture:

- `tests/fixtures/mapping_plan_golden/demo_obesitycoach_daily_profile.json`

This keeps the live demo and the test suite aligned:

- **Live demo**: human-runnable scenario for walkthroughs and presentations
- **Golden fixture**: deterministic pytest case for regression protection

### Golden fixture test harness

The harness lives in:

- `tests/unit/test_mapping_plan_golden.py`

It loads fixture files (for example `case_*.json` and `demo_*.json`), feeds deterministic fake LLM outputs into the repair loop,
and asserts that the final Mapping Plan matches the expected result.

This is the key reproducibility layer for the negotiation prototype.

---

## Mapping Plan validation (deterministic critic)

The deterministic validator is the source of truth (reproducible now, enclave-friendly later).

- Schema: `src/hdt_mapping_plan/schema/mapping-plan.schema.json`
- Validator: `src/hdt_mapping_plan/validate.py`

Typical checks include:
- referenced columns exist in the selected dataset/table schema
- operations are allowlisted
- contract hash integrity
- JSON pointers exist in the provider input schema
- type compatibility between vault columns and contract fields
- output confinement rules (for example, destination allowlists)

---

---

## Evaluation harness (multi-model and ablation experiments)

The repo includes a lightweight experiment runner for comparing **different LLMs** and **prompting/runtime conditions** on the same mapping-plan synthesis tasks:

- Script: `scripts/eval_mapping_plans.py`
- Sample task file: `config/eval_tasks.sample.json`

This harness runs the same deterministic synthesis pipeline (`synthesize_plan_with_repairs`) while varying:

- LLM / model name
- number of initial candidates (`--initial-candidates`)
- repair budget (`--max-iters`)
- repeated runs per task (`--repeats`)
- retrieval hints on/off (`--disable-retriever`)
- provider seed hints on/off (`--disable-seed-hints`)

### What it writes

The harness writes:

- **per-run JSONL** (`--out`)  
  one row per task execution
- **overall summary JSON** (`--summary-out`)
- **grouped summary JSON** (`--grouped-out`)  
  grouped by model + ablation settings
- **task-level summary JSON** (`--task-summary-out`)

This is the recommended path for producing reproducible experiment artifacts for paper tables.

### Quick example

```powershell
python scripts/eval_mapping_plans.py `
  --model qwen2.5:7b-instruct-q4_0 `
  --tasks-json config\eval_tasks.sample.json `
  --out artifacts\eval_qwen25.jsonl `
  --summary-out artifacts\eval_qwen25.summary.json `
  --grouped-out artifacts\eval_qwen25.grouped.json `
  --task-summary-out artifacts\eval_qwen25.by_task.json `
  --repeats 5 `
  --initial-candidates 3 ```
  --max-iters 3 `
 ``` 

Example ablations

Disable retrieval hints entirely:
 ```
python scripts/eval_mapping_plans.py `
  --model qwen2.5:7b-instruct-q4_0 `
  --tasks-json config\eval_tasks.sample.json `
  --out artifacts\eval_no_retriever.jsonl `
  --disable-retriever
 ```  

Keep generic retrieval, but disable provider-specific seed hints:
 ```
python scripts/eval_mapping_plans.py `
  --model qwen2.5:7b-instruct-q4_0 `
  --tasks-json config\eval_tasks.sample.json `
  --out artifacts\eval_no_seed_hints.jsonl `
  --disable-seed-hints
  ```

Notes on reproducibility

The deterministic validator remains the source of truth for plan acceptance.
Repeated runs are recommended even when using structured outputs, because different models (or non-zero-temperature settings, if used) may still vary.
If --tasks-json is omitted, the harness falls back to small built-in toy tasks intended only for smoke testing. For real comparisons, prefer an external task file.


----

### External task-set format

The evaluation harness accepts task files in JSON via `--tasks-json`.

Two task shapes are supported:

1. **Compact shape (recommended)**  
   Best for benchmark conversion and hand-authored evaluation cases.  
   It uses `dataset_spec` and derives the internal vault catalog automatically.

2. **Explicit shape**  
   Mirrors the in-memory `EvalTask` structure and lets you provide `vault_catalog`, `dataset_columns`, and `dataset_column_types` directly.

The recommended compact shape looks like this:

```json
{
  "tasks": [
    {
      "task_id": "birthdate_only_compact",
      "contract": {
        "algo_id": "provider.obesityCoach",
        "algo_version": "0.1.0"
      },
      "contract_input_schema": {
        "type": "object",
        "properties": {
          "person": {
            "type": "object",
            "required": ["birthDate"],
            "properties": {
              "birthDate": { "type": "string", "format": "date" }
            }
          }
        },
        "required": ["person"]
      },
      "dataset_spec": {
        "dataset_id": "vault_dataset_A",
        "table_name": "transactions",
        "columns": [
          { "name": "dob", "type": "TEXT" }
        ]
      }
    }
  ]
}
```

For a fuller example, see `config/eval_tasks.sample.json`
For the full loader rules and experiment workflow, see `docs/EVALUATION.md`

----

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
- `--vault-catalog` (preferred Phase-1 logical catalog path)
- `--vault-db` (secondary temporary catalog generation path)
- `--dataset-id` and `--table-name` (force a specific dataset/table when needed)
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


## Experiments: first task suite + first experiment matrix

This repo includes a reproducible workflow to:
1) generate an evaluation task suite from normalized benchmark pairs,
2) run a small experiment matrix across models and ablations, and
3) aggregate results into paper-ready tables.

### 1) Generate `config/eval_tasks.generated.json` from normalized pairs

Create or edit a normalized pair file (example template):
- `config/benchmark_pairs.v0.json`

Then generate evaluation tasks (compact task format):

```powershell
python scripts\build_eval_tasks_from_pairs.py `
  --pairs-json config\benchmark_pairs.v0.json `
  --out config\eval_tasks.generated.json
````

Sanity check:

```powershell
python -c "import json; d=json.load(open('config/eval_tasks.generated.json','r',encoding='utf-8')); print('tasks=',len(d['tasks']))"
```

### 2) Run the first experiment matrix (3 conditions × N models × 5 repeats)

Baseline:

* `initial_candidates=1`
* retriever ON
* seed hints ON

Ablations:

* retriever OFF (`--disable-retriever`)
* seed hints OFF (`--disable-seed-hints`)

Example PowerShell runner:

```powershell
$models = @(
  "qwen2.5:7b-instruct-q4_0",
  "llama3.1:8b-instruct-q4_0",
  "mistral:7b-instruct-q4_0"
)

$tasks = "config\eval_tasks.generated.json"
$root = "artifacts\experiments\v0"

$conditions = @(
  @{ name = "baseline"; args = @() },
  @{ name = "no_retriever"; args = @("--disable-retriever") },
  @{ name = "no_seed_hints"; args = @("--disable-seed-hints") }
)

foreach ($m in $models) {
  $mDirName = $m.Replace(":", "_")
  $outDir = Join-Path $root $mDirName
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null

  foreach ($c in $conditions) {
    python scripts\eval_mapping_plans.py `
      --model $m `
      --tasks-json $tasks `
      --out (Join-Path $outDir "$($c.name).jsonl") `
      --summary-out (Join-Path $outDir "$($c.name).summary.json") `
      --grouped-out (Join-Path $outDir "$($c.name).grouped.json") `
      --task-summary-out (Join-Path $outDir "$($c.name).by_task.json") `
      --repeats 5 `
      --initial-candidates 1 `
      --max-iters 3 `
      @($c.args)
  }
}
```

Outputs per model/condition:

* `*.jsonl` (per-run traces)
* `*.summary.json` (overall summary)
* `*.grouped.json` (grouped aggregates)
* `*.by_task.json` (task-level aggregates)

### 3) Aggregate summaries into paper tables

Create paper-friendly tables:

```powershell
python scripts\aggregate_experiment_summaries.py `
  --root artifacts\experiments\v0 `
  --out-csv artifacts\experiments\v0\paper_table.v0.csv `
  --out-md artifacts\experiments\v0\paper_table.v0.md
```

The Markdown table (`paper_table.v0.md`) can be pasted directly into the paper appendix or draft.

For more details, see `docs/EXPERIMENTS.md`.


---

## Development notes

### Style + QA
- Run formatting/linting hooks (if configured) via `pre-commit`
- Ensure tests pass: `pytest -q`

### Artifacts
Generated artifacts go under `artifacts/`. This includes:

- Mapping Plans and run manifests from negotiation runs
- demo outputs and telemetry
- evaluation JSONL traces and summary JSON files from `scripts/eval_mapping_plans.py`

Keep large or sensitive files out of git.

### Demo stability
Keep frozen demo assets under `demo/` separate from the evolving working files under `datasets/`.
This prevents routine architecture changes from accidentally breaking the walkthrough scenario.

---

## License
See `LICENSE`.
