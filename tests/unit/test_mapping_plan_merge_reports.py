from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import OUTPUT_DEST_NOT_ALLOWED, UNKNOWN_COLUMN
from hdt_mapping_plan.validate import validate_plan


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_validate_plan_merges_multiple_errors() -> None:
    plan = _load_example_plan()

    # Trigger column error
    plan["required_columns"].append("does_not_exist")

    # Trigger output confinement error
    plan["output"]["destination"] = "http://evil.example.com/out.jsonl"

    rep = validate_plan(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        contract_input_schema=None,  # will also add contract-schema-missing errors; fine
    )
    assert rep.ok is False

    codes = {e.code for e in rep.errors}
    assert UNKNOWN_COLUMN in codes
    assert OUTPUT_DEST_NOT_ALLOWED in codes
