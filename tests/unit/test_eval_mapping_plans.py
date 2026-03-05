from __future__ import annotations

from typing import Any, Mapping

from scripts.eval_mapping_plans import EvalTask, run_one
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash


class FakeAlwaysValidClient(OllamaClient):
	def __init__(self, expected_hash: str) -> None:
		super().__init__(OllamaConfig(model="dummy"))
		self.expected_hash = expected_hash

	def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
		return {
			"plan_version": "1.0",
			"plan_id": "eval_valid_plan",
			"algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
			"dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
			"contract": {
				"contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
				"input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
				"contract_hash": self.expected_hash,
			},
			"limits": {
				"max_rows": 20,
				"batch_rows": 5,
				"max_record_bytes": 1024,
				"max_total_output_bytes": 12000,
			},
			"required_columns": ["dob"],
			"record_mapping": {
				"/person/birthDate": {"op": "column", "name": "dob"},
			},
			"output": {
				"destination": "vault://results/eval_valid_plan.jsonl",
				"format": "jsonl",
				"result_schema_ref": "oci://x#out",
			},
		}


def test_run_one_emits_structured_eval_result() -> None:
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

	expected_hash = compute_contract_schema_hash(contract_input_schema)

	task = EvalTask(
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

	result = run_one(
		client_factory=lambda: FakeAlwaysValidClient(expected_hash),
		model_label="dummy-model",
		task=task,
		max_iters=3,
		initial_candidates=1,
		use_candidate_retrieval=True,
		use_seed_hints=False,
	)

	assert result.task_id == "birthdate_only"
	assert result.model_label == "dummy-model"
	assert result.ok is True
	assert result.iterations >= 1
	assert result.plan_id == "eval_valid_plan"
	assert result.report_ok is True
	assert result.error_count == 0
	assert result.warning_count == 0
	assert result.lint_warning_count == 0
	assert result.used_required_columns == ["dob"]
	assert result.output_destination == "vault://results/eval_valid_plan.jsonl"
	assert result.use_candidate_retrieval is True
	assert result.use_seed_hints is False
