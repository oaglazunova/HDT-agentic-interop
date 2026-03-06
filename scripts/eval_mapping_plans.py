# one script that can run the same task cases through the same deterministic pipeline while varying only:
# the model / client
# initial_candidates
# retriever on/off
# seed hints on/off
# The script should emit structured results per run, e.g. JSONL.
#
# This script is needed for: reproducibility, paper tables, easy model comparison, ablation support

from __future__ import annotations

import argparse
import json
import time
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from hdt_a2a.llm.loop import synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


_LINT_WARNING_WEIGHTS: dict[str, int] = {
    "LINT_GROUPING_USED": 3,
    "LINT_ROW_FILTER_USED": 2,
    "LINT_MANY_CASTS": 2,
    "LINT_MANY_CONSTANTS": 1,
}

_DEFAULT_LINT_WARNING_WEIGHT = 1


@dataclass
class EvalTask:
    task_id: str
    contract: dict[str, Any]
    contract_input_schema: dict[str, Any]
    vault_catalog: dict[str, Any]
    dataset_columns: set[str]
    dataset_column_types: dict[str, str]


@dataclass
class EvalResult:
    task_id: str
    model_label: str
    repeat_index: int
    ok: bool
    iterations: int
    elapsed_ms: int
    initial_candidates: int
    max_iters: int
    use_candidate_retrieval: bool
    use_seed_hints: bool
    plan_id: str | None
    report_ok: bool | None
    error_count: int
    warning_count: int
    first_error_types: list[str]
    lint_warning_count: int
    weighted_lint_score: int
    used_required_columns: list[str]
    output_destination: str | None


# === helpers: ==============


def _compute_lint_metrics(report: Any) -> tuple[int, int]:
    """
    Return:
    - lint_warning_count
    - weighted_lint_score

    Only warnings whose code starts with 'LINT_' are counted.
    Unknown lint codes get the default weight.
    """
    if report is None:
        return 0, 0

    lint_warning_count = 0
    weighted_lint_score = 0

    for w in getattr(report, "warnings", []):
        code = str(getattr(w, "code", "") or "")
        if not code.startswith("LINT_"):
            continue
        lint_warning_count += 1
        weighted_lint_score += _LINT_WARNING_WEIGHTS.get(code, _DEFAULT_LINT_WARNING_WEIGHT)

    return lint_warning_count, weighted_lint_score


def _toy_tasks() -> list[EvalTask]:
    """
    Minimal built-in tasks so the harness works immediately.
    Replace / extend with benchmark-backed tasks later.
    """
    task_1 = EvalTask(
        task_id="birthdate_only",
        contract={"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        contract_input_schema={
            "type": "object",
            "properties": {
                "person": {
                    "type": "object",
                    "required": ["birthDate"],
                    "properties": {
                        "birthDate": {"type": "string", "format": "date"},
                    },
                }
            },
            "required": ["person"],
        },
        vault_catalog={
            "datasets": [
                {
                    "dataset_id": "vault_dataset_A",
                    "tables": [
                        {
                            "table_name": "transactions",
                            "columns": [{"name": "dob", "type": "TEXT"}],
                        }
                    ],
                }
            ]
        },
        dataset_columns={"dob"},
        dataset_column_types={"dob": "TEXT"},
    )

    task_2 = EvalTask(
        task_id="birthdate_and_steps",
        contract={"algo_id": "provider.generic", "algo_version": "0.1.0"},
        contract_input_schema={
            "type": "object",
            "properties": {
                "person": {
                    "type": "object",
                    "required": ["birthDate"],
                    "properties": {
                        "birthDate": {"type": "string", "format": "date"},
                    },
                },
                "activity": {
                    "type": "object",
                    "required": ["stepCount"],
                    "properties": {
                        "stepCount": {"type": "integer"},
                    },
                },
            },
            "required": ["person", "activity"],
        },
        vault_catalog={
            "datasets": [
                {
                    "dataset_id": "vault_dataset_A",
                    "tables": [
                        {
                            "table_name": "transactions",
                            "columns": [
                                {"name": "birth_date", "type": "TEXT"},
                                {"name": "step_count", "type": "INTEGER"},
                                {"name": "noise", "type": "TEXT"},
                            ],
                        }
                    ],
                }
            ]
        },
        dataset_columns={"birth_date", "step_count", "noise"},
        dataset_column_types={
            "birth_date": "TEXT",
            "step_count": "INTEGER",
            "noise": "TEXT",
        },
    )

    return [task_1, task_2]


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field_name} must be a non-empty string")
    return s


