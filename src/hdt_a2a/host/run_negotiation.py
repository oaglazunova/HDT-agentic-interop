from __future__ import annotations

import argparse
import json
import os
import uuid
from importlib import resources
from pathlib import Path
from typing import Any, Mapping
import logging
import httpx

from hdt_a2a.provider_a2a_client import fetch_contract_bundle
from hdt_mapping_plan.normalize import apply_limits_policy, fill_contract_refs
from hdt_mapping_plan.validate import validate_and_lint_plan, compute_contract_schema_hash
from hdt_mapping_plan.vault_catalog import generate_vault_catalog
from hdt_config.settings import init_runtime
from hdt_mapping_plan.hashing import sha256_hex_of_json


log = logging.getLogger(__name__)


# === helpers ========================


def _schema_summary(schema: dict) -> dict:
    """Small, stable summary for INFO logs (avoids huge console spam)."""
    try:
        b = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        b = b""

    props = schema.get("properties")
    prop_keys = sorted(props.keys()) if isinstance(props, dict) else []

    return {
        "top_keys": sorted([k for k in schema.keys() if isinstance(k, str)])[:20],
        "type": schema.get("type"),
        "n_properties": len(prop_keys),
        "properties_preview": prop_keys[:20],
        "bytes": len(b),
    }


class HostRunnerError(RuntimeError):
    pass


