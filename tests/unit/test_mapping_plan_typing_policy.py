from __future__ import annotations

import json

from hdt_mapping_plan.validate import validate_plan_type_compatibility
from hdt_mapping_plan import errors as E


def test_strict_dates_unknown_inference_is_error() -> None:
    plan = {
        "plan_version": "1.0",
        "plan_id": "p",
        "algo": {"algo_id": "a", "algo_version": "1"},
        "dataset": {"dataset_id": "d", "table_name": "t"},
        "contract": {"contract_ref": "x", "input_schema_ref": "x", "contract_hash": "a" * 64},
        "limits": {"max_rows": 1, "batch_rows": 1, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
        "required_columns": ["dob"],
        "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
        "output": {"destination": "vault://r.jsonl", "format": "jsonl", "result_schema_ref": "x"},
    }

    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {"type": "object", "properties": {"birthDate": {"type": "string", "format": "date"}}}
        },
    }

    # No dataset_column_types => inferred becomes unknown for column op
    rep = validate_plan_type_compatibility(
        plan,
        dataset_column_types=None,
        contract_input_schema=contract_input_schema,
        allowed_ops_profile=None,  # default strict_dates
    )
    assert rep.ok is False
    assert any(e.code == E.TYPE_INFERENCE_REQUIRED for e in rep.errors)


def test_permissive_unknown_inference_is_warning() -> None:
    plan = {
        "plan_version": "1.0",
        "plan_id": "p",
        "algo": {"algo_id": "a", "algo_version": "1"},
        "dataset": {"dataset_id": "d", "table_name": "t"},
        "contract": {"contract_ref": "x", "input_schema_ref": "x", "contract_hash": "a" * 64},
        "limits": {"max_rows": 1, "batch_rows": 1, "max_record_bytes": 1024, "max_total_output_bytes": 4096},
        "required_columns": ["x"],
        "record_mapping": {"/v": {"op": "column", "name": "x"}},
        "output": {"destination": "vault://r.jsonl", "format": "jsonl", "result_schema_ref": "x"},
    }

    contract_input_schema = {"type": "object", "properties": {"v": {"type": "number"}}}

    rep = validate_plan_type_compatibility(
        plan,
        dataset_column_types=None,
        contract_input_schema=contract_input_schema,
        allowed_ops_profile={"typing": {"mode": "permissive"}},
    )
    assert rep.ok is True  # no errors
    assert any(w.code == E.TYPE_INFERENCE_FAILED for w in rep.warnings)
