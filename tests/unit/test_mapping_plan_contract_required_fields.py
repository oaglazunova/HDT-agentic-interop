from __future__ import annotations

from hdt_mapping_plan.validate import validate_plan_contract_required_fields


def test_validate_plan_contract_required_fields_reports_missing_leaf_mapping() -> None:
    contract_input_schema = {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "properties": {
                    "birthDate": {"type": "string"},
                },
                "required": ["birthDate"],
            }
        },
        "required": ["person"],
    }

    plan = {"record_mapping": {}}

    report = validate_plan_contract_required_fields(
        plan,
        contract_input_schema=contract_input_schema,
    )

    assert report.ok is False
    assert len(report.errors) == 1
    assert report.errors[0].code == "CONTRACT_REQUIRED_FIELD_MISSING"
    assert "/person/birthDate" in str(report.errors[0].detail)