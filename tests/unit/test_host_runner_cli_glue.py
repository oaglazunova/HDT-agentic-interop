from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import hdt_a2a.host.run_negotiation as rn
from hdt_mapping_plan.validate import compute_contract_schema_hash


def _write_vault_catalog(path: Path) -> None:
    # Minimal catalog: exactly one dataset + one table so host doesn't require extra args
    catalog = {
        "datasets": [
            {
                "dataset_id": "vault_dataset_A",
                "tables": [
                    {
                        "table_name": "transactions",
                        "columns": [
                            {"name": "dob", "type": "date"},
                            {"name": "steps", "type": "INTEGER"},
                        ],
                    }
                ],
            }
        ]
    }
    path.write_text(json.dumps(catalog), encoding="utf-8")


def _contract_input_schema_birthdate_only() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "person": {
                "type": "object",
                "required": ["birthDate"],
                "properties": {
                    "birthDate": {"type": "string", "format": "date"},
                },
            }
        },
        "required": ["person"],
    }


def _fake_bundle() -> dict[str, Any]:
    schema = _contract_input_schema_birthdate_only()
    expected_hash = compute_contract_schema_hash(schema)
    return {
        "contract": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        "contract_input_schema": schema,
        "expected_contract_hash": expected_hash,
    }


def _fake_user_agent_result(contract_hash: str) -> dict[str, Any]:
    # A minimally valid Mapping Plan-like object (host runner will postprocess + validate + persist it)
    plan = {
        "plan_version": "1.0",
        "plan_id": "glue_plan_001",
        "algo": {"algo_id": "provider.obesityCoach", "algo_version": "0.1.0"},
        "dataset": {"dataset_id": "vault_dataset_A", "table_name": "transactions"},
        "contract": {
            "contract_ref": "oci://x/contracts/provider.obesityCoach:0.1.0",
            "input_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#input.schema.json",
            "contract_hash": contract_hash,
        },
        "limits": {
            "max_rows": 10,
            "batch_rows": 5,
            "max_record_bytes": 1024,
            "max_total_output_bytes": 4096,
        },
        "required_columns": ["dob"],
        "record_mapping": {"/person/birthDate": {"op": "column", "name": "dob"}},
        "output": {
            "destination": "vault://results/glue_plan_001.jsonl",
            "format": "jsonl",
            "result_schema_ref": "oci://x/contracts/provider.obesityCoach:0.1.0#output.schema.json",
        },
    }

    user_report = {"ok": True, "errors": [], "warnings": []}
    return {
        "iterations": 1,
        "plan": plan,
        "user_report": user_report,
    }


def test_host_runner_main_writes_artifacts_and_forwards_knobs(tmp_path, monkeypatch) -> None:
    vault_catalog_path = tmp_path / "vault_catalog.json"
    _write_vault_catalog(vault_catalog_path)

    out_dir = tmp_path / "out"
    captured: dict[str, Any] = {}

    # Patch provider bundle fetch (prevents network call)
    bundle = _fake_bundle()

    def fake_fetch_contract_bundle(*, provider_url: str, algo_id: str, algo_version: str):
        captured["provider_url"] = provider_url
        captured["algo_id"] = algo_id
        captured["algo_version"] = algo_version
        return bundle

    monkeypatch.setattr(rn, "fetch_contract_bundle", fake_fetch_contract_bundle)

    # Patch user agent call (prevents network call)
    def fake_call_user_agent_synthesize(**kwargs):
        captured.update(kwargs)

        # Reuse the same minimal valid plan object you already defined.
        base = _fake_user_agent_result(bundle["expected_contract_hash"])
        plan = base["plan"]

        return {
            "iterations": 2,
            "plan": plan,
            "user_report": {"ok": True, "errors": [], "warnings": []},
            "user_reports": [
                {"ok": False, "errors": [{"message": "x"}], "warnings": []},
                {"ok": True, "errors": [], "warnings": []},
            ],
        }

    monkeypatch.setattr(rn, "call_user_agent_synthesize", fake_call_user_agent_synthesize)

    argv = [
        "hdt-a2a-negotiate",
        "--algo-id",
        "provider.obesityCoach",
        "--algo-version",
        "0.1.0",
        "--vault-catalog",
        str(vault_catalog_path),
        "--user-url",
        "http://user:9200/",
        "--provider-url",
        "http://provider:9100/",
        "--ollama-url",
        "http://localhost:11434",
        "--model",
        "qwen2.5:7b-instruct-q4_0",
        "--max-iters",
        "2",
        "--out-dir",
        str(out_dir),
    ]

    # Only add these args if your CLI supports them (after Step 6 plumbing):
    argv += [
        "--initial-candidates",
        "3",
        "--disable-retriever",
        "--disable-seed-hints",
    ]

    monkeypatch.setattr(sys, "argv", argv)

    try:
        rn.main()
    except SystemExit as e:
        assert int(e.code or 0) == 0

    # Assert bundle fetch called with correct identifiers
    assert captured["provider_url"] == "http://provider:9100/"
    assert captured["algo_id"] == "provider.obesityCoach"
    assert captured["algo_version"] == "0.1.0"

    # Assert artifacts written
    assert out_dir.exists()
    json_files = list(out_dir.rglob("*.json"))
    assert json_files, "No JSON artifacts were written under --out-dir"

    run_manifests = [p for p in json_files if p.name.endswith(".run.json")]
    assert run_manifests, "No *.run.json manifest found under --out-dir"

    manifest = json.loads(run_manifests[0].read_text(encoding="utf-8"))
    assert manifest.get("plan_id") == "glue_plan_001"

    # If you implemented Step 6 manifest inputs, these should be present:
    inputs = manifest.get("inputs") or {}
    if "initial_candidates" in inputs:
        assert inputs["initial_candidates"] == 3
        assert inputs["use_candidate_retrieval"] is False
        assert inputs["use_seed_hints"] is False

    # Ensure plan file exists
    plan_path = out_dir / "glue_plan_001.json"
    assert plan_path.is_file(), "Expected plan JSON not found (glue_plan_001.json)"

    ua = manifest["user_agent"]
    assert "reports" in ua
    assert isinstance(ua["reports"], list)
    assert len(ua["reports"]) == 2
    assert ua["reports"][0]["ok"] is False
    assert ua["reports"][-1]["ok"] is True
