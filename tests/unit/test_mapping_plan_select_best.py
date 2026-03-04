from __future__ import annotations

import json
import hashlib
from importlib import resources

from hdt_mapping_plan.select import select_best_plan


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _canonical_sha256_hex(obj: dict) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_select_best_plan_prefers_valid_and_simpler() -> None:
    base = _load_example_plan()

    # Minimal provider input schema matching the example plan's record_mapping pointers
    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "properties": {
                    "birthDate": {"type": "string"},      # plan casts parsed date to string
                    "country": {"type": "string"},
                },
                "required": ["birthDate", "country"],
                "additionalProperties": False,
            },
            "metrics": {
                "type": "object",
                "properties": {
                    "amountCents": {"type": "integer"},
                },
                "required": ["amountCents"],
                "additionalProperties": False,
            },
        },
        "required": ["person", "metrics"],
        "additionalProperties": False,
    }

    schema_hash = _canonical_sha256_hex(contract_input_schema)

    # Candidate 1: invalid (unknown required column)
    p1 = json.loads(json.dumps(base))
    p1["plan_id"] = "p1-invalid"
    p1["required_columns"].append("does_not_exist")
    p1["contract"]["contract_hash"] = schema_hash

    # Candidate 2: valid but more complex (adds coalesce chain into /person/country)
    p2 = json.loads(json.dumps(base))
    p2["plan_id"] = "p2-complex"
    p2["contract"]["contract_hash"] = schema_hash
    expr = {"op": "column", "name": "country_code"}
    for _ in range(6):
        expr = {"op": "coalesce", "args": [expr, {"op": "column", "name": "country_code"}]}
    p2["record_mapping"]["/person/country"] = expr

    # Candidate 3: valid and simpler (as-is)
    p3 = json.loads(json.dumps(base))
    p3["plan_id"] = "p3-simple"
    p3["contract"]["contract_hash"] = schema_hash

    res = select_best_plan(
        [p1, p2, p3],
        dataset_columns={"dob", "country_code", "amount_eur"},
        # For strict mode, pass the contract input schema
        contract_input_schema=contract_input_schema,
        allowed_ops_profile=None,
    )

    assert res.best_plan is not None
    assert res.best_plan["plan_id"] == "p3-simple"
    assert res.valid == 2
