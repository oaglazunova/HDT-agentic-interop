from __future__ import annotations

import json

from hdt_a2a.llm.plan_synthesis import build_base_messages
from hdt_mapping_plan.candidate_retrieval import (
    build_pointer_candidate_cols,
    rank_candidate_columns_for_pointer,
)
from hdt_mapping_plan.validate import compute_contract_schema_hash


def test_rank_candidate_columns_prefers_seed_hint_for_obesitycoach_birthdate() -> None:
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

    ranked = rank_candidate_columns_for_pointer(
        pointer="/person/birthDate",
        dataset_columns={"dob", "date", "steps"},
        dataset_column_types={"dob": "TEXT", "date": "TEXT", "steps": "INTEGER"},
        contract_input_schema=contract_input_schema,
        algo_id="provider.obesityCoach",
        top_k=3,
    )

    assert ranked
    assert ranked[0] == "dob"


def test_rank_candidate_columns_prefers_snake_case_match_without_seed_hints() -> None:
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

    ranked = rank_candidate_columns_for_pointer(
        pointer="/activity/stepCount",
        dataset_columns={"steps", "step_count", "dob"},
        dataset_column_types={"steps": "INTEGER", "step_count": "INTEGER", "dob": "TEXT"},
        contract_input_schema=contract_input_schema,
        algo_id="provider.generic",
        top_k=3,
    )

    assert ranked
    assert ranked[0] == "step_count"


def test_build_pointer_candidate_cols_only_returns_non_empty_required_pointers() -> None:
    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "required": ["birthDate"],
                "properties": {
                    "birthDate": {"type": "string", "format": "date"},
                },
            },
            "metrics": {
                "type": "object",
                "required": ["weightKg"],
                "properties": {
                    "weightKg": {"type": "number"},
                },
            },
        },
        "required": ["person", "metrics"],
    }

    pointer_map = build_pointer_candidate_cols(
        required_pointers=["/person/birthDate", "/metrics/weightKg"],
        dataset_columns={"birth_date"},
        dataset_column_types={"birth_date": "TEXT"},
        contract_input_schema=contract_input_schema,
        algo_id="provider.generic",
        top_k=3,
    )

    assert "/person/birthDate" in pointer_map
    assert pointer_map["/person/birthDate"][0] == "birth_date"
    assert "/metrics/weightKg" not in pointer_map


def test_build_base_messages_populates_pointer_candidates_from_retriever() -> None:
    contract = {"algo_id": "provider.generic", "algo_version": "0.1.0"}

    contract_input_schema = {
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
    }

    vault_catalog = {
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
    }

    messages = build_base_messages(
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        allowed_ops_profile=None,
        expected_contract_hash=compute_contract_schema_hash(contract_input_schema),
        dataset_id="vault_dataset_A",
        table_name="transactions",
        dataset_columns={"birth_date", "step_count", "noise"},
        dataset_column_types={"birth_date": "TEXT", "step_count": "INTEGER", "noise": "TEXT"},
    )

    assert len(messages) == 2
    payload = json.loads(messages[1]["content"])

    pointer_map = payload["pointer_to_candidate_cols"]

    assert pointer_map["/person/birthDate"][0] == "birth_date"
    assert pointer_map["/activity/stepCount"][0] == "step_count"
