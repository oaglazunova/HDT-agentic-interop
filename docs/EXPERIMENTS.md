
# Experiments

This document describes the reproducible workflow for:
- generating a task suite from normalized benchmark pairs,
- running a first experiment matrix (models × ablations × repeats),
- aggregating results into paper-ready tables.

## Overview

Pipeline:

1. Define normalized benchmark pairs (`config/benchmark_pairs.v0.json`)
2. Convert to evaluation tasks (`config/eval_tasks.generated.json`)
3. Run experiments (`scripts/eval_mapping_plans.py`)
4. Aggregate tables (`scripts/aggregate_experiment_summaries.py`)

## Step 1 — Define normalized benchmark pairs

Normalized “pair” format is intentionally simple and benchmark-agnostic:

- `pair_id`
- `contract` (`algo_id`, `algo_version`)
- `dataset` (`dataset_id`, `table_name`, `columns[]`)
- `required_fields[]` (`pointer`, `type`, optional `format`)
- optional `metadata`

Example file:
- `config/benchmark_pairs.v0.json`

## Step 2 — Generate evaluation tasks

Convert benchmark pairs into the compact evaluation task format:

```powershell
python scripts\build_eval_tasks_from_pairs.py `
  --pairs-json config\benchmark_pairs.v0.json `
  --out config\eval_tasks.generated.json
````

Sanity check:

```powershell
python -c "import json; d=json.load(open('config/eval_tasks.generated.json','r',encoding='utf-8')); print('tasks=',len(d['tasks']))"
```

## Step 3 — Run the first experiment matrix

### Conditions

Baseline:

* `initial_candidates=1`
* retriever ON
* seed hints ON

Ablations:

* retriever OFF (`--disable-retriever`)
* seed hints OFF (`--disable-seed-hints`)

### Run parameters

* repeats: `--repeats 5`
* repair budget: `--max-iters 3`
* initial candidates: `--initial-candidates 1` (baseline per spec)

### Example PowerShell runner

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

### Produced artifacts

For each `(model, condition)` you get:

* `*.jsonl` — per-run trace rows
* `*.summary.json` — overall aggregate summary
* `*.grouped.json` — grouped aggregate rows (by model + ablation settings)
* `*.by_task.json` — per-task aggregates

Key fields:

* `ok`, `iterations`, `elapsed_ms`
* `first_error_types` (helps characterize failure modes)
* `use_candidate_retrieval`, `use_seed_hints`, `initial_candidates`, `repeat_index`

## Step 4 — Aggregate to paper tables

Generate a CSV and a Markdown table:

```powershell
python scripts\aggregate_experiment_summaries.py `
  --root artifacts\experiments\v0 `
  --out-csv artifacts\experiments\v0\paper_table.v0.csv `
  --out-md artifacts\experiments\v0\paper_table.v0.md
```

The Markdown table is suitable for paper drafts or appendix.

## Interpretation guide (what to look for)

* Baseline vs `no_retriever`: sensitivity to evidence narrowing and schema size
* Baseline vs `no_seed_hints`: dependence on curated provider hints vs generic heuristics
* `first_error_types`: dominant failure modes by model/condition (e.g., missing pointer, unknown column, unsafe output)
* `avg_iterations`: whether `initial_candidates` reduces repair effort

## Reproducibility recommendations

* Keep the exact `benchmark_pairs.v0.json` and `eval_tasks.generated.json` used for any run.
* Archive the `*.summary.json` and `paper_table.*` files alongside the paper draft.
* Prefer running all models under identical `--max-iters`, `--repeats`, `--initial-candidates`.

````
