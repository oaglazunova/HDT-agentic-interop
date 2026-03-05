# Evaluation Harness

This document describes the experiment runner used to compare LLMs and ablations for Mapping Plan synthesis.

## Purpose

`scripts/eval_mapping_plans.py` runs the same deterministic synthesis pipeline across a task suite while varying:

- model / client
- number of initial candidates
- repair budget
- repeated runs
- retrieval hints on/off
- provider seed hints on/off

It is intended for:

- reproducible local experiments
- ablation studies
- paper tables and appendix artifacts

It is **not** the main online negotiation path; it is an experiment harness around that path.

---

## Core outputs

The runner can write:

- `--out`: JSONL file with one row per task run
- `--summary-out`: overall aggregate summary
- `--grouped-out`: grouped aggregate rows by model + ablation settings
- `--task-summary-out`: grouped rows by task

These outputs are designed to be easy to archive and compare across runs.

---

## Recommended workflow

1. Define or select a task set (`--tasks-json`)
2. Run one model with chosen settings
3. Repeat with:
   - a different model
   - different `--initial-candidates`
   - `--disable-retriever`
   - `--disable-seed-hints`
4. Compare the emitted JSON summaries

---

## CLI overview

```powershell
python scripts/eval_mapping_plans.py `
  --model qwen2.5:7b-instruct-q4_0 `
  --tasks-json config\eval_tasks.sample.json `
  --out artifacts\eval_qwen25.jsonl `
  --summary-out artifacts\eval_qwen25.summary.json `
  --grouped-out artifacts\eval_qwen25.grouped.json `
  --task-summary-out artifacts\eval_qwen25.by_task.json `
  --repeats 5 `
  --initial-candidates 3 `
  --max-iters 3
```

## Important flags

`--model` — model name / label
`--tasks-json` — external task-set file
`--out` — per-run JSONL output
`--repeats` — repeated runs per task
`--initial-candidates` — number of initial synthesized candidates
`--max-iters` — max repair iterations
`--disable-retriever` — remove pointer-to-candidate retrieval hints
`--disable-seed-hints` — keep generic retrieval, but disable provider-specific seed hints

## Task file format

The loader accepts either:

a raw JSON list of tasks, or an object of the form `{ "tasks": [...] }`
Task IDs must be unique.

## Compact shape (recommended)

This shape is best for benchmark-style task generation.
```
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
```

dataset_spec is expanded internally into: `vault_catalog`, `dataset_columns`, `dataset_column_types`

## Explicit shape

This shape mirrors the in-memory task structure more directly:
```
{
  "task_id": "explicit_task",
  "contract": {
    "algo_id": "provider.generic",
    "algo_version": "0.1.0"
  },
  "contract_input_schema": {
    "type": "object"
  },
  "vault_catalog": {
    "datasets": [
      {
        "dataset_id": "vault_dataset_A",
        "tables": [
          {
            "table_name": "transactions",
            "columns": [
              { "name": "dob", "type": "TEXT" }
            ]
          }
        ]
      }
    ]
  },
  "dataset_columns": ["dob"],
  "dataset_column_types": {
    "dob": "TEXT"
  }
}
```
Use the explicit shape only if you need full control over the internal structures.

## Interpreting results

Useful fields in the JSONL output include:

`ok`
`iterations`
`elapsed_ms`
`error_count`
`warning_count`
`lint_score`
`use_candidate_retrieval`
`use_seed_hints`
`repeat_index`

## Recommended paper views:

success rate by model
success rate with/without retrieval
success rate with/without seed hints
average iterations by model
per-task success rate (task difficulty profile)

## Reproducibility notes

The validator is deterministic and remains the acceptance boundary.
Repeated runs are still useful because model outputs may vary across calls.
For real experiments, prefer external task files over built-in toy tasks.
Keep experiment outputs under artifacts/ and archive the exact task JSON used for a run.