def _read_json(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise HostRunnerError(f"file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extract_data_part(result: Mapping[str, Any]) -> dict[str, Any]:
    parts = result.get("parts") or []
    if not isinstance(parts, list):
        raise HostRunnerError("Invalid A2A response: result.parts is not a list")

    for p in parts:
        if not isinstance(p, dict):
            continue
        ptype = p.get("type") or p.get("kind")
        if ptype == "data" and isinstance(p.get("data"), dict):
            return p["data"]

    raise HostRunnerError("No DataPart found in A2A response")


def _load_default_allowed_ops_profile() -> dict[str, Any]:
    p = resources.files("hdt_mapping_plan").joinpath("allowed_ops_profile.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


# === end helpers ========================


def call_user_agent_synthesize(
    *,
    user_url: str,
    provider_url: str,
    algo_id: str,
    algo_version: str,
    vault_catalog: Mapping[str, Any],
    allowed_ops_profile: Mapping[str, Any] | None,
    dataset_id: str | None,
    table_name: str | None,
    max_iters: int,
    initial_candidates: int = 1,
    use_candidate_retrieval: bool = True,
    use_seed_hints: bool = True,
    ollama_url: str | None = None,
    ollama_model: str | None = None,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    rpc_url = user_url.rstrip("/") + "/"

    data: dict[str, Any] = {
        "op": "mapping_plan.synthesize",
        "provider_url": provider_url,
        "algo_id": algo_id,
        "algo_version": algo_version,
        "vault_catalog": vault_catalog,
        "max_iters": max_iters,
        "initial_candidates": int(initial_candidates),
        "use_candidate_retrieval": bool(use_candidate_retrieval),
        "use_seed_hints": bool(use_seed_hints),
    }

    if dataset_id:
        data["dataset_id"] = dataset_id
    if table_name:
        data["table_name"] = table_name

    # NEW: forward policy + LLM overrides
    if allowed_ops_profile is not None:
        data["allowed_ops_profile"] = allowed_ops_profile
    if ollama_url:
        data["ollama_url"] = ollama_url
    if ollama_model:
        data["ollama_model"] = ollama_model

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [
                    {
                        "type": "data",
                        "data": data,  # <-- use the built dict
                    }
                ],
            },
            "configuration": {},
        },
    }

    timeout = httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0)
    with httpx.Client(timeout=timeout) as client:
        try:
            r = client.post(rpc_url, json=req)
        except httpx.ReadTimeout as e:
            raise HostRunnerError(
                f"Timed out waiting for User Agent after {timeout_s}s. "
                "Increase --user-timeout-s or reduce --max-iters / use a smaller model."
            ) from e

    if r.status_code != 200:
        raise HostRunnerError(f"User agent HTTP {r.status_code}: {r.text}")

    payload = r.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise HostRunnerError(f"User agent JSON-RPC error: {payload['error']}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise HostRunnerError(f"Invalid user agent response: {payload}")

    data = _extract_data_part(result)
    if not data.get("ok", False):
        raise HostRunnerError(f"User agent returned ok=false: {data}")

    plan = data.get("plan")
    if not isinstance(plan, dict):
        raise HostRunnerError(f"User agent response missing plan: {data}")

    if allowed_ops_profile is not None and not isinstance(allowed_ops_profile, Mapping):
        raise HostRunnerError("allowed_ops_profile must be a mapping/dict")

    return {
        "iterations": int(data.get("iterations") or 0),
        "plan": plan,
        "user_report": data.get("report"),
        "user_reports": data.get("reports"),  # may be missing; keep as None
    }


def main() -> None:
    init_runtime()
    ap = argparse.ArgumentParser(
        description=(
            "Host runner: negotiate MappingPlan via User A2A agent. "
            "In Phase-1, prefer a hand-authored logical --vault-catalog; "
            "--vault-db is a secondary convenience path."
        )
    )
    ap.add_argument("--user-url", default=os.getenv("HDT_USER_A2A_URL", "http://localhost:9200/"))
    ap.add_argument("--provider-url", default=os.getenv("HDT_PROVIDER_A2A_URL", "http://localhost:9100/"))
    ap.add_argument("--algo-id", required=True)
    ap.add_argument("--algo-version", required=True)

    vault_group = ap.add_argument_group("vault metadata")
    vault_group.add_argument(
        "--vault-catalog",
        default=None,
        help=(
            "Preferred Phase-1 path: hand-authored logical vault_catalog.json. "
            "If omitted, --vault-db can generate a temporary catalog from SQLite."
        ),
    )
    vault_group.add_argument(
        "--vault-db",
        default=None,
        help=(
            "Secondary path: derive a temporary vault catalog from a concrete SQLite schema. "
            "Used only if --vault-catalog is omitted."
        ),
    )
    vault_group.add_argument(
        "--dataset-id",
        default=None,
        help=(
            "Dataset id to target. If omitted and catalog is unambiguous, User Agent may infer it. "
            "When generating catalog from --vault-db, defaults to 'vault_dataset_A'."
        ),
    )
    vault_group.add_argument(
        "--table-name",
        default=None,
        help="Table to target. If omitted and catalog is unambiguous, User Agent may infer it.",
    )
    vault_group.add_argument(
        "--only-table",
        action="append",
        default=None,
        help="(repeatable) When generating a temporary catalog from --vault-db, include only these tables.",
    )

    ap.add_argument(
        "--allowed-ops",
        default=None,
        help="Path to allowed_ops_profile.json. If omitted, use the package default.",
    )

    llm_group = ap.add_argument_group("LLM overrides (forwarded to User Agent)")
    llm_group.add_argument("--ollama-url", default=None, help="Override Ollama base URL for this run")
    llm_group.add_argument("--model", default=None, help="Override Ollama model for this run")

    ap.add_argument("--max-iters", type=int, default=3, help="Repair iterations inside User Agent")
    ap.add_argument("--out-dir", default="artifacts/mapping_plans")
    ap.add_argument("--strict", action="store_true", help="Fail on linter warnings (optional)")

    ap.add_argument(
        "--user-timeout-s",
        type=float,
        default=300.0,
        help="Read timeout in seconds for the User Agent call (LLM+repairs can take time).",
    )

    exp_group = ap.add_argument_group("Synthesis knobs (forwarded to User Agent)")
    exp_group.add_argument("--initial-candidates", type=int, default=1, help="Number of initial candidates to sample")
    exp_group.add_argument(
        "--disable-retriever", action="store_true", help="Disable pointer-to-candidate retrieval hints"
    )
    exp_group.add_argument(
        "--disable-seed-hints", action="store_true", help="Disable provider seed hints (if retriever is enabled)"
    )

    args = ap.parse_args()

    # Load or generate vault_catalog
    if args.vault_catalog:
        vault_catalog = _read_json(args.vault_catalog)
    else:
        if not args.vault_db:
            raise HostRunnerError("Pass --vault-catalog or --vault-db")

        ds_id = str(args.dataset_id) if args.dataset_id else "vault_dataset_A"
        vault_catalog = generate_vault_catalog(
            vault_db_path=args.vault_db,
            dataset_id=ds_id,
            out_path=None,
            only_tables=list(args.only_table) if args.only_table else None,
        )

    # Load allowed ops profile (optional)
    allowed_ops_profile = _read_json(args.allowed_ops) if args.allowed_ops else _load_default_allowed_ops_profile()

    # Fetch provider schema/hash deterministically so host validation can run contract checks.
    log.info(
        "Fetching provider contract bundle: provider_url=%s algo_id=%s algo_version=%s",
        args.provider_url,
        args.algo_id,
        args.algo_version,
    )

    bundle = fetch_contract_bundle(
        provider_url=args.provider_url,
        algo_id=args.algo_id,
        algo_version=args.algo_version,
    )

    # IMPORTANT: contract_input_schema is what host-side validators need.
    contract_input_schema = bundle["contract_input_schema"]

    expected_hash = bundle.get("expected_contract_hash")
    computed_hash = compute_contract_schema_hash(contract_input_schema)

    log.info(
        "Provider bundle fetched: contract=%s expected_hash=%s computed_hash=%s schema=%s",
        bundle.get("contract"),
        expected_hash,
        computed_hash,
        _schema_summary(contract_input_schema),
    )

    # Full dump only at DEBUG (safe if schema is small; otherwise it’s noisy)
    log.debug("Provider bundle full: %s", json.dumps(bundle, ensure_ascii=False, indent=2))

    # 1) Call user agent (which calls provider, runs loop, returns plan)
    res = call_user_agent_synthesize(
        user_url=args.user_url,
        provider_url=args.provider_url,
        algo_id=args.algo_id,
        algo_version=args.algo_version,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
        dataset_id=(str(args.dataset_id) if args.dataset_id else None),
        table_name=args.table_name,
        max_iters=args.max_iters,
        ollama_url=args.ollama_url,
        ollama_model=args.model,
        timeout_s=args.user_timeout_s,
        initial_candidates=args.initial_candidates,
        use_candidate_retrieval=(not args.disable_retriever),
        use_seed_hints=(not args.disable_seed_hints),
    )
    plan = res["plan"]

    # 2) Host-side deterministic postprocessing (belt & suspenders)
    plan = fill_contract_refs(plan, algo_id=args.algo_id, algo_version=args.algo_version)
    plan = apply_limits_policy(plan)

    # 3) Final deterministic validation on host (source of truth)
    report = validate_and_lint_plan(
        plan,
        vault_catalog=vault_catalog,
        allowed_ops_profile=allowed_ops_profile,
        contract_input_schema=contract_input_schema,
    )

    if not report.ok:
        raise HostRunnerError(f"Final validation failed: {report}")

    if args.strict and getattr(report, "warnings", []):
        raise HostRunnerError(f"Strict mode: warnings present: {report.warnings}")

    # 4) Persist (plan + run manifest)
    plan_id = str(plan.get("plan_id") or f"plan_{uuid.uuid4()}")
    plan.setdefault("plan_id", plan_id)

    out_dir = Path(args.out_dir)
    plan_path = out_dir / f"{plan_id}.json"
    run_path = out_dir / f"{plan_id}.run.json"

    # 4a) Write the plan itself (so it can be executed / diffed directly)
    _write_json(plan_path, plan)

    # 4b) Write a run manifest (inputs + reports + hashes)
    host_report = {
        "ok": bool(getattr(report, "ok", False)),
        "errors": [getattr(e, "__dict__", {"message": str(e)}) for e in getattr(report, "errors", [])],
        "warnings": [getattr(w, "__dict__", {"message": str(w)}) for w in getattr(report, "warnings", [])],
    }

    user_agent_block: dict[str, Any] = {"iterations": res["iterations"], "report": res["user_report"]}
    if isinstance(res.get("user_reports"), list):
        user_agent_block["reports"] = res["user_reports"]

    run_manifest = {
        "plan_id": plan_id,
        "plan_path": str(plan_path),
        "host_report": host_report,
        "user_agent": user_agent_block,
        "provider": {
            "provider_url": args.provider_url,
            "algo_id": args.algo_id,
            "algo_version": args.algo_version,
            "expected_contract_hash": expected_hash,
            "computed_contract_hash": computed_hash,
        },
        "policy": {
            "allowed_ops_source": (args.allowed_ops or "package:hdt_mapping_plan/allowed_ops_profile.json"),
            "allowed_ops_hash": sha256_hex_of_json(allowed_ops_profile),
        },
        "inputs": {
            "user_url": args.user_url,
            "vault_catalog_path": args.vault_catalog,
            "vault_db_path": args.vault_db,
            "vault_catalog_mode": ("provided" if args.vault_catalog else "generated_from_db"),
            "dataset_id": args.dataset_id,
            "table_name": args.table_name,
            "max_iters": args.max_iters,
            "ollama_url": args.ollama_url,
            "model": args.model,
            "initial_candidates": args.initial_candidates,
            "use_candidate_retrieval": (not args.disable_retriever),
            "use_seed_hints": (not args.disable_seed_hints),
            "disable_retriever": bool(args.disable_retriever),
            "disable_seed_hints": bool(args.disable_seed_hints),
        },
    }
    _write_json(run_path, run_manifest)

    print(f"OK: wrote {plan_path} and {run_path} (iterations={res['iterations']})")


if __name__ == "__main__":
    main()
