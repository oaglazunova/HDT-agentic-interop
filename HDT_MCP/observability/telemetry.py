from __future__ import annotations

from pathlib import Path
import json
import datetime as _dt
from typing import Callable


def log_event(
    *,
    dir_path: Path,
    disabled: bool,
    kind: str,
    name: str,
    args: dict | None,
    ok: bool,
    ms: int,
    client_id: str,
    corr_id: str | None,
    get_request_id: Callable[[], str],
) -> None:
    if disabled:
        return

    rid = get_request_id()
    payload = {} if args is None else dict(args)
    rec = {
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "kind": kind,
        "name": name,
        "client_id": client_id,
        "request_id": rid,
        "corr_id": corr_id or rid,
        "args": payload,
        "ok": bool(ok),
        "ms": int(ms),
    }
    dir_path.mkdir(parents=True, exist_ok=True)
    with open(dir_path / "mcp-telemetry.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def recent(dir_path: Path, n: int = 50) -> dict:
    p = dir_path / "mcp-telemetry.jsonl"
    if not p.exists():
        return {"records": []}
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    return {"records": [json.loads(x) for x in lines]}
