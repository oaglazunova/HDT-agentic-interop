from __future__ import annotations

from typing import Any, Mapping

from hdt_a2a.llm.loop import synthesize_plan_with_repairs


class FakeClient:
    def __init__(self, plan: dict[str, Any]) -> None:
        self._plan = plan
        self.calls = 0

    def chat_json(self, messages, *, json_schema: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.calls += 1
        return self._plan


def _vault_catalog(*, cols: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "datasets": [
            {
                "dataset_id": "vault_dataset_A",
                "tables": [
                    {
                        "table_name": "daily_profile",
                        "columns": [{"name": n, "type": t} for (n, t) in cols],
                    }
                ],
            }
        ]
    }


def test_unwraps_const_wrapped_parse_date_and_recomputes_required_columns() -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}

    contract_input_schema = {
        "type": "object",
        "properties": {
            "recordId": {"type": "string"},
            "day": {
                "type": "object",
                "required": ["date"],
                "properties": {"date": {"type": "string", "format": "date"}},
            },
            "person": {
                "type": "object",
                "required": ["birthDate"],
                "properties": {"birthDate": {"type": "string", "format": "date"}},
            },
        },
        "required": ["recordId", "day", "person"],
    }

    vault_catalog = _vault_catalog(cols=[("txn_id", "TEXT"), ("date", "TEXT"), ("dob", "TEXT")])

    llm_plan = {
        "plan_id": "plan_12345678",
        "plan_version": "1.0",
        "algo": {"algo_id": contract["algo_id"], "algo_version": contract["algo_version"]},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "daily_profile"},
        "contract": {
            "contract_ref": "oci://local/contracts/UNKNOWN",
            "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
            "contract_hash": "0" * 64,
        },
        "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
        "required_columns": ["txn_id"],  # intentionally incomplete
        "record_mapping": {
            "/recordId": {"op": "column", "name": "txn_id"},
            "/day/date": {
                "op": "const",
                "value": {
                    "op": "parse_date",
                    "format": "%Y-%m-%d",
                    "args": [{"op": "column", "name": "date"}],
                },
            },
            "/person/birthDate": {
                "op": "const",
                "value": {
                    "op": "parse_date",
                    "format": "%Y-%m-%d",
                    "args": [{"op": "column", "name": "dob"}],
                },
            },
        },
        "output": {"destination": "vault://results/x.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
    }

    res = synthesize_plan_with_repairs(
        client=FakeClient(llm_plan),
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        max_iters=1,
        initial_candidates=1,
    )

    assert res.ok is True
    assert res.plan is not None

    rm = res.plan["record_mapping"]
    assert rm["/day/date"]["op"] == "parse_date"
    assert rm["/person/birthDate"]["op"] == "parse_date"
    assert set(res.plan["required_columns"]) == {"txn_id", "date", "dob"}


def test_prunes_record_mapping_pointers_not_in_required_leaf_pointers() -> None:
    contract = {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"}

    # Contract schema ONLY contains /person/birthDate.
    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "required": ["birthDate"],
                "properties": {"birthDate": {"type": "string", "format": "date"}},
            }
        },
        "required": ["person"],
    }

    vault_catalog = _vault_catalog(cols=[("txn_id", "TEXT"), ("dob", "TEXT")])

    llm_plan = {
        "plan_id": "plan_abcdefgh",
        "plan_version": "1.0",
        "algo": {"algo_id": contract["algo_id"], "algo_version": contract["algo_version"]},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "daily_profile"},
        "contract": {
            "contract_ref": "oci://local/contracts/UNKNOWN",
            "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
            "contract_hash": "0" * 64,
        },
        "limits": {"max_rows": 10, "batch_rows": 5, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
        "required_columns": ["txn_id", "dob"],
        "record_mapping": {
            "/recordId": {"op": "column", "name": "txn_id"},  # extra, should be pruned
            "/person/birthDate": {"op": "column", "name": "dob"},  # should be coerced to parse_date
        },
        "output": {"destination": "vault://results/y.jsonl", "format": "jsonl", "result_schema_ref": "oci://x#out"},
    }

    res = synthesize_plan_with_repairs(
        client=FakeClient(llm_plan),
        contract=contract,
        contract_input_schema=contract_input_schema,
        vault_catalog=vault_catalog,
        max_iters=1,
        initial_candidates=1,
    )

    assert res.ok is True
    assert res.plan is not None

    rm = res.plan["record_mapping"]
    assert "/recordId" not in rm
    assert rm["/person/birthDate"]["op"] == "parse_date"
    assert "dob" in res.plan["required_columns"]
