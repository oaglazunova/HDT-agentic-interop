from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import (
    COLUMN_NOT_DECLARED,
    FILTER_OP_NOT_ALLOWED,
    OP_NOT_ALLOWED,
    UNKNOWN_COLUMN,
)
from hdt_mapping_plan.validate import validate_plan_semantics


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_semantic_validation_accepts_example_plan() -> None:
    plan = _load_example_plan()
    dataset_columns = {"dob", "country_code", "amount_eur", "merchant", "ts"}
    rep = validate_plan_semantics(plan, dataset_columns=dataset_columns)
    assert rep.ok is True
    assert rep.errors == []


def test_semantic_validation_flags_unknown_required_column() -> None:
    plan = _load_example_plan()
    plan["required_columns"].append("does_not_exist")

    dataset_columns = {"dob", "country_code", "amount_eur"}
    rep = validate_plan_semantics(plan, dataset_columns=dataset_columns)
    assert rep.ok is False
    assert any(e.code == UNKNOWN_COLUMN for e in rep.errors)


def test_semantic_validation_flags_column_not_declared_in_required_columns() -> None:
    plan = _load_example_plan()
    plan["required_columns"] = [c for c in plan["required_columns"] if c != "dob"]

    dataset_columns = {"dob", "country_code", "amount_eur"}
    rep = validate_plan_semantics(plan, dataset_columns=dataset_columns)
    assert rep.ok is False
    assert any(e.code == COLUMN_NOT_DECLARED for e in rep.errors)


def test_semantic_validation_respects_expr_op_allowlist_profile() -> None:
    plan = _load_example_plan()
    dataset_columns = {"dob", "country_code", "amount_eur"}

    # Disallow 'scale' explicitly. The example plan uses it.
    allowed_ops_profile = {
        "expr_ops": [
            "column",
            "const",
            "cast",
            "to_string",
            "parse_date",
            "parse_datetime",
            "round",
            "lower",
            "upper",
            "coalesce",
        ],
    }
    rep = validate_plan_semantics(plan, dataset_columns=dataset_columns, allowed_ops_profile=allowed_ops_profile)
    assert rep.ok is False
    assert any(e.code == OP_NOT_ALLOWED for e in rep.errors)


def test_semantic_validation_respects_filter_op_allowlist_profile() -> None:
    plan = _load_example_plan()
    plan["row_filter"] = {
        "op": "and",
        "args": [
            {"op": "not_null", "args": [{"op": "column", "name": "dob"}]},
        ],
    }

    dataset_columns = {"dob", "country_code", "amount_eur"}
    allowed_ops_profile = {"filter_ops": ["eq", "neq"]}  # does not include 'and' or 'not_null'
    rep = validate_plan_semantics(plan, dataset_columns=dataset_columns, allowed_ops_profile=allowed_ops_profile)
    assert rep.ok is False
    assert any(e.code == FILTER_OP_NOT_ALLOWED for e in rep.errors)
