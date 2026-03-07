from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from scripts.eval_mapping_plans import EvalTask, run_one
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash


class FakeAlwaysInvalidClient(OllamaClient):
    def __init__(self, expected_hash: str) -> None:
        super().__init__(OllamaConfig(model="dummy"))
        self.expected_hash = expected_hash

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        # Return a clearly invalid plan (missing required mapping etc.)
        return {
            "plan_version": "1.0",
            "plan_id": "invalid",
            "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
                "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
                "contract_hash": self.expected_hash,
            },
            "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
            "record_mapping": {},  # invalid
            "required_columns": [],
            "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
        }


def test_dump_plans_dir_writes_failure_files(tmp_path: Path) -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    schema = {
        "type": "object",
        "properties": {
            "person": {"type": "object", "required": ["birthDate"], "properties": {"birthDate": {"type": "string"}}}
        },
        "required": ["person"],
    }
    expected_hash = compute_contract_schema_hash(schema)

    task = EvalTask(
        task_id="t_fail",
        contract=contract,
        contract_input_schema=schema,
        vault_catalog={
            "datasets": [
                {
                    "dataset_id": "vault_dataset_A",
                    "tables": [{"table_name": "transactions", "columns": [{"name": "dob", "type": "TEXT"}]}],
                }
            ]
        },
        dataset_columns={"dob"},
        dataset_column_types={"dob": "TEXT"},
    )

    dump_dir = tmp_path / "dumps"

    res = run_one(
        client_factory=lambda: FakeAlwaysInvalidClient(expected_hash),
        model_label="dummy",
        task=task,
        max_iters=1,
        initial_candidates=1,
        use_candidate_retrieval=True,
        use_seed_hints=True,
        repeat_index=0,
        dump_dir=dump_dir,
    )

    assert res.ok is False
    assert (dump_dir / "t_fail.0.plan.json").exists()
    assert (dump_dir / "t_fail.0.report.json").exists()

    payload = json.loads((dump_dir / "t_fail.0.report.json").read_text(encoding="utf-8"))
    assert "final_report" in payload
