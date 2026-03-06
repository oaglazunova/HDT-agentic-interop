from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import ARITY_MISMATCH, ARG_TYPE_MISMATCH, TYPE_MISMATCH
from hdt_mapping_plan.validate import validate_plan_semantics


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_row_filter_arity_mismatch_eq() -> None:
    plan = _load_example_plan()
    plan["row_filter"] = {"op": "eq", "args": [{"op": "column", "name": "country_code"}]}

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
    )
    assert rep.ok is False
    assert any(e.code == ARITY_MISMATCH for e in rep.errors)


def test_row_filter_and_requires_bool_args() -> None:
    plan = _load_example_plan()
    # numeric column used as boolean in AND
    plan["row_filter"] = {
        "op": "and",
        "args": [{"op": "column", "name": "amount_eur"}, {"op": "not_null", "args": [{"op": "column", "name": "dob"}]}],
    }

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
    )
    assert rep.ok is False
    assert any(e.code == ARG_TYPE_MISMATCH for e in rep.errors)


def test_row_filter_lt_type_mismatch_string_vs_int() -> None:
    plan = _load_example_plan()
    plan["row_filter"] = {"op": "lt", "args": [{"op": "column", "name": "country_code"}, 5]}

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        dataset_column_types={"dob": "TEXT", "country_code": "TEXT", "amount_eur": "REAL"},
    )
    assert rep.ok is False
    assert any(e.code == TYPE_MISMATCH for e in rep.errors)
