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

log = logging.getLogger(__name__)


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


def call_user_agent_synthesize(
    *,
    user_url: str,
    provider_url: str,
    algo_id: str,
    algo_version: str,
    vault_catalog: Mapping[str, Any],
    dataset_id: str | None,
    table_name: str | None,
    max_iters: int,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    rpc_url = user_url.rstrip("/") + "/"
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
                        "data": {
                            "op": "mapping_plan.synthesize",
                            "provider_url": provider_url,
                            "algo_id": algo_id,
                            "algo_version": algo_version,
                            "vault_catalog": vault_catalog,
                            **({"dataset_id": dataset_id} if dataset_id else {}),
                            **({"table_name": table_name} if table_name else {}),
                            "max_iters": max_iters,
                        },
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

    return {
        "iterations": int(data.get("iterations") or 0),
        "plan": plan,
        "user_report": data.get("report"),
    }


def _load_default_allowed_ops_profile() -> dict[str, Any]:
    p = resources.files("hdt_mapping_plan").joinpath("allowed_ops_profile.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    init_runtime()
    ap = argparse.ArgumentParser(description="Host runner: negotiate MappingPlan via User A2A agent (7A).")
    ap.add_argument("--user-url", default=os.getenv("HDT_USER_A2A_URL", "http://localhost:9200/"))
    ap.add_argument("--provider-url", default=os.getenv("HDT_PROVIDER_A2A_URL", "http://localhost:9100/"))
    ap.add_argument("--algo-id", required=True)
    ap.add_argument("--algo-version", required=True)

    vault_group = ap.add_argument_group("vault metadata")
    vault_group.add_argument(
        "--vault-catalog",
        default=None,
        help="Path to a vault_catalog.json. If omitted, use --vault-db to generate one.",
    )
    vault_group.add_argument(
        "--vault-db",
        default=None,
        help="Path to vault SQLite DB. Used only if --vault-catalog is omitted.",
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
        help="(repeatable) When generating catalog from --vault-db, include only these tables.",
    )

    ap.add_argument(
        "--allowed-ops",
        default=None,
        help="Path to allowed_ops_profile.json. If omitted, use the package default.",
    )

    ap.add_argument("--max-iters", type=int, default=3, help="Repair iterations inside User Agent")
    ap.add_argument("--out-dir", default="artifacts/mapping_plans")
    ap.add_argument("--strict", action="store_true", help="Fail on linter warnings (optional)")

    ap.add_argument(
        "--user-timeout-s",
        type=float,
        default=300.0,
        help="Read timeout in seconds for the User Agent call (LLM+repairs can take time).",
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
        args.provider_url, args.algo_id, args.algo_version
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
        dataset_id=(str(args.dataset_id) if args.dataset_id else None),
        table_name=args.table_name,
        max_iters=args.max_iters,
        timeout_s=args.user_timeout_s,
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

    # 4) Persist
    plan_id = str(plan.get("plan_id") or f"plan_{uuid.uuid4()}")
    out_path = Path(args.out_dir) / f"{plan_id}.json"

    artifact = {
        "plan": plan,
        "host_report": {
            "ok": report.ok,
            "errors": [getattr(e, "__dict__", {"message": str(e)}) for e in getattr(report, "errors", [])],
            "warnings": [getattr(w, "__dict__", {"message": str(w)}) for w in getattr(report, "warnings", [])],
        },
        "user_agent_iterations": res["iterations"],
        "user_agent_report": res["user_report"],
        "provider_bundle": {"expected_contract_hash": bundle.get("expected_contract_hash")},
        "inputs": {
            "algo_id": args.algo_id,
            "algo_version": args.algo_version,
            "provider_url": args.provider_url,
            "user_url": args.user_url,
            "vault_catalog_path": args.vault_catalog,
            "vault_db_path": args.vault_db,
            "allowed_ops_path": args.allowed_ops,
            "dataset_id": args.dataset_id,
            "table_name": args.table_name,
        },
    }
    _write_json(out_path, artifact)

    print(f"OK: wrote {out_path} (iterations={res['iterations']})")


if __name__ == "__main__":
    main()