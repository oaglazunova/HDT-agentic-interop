from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import ARG_TYPE_MISMATCH, TYPE_MISMATCH
from hdt_mapping_plan.validate import compute_contract_schema_hash, validate_plan_type_compatibility


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _contract_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "properties": {
                    "birthDate": {"type": "string", "format": "date"},
                    "country": {"type": "string"},
                },
            },
            "metrics": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                },
            },
        },
    }


def test_date_expected_requires_parse_date() -> None:
    plan = _load_example_plan()
    schema = _contract_input_schema()
    plan["contract"]["contract_hash"] = compute_contract_schema_hash(schema)

    # Bad: dob TEXT -> inferred string, expected date
    plan["record_mapping"]["/person/birthDate"] = {"op": "column", "name": "dob"}

    rep = validate_plan_type_compatibility(
        plan,
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
        contract_input_schema=schema,
    )
    assert rep.ok is False
    assert any(e.code == TYPE_MISMATCH for e in rep.errors)

    # Good: parse_date(TEXT) -> date
    plan["record_mapping"]["/person/birthDate"] = {
        "op": "parse_date",
        "format": "%Y-%m-%d",
        "args": [{"op": "column", "name": "dob"}],
    }
    rep2 = validate_plan_type_compatibility(
        plan,
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
        contract_input_schema=schema,
    )
    assert rep2.ok is True


def test_lower_requires_string_arg() -> None:
    plan = _load_example_plan()
    schema = _contract_input_schema()
    plan["contract"]["contract_hash"] = compute_contract_schema_hash(schema)

    # lower(amount_eur) where amount_eur is REAL -> arg type mismatch
    plan["record_mapping"]["/person/country"] = {
        "op": "lower",
        "args": [{"op": "column", "name": "amount_eur"}],
    }
    rep = validate_plan_type_compatibility(
        plan,
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
        contract_input_schema=schema,
    )
    assert rep.ok is False
    assert any(e.code == ARG_TYPE_MISMATCH for e in rep.errors)
