from __future__ import annotations

import json
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import DataPart
from a2a.utils import get_data_parts, new_agent_parts_message

from .contract_registry import ContractNotFoundError, ContractRegistry


def _parse_request(context: RequestContext) -> dict[str, Any]:
    msg = context.message
    if msg is not None and getattr(msg, "parts", None):
        # 1) Prefer DataPart (no JSON parsing needed)
        try:
            data_parts = get_data_parts(msg.parts)
            if data_parts:
                first = data_parts[0]
                if isinstance(first, dict):
                    return first
        except Exception:
            pass

        # 2) Fallback: parse the first TextPart that looks like JSON
        for p in msg.parts:
            # support both dict-like parts and object parts
            kind = getattr(p, "kind", None) or (p.get("kind") if isinstance(p, dict) else None)
            if kind != "text":
                continue

            text = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
            if not isinstance(text, str) or not text.strip():
                continue

            s = text.strip()
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return {"op": "text", "text": s}

    # 3) Last-resort fallback: whatever the SDK exposes as "user input"
    raw = ""
    if hasattr(context, "get_user_input"):
        try:
            raw = (context.get_user_input() or "").strip()
        except Exception:
            raw = ""

    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"op": "text", "text": raw}
    except Exception:
        return {"op": "text", "text": raw}



class ProviderAgentExecutor(AgentExecutor):
    def __init__(self, registry: ContractRegistry | None = None) -> None:
        self._registry = registry or ContractRegistry()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        req = _parse_request(context)
        op = str(req.get("op") or "").strip() or "get_contract"

        try:
            if op == "list_contracts":
                payload: dict[str, Any] = {"ok": True, "contracts": self._registry.list_contracts()}

            elif op == "get_contract":
                algo_id = str(req.get("algo_id") or "")
                algo_version = str(req.get("algo_version") or "")
                if not algo_id or not algo_version:
                    raise ValueError("get_contract requires algo_id and algo_version")

                payload = {"ok": True, **self._registry.get_contract_bundle(algo_id=algo_id, algo_version=algo_version)}

            else:
                raise ValueError(f"Unknown op: {op}. Supported: list_contracts, get_contract")

        except ContractNotFoundError as e:
            payload = {"ok": False, "error": {"code": "CONTRACT_NOT_FOUND", "message": str(e)}}
        except Exception as e:
            payload = {"ok": False, "error": {"code": "BAD_REQUEST", "message": str(e)}}

        msg = new_agent_parts_message(
            parts=[DataPart(data=payload)],
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(msg)
        await event_queue.close()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")
