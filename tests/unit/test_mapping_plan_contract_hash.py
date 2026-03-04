from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import CONTRACT_HASH_MISMATCH
from hdt_mapping_plan.validate import compute_contract_schema_hash, validate_plan_contract_hash


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _contract_input_schema_for_example() -> dict:
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


def test_contract_hash_matches() -> None:
    plan = _load_example_plan()
    schema = _contract_input_schema_for_example()
    plan["contract"]["contract_hash"] = compute_contract_schema_hash(schema)

    rep = validate_plan_contract_hash(plan, contract_input_schema=schema)
    assert rep.ok is True
    assert rep.errors == []


def test_contract_hash_mismatch_detected() -> None:
    plan = _load_example_plan()
    schema = _contract_input_schema_for_example()
    plan["contract"]["contract_hash"] = "sha256:deadbeef"

    rep = validate_plan_contract_hash(plan, contract_input_schema=schema)
    assert rep.ok is False
    assert any(e.code == CONTRACT_HASH_MISMATCH for e in rep.errors)
