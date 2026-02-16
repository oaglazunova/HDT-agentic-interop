from __future__ import annotations

from typing import Any, Mapping

from hdt_a2a.llm.loop import synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash  # <-- add this


class FakeOllama(OllamaClient):
    def __init__(self, *, contract_hash: str) -> None:
        super().__init__(OllamaConfig(model="dummy"))
        self.calls = 0
        self.contract_hash = contract_hash

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        self.calls += 1

        if self.calls == 1:
            return {
                "plan_version": "1.0",
                "plan_id": "bad_plan",
                "algo": {"algo_id": "provider.riskScore", "algo_version": "1.2.0"},
                "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
                "contract": {
                    "contract_ref": "oci://x/contracts/provider.riskScore:1.2.0",
                    "input_schema_ref": "oci://x/contracts/provider.riskScore:1.2.0#input.schema.json",
                    "contract_hash": self.contract_hash,  # <-- use computed
                },
                "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
                "required_columns": [],  # schema-invalid on purpose
                "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
                "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
            }

        return {
            "plan_version": "1.0",
            "plan_id": "good_plan",
            "algo": {"algo_id": "provider.riskScore", "algo_version": "1.2.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.riskScore:1.2.0",
                "input_schema_ref": "oci://x/contracts/provider.riskScore:1.2.0#input.schema.json",
                "contract_hash": self.contract_hash,  # <-- use computed
            },
            "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
            "required_columns": ["dob"],
            "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
            "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
        }


def test_synthesize_plan_with_repairs_stops_on_ok() -> None:
    contract = {"algo_id": "provider.riskScore", "algo_version": "1.2.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {"person": {"type": "object", "properties": {"birthDate": {"type": "string"}}}},
    }

    expected_hash = compute_contract_schema_hash(contract_input_schema)  # <-- compute once
    client = FakeOllama(contract_hash=expected_hash)

    vault_catalog = {
        "datasets": [
            {"dataset_id": "vault_dataset_A", "tables": [{"table_name": "transactions", "columns": [{"name": "dob", "type": "date"}]}]}
        ]
    }

    res = synthesize_plan_with_repairs(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
        max_iters=3,
    )

    assert res.ok is True
    assert res.report.errors == []
    assert res.plan["plan_id"] == "good_plan"
    assert res.iterations == 2
    assert len(res.reports) == 2
