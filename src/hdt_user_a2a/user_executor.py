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


def _get_str(d: dict[str, Any], key: str) -> str | None:
    v = d.get(key)
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def _parse_ollama_overrides(req: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Allows host to override LLM settings per run without restarting the agent.

    Accepted shapes:
      - {"ollama_url": "...", "ollama_model": "..."}
      - {"ollama": {"base_url": "...", "model": "..."}}
      - {"ollama": {"url": "...", "model": "..."}}
      - (optional convenience) {"model": "..."}  # if you choose to allow it
    """
    ollama_cfg = req.get("ollama")
    if not isinstance(ollama_cfg, dict):
        ollama_cfg = {}

    url = (
        _get_str(req, "ollama_url")
        or _get_str(req, "ollama_base_url")
        or _get_str(ollama_cfg, "base_url")
        or _get_str(ollama_cfg, "url")
    )

    model = (
        _get_str(req, "ollama_model")
        or _get_str(ollama_cfg, "model")
        or _get_str(req, "model")  # optional convenience; safe because we still strip/None-check
    )

    return url, model


def _get_bool(req: dict[str, Any], key: str) -> bool | None:
    v = req.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return None


def _get_int(req: dict[str, Any], key: str, default: int) -> int:
    v = req.get(key)
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


# === end helpers ===========================


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

            allowed_ops_profile = req.get("allowed_ops_profile")
            if allowed_ops_profile is not None and not isinstance(allowed_ops_profile, dict):
                allowed_ops_profile = None  # ignore invalid shape instead of crashing

            if not provider_url or not algo_id or not algo_version or not isinstance(vault_catalog, dict):
                payload = {
                    "ok": False,
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": "missing provider_url/algo_id/algo_version/vault_catalog",
                    },
                }
            else:
                ollama_url_override, ollama_model_override = _parse_ollama_overrides(req)

                cfg = OllamaConfig(
                    base_url=ollama_url_override or os.getenv("OLLAMA_URL", "http://localhost:11434"),
                    model=ollama_model_override or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_0"),
                    timeout_s=float(os.getenv("OLLAMA_TIMEOUT_S", "300")),
                    structured_mode=os.getenv("OLLAMA_STRUCTURED_MODE", "json"),
                    fallback_to_json_on_error=bool(int(os.getenv("OLLAMA_FALLBACK_TO_JSON", "0"))),
                    # optional speed knobs (recommended):
                    num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "1600")),
                    num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "4096")),
                )
                client = OllamaClient(cfg)

                initial_candidates = max(_get_int(req, "initial_candidates", 1), 1)

                use_candidate_retrieval = _get_bool(req, "use_candidate_retrieval")
                if use_candidate_retrieval is None:
                    disable_retriever = _get_bool(req, "disable_retriever")
                    use_candidate_retrieval = not disable_retriever if disable_retriever is not None else True

                use_seed_hints = _get_bool(req, "use_seed_hints")
                if use_seed_hints is None:
                    disable_seed_hints = _get_bool(req, "disable_seed_hints")
                    use_seed_hints = not disable_seed_hints if disable_seed_hints is not None else True

                try:
                    res = synthesize_plan_via_provider(
                        client=client,
                        provider_url=provider_url,
                        algo_id=algo_id,
                        algo_version=algo_version,
                        vault_catalog=vault_catalog,
                        allowed_ops_profile=allowed_ops_profile,
                        dataset_id=req.get("dataset_id"),
                        table_name=req.get("table_name"),
                        max_iters=int(req.get("max_iters") or 3),
                        initial_candidates=initial_candidates,
                        use_candidate_retrieval=use_candidate_retrieval,
                        use_seed_hints=use_seed_hints,
                    )

                    reports_obj = getattr(res, "reports", None)
                    if isinstance(reports_obj, list) and reports_obj:
                        reports_list = [_report_to_dict(r) for r in reports_obj]
                    else:
                        # Backward compatible fallback (for older fakes/tests)
                        reports_list = [_report_to_dict(res.report)]

                    payload = {
                        "ok": bool(res.ok),
                        "iterations": int(res.iterations),
                        "plan": res.plan,
                        "report": _report_to_dict(res.report),  # final
                        "reports": reports_list,  # intermediate + final
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
