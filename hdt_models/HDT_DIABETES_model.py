from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# Ensure repo root on sys.path (so `hdt_mcp` and `config` resolve when run as a script)
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[1] if (_THIS_FILE.parents and (_THIS_FILE.parents[0].name in {"Virtual_Twin_Models", "scripts"})) else Path.cwd()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Prefer explicit imports (avoid wildcard)
try:
    # If you keep calculations under Virtual_Twin_Models
    from Virtual_Twin_Models.HDT_DIABETES_calculations import (
        manipulate_initial_metrics_trivia,
        manipulate_initial_metrics_sugarvita,
        normalize_metrics,
        get_health_literacy_score_trivia,
        get_health_literacy_score_sugarvita,
        get_final_health_literacy_score,
        get_player_types,
    )
except Exception:
    # Fallback if script lives in same folder as calculations
    from HDT_DIABETES_calculations import (  # type: ignore
        manipulate_initial_metrics_trivia,
        manipulate_initial_metrics_sugarvita,
        normalize_metrics,
        get_health_literacy_score_trivia,
        get_health_literacy_score_sugarvita,
        get_final_health_literacy_score,
        get_player_types,
    )


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_runtime_env() -> None:
    """
    Prefer centralized runtime init (your refactor). If not available,
    do nothing (env can be provided by shell / IDE / pre-commit).
    """
    try:
        from config.settings import init_runtime  # type: ignore
        init_runtime()
    except Exception:
        # Intentionally no side-effects here. Provide env externally if needed.
        return


def _default_storage_path() -> Path:
    # Prefer env override, else default to repo-root/data/diabetes_pt_hl_storage.json
    p = os.getenv("HDT_DIABETES_STORAGE_PATH")
    if p:
        return Path(p).expanduser().resolve()
    return (_REPO_ROOT / "data" / "diabetes_pt_hl_storage.json").resolve()


def load_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {"users": {}}
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return {"users": {}}
        data = json.loads(content)
        if not isinstance(data, dict) or "users" not in data:
            return {"users": {}}
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        return data
    except json.JSONDecodeError:
        # Preserve the corrupted file as-is; start fresh in memory
        print(f"[diabetes] WARN: JSON file invalid/corrupted: {path}")
        return {"users": {}}


def save_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=4, ensure_ascii=False)

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)

    tmp_path.replace(path)


def _pick_gateway_module() -> str:
    explicit = os.getenv("HDT_GATEWAY_MODULE")
    if explicit:
        return explicit

    # Reasonable defaults for your repo
    candidates = [
        "hdt_mcp.gateway",
        "hdt_mcp.server",
    ]
    for m in candidates:
        try:
            importlib.import_module(m)
            return m
        except Exception:
            continue

    raise RuntimeError(
        "Could not import a gateway module. Set HDT_GATEWAY_MODULE explicitly "
        "(e.g., hdt_mcp.gateway)."
    )


def _unwrap_tool_result(res: Any) -> Any:
    """
    MCP responses typically have res.content[0].text; keep resilient to SDK shape changes.
    """
    content = getattr(res, "content", None)
    if not content:
        return res
    c0 = content[0]
    if isinstance(c0, dict) and "text" in c0:
        return c0["text"]
    return getattr(c0, "text", c0)


def _as_json(x: Any) -> Any:
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return json.loads(s)
            except Exception:
                return x
        return x
    return x


def _extract_metrics(payload: dict, *, kind: str) -> Optional[dict]:
    """
    Supports both shapes:
      - old REST shape: payload["data"]["trivia_results"] / ["sugarvita_results"]
      - current Sources MCP shape: payload["data"] is already the metrics dict
    """
    if not isinstance(payload, dict):
        return None
    if "error" in payload:
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    if kind == "trivia" and "trivia_results" in data and isinstance(data["trivia_results"], dict):
        return data["trivia_results"]
    if kind == "sugarvita" and "sugarvita_results" in data and isinstance(data["sugarvita_results"], dict):
        return data["sugarvita_results"]

    # Current MCP shape (metrics dict directly)
    return data


@dataclass(frozen=True)
class FetchResult:
    trivia_payload: dict
    sugarvita_payload: dict


async def fetch_user_data_via_mcp(
    *,
    user_id: int,
    gateway_module: str,
    start_date: str | None,
    end_date: str | None,
    purpose: str,
    client_id: str,
) -> FetchResult:
    # Lazy import so this file can be imported without MCP installed
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    env = dict(os.environ)
    env.setdefault("MCP_TRANSPORT", "stdio")
    env.setdefault("MCP_CLIENT_ID", client_id)

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", gateway_module],
        env=env,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            trivia_res = await session.call_tool(
                "hdt.trivia.fetch@v1",
                {"user_id": int(user_id), "start_date": start_date, "end_date": end_date, "purpose": purpose},
            )
            sugar_res = await session.call_tool(
                "hdt.sugarvita.fetch@v1",
                {"user_id": int(user_id), "start_date": start_date, "end_date": end_date, "purpose": purpose},
            )

            trivia_payload = _as_json(_unwrap_tool_result(trivia_res))
            sugar_payload = _as_json(_unwrap_tool_result(sugar_res))

            if not isinstance(trivia_payload, dict):
                trivia_payload = {"error": {"code": "bad_shape", "message": "Trivia tool did not return dict"}, "raw": trivia_payload}
            if not isinstance(sugar_payload, dict):
                sugar_payload = {"error": {"code": "bad_shape", "message": "SugarVita tool did not return dict"}, "raw": sugar_payload}

            return FetchResult(trivia_payload=trivia_payload, sugarvita_payload=sugar_payload)


