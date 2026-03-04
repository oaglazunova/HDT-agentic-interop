from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.validate import validate_plan_schema


def test_schema_validation_rejects_empty_object() -> None:
    rep = validate_plan_schema({})
    assert rep.ok is False
    assert rep.errors
    assert any(e.code == "SCHEMA_INVALID" for e in rep.errors)


def test_schema_validation_accepts_example_plan() -> None:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    plan = json.loads(p.read_text(encoding="utf-8"))
    rep = validate_plan_schema(plan)
    assert rep.ok is True
    assert rep.errors == []