def _normalize_column_list(columns_value: Any, *, field_name: str) -> list[dict[str, str]]:
    if not isinstance(columns_value, list) or not columns_value:
        raise ValueError(f"{field_name} must be a non-empty list")

    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for idx, col in enumerate(columns_value):
        if not isinstance(col, dict):
            raise ValueError(f"{field_name}[{idx}] must be an object")

        name = _require_non_empty_string(col.get("name"), field_name=f"{field_name}[{idx}].name")
        typ = _require_non_empty_string(col.get("type"), field_name=f"{field_name}[{idx}].type")

        if name in seen:
            raise ValueError(f"{field_name} contains duplicate column name: {name}")
        seen.add(name)

        out.append({"name": name, "type": typ})

    return out


def _task_from_explicit_record(item: Mapping[str, Any]) -> EvalTask:
    task_id = _require_non_empty_string(item.get("task_id"), field_name="task_id")
    contract = _require_mapping(item.get("contract"), field_name=f"{task_id}.contract")
    contract_input_schema = _require_mapping(
        item.get("contract_input_schema"),
        field_name=f"{task_id}.contract_input_schema",
    )
    vault_catalog = _require_mapping(item.get("vault_catalog"), field_name=f"{task_id}.vault_catalog")

    dataset_columns_raw = item.get("dataset_columns")
    if not isinstance(dataset_columns_raw, list) or not dataset_columns_raw:
        raise ValueError(f"{task_id}.dataset_columns must be a non-empty list")

    dataset_columns = {
        _require_non_empty_string(x, field_name=f"{task_id}.dataset_columns[]") for x in dataset_columns_raw
    }

    dataset_column_types_raw = item.get("dataset_column_types")
    if not isinstance(dataset_column_types_raw, dict) or not dataset_column_types_raw:
        raise ValueError(f"{task_id}.dataset_column_types must be a non-empty object")

    dataset_column_types = {
        _require_non_empty_string(k, field_name=f"{task_id}.dataset_column_types key"): _require_non_empty_string(
            v, field_name=f"{task_id}.dataset_column_types[{k}]"
        )
        for k, v in dataset_column_types_raw.items()
    }

    missing = sorted(dataset_columns - set(dataset_column_types))
    if missing:
        raise ValueError(f"{task_id}.dataset_column_types is missing entries for columns: {missing}")

    return EvalTask(
        task_id=task_id,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        dataset_columns=dataset_columns,
        dataset_column_types=dataset_column_types,
    )


def _task_from_compact_record(item: Mapping[str, Any]) -> EvalTask:
    task_id = _require_non_empty_string(item.get("task_id"), field_name="task_id")
    contract = _require_mapping(item.get("contract"), field_name=f"{task_id}.contract")
    contract_input_schema = _require_mapping(
        item.get("contract_input_schema"),
        field_name=f"{task_id}.contract_input_schema",
    )

    dataset_spec = _require_mapping(item.get("dataset_spec"), field_name=f"{task_id}.dataset_spec")
    dataset_id = _require_non_empty_string(
        dataset_spec.get("dataset_id"), field_name=f"{task_id}.dataset_spec.dataset_id"
    )
    table_name = _require_non_empty_string(
        dataset_spec.get("table_name"), field_name=f"{task_id}.dataset_spec.table_name"
    )
    columns = _normalize_column_list(dataset_spec.get("columns"), field_name=f"{task_id}.dataset_spec.columns")

    vault_catalog = {
        "datasets": [
            {
                "dataset_id": dataset_id,
                "tables": [
                    {
                        "table_name": table_name,
                        "columns": columns,
                    }
                ],
            }
        ]
    }

    dataset_columns = {col["name"] for col in columns}
    dataset_column_types = {col["name"]: col["type"] for col in columns}

    return EvalTask(
        task_id=task_id,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        dataset_columns=dataset_columns,
        dataset_column_types=dataset_column_types,
    )


def _normalize_task_record(item: Any) -> EvalTask:
    record = _require_mapping(item, field_name="task item")

    has_explicit = all(k in record for k in ("vault_catalog", "dataset_columns", "dataset_column_types"))
    has_compact = "dataset_spec" in record

    if has_explicit and has_compact:
        raise ValueError("task item must use either explicit shape or compact shape, not both")

    if has_explicit:
        return _task_from_explicit_record(record)

    if has_compact:
        return _task_from_compact_record(record)

    raise ValueError(
        "task item must contain either explicit fields "
        "(vault_catalog, dataset_columns, dataset_column_types) "
        "or compact field (dataset_spec)"
    )


