from __future__ import annotations

from typing import Any, Mapping

from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_a2a.llm.plan_synthesis import build_base_messages
from hdt_a2a.llm.repair import repair_mapping_plan_candidate
from hdt_mapping_plan.validate import CriticIssue, CriticReport, compute_contract_schema_hash
from hdt_mapping_plan import errors as E


class FakeOllama(OllamaClient):
    def __init__(self) -> None:
        super().__init__(OllamaConfig(model="dummy"))
        self.last_messages = None

    def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        self.last_messages = messages
        # "repair" output: just return a valid-ish plan with fixed required_columns
        return {
            "plan_version": "1.0",
            "plan_id": "plan_test_repair",
            "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
                "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
                "contract_hash": "a" * 64,
            },
            "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
            "required_columns": ["dob"],
            "record_mapping": {
                "/person/birthDate": {
                    "op": "cast",
                    "type": "string",
                    "args": [{"op": "parse_date", "format": "%Y-%m-%d", "args": [{"op": "column", "name": "dob"}]}],
                }
            },
            "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
        }


def test_repair_appends_repair_message() -> None:
    client = FakeOllama()

    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {"person": {"type": "object", "properties": {"birthDate": {"type": "string"}}}},
    }
    vault_catalog = {
        "datasets": [
            {
                "dataset_id": "vault_dataset_A",
                "tables": [{"table_name": "transactions", "columns": [{"name": "dob", "type": "date"}]}],
            }
        ]
    }

    expected_hash = compute_contract_schema_hash(contract_input_schema)

    base_messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
        expected_contract_hash=expected_hash,
        dataset_id="vault_dataset_A",
        table_name="transactions",
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
    )

    prev_plan = {
        "plan_version": "1.0",
        "plan_id": "bad",
        "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
        "contract": {"contract_ref": "x", "input_schema_ref": "x", "contract_hash": "a" * 64},
        "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
        "required_columns": [],
        "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
        "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "x"},
    }

    rep = CriticReport(
        ok=False,
        errors=[
            CriticIssue(
                code=E.COLUMN_NOT_DECLARED,
                path="/record_mapping/~1person~1birthDate/name",
                detail="referenced column is not declared in required_columns: dob",
                severity="error",
                hint="Add the column to required_columns.",
            )
        ],
        warnings=[],
    )

    out = repair_mapping_plan_candidate(
        client=client,
        base_messages=base_messages,
        previous_plan=prev_plan,
        critic_report=rep,
    )

    assert out["plan_id"] == "plan_test_repair"
    assert client.last_messages is not None
    assert len(client.last_messages) == len(base_messages) + 1
    assert client.last_messages[-1]["role"] == "user"
    assert "VALIDATION REPORT" in client.last_messages[-1]["content"]
