from __future__ import annotations

from scripts.eval_mapping_plans import (
    EvalResult,
    EvalTask,
    run_suite,
    summarize_results,
    summarize_results_by_task,
    summarize_results_grouped,
)
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash
from typing import Any, Mapping


class FakeAlwaysValidClient(OllamaClient):
    def __init__(self, expected_hash: str) -> None:
        super().__init__(OllamaConfig(model="dummy"))
        self.expected_hash = expected_hash

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "plan_version": "1.0",
            "plan_id": "repeat_valid_plan",
            "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
                "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
                "contract_hash": self.expected_hash,
            },
            "limits": {
                "max_rows": 10,
                "batch_rows": 5,
                "max_record_bytes": 1024,
                "max_total_output_bytes": 4096,
            },
            "required_columns": ["dob"],
            "record_mapping": {
                "/person/birthDate": {"op": "column", "name": "dob"},
            },
            "output": {
                "destination": "vault://results/repeat_valid_plan.jsonl",
                "format": "jsonl",
                "result_schema_ref": "oci://x#out",
            },
        }


def _task() -> EvalTask:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "properties": {
                    "birthDate": {"type": "string", "format": "date"},
                },
            }
        },
    }

    return EvalTask(
        task_id="birthdate_only",
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog={
            "datasets": [
                {
                    "dataset_id": "vault_dataset_A",
                    "tables": [
                        {
                            "table_name": "transactions",
                            "columns": [{"name": "dob", "type": "date"}],
                        }
                    ],
                }
            ]
        },
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
    )


def test_run_suite_repeats_tasks_and_records_repeat_index() -> None:
    task = _task()
    expected_hash = compute_contract_schema_hash(task.contract_input_schema)

    results = run_suite(
        client_factory=lambda: FakeAlwaysValidClient(expected_hash),
        model_label="dummy-model",
        tasks=[task],
        max_iters=3,
        initial_candidates=1,
        use_candidate_retrieval=True,
        use_seed_hints=False,
        repeats=3,
    )

    assert len(results) == 3
    assert [r.repeat_index for r in results] == [0, 1, 2]
    assert all(r.ok is True for r in results)


def test_summary_helpers_aggregate_runs_correctly() -> None:
    rows = [
        EvalResult(
            task_id="t1",
            model_label="m1",
            repeat_index=0,
            ok=True,
            iterations=1,
            elapsed_ms=100,
            initial_candidates=1,
            max_iters=3,
            use_candidate_retrieval=True,
            use_seed_hints=False,
            plan_id="p1",
            report_ok=True,
            error_count=0,
            warning_count=1,
            first_error_types=[],
            lint_warning_count=1,
            weighted_lint_score=3,
            used_required_columns=["a"],
            output_destination="vault://x",
        ),
        EvalResult(
            task_id="t1",
            model_label="m1",
            repeat_index=1,
            ok=False,
            iterations=3,
            elapsed_ms=300,
            initial_candidates=1,
            max_iters=3,
            use_candidate_retrieval=True,
            use_seed_hints=False,
            plan_id=None,
            report_ok=False,
            error_count=2,
            warning_count=0,
            first_error_types=["SomeErrorType"],
            lint_warning_count=0,
            weighted_lint_score=0,
            used_required_columns=[],
            output_destination=None,
        ),
        EvalResult(
            task_id="t2",
            model_label="m1",
            repeat_index=0,
            ok=True,
            iterations=2,
            elapsed_ms=200,
            initial_candidates=1,
            max_iters=3,
            use_candidate_retrieval=True,
            use_seed_hints=False,
            plan_id="p2",
            report_ok=True,
            error_count=0,
            warning_count=0,
            first_error_types=[],
            lint_warning_count=0,
            weighted_lint_score=0,
            used_required_columns=["b"],
            output_destination="vault://y",
        ),
    ]

    overall = summarize_results(rows)
    assert overall["runs"] == 3
    assert overall["ok"] == 2
    assert abs(overall["success_rate"] - (2 / 3)) < 1e-9
    assert abs(overall["avg_elapsed_ms"] - 200.0) < 1e-9
    assert abs(overall["avg_iterations"] - 2.0) < 1e-9

    grouped = summarize_results_grouped(rows)
    assert len(grouped) == 1
    assert grouped[0]["model_label"] == "m1"
    assert grouped[0]["runs"] == 3
    assert grouped[0]["ok"] == 2

    by_task = summarize_results_by_task(rows)
    assert len(by_task) == 2
    t1 = next(row for row in by_task if row["task_id"] == "t1")
    t2 = next(row for row in by_task if row["task_id"] == "t2")

    assert t1["runs"] == 2
    assert t1["ok"] == 1
    assert t2["runs"] == 1
    assert t2["ok"] == 1

    assert abs(overall["avg_lint_warning_count"] - (1 / 3)) < 1e-9
    assert abs(overall["avg_weighted_lint_score"] - 1.0) < 1e-9
