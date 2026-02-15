from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import MAX_ARGS_EXCEEDED, MAX_DEPTH_EXCEEDED
from hdt_mapping_plan.validate import validate_plan_semantics


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_rejects_expr_depth_exceeded() -> None:
    plan = _load_example_plan()

    expr = {"op": "column", "name": "dob"}
    for _ in range(5):
        expr = {"op": "cast", "type": "string", "args": [expr]}

    plan["record_mapping"]["/person/birthDate"] = expr

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        allowed_ops_profile={"limits": {"max_expr_depth": 3}},
    )
    assert rep.ok is False
    assert any(e.code == MAX_DEPTH_EXCEEDED for e in rep.errors)


def test_rejects_max_args_exceeded() -> None:
    plan = _load_example_plan()

    plan["record_mapping"]["/metrics/test"] = {
        "op": "coalesce",
        "args": [
            {"op": "column", "name": "dob"},
            {"op": "column", "name": "dob"},
            {"op": "column", "name": "dob"},
            {"op": "column", "name": "dob"},
        ],
    }
    if "dob" not in plan["required_columns"]:
        plan["required_columns"].append("dob")

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        allowed_ops_profile={"limits": {"max_args": 2}},
    )
    assert rep.ok is False
    assert any(e.code == MAX_ARGS_EXCEEDED for e in rep.errors)
