from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import CONTRACT_POINTER_INVALID, UNKNOWN_CONTRACT_FIELD
from hdt_mapping_plan.validate import validate_plan_contract_pointers


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _contract_input_schema_for_example() -> dict:
    # Minimal provider input schema that matches the example plan pointers.
    return {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "properties": {
                    "birthDate": {"type": "string"},
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


def test_unknown_contract_field_detected() -> None:
    plan = _load_example_plan()
    plan["record_mapping"]["/person/doesNotExist"] = plan["record_mapping"]["/person/country"]

    rep = validate_plan_contract_pointers(plan, contract_input_schema=_contract_input_schema_for_example())
    assert rep.ok is False
    assert any(e.code == UNKNOWN_CONTRACT_FIELD for e in rep.errors)


def test_invalid_pointer_detected() -> None:
    plan = _load_example_plan()
    # invalid because it doesn't start with '/'
    plan["record_mapping"]["person/birthDate"] = plan["record_mapping"]["/person/birthDate"]

    rep = validate_plan_contract_pointers(plan, contract_input_schema=_contract_input_schema_for_example())
    assert rep.ok is False
    assert any(e.code == CONTRACT_POINTER_INVALID for e in rep.errors)