def process_user(storage_data: dict, *, user_id: int, trivia_payload: dict, sugarvita_payload: dict) -> bool:
    trivia_metrics_raw = _extract_metrics(trivia_payload, kind="trivia")
    sugarvita_metrics_raw = _extract_metrics(sugarvita_payload, kind="sugarvita")

    if trivia_metrics_raw is None or sugarvita_metrics_raw is None:
        print(f"[diabetes] Skipping user {user_id}: missing/denied trivia or sugarvita metrics.")
        return False

    # 1) Manipulate + normalize
    trivia_metrics = manipulate_initial_metrics_trivia(trivia_metrics_raw)
    sugarvita_pt_metrics, sugarvita_hl_metrics = manipulate_initial_metrics_sugarvita(sugarvita_metrics_raw)

    normalized_trivia = normalize_metrics(trivia_metrics)
    normalized_sugarvita_pt = normalize_metrics(sugarvita_pt_metrics)
    normalized_sugarvita_hl = normalize_metrics(sugarvita_hl_metrics)

    # 2) Compute scores
    trivia_score = get_health_literacy_score_trivia(normalized_trivia)
    sugarvita_score = get_health_literacy_score_sugarvita(normalized_sugarvita_hl)
    final_score = get_final_health_literacy_score(trivia_score, sugarvita_score)

    # 3) Player types
    player_types = get_player_types(normalized_sugarvita_pt)

    entry = {
        "date": _utc_now_z(),
        "final_scores": {
            "health_literacy_score": {
                "domain": {
                    "name": "diabetes",
                    "score": final_score,
                    "sources": {"trivia": trivia_score, "sugarvita": sugarvita_score},
                }
            },
            "player_types_labels": player_types,
        },
        "metrics_overviews": {
            "trivia": trivia_metrics,
            "sugarvita": {"pt": sugarvita_pt_metrics, "hl": sugarvita_hl_metrics},
        },
        # Extra traceability for audit/debug
        "inputs": {
            "trivia": {
                "source": trivia_payload.get("source"),
                "latest_activity": trivia_payload.get("latest_activity"),
                "provenance": trivia_payload.get("provenance"),
            },
            "sugarvita": {
                "source": sugarvita_payload.get("source"),
                "latest_activity": sugarvita_payload.get("latest_activity"),
                "provenance": sugarvita_payload.get("provenance"),
            },
        },
    }

    users = storage_data.setdefault("users", {})
    user_storage = users.setdefault(str(user_id), {"entries": []})
    user_storage["entries"].append(entry)
    return True


def _parse_user_ids(s: str) -> list[int]:
    out: list[int] = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def _load_user_ids_from_config() -> list[int]:
    """
    Fallback: read config/users.json if present and return all user_id values.
    """
    # If you have config.settings, prefer its config_dir()
    cfg_path = _REPO_ROOT / "config" / "users.json"
    try:
        from config.settings import config_dir  # type: ignore
        cfg_path = config_dir() / "users.json"
    except Exception:
        pass

    if not cfg_path.exists():
        return []

    try:
        obj = json.loads(cfg_path.read_text(encoding="utf-8"))
        users = obj.get("users")
        if isinstance(users, list):
            ids = []
            for u in users:
                if isinstance(u, dict) and "user_id" in u:
                    ids.append(int(u["user_id"]))
            return ids
    except Exception:
        return []

    return []


async def main() -> int:
    _load_runtime_env()

    ap = argparse.ArgumentParser(description="Diabetes model runner (MCP-native).")
    ap.add_argument("--user-ids", default=os.getenv("HDT_DIABETES_USER_IDS", ""), help="Comma-separated user IDs.")
    ap.add_argument("--start-date", default=os.getenv("HDT_START_DATE"), help="YYYY-MM-DD (optional).")
    ap.add_argument("--end-date", default=os.getenv("HDT_END_DATE"), help="YYYY-MM-DD (optional).")
    ap.add_argument("--purpose", default=os.getenv("HDT_PURPOSE", "modeling"), help="Policy lane/purpose (e.g., modeling).")
    ap.add_argument("--client-id", default=os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1"), help="MCP client id.")
    ap.add_argument("--out", default=str(_default_storage_path()), help="Output JSON file path.")
    args = ap.parse_args()

    gateway_module = _pick_gateway_module()
    out_path = Path(args.out).expanduser().resolve()

    user_ids: list[int] = _parse_user_ids(args.user_ids)
    if not user_ids:
        user_ids = _load_user_ids_from_config()

    if not user_ids:
        raise SystemExit("No user IDs provided (use --user-ids or set HDT_DIABETES_USER_IDS, or define config/users.json).")

    storage_data = load_json(out_path)

    ok_any = False
    for uid in user_ids:
        try:
            fetched = await fetch_user_data_via_mcp(
                user_id=uid,
                gateway_module=gateway_module,
                start_date=args.start_date,
                end_date=args.end_date,
                purpose=args.purpose,
                client_id=args.client_id,
            )
            ok = process_user(
                storage_data,
                user_id=uid,
                trivia_payload=fetched.trivia_payload,
                sugarvita_payload=fetched.sugarvita_payload,
            )
            ok_any = ok_any or ok
        except Exception as e:
            print(f"[diabetes] ERROR processing user {uid}: {e}")

    save_json_atomic(out_path, storage_data)

    if ok_any:
        print(f"[diabetes] Done. Updated: {out_path}")
        return 0

    print(f"[diabetes] Completed with warnings (no users processed). Output written: {out_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