def _load_tasks_from_json(path: Path) -> list[EvalTask]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        items = raw.get("tasks")
        if not isinstance(items, list):
            raise ValueError("tasks JSON object must contain a 'tasks' list")
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("tasks JSON must be either a list or an object with a 'tasks' list")

    tasks = [_normalize_task_record(item) for item in items]

    if not tasks:
        raise ValueError("tasks JSON must contain at least one task")

    seen_ids: set[str] = set()
    for task in tasks:
        if task.task_id in seen_ids:
            raise ValueError(f"duplicate task_id: {task.task_id}")
        seen_ids.add(task.task_id)

    return tasks


def _make_ollama_client(model_name: str) -> OllamaClient:
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    # IMPORTANT: bump default from 60s -> 600s for experiments
    timeout_s = float(os.getenv("OLLAMA_TIMEOUT_S", "600"))

    # Optional, but useful for larger prompts / structured outputs
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "900"))

    structured_mode = os.getenv("OLLAMA_STRUCTURED_MODE", "auto").strip().lower()
    if structured_mode not in ("json", "schema", "auto"):
        structured_mode = "auto"

    fallback_to_json = os.getenv("OLLAMA_FALLBACK_TO_JSON", "1").strip().lower() in ("1", "true", "yes", "on")

    cfg = OllamaConfig(
        base_url=base_url,
        model=model_name,
        timeout_s=timeout_s,
        num_ctx=num_ctx,
        num_predict=num_predict,
        structured_mode=structured_mode,  # type: ignore[arg-type]
        fallback_to_json_on_error=fallback_to_json,
    )
    return OllamaClient(cfg)


def _build_client_factory(model_name: str) -> Callable[[], Any]:
    """
    Returns a no-arg factory so each task run gets a fresh client if desired.
    """
    return lambda: _make_ollama_client(model_name)


