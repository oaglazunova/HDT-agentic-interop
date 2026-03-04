from __future__ import annotations

import json
from importlib import resources

from hdt_mapping_plan.errors import OUTPUT_DEST_NOT_ALLOWED, OUTPUT_FORMAT_NOT_ALLOWED
from hdt_mapping_plan.validate import validate_plan_semantics


def _load_example_plan() -> dict:
    p = resources.files("hdt_mapping_plan").joinpath("examples/example_plan.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_rejects_http_destination() -> None:
    plan = _load_example_plan()
    plan["output"]["destination"] = "http://evil.example.com/out.jsonl"

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
    )
    assert rep.ok is False
    assert any(e.code == OUTPUT_DEST_NOT_ALLOWED for e in rep.errors)


def test_rejects_traversal_destination() -> None:
    plan = _load_example_plan()
    plan["output"]["destination"] = "vault://results/../secrets.jsonl"

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
    )
    assert rep.ok is False
    assert any(e.code == OUTPUT_DEST_NOT_ALLOWED for e in rep.errors)


def test_accepts_vault_destination_and_format() -> None:
    plan = _load_example_plan()
    plan["output"]["destination"] = "vault://results/plan123.jsonl"
    plan["output"]["format"] = "jsonl"

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        allowed_ops_profile=None,
    )
    assert rep.ok is True


def test_profile_can_restrict_formats() -> None:
    plan = _load_example_plan()
    plan["output"]["destination"] = "vault://results/plan123.parquet"
    plan["output"]["format"] = "parquet"

    rep = validate_plan_semantics(
        plan,
        dataset_columns={"dob", "country_code", "amount_eur"},
        allowed_ops_profile={"output": {"allowed_formats": ["jsonl"]}},
    )
    assert rep.ok is False
    assert any(e.code == OUTPUT_FORMAT_NOT_ALLOWED for e in rep.errors)
