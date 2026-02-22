from __future__ import annotations

import json
import os
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import DataPart
from a2a.utils import new_agent_parts_message

from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig
from hdt_a2a.llm.loop_from_provider import synthesize_plan_via_provider


def _parse_request(context: RequestContext) -> dict[str, Any]:
    msg = context.message
    if msg is not None:
        try:
            md = msg.model_dump(mode="json", exclude_none=True)
            for p in md.get("parts") or []:
                if not isinstance(p, dict):
                    continue
                ptype = p.get("type") or p.get("kind")
                if ptype == "data" and isinstance(p.get("data"), dict):
                    return p["data"]
                if ptype == "text" and isinstance(p.get("text"), str) and p["text"].strip():
                    return json.loads(p["text"])
        except Exception:
            pass
    return {}


def _report_to_dict(report: Any) -> dict[str, Any]:
    # Keep stable + serializable. Don’t leak objects.
    return {
        "ok": bool(getattr(report, "ok", False)),
        "errors": [getattr(e, "__dict__", {"message": str(e)}) for e in getattr(report, "errors", [])],
        "warnings": [getattr(w, "__dict__", {"message": str(w)}) for w in getattr(report, "warnings", [])],
    }


class UserAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        req = _parse_request(context)
        op = str(req.get("op") or "")

        if op != "mapping_plan.synthesize":
            payload = {"ok": False, "error": {"code": "BAD_REQUEST", "message": "op must be mapping_plan.synthesize"}}
        else:
            provider_url = str(req.get("provider_url") or os.getenv("HDT_PROVIDER_A2A_URL") or "")
            algo_id = str(req.get("algo_id") or "")
            algo_version = str(req.get("algo_version") or "")
            vault_catalog = req.get("vault_catalog")

            if not provider_url or not algo_id or not algo_version or not isinstance(vault_catalog, dict):
                payload = {
                    "ok": False,
                    "error": {"code": "BAD_REQUEST", "message": "missing provider_url/algo_id/algo_version/vault_catalog"},
                }
            else:
                cfg = OllamaConfig(
                    base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
                    model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_0"),
                    timeout_s=float(os.getenv("OLLAMA_TIMEOUT_S", "300")),
                    # optional speed knobs (recommended):
                    num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "1600")),
                    num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "4096")),

                    structured_mode=os.getenv("OLLAMA_STRUCTURED_MODE", "json"),
                    fallback_to_json_on_error=bool(int(os.getenv("OLLAMA_FALLBACK_TO_JSON", "0"))),
                )
                client = OllamaClient(cfg)

                try:
                    res = synthesize_plan_via_provider(
                        client=client,
                        provider_url=provider_url,
                        algo_id=algo_id,
                        algo_version=algo_version,
                        vault_catalog=vault_catalog,
                        dataset_id=req.get("dataset_id"),
                        table_name=req.get("table_name"),
                        max_iters=int(req.get("max_iters") or 3),
                    )
                    payload = {
                        "ok": bool(res.ok),
                        "iterations": int(res.iterations),
                        "plan": res.plan,
                        "report": _report_to_dict(res.report),
                    }
                except Exception as e:
                    payload = {"ok": False, "error": {"code": "INTERNAL", "message": str(e)}}

        msg = new_agent_parts_message(
            parts=[DataPart(data=payload)],
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(msg)
        await event_queue.close()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")
