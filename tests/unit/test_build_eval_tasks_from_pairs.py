from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_eval_tasks_from_pairs import load_pairs_json, write_eval_tasks_json


def test_load_pairs_json_builds_compact_eval_tasks(tmp_path: Path) -> None:
    payload = {
        "pairs": [
            {
                "pair_id": "pair_birthdate_only",
                "contract": {
                    "algo_id": "provider.obesityCoach",
                    "algo_version": "0.1.0",
                },
                "dataset": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [
                        {"name": "dob", "type": "TEXT"},
                        {"name": "noise", "type": "TEXT"},
                    ],
                },
                "required_fields": [
                    {"pointer": "/person/birthDate", "type": "string", "format": "date"},
                ],
            }
        ]
    }

    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = load_pairs_json(path)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["task_id"] == "pair_birthdate_only"
    assert task["dataset_spec"]["dataset_id"] == "vault_dataset_A"
    assert task["dataset_spec"]["table_name"] == "transactions"
    assert task["dataset_spec"]["columns"][0]["name"] == "dob"

    schema = task["contract_input_schema"]
    assert schema["type"] == "object"
    assert "person" in schema["properties"]
    assert "birthDate" in schema["properties"]["person"]["properties"]
    assert schema["properties"]["person"]["properties"]["birthDate"]["type"] == "string"
    assert schema["properties"]["person"]["properties"]["birthDate"]["format"] == "date"


def test_load_pairs_json_builds_nested_schema_from_multiple_pointers(tmp_path: Path) -> None:
    payload = {
        "pairs": [
            {
                "pair_id": "pair_multi",
                "contract": {
                    "algo_id": "provider.generic",
                    "algo_version": "0.1.0",
                },
                "dataset": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "daily_profile",
                    "columns": [
                        {"name": "birth_date", "type": "TEXT"},
                        {"name": "step_count", "type": "INTEGER"},
                    ],
                },
                "required_fields": [
                    {"pointer": "/person/birthDate", "type": "string", "format": "date"},
                    {"pointer": "/activity/stepCount", "type": "integer"},
                ],
            }
        ]
    }

    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = load_pairs_json(path)
    schema = tasks[0]["contract_input_schema"]

    assert "person" in schema["properties"]
    assert "activity" in schema["properties"]

    person = schema["properties"]["person"]
    activity = schema["properties"]["activity"]

    assert "birthDate" in person["properties"]
    assert person["properties"]["birthDate"]["format"] == "date"
    assert "stepCount" in activity["properties"]
    assert activity["properties"]["stepCount"]["type"] == "integer"


def test_write_eval_tasks_json_wraps_tasks_list(tmp_path: Path) -> None:
    tasks = [
        {
            "task_id": "t1",
            "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
            "contract_input_schema": {"type": "object"},
            "dataset_spec": {
                "dataset_id": "vault_dataset_A",
                "table_name": "transactions",
                "columns": [{"name": "dob", "type": "TEXT"}],
            },
        }
    ]

    out_path = tmp_path / "eval_tasks.json"
    write_eval_tasks_json(tasks=tasks, out_path=out_path)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "tasks" in payload
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["task_id"] == "t1"


def test_load_pairs_json_rejects_duplicate_pair_ids(tmp_path: Path) -> None:
    payload = {
        "pairs": [
            {
                "pair_id": "dup",
                "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
                "dataset": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [{"name": "a", "type": "TEXT"}],
                },
                "required_fields": [{"pointer": "/x", "type": "string"}],
            },
            {
                "pair_id": "dup",
                "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
                "dataset": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [{"name": "b", "type": "TEXT"}],
                },
                "required_fields": [{"pointer": "/y", "type": "string"}],
            },
        ]
    }

    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate pair_id"):
        load_pairs_json(path)


def test_load_pairs_json_rejects_invalid_pointer(tmp_path: Path) -> None:
    payload = {
        "pairs": [
            {
                "pair_id": "bad_ptr",
                "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
                "dataset": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [{"name": "a", "type": "TEXT"}],
                },
                "required_fields": [{"pointer": "not/a/pointer", "type": "string"}],
            }
        ]
    }

    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must start with '/'"):
        load_pairs_json(path)
