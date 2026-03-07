from __future__ import annotations

from hdt_mapping_plan.normalize import normalize_expr_shapes


def test_normalize_const_null_expr_to_literal_none() -> None:
    plan = {
        "record_mapping": {
            "/hydration/waterMl": {"op": "const", "value": {"op": "null"}},
        }
    }

    out = normalize_expr_shapes(plan)
    expr = out["record_mapping"]["/hydration/waterMl"]
    assert expr["op"] == "const"
    assert expr["value"] is None
