from __future__ import annotations

from hdt_mapping_plan.normalize import apply_limits_policy, fill_contract_refs


def test_fill_contract_refs_overrides_unknown() -> None:
    plan = {
        "contract": {
            "contract_ref": "oci://local/contracts/UNKNOWN",
            "input_schema_ref": "oci://local/contracts/UNKNOWN#input.schema.json",
            "contract_hash": "abc",
        },
        "output": {
            "destination": "vault://results/x.jsonl",
            "format": "jsonl",
            "result_schema_ref": "oci://local/contracts/UNKNOWN#output.schema.json",
        },
    }

    out = fill_contract_refs(plan, algo_id="provider.obesityCoach", algo_version="0.1.0")
    assert out["contract"]["contract_ref"] == "oci://local/contracts/provider.obesityCoach/0.1.0"
    assert out["contract"]["input_schema_ref"].endswith("#input.schema.json")
    assert out["output"]["result_schema_ref"].endswith("#output.schema.json")


def test_apply_limits_policy_clamps_permissive() -> None:
    plan = {"limits": {"max_rows": 100_000, "batch_rows": 5_000, "max_record_bytes": 100_000, "max_total_output_bytes": 200_000_000}}
    out = apply_limits_policy(plan)

    limits = out["limits"]
    assert limits["max_rows"] <= 10_000
    assert limits["batch_rows"] <= 2_000
    assert limits["batch_rows"] <= limits["max_rows"]
    assert limits["max_record_bytes"] <= 8_192
    assert limits["max_total_output_bytes"] <= 10_000_000
    assert limits["max_total_output_bytes"] <= limits["max_rows"] * limits["max_record_bytes"]