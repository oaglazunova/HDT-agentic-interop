from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_mapping_plans import _load_tasks_from_json


def test_load_tasks_from_json_accepts_compact_shape(tmp_path: Path) -> None:
    payload = {
        "tasks": [
            {
                "task_id": "compact_task",
                "contract": {
                    "algo_id": "provider.generic",
                    "algo_version": "0.1.0",
                },
                "contract_input_schema": {
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
                },
                "dataset_spec": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [
                        {"name": "step_count", "type": "INTEGER"},
                        {"name": "noise", "type": "TEXT"},
                    ],
                },
            }
        ]
    }

    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = _load_tasks_from_json(path)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "compact_task"
    assert task.dataset_columns == {"step_count", "noise"}
    assert task.dataset_column_types["step_count"] == "INTEGER"
    assert task.vault_catalog["datasets"][0]["dataset_id"] == "vault_dataset_A"
    assert task.vault_catalog["datasets"][0]["tables"][0]["table_name"] == "transactions"


def test_load_tasks_from_json_accepts_explicit_shape(tmp_path: Path) -> None:
    payload = [
        {
            "task_id": "explicit_task",
            "contract": {
                "algo_id": "provider.generic",
                "algo_version": "0.1.0",
            },
            "contract_input_schema": {
                "type": "object",
                "properties": {
                    "person": {
                        "type": "object",
                        "properties": {
                            "birthDate": {"type": "string", "format": "date"},
                        },
                    }
                },
            },
            "vault_catalog": {
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
            },
            "dataset_columns": ["dob"],
            "dataset_column_types": {"dob": "TEXT"},
        }
    ]

    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = _load_tasks_from_json(path)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "explicit_task"
    assert task.dataset_columns == {"dob"}
    assert task.dataset_column_types == {"dob": "TEXT"}


def test_load_tasks_from_json_rejects_missing_shape_fields(tmp_path: Path) -> None:
    payload = {
        "tasks": [
            {
                "task_id": "bad_task",
                "contract": {
                    "algo_id": "provider.generic",
                    "algo_version": "0.1.0",
                },
                "contract_input_schema": {"type": "object"},
            }
        ]
    }

    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="either explicit fields|either explicit shape or compact shape|must contain either"):
        _load_tasks_from_json(path)


def test_load_tasks_from_json_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    payload = {
        "tasks": [
            {
                "task_id": "dup",
                "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
                "contract_input_schema": {"type": "object"},
                "dataset_spec": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [{"name": "a", "type": "TEXT"}],
                },
            },
            {
                "task_id": "dup",
                "contract": {"algo_id": "provider.generic", "algo_version": "0.1.0"},
                "contract_input_schema": {"type": "object"},
                "dataset_spec": {
                    "dataset_id": "vault_dataset_A",
                    "table_name": "transactions",
                    "columns": [{"name": "b", "type": "TEXT"}],
                },
            },
        ]
    }

    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate task_id"):
        _load_tasks_from_json(path)