def run_one(
    *,
    client_factory: Callable[[], Any],
    model_label: str,
    task: EvalTask,
    max_iters: int,
    initial_candidates: int,
    use_candidate_retrieval: bool,
    use_seed_hints: bool,
    repeat_index: int,
) -> EvalResult:
    client = client_factory()

    start = time.perf_counter()
    try:
        res = synthesize_plan_with_repairs(
            client=client,
            contract=task.contract,
            contract_input_schema=task.contract_input_schema,
            vault_catalog=task.vault_catalog,
            dataset_columns=task.dataset_columns,
            dataset_column_types=task.dataset_column_types,
            max_iters=max_iters,
            initial_candidates=initial_candidates,
            use_candidate_retrieval=use_candidate_retrieval,
            use_seed_hints=use_seed_hints,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

    except Exception as ex:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        # Produce a row that still lets aggregation work
        return EvalResult(
            task_id=task.task_id,
            model_label=model_label,
            repeat_index=repeat_index,
            ok=False,
            iterations=0,
            elapsed_ms=elapsed_ms,
            initial_candidates=initial_candidates,
            max_iters=max_iters,
            use_candidate_retrieval=use_candidate_retrieval,
            use_seed_hints=use_seed_hints,
            plan_id=None,
            report_ok=None,
            error_count=1,
            warning_count=0,
            first_error_types=[ex.__class__.__name__],
            used_required_columns=[],
            output_destination=None,
        )

    report = res.report
    plan = res.plan

    used_required_columns: list[str] = []
    output_destination: str | None = None
    plan_id: str | None = None

    if isinstance(plan, dict):
        plan_id = str(plan.get("plan_id")) if plan.get("plan_id") is not None else None
        req_cols = plan.get("required_columns")
        if isinstance(req_cols, list):
            used_required_columns = [str(x) for x in req_cols]
        output = plan.get("output")
        if isinstance(output, dict) and output.get("destination") is not None:
            output_destination = str(output["destination"])

    error_count = len(report.errors) if report is not None else 0
    warning_count = len(report.warnings) if report is not None else 0

    first_error_types: list[str] = []
    if report is not None:
        for err in report.errors:
            t = _extract_error_type(err)
            if t not in first_error_types:
                first_error_types.append(t)
            if len(first_error_types) >= 5:
                break

    lint_warning_count, weighted_lint_score = _compute_lint_metrics(report)

    report_ok = report.ok if report is not None else None

    return EvalResult(
        task_id=task.task_id,
        model_label=model_label,
        repeat_index=repeat_index,
        ok=res.ok,
        iterations=res.iterations,
        elapsed_ms=elapsed_ms,
        initial_candidates=initial_candidates,
        max_iters=max_iters,
        use_candidate_retrieval=use_candidate_retrieval,
        use_seed_hints=use_seed_hints,
        plan_id=plan_id,
        report_ok=report_ok,
        error_count=error_count,
        warning_count=warning_count,
        first_error_types=first_error_types,
        lint_warning_count=lint_warning_count,
        weighted_lint_score=weighted_lint_score,
        used_required_columns=used_required_columns,
        output_destination=output_destination,
    )


def run_suite(
    *,
    client_factory: Callable[[], Any],
    model_label: str,
    tasks: list[EvalTask],
    max_iters: int,
    initial_candidates: int,
    use_candidate_retrieval: bool,
    use_seed_hints: bool,
    repeats: int = 1,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    total_repeats = max(int(repeats), 1)

    for repeat_index in range(total_repeats):
        for task in tasks:
            results.append(
                run_one(
                    client_factory=client_factory,
                    model_label=model_label,
                    task=task,
                    max_iters=max_iters,
                    initial_candidates=initial_candidates,
                    use_candidate_retrieval=use_candidate_retrieval,
                    use_seed_hints=use_seed_hints,
                    repeat_index=repeat_index,
                )
            )

    return results


def _extract_error_type(err: Any) -> str:
    """
    Best-effort extraction of a stable error 'type' label for analysis.

    Supports:
    - dict errors (common for serialized reports)
    - objects with attributes (code/kind/type)
    - strings / unknown objects
    """
    if isinstance(err, dict):
        for k in ("code", "type", "kind", "name"):
            v = err.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        msg = err.get("message") or err.get("msg")
        if isinstance(msg, str) and msg.strip():
            # Keep it compact/stable-ish
            return msg.strip().split(":")[0][:80]

        return "dict_error"

    for attr in ("code", "type", "kind", "name"):
        v = getattr(err, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    if isinstance(err, str) and err.strip():
        return err.strip().split(":")[0][:80]

    return err.__class__.__name__


def summarize_results(results: list[EvalResult]) -> dict[str, Any]:
    total = len(results)
    ok_count = sum(1 for r in results if r.ok)

    return {
        "runs": total,
        "ok": ok_count,
        "success_rate": (ok_count / total) if total else 0.0,
        "avg_elapsed_ms": (sum(r.elapsed_ms for r in results) / total) if total else 0.0,
        "avg_iterations": (sum(r.iterations for r in results) / total) if total else 0.0,
        "avg_error_count": (sum(r.error_count for r in results) / total) if total else 0.0,
        "avg_warning_count": (sum(r.warning_count for r in results) / total) if total else 0.0,
        "avg_lint_warning_count": (sum(r.lint_warning_count for r in results) / total) if total else 0.0,
        "avg_weighted_lint_score": (sum(r.weighted_lint_score for r in results) / total) if total else 0.0,
    }


def summarize_results_grouped(results: list[EvalResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[EvalResult]] = {}

    for r in results:
        key = (
            r.model_label,
            r.initial_candidates,
            r.use_candidate_retrieval,
            r.use_seed_hints,
        )
        groups.setdefault(key, []).append(r)

    rows: list[dict[str, Any]] = []

    for key, group_rows in sorted(groups.items(), key=lambda item: item[0]):
        model_label, initial_candidates, use_candidate_retrieval, use_seed_hints = key
        total = len(group_rows)
        ok_count = sum(1 for r in group_rows if r.ok)

        rows.append(
            {
                "model_label": model_label,
                "initial_candidates": initial_candidates,
                "use_candidate_retrieval": use_candidate_retrieval,
                "use_seed_hints": use_seed_hints,
                "runs": total,
                "ok": ok_count,
                "success_rate": (ok_count / total) if total else 0.0,
                "avg_elapsed_ms": (sum(r.elapsed_ms for r in group_rows) / total) if total else 0.0,
                "avg_iterations": (sum(r.iterations for r in group_rows) / total) if total else 0.0,
                "avg_error_count": (sum(r.error_count for r in group_rows) / total) if total else 0.0,
                "avg_warning_count": (sum(r.warning_count for r in group_rows) / total) if total else 0.0,
                "avg_lint_warning_count": (sum(r.lint_warning_count for r in group_rows) / total) if total else 0.0,
                "avg_weighted_lint_score": (sum(r.weighted_lint_score for r in group_rows) / total) if total else 0.0,
            }
        )

    return rows


def summarize_results_by_task(results: list[EvalResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[EvalResult]] = {}

    for r in results:
        key = (r.model_label, r.task_id)
        groups.setdefault(key, []).append(r)

    rows: list[dict[str, Any]] = []

    for (model_label, task_id), group_rows in sorted(groups.items(), key=lambda item: item[0]):
        total = len(group_rows)
        ok_count = sum(1 for r in group_rows if r.ok)

        rows.append(
            {
                "model_label": model_label,
                "task_id": task_id,
                "runs": total,
                "ok": ok_count,
                "success_rate": (ok_count / total) if total else 0.0,
                "avg_elapsed_ms": (sum(r.elapsed_ms for r in group_rows) / total) if total else 0.0,
                "avg_iterations": (sum(r.iterations for r in group_rows) / total) if total else 0.0,
                "avg_error_count": (sum(r.error_count for r in group_rows) / total) if total else 0.0,
                "avg_warning_count": (sum(r.warning_count for r in group_rows) / total) if total else 0.0,
                "avg_lint_warning_count": (sum(r.lint_warning_count for r in group_rows) / total) if total else 0.0,
                "avg_weighted_lint_score": (sum(r.weighted_lint_score for r in group_rows) / total) if total else 0.0,
            }
        )

    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate mapping-plan synthesis across models.")
    parser.add_argument("--model", required=True, help="Model name / label (e.g. llama3.1:8b)")
    parser.add_argument("--tasks-json", default="", help="Optional JSON file with evaluation tasks.")
    parser.add_argument("--out", required=True, help="Output JSONL file path.")
    parser.add_argument("--max-iters", type=int, default=3)
    parser.add_argument("--initial-candidates", type=int, default=1)
    parser.add_argument(
        "--disable-retriever",
        action="store_true",
        help="Disable pointer-to-candidate retrieval hints in prompts.",
    )
    parser.add_argument(
        "--disable-seed-hints",
        action="store_true",
        help="Disable provider-specific seed hints while keeping generic retrieval on.",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Number of repeated runs per task.")
    parser.add_argument("--summary-out", default="", help="Optional JSON file for aggregate summary.")
    parser.add_argument("--grouped-out", default="", help="Optional JSON file for grouped summary rows.")
    parser.add_argument("--task-summary-out", default="", help="Optional JSON file for task-level grouped rows.")

    return parser.parse_args()


# === end helpers =============


def main() -> int:
    args = _parse_args()

    tasks = _load_tasks_from_json(Path(args.tasks_json)) if args.tasks_json else _toy_tasks()
    client_factory = _build_client_factory(args.model)

    use_candidate_retrieval = not bool(args.disable_retriever)
    use_seed_hints = not bool(args.disable_seed_hints)

    results = run_suite(
        client_factory=client_factory,
        model_label=args.model,
        tasks=tasks,
        max_iters=max(int(args.max_iters), 1),
        initial_candidates=max(int(args.initial_candidates), 1),
        use_candidate_retrieval=use_candidate_retrieval,
        use_seed_hints=use_seed_hints,
        repeats=max(int(args.repeats), 1),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    overall = summarize_results(results)
    grouped = summarize_results_grouped(results)
    by_task = summarize_results_by_task(results)

    summary = {
        "model": args.model,
        "repeats": max(int(args.repeats), 1),
        "tasks_defined": len(tasks),
        "initial_candidates": max(int(args.initial_candidates), 1),
        "max_iters": max(int(args.max_iters), 1),
        "use_candidate_retrieval": use_candidate_retrieval,
        "use_seed_hints": use_seed_hints,
        "task_groups": len(by_task),
        **overall,
    }

    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.grouped_out:
        grouped_path = Path(args.grouped_out)
        grouped_path.parent.mkdir(parents=True, exist_ok=True)
        grouped_path.write_text(json.dumps(grouped, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.task_summary_out:
        task_path = Path(args.task_summary_out)
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(json.dumps(by_task, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
