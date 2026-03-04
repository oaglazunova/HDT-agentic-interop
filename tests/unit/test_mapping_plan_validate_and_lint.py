from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import LINT_GROUPING_USED, UNKNOWN_COLUMN
from hdt_mapping_plan.validate import validate_and_lint_plan


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_validate_and_lint_merges_errors_and_warnings() -> None:
    plan = _load_example_plan()

    # Create a hard error (unknown column)
    plan["required_columns"].append("does_not_exist")

    # Create a lint warning (grouping used)
    plan["grouping"] = {"group_by": ["country_code"], "max_group_size": 10}

    rep = validate_and_lint_plan(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        allowed_ops_profile=None,
        contract_input_schema=None,
    )

    assert rep.ok is False
    codes_err = {e.code for e in rep.errors}
    codes_warn = {w.code for w in rep.warnings}

    assert UNKNOWN_COLUMN in codes_err
    assert LINT_GROUPING_USED in codes_warn
