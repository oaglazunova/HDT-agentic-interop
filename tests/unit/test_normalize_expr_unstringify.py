from __future__ import annotations

from hdt_mapping_plan.normalize import normalize_expr_shapes


def test_normalize_expr_shapes_unstringifies_const_wrapped_expression() -> None:
    plan = {
        "record_mapping": {
            "/day/date": {
                "op": "const",
                "value": {
                    "const": "{'op': 'parse_date', 'format': '%Y-%m-%d', 'args': [{'op': 'column', 'name': 'date'}]}"
                },
            }
        }
    }

    out = normalize_expr_shapes(plan)
    expr = out["record_mapping"]["/day/date"]

    assert expr["op"] == "parse_date"
    assert expr["args"][0]["op"] == "column"
    assert expr["args"][0]["name"] == "date"
