from __future__ import annotations

from typing import Any, Mapping

import pytest

from hdt_a2a.llm.plan_synthesis import generate_mapping_plan_candidate
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


class FakeOllama(OllamaClient):
    def __init__(self) -> None:
        super().__init__(OllamaConfig(model="dummy"))

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        # Return a minimal plan matching your schema.
        # Keep it consistent with your example schema requirements.
        return {
            "plan_version": "1.0",
            "plan_id": "plan_test_0001",
            "algo": {"algo_id": "provider.riskScore", "algo_version": "1.2.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.riskScore:1.2.0",
                "input_schema_ref": "oci://x/contracts/provider.riskScore:1.2.0#input.schema.json",
                "contract_hash": "a" * 64,
            },
            "limits": {
                "max_rows": 10,
                "batch_rows": 5,
                "max_record_bytes": 1024,
                "max_total_output_bytes": 4096,
            },
            "required_columns": ["dob"],
            "record_mapping": {
                "/person/birthDate": {
                    "op": "cast",
                    "type": "string",
                    "args": [{"op": "parse_date", "format": "%Y-%m-%d", "args": [{"op": "column", "name": "dob"}]}],
                }
            },
            "output": {
                "destination": "vault://results/x.jsonl",
                "format": "jsonl",
                "result_schema_ref": "oci://x/contracts/provider.riskScore:1.2.0#output.schema.json",
            },
        }


def test_generate_mapping_plan_candidate_smoke() -> None:
    client = FakeOllama()

    contract = {"algo_id": "provider.riskScore", "algo_version": "1.2.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {"person": {"type": "object", "properties": {"birthDate": {"type": "string"}}}},
    }
    vault_catalog = {
        "datasets": [
            {
                "dataset_id": "vault_dataset_A",
                "tables": [
                    {"table_name": "transactions", "columns": [{"name": "dob", "type": "date"}]},
                ],
            }
        ]
    }

    plan = generate_mapping_plan_candidate(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
    )
    assert plan["plan_version"] == "1.0"
    assert "record_mapping" in plan
