# Benchmark Task Conversion

This repository uses a two-step conversion path for evaluation tasks:

1. Normalize external benchmark records into `benchmark_pairs` JSON
2. Convert them into evaluation task JSON with:

```powershell
python scripts/build_eval_tasks_from_pairs.py `
  --pairs-json config\benchmark_pairs.sample.json `
  --out config\eval_tasks.generated.json
```

The normalized pair format is intentionally simple:

`pair_id`
`contract`
`dataset`
`required_fields`
`optional metadata`

This avoids binding the evaluation harness directly to any one upstream benchmark schema.


---

# Run order

Run the new converter tests first:

```bash
pytest tests/unit/test_build_eval_tasks_from_pairs.py -q
```

Then the existing task-loader tests:

`pytest tests/unit/test_eval_task_loader.py -q`

Then the harness tests:
```
pytest tests/unit/test_eval_mapping_plans.py \
       tests/unit/test_eval_mapping_plans_repeat_summary.py -q
```
Then full:
`
pytest -q`

## How to use it

Convert benchmark-like pairs into eval tasks
```
python scripts\build_eval_tasks_from_pairs.py `
  --pairs-json config\benchmark_pairs.sample.json `
  --out config\eval_tasks.generated.json
  ```

Run the evaluation harness on the generated task set
```
python scripts\eval_mapping_plans.py `
  --model qwen2.5:7b-instruct-q4_0 `
  --tasks-json config\eval_tasks.generated.json `
  --out artifacts\eval_generated.jsonl `
  --summary-out artifacts\eval_generated.summary.json `
  --grouped-out artifacts\eval_generated.grouped.json `
  --task-summary-out artifacts\eval_generated.by_task.json `
  --repeats 5 `
  --initial-candidates 3
  ```

That gives a complete path from benchmark-shaped inputs to paper-ready outputs.
