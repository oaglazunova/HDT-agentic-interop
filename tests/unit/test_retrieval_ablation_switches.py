from __future__ import annotations

import json

from hdt_a2a.llm.plan_synthesis import build_base_messages
from hdt_mapping_plan.validate import compute_contract_schema_hash


def test_build_base_messages_can_disable_candidate_retrieval() -> None:
    contract = {"algo_id": "provider.generic", "algo_version": "0.1.0"}
    contract_input_schema = {
        "type": "object",
        "properties": {
            "activity": {
                "type": "object",
                "required": ["stepCount"],
                "properties": {
                    "stepCount": {"type": "integer"},
                },
            }
        },
        "required": ["activity"],
    }

    vault_catalog = {
        "datasets": [
            {
                "dataset_id": "vault_dataset_A",
                "tables": [
                    {
                        "table_name": "transactions",
                        "columns": [{"name": "step_count", "type": "INTEGER"}],
                    }
                ],
            }
        ]
    }

    messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
        expected_contract_hash=compute_contract_schema_hash(contract_input_schema),
        dataset_id="vault_dataset_A",
        table_name="transactions",
        dataset_columns={"step_count"},
        dataset_column_types={"step_count": "INTEGER"},
        use_candidate_retrieval=False,
        use_seed_hints=True,
    )

    payload = json.loads(messages[1]["content"])
    assert payload["pointer_to_candidate_cols"] == {}


def test_build_base_messages_can_disable_seed_hints_only() -> None:
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

    vault_catalog = {
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
    }

    messages_with_hints = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
        expected_contract_hash=compute_contract_schema_hash(contract_input_schema),
        dataset_id="vault_dataset_A",
        table_name="transactions",
        dataset_columns={"dob"},
        dataset_column_types={},  # intentionally no type signal
        use_candidate_retrieval=True,
        use_seed_hints=True,
    )

    payload_with_hints = json.loads(messages_with_hints[1]["content"])
    assert payload_with_hints["pointer_to_candidate_cols"]["/person/birthDate"][0] == "dob"

    messages_without_hints = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
        expected_contract_hash=compute_contract_schema_hash(contract_input_schema),
        dataset_id="vault_dataset_A",
        table_name="transactions",
        dataset_columns={"dob"},
        dataset_column_types={},  # intentionally no type signal
        use_candidate_retrieval=True,
        use_seed_hints=False,
    )

    payload_without_hints = json.loads(messages_without_hints[1]["content"])
    assert payload_without_hints["pointer_to_candidate_cols"] == {}
