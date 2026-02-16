from __future__ import annotations

import json
from typing import Any, Mapping, Sequence
from collections import Counter

from hdt_a2a.llm.ollama_client import OllamaClient
from hdt_a2a.llm.plan_synthesis import load_mapping_plan_schema
from hdt_mapping_plan.validate import CriticReport


# === helpers =========================

def _stable_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def _critic_report_payload(report: CriticReport, *, max_items: int = 50) -> dict[str, Any]:
    """
    Convert CriticReport into a compact, deterministic payload suitable for LLM repair.
    Cap size so prompts don't explode.
    """
    errs = [
        {
            "code": e.code,
            "path": e.path,
            "detail": e.detail,
            "hint": e.hint,
            "severity": e.severity,
        }
        for e in (report.errors or [])
    ]
    warns = [
        {
            "code": w.code,
            "path": w.path,
            "detail": w.detail,
            "hint": w.hint,
            "severity": w.severity,
        }
        for w in (report.warnings or [])
    ]
    # Deterministic truncation
    errs = errs[:max_items]
    warns = warns[:max_items]
    # return {"ok": report.ok, "errors": errs, "warnings": warns}

    err_counts = dict(Counter(e["code"] for e in errs))
    warn_counts = dict(Counter(w["code"] for w in warns))

    return {"ok": report.ok, "error_counts": err_counts, "warning_counts": warn_counts, "errors": errs[:max_items],
            "warnings": warns[:max_items]}


# === end helpers ============================================

def build_repair_message(
    *,
    previous_plan: Mapping[str, Any],
    critic_report: CriticReport,
) -> dict[str, str]:
    """
    Produce a single user message instructing the model to repair only reported issues.
    """
    payload = _critic_report_payload(critic_report)

    content = "\n".join(
        [
            "You previously returned a MappingPlan JSON that failed deterministic validation.",
            "Repair the plan using ONLY the issues listed below.",
            "",
            "Rules:",
            "1) Return ONLY JSON matching the provided JSON Schema.",
            "2) Fix ONLY what is necessary to address the listed errors.",
            "3) Keep all unrelated fields stable (do not rename plan_id, do not rewrite limits/output unless required).",
            "4) Ensure every referenced column appears in required_columns, and required_columns is minimized.",
            "",
            "PREVIOUS PLAN JSON:",
            _stable_json(previous_plan),
            "",
            "VALIDATION REPORT (deterministic critic):",
            _stable_json(payload),
        ]
    )
    return {"role": "user", "content": content}


def repair_mapping_plan_candidate(
    *,
    client: OllamaClient,
    base_messages: Sequence[Mapping[str, Any]],
    previous_plan: Mapping[str, Any],
    critic_report: CriticReport,
) -> dict[str, Any]:
    """
    Calls Ollama structured output to repair a previously generated plan.
    base_messages should be the original [system,user] messages from plan synthesis.
    """
    schema = load_mapping_plan_schema()
    repair_msg = build_repair_message(previous_plan=previous_plan, critic_report=critic_report)

    # Append repair message to the conversation
    messages = list(base_messages) + [repair_msg]
    return client.chat_json(messages, json_schema=schema)
