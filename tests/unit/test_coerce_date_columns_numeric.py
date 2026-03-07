from __future__ import annotations

from hdt_mapping_plan.normalize import coerce_date_columns


def test_coerce_date_columns_wraps_numeric_column_with_to_string_then_parse_date() -> None:
    plan = {
        "record_mapping": {
            "/person/birthDate": {"op": "column", "name": "dob"},
        }
    }

    schema = {
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

    types = {"dob": "INTEGER"}

    out = coerce_date_columns(plan, contract_input_schema=schema, dataset_column_types=types)

    expr = out["record_mapping"]["/person/birthDate"]
    assert expr["op"] == "parse_date"
    assert expr["args"][0]["op"] == "to_string"
    assert expr["args"][0]["args"][0]["op"] == "column"
    assert expr["args"][0]["args"][0]["name"] == "dob"
