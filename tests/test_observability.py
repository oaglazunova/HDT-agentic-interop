import json
from pathlib import Path
from hdt_mcp.server import _log_event, _apply_policy_metrics, REDACT_TOKEN

def test_policy_redactions_count(tmp_path, monkeypatch):
    # simple policy application sanity check
    doc = {"user": {"email": "a@b.c", "name": "X"}, "records": [{"email":"c@d.e"}]}
    # monkeypatch policy to redact both emails
    from hdt_mcp import server as S
    S._POLICY_OVERRIDE = {
        "defaults": {"analytics": {"allow": True, "redact": ["user.email", "records.email"]}}
    }
    out, n = S._apply_policy_metrics("analytics", "tool@v1", doc, client_id=None)
    assert n == 2
    # ensure token is present twice
    flat = json.dumps(out)
    assert flat.count(REDACT_TOKEN) == 2
    S._POLICY_OVERRIDE = None

def test_log_corr_id_present(tmp_path, monkeypatch):
    from hdt_mcp import server as S
    monkeypatch.setenv("PYTHONHASHSEED", "0")  # avoid random effects in CI
    logf = Path(S._TELEMETRY_DIR) / "mcp-telemetry.jsonl"
    if logf.exists():
        logf.unlink()
    S._log_event("tool", "x", {"k":"v"}, True, 10, corr_id="abc123")
    line = logf.read_text(encoding="utf-8").strip().splitlines()[-1]
    row = json.loads(line)
    assert row["corr_id"] == "abc123"
    assert row["args"]["k"] == "v"
