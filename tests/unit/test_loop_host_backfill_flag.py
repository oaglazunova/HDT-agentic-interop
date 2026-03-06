from __future__ import annotations

from typing import Any, Mapping

from hdt_a2a.llm.loop import synthesize_plan_with_repairs
from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_mapping_plan.validate import compute_contract_schema_hash


def _vault_catalog_with_dob() -> dict[str, Any]:
    return {
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
    }


def _contract_birthdate_only() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}
    contract_input_schema = {
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
    }
    return contract, contract_input_schema


def _minimal_candidate_missing_required_mapping(expected_hash: str) -> dict[str, Any]:
    # Must include plan_id; loop will overwrite algo/dataset/contract refs via immutables/fill_contract_refs.
    return {
        "plan_version": "1.0",
        "plan_id": "initial_missing_required",
        "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
        "contract": {
            "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
            "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
            "contract_hash": expected_hash,
        },
        "limits": {
            "max_rows": 10,
            "batch_rows": 5,
            "max_record_bytes": 1024,
            "max_total_output_bytes": 4096,
        },
        # Missing the required pointer mapping on purpose:
        "record_mapping": {},
        "required_columns": [],
        "output": {
            "destination": "vault://results/initial.jsonl",
            "format": "jsonl",
            "result_schema_ref": "oci://x#out",
        },
    }


def _valid_repaired_candidate(expected_hash: str) -> dict[str, Any]:
    return {
        "plan_version": "1.0",
        "plan_id": "repaired_valid",
        "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
        "contract": {
            "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
            "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
            "contract_hash": expected_hash,
        },
        "limits": {
            "max_rows": 10,
            "batch_rows": 5,
            "max_record_bytes": 1024,
            "max_total_output_bytes": 4096,
        },
        "record_mapping": {
            "/person/birthDate": {"op": "column", "name": "dob"},
        },
        "required_columns": ["dob"],
        "output": {
            "destination": "vault://results/repaired_valid.jsonl",
            "format": "jsonl",
            "result_schema_ref": "oci://x#out",
        },
    }


def test_backfill_disabled_requires_repair_when_required_pointer_missing() -> None:
    contract, contract_input_schema = _contract_birthdate_only()
    expected_hash = compute_contract_schema_hash(contract_input_schema)

    class FakeClient(OllamaClient):
        def __init__(self) -> None:
            super().__init__(OllamaConfig(model="dummy"))
            self.calls = 0

        def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return _minimal_candidate_missing_required_mapping(expected_hash)
            if self.calls == 2:
                return _valid_repaired_candidate(expected_hash)
            raise AssertionError("Unexpected extra model call")

    client = FakeClient()

    res = synthesize_plan_with_repairs(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=_vault_catalog_with_dob(),
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
        max_iters=3,
        initial_candidates=1,
        use_candidate_retrieval=True,
        use_seed_hints=True,
        host_backfill_required_mappings=False,
    )

    assert client.calls == 2  # 1x initial, 1x repair
    assert res.ok is True
    assert res.plan is not None
    assert res.plan["plan_id"] == "repaired_valid"

    # First report must be failing (missing required mapping)
    assert len(res.reports) >= 2
    assert res.reports[0].ok is False
    assert res.reports[0].errors


def test_backfill_enabled_can_succeed_without_repair_for_missing_required_pointer() -> None:
    contract, contract_input_schema = _contract_birthdate_only()
    expected_hash = compute_contract_schema_hash(contract_input_schema)

    class FakeClient(OllamaClient):
        def __init__(self) -> None:
            super().__init__(OllamaConfig(model="dummy"))
            self.calls = 0

        def chat_json(self, messages, *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
            self.calls += 1
            # Return a candidate missing required mapping; host backfill should fill it.
            return _minimal_candidate_missing_required_mapping(expected_hash)

    client = FakeClient()

    res = synthesize_plan_with_repairs(
        client=client,
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=_vault_catalog_with_dob(),
        dataset_columns={"dob"},
        dataset_column_types={"dob": "date"},
        max_iters=3,
        initial_candidates=1,
        use_candidate_retrieval=True,
        use_seed_hints=True,
        host_backfill_required_mappings=True,
    )

    assert client.calls == 1  # no repair call needed
    assert res.ok is True
    assert res.plan is not None

    rm = res.plan.get("record_mapping")
    assert isinstance(rm, dict)
    assert "/person/birthDate" in rm

    expr = rm["/person/birthDate"]
    assert isinstance(expr, dict)

    # Accept either {"op":"column","name":"dob"} or {"op":"parse_date", "args":[{"op":"column","name":"dob"}], ...}
    if expr.get("op") == "column":
        assert expr.get("name") == "dob"
    elif expr.get("op") == "parse_date":
        args = expr.get("args")
        assert isinstance(args, list) and args
        assert isinstance(args[0], dict)
        assert args[0].get("op") == "column"
        assert args[0].get("name") == "dob"
    else:
        raise AssertionError(f"Unexpected mapping op: {expr.get('op')}")

    # required_columns should be consistent with referenced columns after post-processing
    req_cols = res.plan.get("required_columns")
    assert req_cols == ["dob"]
