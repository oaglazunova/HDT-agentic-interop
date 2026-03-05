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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from hdt_a2a.llm.loop import synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash


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
	ok: bool
	iterations: int
	elapsed_ms: int
	initial_candidates: int
	max_iters: int
	plan_id: str | None
	report_ok: bool | None
	error_count: int
	warning_count: int
	lint_warning_count: int
	used_required_columns: list[str]
	output_destination: str | None
	use_candidate_retrieval: bool
	use_seed_hints: bool


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


def _load_tasks_from_json(path: Path) -> list[EvalTask]:
	raw = json.loads(path.read_text(encoding="utf-8"))
	tasks: list[EvalTask] = []

	for item in raw:
		tasks.append(
			EvalTask(
				task_id=str(item["task_id"]),
				contract=dict(item["contract"]),
				contract_input_schema=dict(item["contract_input_schema"]),
				vault_catalog=dict(item["vault_catalog"]),
				dataset_columns={str(x) for x in item["dataset_columns"]},
				dataset_column_types={str(k): str(v) for k, v in item["dataset_column_types"].items()},
			)
		)

	return tasks


def _make_ollama_client(model_name: str) -> OllamaClient:
	return OllamaClient(OllamaConfig(model=model_name))


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
) -> EvalResult:
	client = client_factory()

	start = time.perf_counter()
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

	lint_warning_count = 0
	if report is not None:
		lint_warning_count = sum(
			1
			for w in report.warnings
			if str(getattr(w, "code", "")).startswith("LINT_")
		)

	report_ok = report.ok if report is not None else None

	return EvalResult(
		task_id=task.task_id,
		model_label=model_label,
		ok=res.ok,
		iterations=res.iterations,
		elapsed_ms=elapsed_ms,
		initial_candidates=initial_candidates,
		max_iters=max_iters,
		plan_id=plan_id,
		report_ok=report_ok,
		error_count=error_count,
		warning_count=warning_count,
		lint_warning_count=lint_warning_count,
		used_required_columns=used_required_columns,
		output_destination=output_destination,
		use_candidate_retrieval=use_candidate_retrieval,
		use_seed_hints=use_seed_hints,
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
) -> list[EvalResult]:
	return [
		run_one(
			client_factory=client_factory,
			model_label=model_label,
			task=task,
			max_iters=max_iters,
			initial_candidates=initial_candidates,
			use_candidate_retrieval=use_candidate_retrieval,
			use_seed_hints=use_seed_hints,
		)
		for task in tasks
	]


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
	return parser.parse_args()


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
	)

	out_path = Path(args.out)
	out_path.parent.mkdir(parents=True, exist_ok=True)

	with out_path.open("w", encoding="utf-8") as f:
		for row in results:
			f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

	total = len(results)
	ok_count = sum(1 for r in results if r.ok)

	summary = {
		"model": args.model,
		"tasks": total,
		"ok": ok_count,
		"success_rate": (ok_count / total) if total else 0.0,
		"avg_elapsed_ms": (sum(r.elapsed_ms for r in results) / total) if total else 0.0,
		"avg_iterations": (sum(r.iterations for r in results) / total) if total else 0.0,
		"use_candidate_retrieval": use_candidate_retrieval,
		"use_seed_hints": use_seed_hints,
	}
	print(json.dumps(summary, ensure_ascii=False))

	return 0


if __name__ == "__main__":
	raise SystemExit(main())