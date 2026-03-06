from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import LINT_GROUPING_USED, LINT_MANY_CASTS, LINT_NEAR_BUDGET, LINT_MANY_COALESCE
from hdt_mapping_plan.lint import lint_plan, score_plan


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_grouping_emits_warning() -> None:
    plan = _load_example_plan()
    plan["grouping"] = {"group_by": ["country_code"], "max_group_size": 10}

    rep = lint_plan(plan)
    assert rep.ok is True
    assert rep.errors == []
    assert any(w.code == LINT_GROUPING_USED for w in rep.warnings)


def test_many_casts_emits_warning_and_increases_score() -> None:
    plan = _load_example_plan()

    # add multiple casts
    plan["record_mapping"]["/x/a"] = {"op": "cast", "type": "string", "args": [{"op": "column", "name": "c1"}]}
    plan["record_mapping"]["/x/b"] = {"op": "cast", "type": "string", "args": [{"op": "column", "name": "c2"}]}
    plan["record_mapping"]["/x/c"] = {"op": "cast", "type": "string", "args": [{"op": "column", "name": "c3"}]}

    rep = lint_plan(plan, profile={"lint": {"cast_warn_threshold": 3}})
    assert any(w.code == LINT_MANY_CASTS for w in rep.warnings)

    s = score_plan(plan)
    assert isinstance(s, int)
    assert s > 0


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_near_budget_warning_on_nodes() -> None:
    plan = _load_example_plan()

    # Make a long coalesce chain to create many nodes deterministically
    expr = {"op": "column", "name": "c0"}
    for i in range(50):
        expr = {"op": "coalesce", "args": [expr, {"op": "column", "name": f"c{i + 1}"}]}
    plan["record_mapping"]["/x/deep"] = expr

    rep = lint_plan(plan, profile={"limits": {"max_total_expr_nodes": 60}, "lint": {"near_budget_ratio": 0.8}})
    assert any(w.code == LINT_NEAR_BUDGET for w in rep.warnings)


def test_many_coalesce_warning_and_score_increases() -> None:
    plan = _load_example_plan()

    expr = {"op": "column", "name": "c0"}
    for _ in range(6):
        expr = {"op": "coalesce", "args": [expr, {"op": "column", "name": "c1"}]}
    plan["record_mapping"]["/x/a"] = expr

    rep = lint_plan(plan, profile={"lint": {"coalesce_warn": 5}})
    assert any(w.code == LINT_MANY_COALESCE for w in rep.warnings)

    s = score_plan(plan)
    assert s > 0
