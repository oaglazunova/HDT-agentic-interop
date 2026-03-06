from __future__ import annotations

import uuid
from typing import Any, Mapping

import httpx

from hdt_mapping_plan.validate import compute_contract_schema_hash


class ProviderA2AError(RuntimeError):
    pass


def _extract_data_part(message_result: Mapping[str, Any]) -> dict[str, Any]:
    parts = message_result.get("parts") or []
    if not isinstance(parts, list):
        raise ProviderA2AError("Invalid A2A response: result.parts is not a list")

    for p in parts:
        if not isinstance(p, dict):
            continue
        ptype = p.get("type") or p.get("kind")  # tolerate both
        if ptype == "data" and isinstance(p.get("data"), dict):
            return p["data"]

    raise ProviderA2AError("No DataPart found in A2A response")


def fetch_contract_bundle(
    *,
    provider_url: str,
    algo_id: str,
    algo_version: str,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """
    Calls provider A2A server message/send with a DataPart request and returns:
      { contract, contract_input_schema, expected_contract_hash }
    Also verifies expected_contract_hash == sha256(schema) deterministically.
    """
    rpc_url = provider_url.rstrip("/") + "/"

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
                        "type": "data",  # most interoperable
                        "data": {
                            "op": "get_contract",
                            "algo_id": algo_id,
                            "algo_version": algo_version,
                        },
                    }
                ],
            },
            "configuration": {},
        },
    }

    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(rpc_url, json=req)

    if r.status_code != 200:
        raise ProviderA2AError(f"Provider A2A HTTP {r.status_code}: {r.text}")

    payload = r.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise ProviderA2AError(f"Provider A2A JSON-RPC error: {payload['error']}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise ProviderA2AError(f"Invalid A2A response: missing result: {payload}")

    data = _extract_data_part(result)
    if not data.get("ok", False):
        raise ProviderA2AError(f"Provider returned ok=false: {data}")

    schema = data.get("contract_input_schema")
    expected = data.get("expected_contract_hash")
    if not isinstance(schema, dict) or not isinstance(expected, str) or not expected:
        raise ProviderA2AError(f"Provider response missing schema/hash: {data}")

    computed = compute_contract_schema_hash(schema)
    if computed != expected:
        raise ProviderA2AError(f"Contract hash mismatch (provider={expected}, computed={computed}). Refuse to proceed.")

    return {
        "contract": data["contract"],
        "contract_input_schema": schema,
        "expected_contract_hash": expected,
    }
