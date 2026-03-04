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
            # "bad" output: MUST still fail after deterministic normalizers
            # Use an unknown column so validation fails and triggers repair.
            return {
                "plan_version": "1.0",
                "plan_id": "bad_plan",
                "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
                "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
                "contract": {"contract_ref": "x", "input_schema_ref": "x", "contract_hash": self.contract_hash},
                "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
                # Even if your code auto-fills required_columns, the unknown column will still fail.
                "required_columns": ["UNKNOWN_COLUMN"],
                "record_mapping": {"/person/birthDate": {"op": "column", "name": "UNKNOWN_COLUMN"}},
                "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "x"},
            }

        return {
            "plan_version": "1.0",
            "plan_id": "good_plan",
            "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
            "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
            "contract": {
                "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
                "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
                "contract_hash": self.contract_hash,  # <-- use computed
            },
            "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
            "required_columns": ["dob"],
            "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
            "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
        }


def test_synthesize_plan_with_repairs_stops_on_ok() -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
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
    assert res.plan["record_mapping"]["/person/birthDate"]["op"] == "column"
    assert res.plan["record_mapping"]["/person/birthDate"]["name"] == "dob"
    assert res.plan["required_columns"] == ["dob"]
    assert res.iterations == 2
    assert len(res.reports) == 2


def test_loop_lifts_must_include_to_root() -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {"person": {"type": "object", "properties": {"birthDate": {"type": "string"}}}},
    }

    expected_hash = compute_contract_schema_hash(contract_input_schema)

    class FakeOllamaMustInclude(OllamaClient):
        def __init__(self) -> None:
            super().__init__(OllamaConfig(model="dummy"))

        def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "plan_version": "1.0",
                "plan_id": "example_plan",
                "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
                "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
                "contract": {
                    "contract_ref": "oci://local/contracts/UNKNOWN",
                    "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
                    "contract_hash": expected_hash,
                },
                "must_include": {
                    "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
                    "required_columns": ["dob"],
                    "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
                    "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
                },
                "rules": ["not allowed in schema"],
            }

    vault_catalog = {
        "datasets": [
            {"dataset_id": "vault_dataset_A", "tables": [{"table_name": "transactions", "columns": [{"name": "dob", "type": "date"}]}]}
        ]
    }

    res = synthesize_plan_with_repairs(
        client=FakeOllamaMustInclude(),
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
        max_iters=1,
    )

    assert res.ok is True
    assert "must_include" not in res.plan
    assert "rules" not in res.plan
    assert "limits" in res.plan and "output" in res.plan and "record_mapping" in res.plan and "required_columns" in res.plan



def test_loop_returns_valid_initial_candidate_without_repair_when_multiple_are_requested() -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {"person": {"type": "object", "properties": {"birthDate": {"type": "string"}}}},
    }

    expected_hash = compute_contract_schema_hash(contract_input_schema)

    class FakeOllamaMultiInitial(OllamaClient):
        def __init__(self) -> None:
            super().__init__(OllamaConfig(model="dummy"))
            self.calls = 0

        def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
            self.calls += 1

            if self.calls == 1:
                # invalid first candidate
                return {
                    "plan_version": "1.0",
                    "plan_id": "bad_initial",
                    "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
                    "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
                    "contract": {
                        "contract_ref": "x",
                        "input_schema_ref": "x",
                        "contract_hash": expected_hash,
                    },
                    "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
                    "required_columns": ["UNKNOWN_COLUMN"],
                    "record_mapping": {"/person/birthDate": {"op": "column", "name": "UNKNOWN_COLUMN"}},
                    "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "x"},
                }

            if self.calls == 2:
                # valid second candidate
                return {
                    "plan_version": "1.0",
                    "plan_id": "good_initial",
                    "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
                    "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
                    "contract": {
                        "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
                        "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
                        "contract_hash": expected_hash,
                    },
                    "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
                    "required_columns": ["dob"],
                    "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
                    "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
                }

            raise AssertionError("repair should not be called when a valid initial candidate exists")

    vault_catalog = {
        "datasets": [
            {"dataset_id": "vault_dataset_A", "tables": [{"table_name": "transactions", "columns": [{"name": "dob", "type": "date"}]}]}
        ]
    }

    client = FakeOllamaMultiInitial()

    res = synthesize_plan_with_repairs(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
        max_iters=3,
        initial_candidates=2,
    )

    assert res.ok is True
    assert res.plan is not None
    assert res.plan["plan_id"] == "good_initial"
    assert res.plan["record_mapping"]["/person/birthDate"]["name"] == "dob"
    assert res.iterations == 1
    assert len(res.reports) == 1
    assert client.calls == 2
